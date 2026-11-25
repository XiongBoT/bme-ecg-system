"""Bounded administrative metadata; never exposes waveforms or credentials."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid

from fastapi import HTTPException
from analysis_tasks import FileLock

SESSION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z')


def connect(data):
    db = sqlite3.connect(Path(data) / 'cloud.sqlite', timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA synchronous=FULL')
    return db


def audit(db, actor, action, target, status='complete', detail=''):
    db.execute('INSERT INTO management_events(actor_id,action,target,status,detail,created) VALUES(?,?,?,?,?,?)',
               (actor, action, target, status, detail[:300], time.time()))


def require_actor(db, actor):
    if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1 AND is_admin=1', (actor,)).fetchone():
        raise HTTPException(403, '管理员权限已失效')


class DatabaseManager:
    def __init__(self, data, mutation_lock=None, active_session=lambda: None):
        self.data = Path(data)
        self.lock = mutation_lock or threading.RLock()
        self.active_session = active_session
        with closing(connect(data)) as db, db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS management_jobs(
                job_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '', processed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
                result TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '');
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_management ON management_jobs((1))
                WHERE status IN ('queued','running');
            CREATE TABLE IF NOT EXISTS management_events(
                id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL,
                target TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS management_events_recent ON management_events(created DESC,id DESC);
            CREATE INDEX IF NOT EXISTS sessions_admin_device_date ON sessions(ingest_device_id,created_at DESC,id DESC);
            CREATE INDEX IF NOT EXISTS sessions_admin_date ON sessions(created_at DESC,id DESC);
            ''')

    def overview(self):
        with closing(connect(self.data)) as db:
            db.execute('BEGIN')
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            # Names originate in SQLite, but still quote them as identifiers.
            counts = {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}
            points = db.execute('SELECT COALESCE(SUM(sample_count),0) FROM sessions').fetchone()[0]
            uploading = db.execute('SELECT COUNT(*) FROM sessions WHERE complete=0').fetchone()[0]
            trashed = db.execute('SELECT COUNT(*) FROM session_details WHERE trashed_at IS NOT NULL').fetchone()[0]
            latest = db.execute("SELECT updated,result FROM management_jobs WHERE kind='scan' AND status='complete' ORDER BY updated DESC LIMIT 1").fetchone()
        try:
            usage = shutil.disk_usage(self.data)
            disk = {'free_bytes': usage.free, 'total_bytes': usage.total}
        except OSError:
            disk = {'free_bytes': None, 'total_bytes': None}
        sizes = {}
        for name in ('cloud.sqlite', 'cloud.sqlite-wal', 'cloud.sqlite-shm'):
            try: sizes[name] = (self.data / name).stat().st_size
            except FileNotFoundError: sizes[name] = 0
            except OSError: sizes[name] = None
        return {'counts': counts, 'sample_count': points, 'uploading': uploading, 'trashed': trashed,
                'database_bytes': sizes, 'disk': disk,
                'storage_scan': {'measured_at': latest['updated'], **json.loads(latest['result'])} if latest else None,
                'backup_policy': 'server_only', 'measured_at': time.time()}

    def records(self, *, limit=25, offset=0, q='', state='active', owner_id=None, device_id=None,
                started_from=None, started_before=None, registered_day=None):
        clauses, params = [], []
        if state == 'trashed': clauses.append('d.trashed_at IS NOT NULL')
        else:
            clauses.append('d.trashed_at IS NULL')
            if state in ('complete', 'uploading'):
                clauses.append('s.complete=?'); params.append(int(state == 'complete'))
        if q.strip():
            clauses.append("instr(lower(s.id||' '||COALESCE(d.name,'')),lower(?))>0"); params.append(q.strip())
        if owner_id == 'unassigned': clauses.append('s.owner_id IS NULL')
        elif owner_id: clauses.append('s.owner_id=?'); params.append(owner_id)
        if device_id: clauses.append('s.ingest_device_id=?'); params.append(device_id)
        if registered_day:
            if registered_day.isoformat() == '9999-12-31':
                raise HTTPException(422, '登记日期须早于 9999-12-31')
            start = datetime.combine(registered_day, datetime.min.time(), timezone(timedelta(hours=8)))
            clauses.append('julianday(s.created_at)>=julianday(?) AND julianday(s.created_at)<julianday(?)')
            params.extend([start.isoformat(), (start + timedelta(days=1)).isoformat()])
        for value, op in ((started_from, '>='), (started_before, '<')):
            if value:
                clauses.append("julianday(json_extract(s.metadata,'$.started_utc'))" + op + 'julianday(?)')
                params.append(value.isoformat())
        join = ' FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id LEFT JOIN users u ON u.id=s.owner_id WHERE ' + ' AND '.join(clauses)
        with closing(connect(self.data)) as db:
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*)' + join, params).fetchone()[0]
            rows = db.execute("SELECT s.id AS session_id,s.owner_id,u.username,s.ingest_device_id AS device_id,"
                "s.created_at,s.sample_count,s.complete,COALESCE(d.name,'') AS name,d.trashed_at,"
                "json_extract(s.metadata,'$.started_utc') AS started_utc,json_extract(s.metadata,'$.source') AS source" +
                join + ' ORDER BY s.created_at DESC,s.id DESC LIMIT ? OFFSET ?', (*params, limit, offset))
            return {'records': [dict(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}

    def change_trash(self, actor, sid, trashed):
        if not SESSION_ID.fullmatch(sid): raise HTTPException(422, '记录编号无效')
        compute = FileLock(self.data / '.analysis-compute.lock')
        with self.lock:
            if not compute.acquire(): raise HTTPException(409, '后台正在分析，请稍后再整理记录')
            try:
                with closing(connect(self.data)) as db, db:
                    db.execute('BEGIN IMMEDIATE'); require_actor(db, actor)
                    item = db.execute('SELECT complete FROM sessions WHERE id=?', (sid,)).fetchone()
                    if item is None: raise HTTPException(404, '记录不存在')
                    pending = db.execute("SELECT 1 FROM analysis_jobs WHERE session_id=? AND status IN ('queued','running')", (sid,)).fetchone()
                    if trashed and (not item['complete'] or pending or self.active_session() == sid):
                        raise HTTPException(409, '请等待上传和分析完成后再移入回收站')
                    stamp = datetime.now(timezone.utc).isoformat() if trashed else None
                    db.execute('INSERT INTO session_details(session_id,trashed_at) VALUES(?,?) '
                        'ON CONFLICT(session_id) DO UPDATE SET trashed_at=excluded.trashed_at', (sid, stamp))
                    audit(db, actor, 'trash' if trashed else 'restore', sid)
                    return {'ok': True, 'session_id': sid, 'trashed_at': stamp}
            finally: compute.release()

    def enqueue(self, actor, kind):
        if kind not in ('scan', 'check', 'backup'): raise HTTPException(422, '未知维护任务')
        with closing(connect(self.data)) as db, db:
            db.execute('BEGIN IMMEDIATE'); require_actor(db, actor)
            if db.execute("SELECT 1 FROM management_jobs WHERE status IN ('queued','running')").fetchone():
                raise HTTPException(409, '已有维护任务，请等待完成')
            jid, stamp = uuid.uuid4().hex, time.time()
            db.execute("INSERT INTO management_jobs(job_id,actor_id,kind,status,stage,created,updated) VALUES(?,?,?,'queued','等待后台处理',?,?)",
                       (jid, actor, kind, stamp, stamp))
            audit(db, actor, kind, jid, 'queued')
            return {'job_id': jid, 'kind': kind, 'status': 'queued'}

    def jobs(self):
        with closing(connect(self.data)) as db:
            rows = db.execute('SELECT * FROM management_jobs ORDER BY created DESC,job_id DESC LIMIT 25')
            return [{**dict(row), 'result': json.loads(row['result'])} for row in rows]

    def activity(self, limit=50, offset=0):
        with closing(connect(self.data)) as db:
            return [dict(row) for row in db.execute('SELECT * FROM management_events ORDER BY created DESC,id DESC LIMIT ? OFFSET ?', (limit, offset))]

    def backups(self):
        with closing(connect(self.data)) as db:
            rows = db.execute("SELECT job_id,updated,result FROM management_jobs WHERE kind='backup' AND status='complete' ORDER BY created DESC LIMIT 100")
            result = []
            for row in rows:
                item = json.loads(row['result'])
                # No absolute path, file URL or credential content leaves the server.
                result.append({'job_id': row['job_id'], 'created': row['updated'],
                    **{key: item.get(key) for key in ('filename', 'bytes', 'sha256', 'chunks', 'sessions')}})
            return result
