"""Reproducible error decomposition of completed fixed-model benchmark reports."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from research.render_benchmark import MODES, pct, table, validate_reports

LABELS = ['N','S','V']
COUNTS = ['support','predicted','unclassified_target_beats','out_of_scope_predictions','unmatched_predictions']


def checked_score(score):
    if score['labels'] != LABELS: raise ValueError('Unexpected class order')
    vectors=[score[k] for k in COUNTS]+score['confusion']
    if len(score['confusion'])!=3 or any(len(v)!=3 for v in vectors): raise ValueError('Invalid matrix shape')
    if any(type(n) is not int or n<0 for v in vectors for n in v): raise ValueError('Invalid count')
    matrix=score['confusion']
    for i in range(3):
        if sum(matrix[i])+score['unclassified_target_beats'][i]!=score['support'][i]: raise ValueError('Reference counts do not conserve')
        if sum(row[i] for row in matrix)+score['out_of_scope_predictions'][i]+score['unmatched_predictions'][i]!=score['predicted'][i]: raise ValueError('Prediction counts do not conserve')
    return score


def ratio(a,b): return a/b if b else None


def metrics(score):
    return {label:{'precision':ratio(score['confusion'][i][i],score['predicted'][i]),
                   'recall':ratio(score['confusion'][i][i],score['support'][i]),
                   'f1':ratio(2*score['confusion'][i][i],score['support'][i]+score['predicted'][i])}
            for i,label in enumerate(LABELS)}


def s_errors(score):
    return dict(support=score['support'][1],correct=score['confusion'][1][1],
                to_n=score['confusion'][1][0],to_v=score['confusion'][1][2],
                no_matched_output=score['unclassified_target_beats'][1],
                false_s_from_n=score['confusion'][0][1],false_s_from_v=score['confusion'][2][1],
                false_s_other=score['out_of_scope_predictions'][1],false_s_unmatched=score['unmatched_predictions'][1])


def diagnose(qrs, classifier):
    validate_reports(qrs,classifier)
    if classifier['configuration']['model']['weights_sha256'] != classifier['code_sha256'].get('cloud_model/vendor/cardioedge/portable_weights.npz'):
        raise ValueError('Model weight provenance differs')
    result={'schema':1,'cohort':classifier['configuration']['records'],
            'weights_sha256':classifier['configuration']['model']['weights_sha256'],
            'environment':{k:classifier['environment'][k] for k in ('python','platform','machine','thread_limits','packages')},'modes':{}}
    for mode in MODES:
        aggregates=classifier['aggregate'][mode]
        for tolerance in (150,50):
            key=f'scores_{tolerance}ms';total=checked_score(aggregates[key])
            rows=[checked_score(r['modes'][mode][key]) for r in classifier['records']]
            for field in COUNTS:
                if [sum(row[field][i] for row in rows) for i in range(3)]!=total[field]: raise ValueError('Aggregate count differs from records')
            if [[sum(row['confusion'][i][j] for row in rows) for j in range(3)] for i in range(3)]!=total['confusion']: raise ValueError('Aggregate matrix differs from records')
            if mode=='reference_r':
                if any(r['modes'][mode][key]['support']!=r['modes']['end_to_end'][key]['support'] for r in classifier['records']): raise ValueError('Reference-R cohort differs')
        score=aggregates['scores_150ms'];per_record=[];reasons=Counter();wall=signal=0
        for record in classifier['records']:
            item=record['modes'][mode];perf=item['performance']
            counts=list(item['rejection_reasons'].values())
            if any(type(n) is not int or n<0 for n in counts) or sum(counts)!=item['rejected_candidates']:
                raise ValueError('Rejection reasons do not conserve')
            values=[record['signal_seconds'],perf['wall_seconds']]+[perf[k] for k in ('block_p95_ms','confirmation_p95_ms','inference_p95_ms') if perf[k] is not None]
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values) or record['signal_seconds']<=0: raise ValueError('Invalid performance timing')
            wall+=perf['wall_seconds'];signal+=record['signal_seconds'];reasons.update(item['rejection_reasons'])
            errors=s_errors(item['scores_150ms'])
            per_record.append(dict(record=record['record'],**errors,misses=errors['support']-errors['correct'],performance=perf))
        if not math.isclose(wall,aggregates['performance']['wall_seconds'],rel_tol=1e-9) or not math.isclose(signal,aggregates['performance']['signal_seconds'],rel_tol=1e-9): raise ValueError('Aggregate timing differs')
        if sum(r['modes'][mode]['rejected_candidates'] for r in classifier['records'])!=aggregates['rejected_candidates']: raise ValueError('Rejected candidate count differs')
        per_record.sort(key=lambda r:(-r['misses'],r['record']))
        missed=score['support'][1]-score['confusion'][1][1]
        for row in per_record: row['share_of_s_misses']=ratio(row['misses'],missed)
        result['modes'][mode]=dict(s_errors=s_errors(score),metrics=metrics(score),
            metrics_50ms=metrics(aggregates['scores_50ms']),coverage=ratio(sum(map(sum,score['confusion'])),sum(score['support'])),
            wall_seconds=wall,signal_seconds=signal,real_time_factor=ratio(wall,signal),
            rejected_candidates=aggregates['rejected_candidates'],rejection_reasons=dict(sorted(reasons.items())),records=per_record)
    return result


def render(result):
    lines=['# 当前固定模型的分类误差诊断','',
        '[评测导航](README.md) · [原始分类汇总](classification-benchmark.json) · [机器可读诊断](classification-diagnostics.json) · [复跑说明](../../心电云端平台/research/README.md)','',
        '本页重算已有公开数据评测的汇总，不是新一轮推理或训练。模型、阈值、质量门控与默认算法均未改变。', '',
        f"固定队列 {len(result['cohort'])} 条；权重 SHA-256：`{result['weights_sha256']}`。主指标使用 150 ms 匹配。",'',
        '## 类别性能与 S 类误差','']
    rows=[]
    for mode,label in MODES.items():
        value=result['modes'][mode]
        for cls,m in value['metrics'].items(): rows.append([label,cls,pct(m['precision']),pct(m['recall']),pct(m['f1']),pct(value['metrics_50ms'][cls]['f1'])])
    lines += [table(['路径','类别','精确率','召回率','F1（150 ms）','F1（50 ms）'],rows),'']
    fields=[('support','参考 S 心搏'),('correct','正确 S'),('to_n','S → N'),('to_v','S → V'),('no_matched_output','S 未匹配到输出'),('false_s_from_n','N → S'),('false_s_from_v','V → S'),('false_s_other','非目标心搏 → S'),('false_s_unmatched','无参考匹配的 S 预测')]
    lines += [table(['项目',*MODES.values()],[[label,*[result['modes'][mode]['s_errors'][key] for mode in MODES]] for key,label in fields]),'',
        '前四项分解满足：参考 S = 正确 S + S→N + S→V + 未匹配输出。S 精确率分母还包含 N/V/非目标心搏误分及无参考匹配预测；未输出不当作 N。','']
    a,b=[result['modes'][m] for m in MODES]
    lines += ['## 能支持的结论与待验证原因','',
        f"实际路径 S→N 为 {a['s_errors']['to_n']} 拍，占参考 S 的 {pct(ratio(a['s_errors']['to_n'],a['s_errors']['support']))}。参考 R 对照中仍有 {b['s_errors']['to_n']} 拍 S→N。仅更换 R 位置不能消除本次主要分类混淆。",
        f"参考 R 对照的 S 正确输出比实际路径净增加 {b['s_errors']['correct']-a['s_errors']['correct']} 拍；这是总量差异，不能认定这些拍与原误差逐拍一一对应。",'',
        '- “未匹配输出”合并了漏检、门控、上下文不足、拒绝与匹配误差；当前汇总无法把每个 S 心搏分配到具体原因。拒绝候选没有参考类别，不能把总拒绝数当作 S 类漏检数。',
        '- 下一步按下表优先回看公开数据的 S→N、S→V、未输出及误报 S 片段，并对齐逐拍 R 偏差、质量门控、RR 和模型输入。形态重叠、类别不平衡、滚动归一化或域差异只是待检验假设。',
        '- 本报告定位候选方向，不据此在测试集调参。后续若训练，须重新固定患者级训练/验证/测试划分，再比较模型。', '',
        '## 各记录对 S 类未正确输出的贡献','',
        '按实际路径的 S 未正确输出数排序；包含误分类和未输出。无 S 的记录仍可能贡献 S 误报，见最后一列。','']
    rows=[]
    for r in a['records']:
        rows.append([r['record'],r['support'],r['correct'],r['to_n'],r['to_v'],r['no_matched_output'],pct(r['share_of_s_misses']),sum(r[k] for k in ('false_s_from_n','false_s_from_v','false_s_other','false_s_unmatched'))])
    lines += [table(['记录','S 支持数','正确 S','S→N','S→V','未输出','占全部 S 未正确输出','误报 S'],rows),'',
        '## 性能口径','',
        table(['路径','信号时长（秒）','处理墙钟（秒）','处理/信号时间'],[[label,f"{result['modes'][mode]['signal_seconds']:.2f}",f"{result['modes'][mode]['wall_seconds']:.2f}",f"{result['modes'][mode]['real_time_factor']:.5f}"] for mode,label in MODES.items()]),'',
        f"原评测环境：Python {result['environment']['python']}，{result['environment']['platform']}，{result['environment']['machine']}；线程限制 `{json.dumps(result['environment']['thread_limits'],sort_keys=True)}`。本次复用原计时，未重新测量。",'',
        '逐记录块处理、推理及确认延迟 P95 保存在诊断 JSON。各记录 P95 不能直接平均成全队列 P95；处理/信号时间不是在线并发容量，也不包含公网、上传或排队耗时。参考 R 路径跳过检测过程，其计时只作诊断对照。','',
        '## 复现与边界','',
        '从云端目录运行 `python -m research.classification_diagnostics` 生成本页及 JSON；追加 `--check` 只核对是否过期。输入摘要、生成器摘要、计数守恒、同队列及共享评测协议均被检查。','',
        '数据为此前已用于探索的 MIT-BIH 公开数据，未进行全新盲测、真实设备或临床有效性验证。无样本/无预测的比率显示“—”；原始心电和账号数据不随诊断输出。','']
    return '\n'.join(lines)


def main():
    root=Path(__file__).resolve().parents[2];folder=root/'docs'/'algorithm-validation'
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true');args=parser.parse_args()
    paths=[folder/'qrs-comparison.json',folder/'classification-benchmark.json']
    qrs,classes=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    result=diagnose(qrs,classes)
    result['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result['generator_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    outputs={folder/'classification-diagnostics.json':json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',folder/'分类误差诊断.md':render(result)}
    for path,content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=content: raise SystemExit('Stale diagnostic: '+path.name)
        else:path.write_text(content,encoding='utf-8',newline='\n')
    print('Classification diagnostics checked' if args.check else 'Classification diagnostics generated')


if __name__=='__main__':main()
