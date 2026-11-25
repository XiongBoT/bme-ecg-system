"""Explicitly enabled, serialized inference over immutable uploaded records."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

NAME = 'CardioEdgeAI v1 INT8'
VERSION = 'cardioedge-v1-int8-cloud1'
NOTICE = '课程研究模型输出，不作为临床诊断；N类包含束支阻滞，S类能力有限，分数不是诊断概率。'
ROOT = Path(__file__).resolve().parent
MAX_SAMPLES = 1000000


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class AnalysisBusy(Exception):
    pass


class AnalysisService:
    def __init__(self, data, configured=''):
        if configured not in ('', 'none', 'cardioedge'):
            raise ValueError('ECG_MODEL仅支持none或cardioedge')
        self.directory = Path(data) / 'analysis'
        self.enabled = configured == 'cardioedge'
        self.model_status = 'not_configured'
        self.error = None
        self.active_session = None
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.fingerprint = 'disabled'
        if self.enabled:
            try:
                from .vendor.cardioedge.stream import StreamingClassifier, WEIGHT_HASH
                from .vendor.contracts import SamplePoint, SampleBatch
                # Constructor checks the pinned weight hash before NumPy loads it.
                engine = StreamingClassifier()
                self.candidate = engine.model
                self.classifier_type = StreamingClassifier
                self.point_type, self.batch_type = SamplePoint, SampleBatch
                fingerprint = hashlib.sha256()
                for path in sorted(ROOT.rglob('*.py')):
                    fingerprint.update(path.relative_to(ROOT).as_posix().encode())
                    fingerprint.update(path.read_bytes())
                fingerprint.update(WEIGHT_HASH.encode())
                self.fingerprint = fingerprint.hexdigest()
                self.model_status = 'ready'
            except Exception as exc:
                self.error = str(exc)[:500]
                self.model_status = 'error'

    def identity(self):
        return {'model_status': self.model_status, 'model_result': None,
                'model_name': NAME if self.enabled else None,
                'model_version': VERSION if self.enabled else None}

    def digest(self, metadata, complete, manifest):
        content = {'metadata': metadata, 'complete': bool(complete), 'manifest': manifest,
                   'model_fingerprint': self.fingerprint, 'model_version': VERSION}
        return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def response(self, sid, status, message, digest=None, **fields):
        return {**self.identity(), 'session_id': sid, 'analysis_status': status,
                'message': message, 'source_digest': digest, 'analyzed_at': None,
                'input_summary': None, **fields}

    def read(self, sid, digest):
        if not self.enabled:
            return self.response(sid, 'not_configured', '未接入模型', digest)
        if self.model_status != 'ready':
            return self.response(sid, 'failed', '模型加载失败：' + str(self.error), digest)
        with self.state_lock:
            if self.active_session == sid:
                return self.response(sid, 'running', '正在读取已保存记录并分析', digest)
        path = self.directory / f'{sid}.json'
        if not path.is_file():
            return self.response(sid, 'not_run', '模型已就绪，点击分析以复核已上传记录', digest)
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved['source_digest'] != digest or saved['model_version'] != VERSION:
                return self.response(sid, 'stale', '记录或模型版本已变化，需要重新分析', digest)
            if saved['session_id'] != sid or saved['analysis_status'] not in ('complete', 'ineligible', 'failed'):
                raise ValueError('结果元数据不正确')
            return saved
        except (OSError, ValueError, KeyError):
            return self.response(sid, 'failed', '已有分析结果无法读取，请重新分析', digest)

    def save(self, sid, response):
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f'{sid}.json'
        temporary = target.with_suffix(f'.{uuid.uuid4().hex}.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(response, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            if os.name != 'nt':
                fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def run(self, sid, metadata, complete, sample_count, digest, batches):
        if not self.enabled or self.model_status != 'ready':
            return self.read(sid, digest)
        if not self.lock.acquire(blocking=False):
            raise AnalysisBusy('已有模型分析正在运行，请等待完成后重试')
        with self.state_lock:
            self.active_session = sid
        try:
            if not complete:
                result = self.response(sid, 'ineligible', '会话尚未上传完成，结束采集并传完后再分析', digest)
            elif sample_count > MAX_SAMPLES:
                result = self.response(sid, 'ineligible', '单次模型分析限100万点，请按会话分段保存', digest)
            else:
                result = self._analyze(sid, metadata, sample_count, digest, batches)
            result['analyzed_at'] = utc_now()
            self.save(sid, result)
            return result
        finally:
            with self.state_lock:
                self.active_session = None
            self.lock.release()

    def _analyze(self, sid, metadata, expected_count, digest, batches):
        source = metadata['source']
        source_allowed = source in ('serial', 'replay')
        engine = self.classifier_type(vref=metadata['vref_v'], sample_rate=metadata['sample_rate_hz'], model=self.candidate)
        beats, rejections = [], []
        rejection_counts, skipped_reasons = Counter(), Counter()
        total = eligible = 0
        for descriptor, rows in batches:
            points = tuple(self.point_type(*row) for row in rows)
            total += len(points)
            for point in points:
                if not source_allowed:
                    skipped_reasons['source_not_real'] += 1
                elif point.mode == 1:
                    skipped_reasons['board_simulated'] += 1
                elif point.mode != 0:
                    skipped_reasons['mode_unknown'] += 1
                elif not point.valid:
                    skipped_reasons['invalid_adc'] += 1
                else:
                    eligible += 1
            batch = self.batch_type(sid, source, points, time.monotonic(), descriptor['received_last_utc'])
            for item in engine.process(batch):
                scores = {label: float(item['scores'][label]) for label in ('N', 'S', 'V')}
                beats.append({'sample_id': item['r_sample'], 'time_s': item['r_sample'] / 360,
                    'label': item['label'], 'score': scores[item['label']], 'scores': scores,
                    'segment_id': item['segment_id'], 'requires_review': item['requires_review'],
                    'classified_at_sample': item['classified_at_sample']})
            for rejected in engine.take_rejections():
                rejection_counts[rejected['reason']] += 1
                if len(rejections) < 500:
                    rejections.append({'sample_id': rejected['r_sample'], 'reason': rejected['reason']})
        if total != expected_count:
            raise ValueError('模型输入点数与会话索引不同')
        input_summary = {'total_samples': total, 'eligible_samples': eligible,
                         'skipped_samples': total - eligible, 'skipped_reasons': dict(skipped_reasons),
                         'source_policy': 'serial/replay + mode=0 + valid ADC; signal quality gate also applies'}
        snapshot = engine.snapshot()
        if not beats:
            if not source_allowed:
                message = '本地合成或来源未知的数据不参与分类'
            elif not eligible:
                message = '没有有效实采数据：板端模拟、未知模式和无效ADC均不参与分类'
            else:
                message = '未产生可分类心搏：' + snapshot['detail']
            return self.response(sid, 'ineligible', message, digest, input_summary=input_summary)
        counts = {label: sum(beat['label'] == label for beat in beats) for label in ('N', 'S', 'V')}
        result = {'beat_count': len(beats), 'counts': counts,
                  'percentages': {k: round(v * 100 / len(beats), 2) for k, v in counts.items()},
                  'beats': beats, 'eligible_samples': eligible, 'skipped_samples': total - eligible,
                  'segments_analyzed': len({beat['segment_id'] for beat in beats}),
                  'quality_rejections': rejections, 'quality_rejection_counts': dict(rejection_counts),
                  'quality_rejections_truncated': sum(rejection_counts.values()) > len(rejections),
                  'notice': NOTICE}
        return self.response(sid, 'complete', f'已分析{len(beats)}个心搏；' + NOTICE,
                             digest, model_result=result, input_summary=input_summary)
