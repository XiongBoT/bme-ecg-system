"""Durable analysis queue with one separately scheduled compute process per data directory."""
from contextlib import closing
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from protocol import decode_chunk


class FileLock:
    def __init__(self, path):
        self.path, self.file = Path(path), None

    def acquire(self):
        if self.path.is_symlink(): raise OSError('锁文件不能为符号链接')
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if not self.file.tell(): self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close(); self.file = None
            return False

    def release(self):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close(); self.file = None


def connect(data):
    db = sqlite3.connect(Path(data)/'cloud.sqlite', timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA synchronous=FULL')
    return db


def load_input(data, sid, model):
    with closing(connect(data)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT s.*,d.trashed_at FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE s.id=?', (sid,)).fetchone()
        if row is None or row['trashed_at']: raise ValueError('记录不存在或已移入回收站')
        chunks = [dict(c) for c in db.execute('SELECT * FROM chunks WHERE session_id=? ORDER BY chunk_id', (sid,))]
        metadata = json.loads(row['metadata'])
        manifest = [{k:c[k] for k in ('chunk_id','sha256','sample_count')} for c in chunks]
        return dict(row), metadata, chunks, model.digest(metadata, row['complete'], manifest)


class Interrupted(Exception): pass
class QueueFull(ValueError): pass


def worker(data, configured, stop):
    master, compute = FileLock(Path(data)/'.analysis-worker.lock'), FileLock(Path(data)/'.analysis-compute.lock')
    while not stop.is_set() and not master.acquire(): stop.wait(.25)
    if stop.is_set(): master.release(); return
    try:
        from cloud_model.engine import AnalysisService
        from physiology_analysis import PhysiologyService
        model = AnalysisService(Path(data), configured)
        physiology = PhysiologyService(Path(data))
        with closing(connect(data)) as db, db:
            db.execute("UPDATE analysis_jobs SET status='queued',stage='服务重启，等待恢复',updated=? WHERE status='running'", (time.time(),))
        while not stop.is_set():
            with closing(connect(data)) as db:
                item = db.execute("SELECT * FROM analysis_jobs WHERE status='queued' ORDER BY created,job_id LIMIT 1").fetchone()
            if item is None: stop.wait(.4); continue
            while not stop.is_set() and not compute.acquire(): stop.wait(.25)
            if stop.is_set(): compute.release(); break
            job = dict(item)
            def update(**fields):
                fields['updated'] = time.time()
                with closing(connect(data)) as db, db:
                    db.execute('UPDATE analysis_jobs SET '+','.join(k+'=?' for k in fields)+' WHERE job_id=?', (*fields.values(), job['job_id']))
            try:
                update(status='running', stage='正在校验并分析', worker_pid=os.getpid(), processed=0)
                service = {'model': model, 'physiology': physiology}[job['kind']]
                item, metadata, chunks, digest = load_input(data, job['session_id'], service)
                if digest != job['source_digest']: raise ValueError('记录或分析版本已变化，请重新提交分析')
                if not item['complete']: raise ValueError('记录尚未上传完成')
                def batches():
                    processed, last_update = 0, 0
                    for chunk in chunks:
                        if stop.is_set(): raise Interrupted()
                        raw = (Path(data)/'sessions'/job['session_id']/'chunks'/f"{chunk['chunk_id']:08d}.bin").read_bytes()
                        rows = decode_chunk(raw, chunk['sha256'])
                        yield json.loads(chunk['descriptor']), rows
                        processed += len(rows)
                        if time.monotonic()-last_update >= .2 or processed == item['sample_count']:
                            update(processed=processed)
                            last_update = time.monotonic()
                result = service.run(job['session_id'], metadata, item['complete'], item['sample_count'], digest, batches())
                if stop.is_set(): raise Interrupted()
                status = result['analysis_status']
                update(status=status if status in ('complete','ineligible','failed','not_configured') else 'failed',
                       stage=result.get('message','分析结束')[:300], processed=item['sample_count'],
                       error=result.get('message','')[:300] if status in ('failed','not_configured') else '')
            except Interrupted:
                update(status='queued', stage='服务停止，等待下次恢复')
            except Exception as exc:
                update(status='failed', stage='分析未完成，可重试', error=str(exc)[:300])
            finally:
                compute.release()
    finally:
        compute.release(); master.release()


class AnalysisQueue:
    def __init__(self, data, configured):
        self.data, self.configured = Path(data), configured
        self.context = multiprocessing.get_context('spawn')
        self.process = self.stop = None
        self.lock = threading.Lock()
        with closing(connect(self.data)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''
            CREATE TABLE IF NOT EXISTS analysis_jobs(job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                source_digest TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                error TEXT NOT NULL DEFAULT '', worker_pid INTEGER, kind TEXT NOT NULL DEFAULT 'model')''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(analysis_jobs)')}
            if 'kind' not in columns:
                db.execute("ALTER TABLE analysis_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'model'")
            db.execute('DROP INDEX IF EXISTS one_active_analysis')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_analysis_kind ON analysis_jobs(session_id,kind) WHERE status IN ('queued','running')")

    def start(self):
        with self.lock:
            if self.process is not None and self.process.is_alive(): return
            if self.process is not None: self.process.close()
            self.stop = self.context.Event()
            self.process = self.context.Process(target=worker, args=(str(self.data), self.configured, self.stop), name='ecg-cloud-analysis', daemon=True)
            self.process.start()

    def close(self):
        with self.lock:
            if self.process is None: return
            self.stop.set(); self.process.join(4)
            if self.process.is_alive(): self.process.terminate(); self.process.join(3)
            self.process.close(); self.process = None

    def has_pending(self):
        with closing(connect(self.data)) as db:
            return db.execute("SELECT 1 FROM analysis_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone() is not None

    def latest(self, sid, kind='model'):
        with closing(connect(self.data)) as db:
            row = db.execute('SELECT * FROM analysis_jobs WHERE session_id=? AND kind=? ORDER BY created DESC,job_id DESC LIMIT 1', (sid,kind)).fetchone()
            return dict(row) if row else None

    def get(self, job_id):
        with closing(connect(self.data)) as db:
            row = db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def enqueue(self, sid, digest, total, force=False, cached=False, authorize=None, kind='model', job_id=None, on_enqueued=None):
        if kind not in ('model','physiology'): raise ValueError('未知分析类型')
        with closing(connect(self.data)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if authorize is not None:authorize(db)
            def accepted(row):
                result = dict(row)
                if on_enqueued is not None: on_enqueued(db, result)
                return result
            if job_id:
                prior = db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone()
                if prior: return accepted(prior)
            row = db.execute('SELECT s.complete,d.trashed_at FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE s.id=?',(sid,)).fetchone()
            if not row or not row['complete'] or row['trashed_at']:
                raise ValueError('记录未完成或已移入回收站')
            row = db.execute("SELECT * FROM analysis_jobs WHERE session_id=? AND kind=? AND status IN ('queued','running')", (sid,kind)).fetchone()
            if row: return accepted(row)
            if cached and not force:
                row = db.execute("SELECT * FROM analysis_jobs WHERE session_id=? AND kind=? AND source_digest=? ORDER BY created DESC,job_id DESC LIMIT 1", (sid,kind,digest)).fetchone()
                if row and row['status'] in ('complete','ineligible'): return accepted(row)
            if db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 64:
                raise QueueFull('分析队列已满，请稍后提交')
            jid, stamp = job_id or uuid.uuid4().hex, time.time()
            db.execute("INSERT INTO analysis_jobs(job_id,session_id,source_digest,status,stage,total,created,updated,kind) VALUES(?,?,?,'queued','等待后台分析',?,?,?,?)",
                       (jid,sid,digest,total,stamp,stamp,kind))
            return accepted(db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (jid,)).fetchone())
