import copy
import json
from pathlib import Path
import unittest

from research.classification_diagnostics import checked_score, diagnose, metrics, render


class ClassificationDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).resolve().parents[2]/'docs'/'algorithm-validation'
        cls.qrs=json.loads((folder/'qrs-comparison.json').read_text(encoding='utf-8'))
        cls.classes=json.loads((folder/'classification-benchmark.json').read_text(encoding='utf-8'))

    def test_report_conservation_and_s_error_contribution(self):
        result=diagnose(self.qrs,self.classes)
        for mode in result['modes'].values():
            s=mode['s_errors']
            self.assertEqual(s['support'],s['correct']+s['to_n']+s['to_v']+s['no_matched_output'])
            self.assertEqual(sum(r['misses'] for r in mode['records']),s['support']-s['correct'])
            self.assertAlmostEqual(sum(r['share_of_s_misses'] for r in mode['records']),1)
        self.assertEqual(result['modes']['end_to_end']['s_errors']['to_n'],1156)
        self.assertIn('不能认定',render(result))

    def test_missing_mode_duplicate_records_and_mismatched_inputs_rejected(self):
        for change in ('mode','cohort','input','environment','weights','rejections'):
            c=copy.deepcopy(self.classes)
            if change=='mode':del c['records'][0]['modes']['reference_r']
            if change=='cohort':c['records'][1]['record']=c['records'][0]['record']
            if change=='input':c['records'][0]['adc_sha256']='wrong'
            if change=='environment':c['environment']['thread_limits']={}
            if change=='weights':c['configuration']['model']['weights_sha256']='wrong'
            if change=='rejections':c['records'][0]['modes']['end_to_end']['rejection_reasons']['invalid']=1
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):diagnose(self.qrs,c)

    def test_nonconserving_and_invalid_counts_rejected(self):
        source=self.classes['aggregate']['end_to_end']['scores_150ms']
        for bad in (-1,True,1.5):
            score=copy.deepcopy(source);score['confusion'][1][0]=bad
            with self.assertRaises(ValueError):checked_score(score)
        c=copy.deepcopy(self.classes)
        score=c['aggregate']['end_to_end']['scores_50ms']
        score['support'][1]+=1;score['unclassified_target_beats'][1]+=1
        with self.assertRaises(ValueError):diagnose(self.qrs,c)

    def test_nonfinite_and_inconsistent_performance_rejected(self):
        for value in (float('nan'),float('inf'),-1):
            c=copy.deepcopy(self.classes);c['records'][0]['modes']['end_to_end']['performance']['wall_seconds']=value
            with self.assertRaises(ValueError):diagnose(self.qrs,c)
        c=copy.deepcopy(self.classes);c['aggregate']['reference_r']['performance']['wall_seconds']+=1
        with self.assertRaises(ValueError):diagnose(self.qrs,c)

    def test_zero_samples_remain_undefined_and_missing_prediction_gives_zero_recall(self):
        score={'labels':['N','S','V'],'confusion':[[0]*3 for _ in range(3)]}
        for key in ('support','predicted','unclassified_target_beats','out_of_scope_predictions','unmatched_predictions'):score[key]=[0]*3
        self.assertIsNone(metrics(checked_score(score))['S']['f1'])
        score['support'][1]=1;score['unclassified_target_beats'][1]=1
        values=metrics(checked_score(score))['S']
        self.assertEqual(values['recall'],0);self.assertEqual(values['f1'],0);self.assertIsNone(values['precision'])


if __name__=='__main__':unittest.main()
