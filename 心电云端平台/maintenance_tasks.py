"""One low-priority maintenance process per data directory, with durable status."""
from contextlib import closing
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time

from analysis_tasks import FileLock
from database_management import connect, audit
from database_backup import scan_storage, check_snapshot, create_backup, cleanup_interrupted
from backup_schedule import scheduled_job_started


class Stopped(Exception): pass


def worker(data, stop):
    data = Path(data)
    master = FileLock(data / '.maintenance-worker.lock')
    while not stop.is_set() and not master.acquire(): stop.wait(.25)
    if stop.is_set(): master.release(); return
    try:
        if hasattr(os, 'nice'): os.nice(5)
        cleaned, cleanup_error = 0, ''
        try: cleaned = cleanup_interrupted(data)
        except (OSError, ValueError, sqlite3.Error):
            cleanup_error = '未能检查遗留临时文件，请核对服务器维护目录权限和类型；文件已保留'
        with closing(connect(data)) as db, db:
            if cleaned: audit(db, 'system', 'cleanup', 'maintenance', 'complete', f'清理 {cleaned} 个本模块遗留临时目录')
            if cleanup_error: audit(db, 'system', 'cleanup', 'maintenance', 'failed', cleanup_error)
            for row in db.execute("SELECT * FROM management_jobs WHERE status='running'").fetchall():
                audit(db, row['actor_id'], row['kind'], row['job_id'], 'interrupted', '维护进程中断，请重新执行')
            db.execute("UPDATE management_jobs SET status='interrupted',stage='维护进程中断，请重新执行',updated=? WHERE status='running'", (time.time(),))
        while not stop.is_set():
            with closing(connect(data)) as db, db:
                row = db.execute("SELECT * FROM management_jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    now = time.time()
                    db.execute("UPDATE management_jobs SET status='running',stage='开始处理',updated=? WHERE job_id=?", (now, row['job_id']))
                    scheduled_job_started(db, row['job_id'], now)
            if row is None: stop.wait(.3); continue
            job = dict(row)
            last_update = 0
            def progress(processed, total, stage):
                nonlocal last_update
                if stop.is_set(): raise Stopped()
                if stage is None: return
                if time.monotonic() - last_update >= .4 or (total and processed == total):
                    with closing(connect(data)) as db, db:
                        db.execute('UPDATE management_jobs SET processed=?,total=?,stage=?,updated=? WHERE job_id=?',
                                   (processed, total, stage, time.time(), job['job_id']))
                    last_update = time.monotonic()
            try:
                if job['kind'] == 'scan': result = scan_storage(data, progress)
                elif job['kind'] == 'check': result = check_snapshot(data, progress, job_id=job['job_id'])
                elif job['kind'] == 'backup': result = create_backup(data, job['job_id'], progress)
                else: raise ValueError('未知维护任务')
                status, error = 'complete', ''
                stage = '检查完成，发现问题' if result.get('ok') is False else '处理完成'
            except Stopped:
                status, error, stage, result = 'interrupted', '服务停止，任务未完成', '已中断，可重新执行', {}
            except Exception as exc:
                # Avoid leaking server paths through arbitrary OS exception strings.
                message = str(exc) if isinstance(exc, ValueError) else '维护失败，请检查服务器空间、权限及数据文件'
                status, error, stage, result = 'failed', message[:250], '未完成，可重试', {}
            with closing(connect(data)) as db, db:
                db.execute('UPDATE management_jobs SET status=?,stage=?,error=?,result=?,updated=? WHERE job_id=?',
                           (status, stage, error, json.dumps(result, ensure_ascii=False), time.time(), job['job_id']))
                audit(db, job['actor_id'], job['kind'], job['job_id'], status, error or stage)
    finally: master.release()


class MaintenanceQueue:
    def __init__(self, data):
        self.data = Path(data)
        self.context = multiprocessing.get_context('spawn')
        self.process = self.stop = None
        self.lock = threading.Lock()

    def has_pending(self):
        with closing(connect(self.data)) as db:
            return db.execute("SELECT 1 FROM management_jobs WHERE status IN ('queued','running')").fetchone() is not None

    def start(self):
        with self.lock:
            if self.process is not None and self.process.is_alive(): return
            if self.process is not None: self.process.close()
            self.stop = self.context.Event()
            self.process = self.context.Process(target=worker, args=(str(self.data), self.stop), name='ecg-maintenance', daemon=True)
            self.process.start()

    def close(self):
        with self.lock:
            if self.process is None: return
            self.stop.set(); self.process.join(4)
            if self.process.is_alive(): self.process.terminate(); self.process.join(3)
            self.process.close(); self.process = None
