"""Durable daily server-only backups, submitted to the existing maintenance queue."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import logging
import shutil
import threading
from time import time as clock
import uuid

from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from database_management import connect,audit,require_actor

LOCAL=timezone(timedelta(hours=8))
MIN_FREE=1024**3
log=logging.getLogger(__name__)


class ScheduleInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: StrictBool
    hour: int=Field(ge=0,le=23,strict=True)
    minute: int=Field(ge=0,le=59,strict=True)
    revision: int=Field(ge=0,strict=True)


def next_time(now,hour,minute):
    day=datetime.fromtimestamp(now,LOCAL).replace(hour=hour,minute=minute,second=0,microsecond=0)
    if day.timestamp()<=now:day+=timedelta(days=1)
    return day.timestamp()


def scheduled_job_started(db,job_id,now):
    """A queued backup resumed after downtime covers all missed daily slots.

    Called in the worker's claim transaction, so stale running/interrupted jobs
    cannot consume a catch-up slot without actually starting a backup.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_schedule_runs'").fetchone():return
    if not db.execute('SELECT 1 FROM backup_schedule_runs WHERE job_id=?',(job_id,)).fetchone():return
    row=db.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone()
    if row and row['enabled'] and row['next_due'] is not None and row['next_due']<=now:
        db.execute("UPDATE backup_schedule SET next_due=?,retry_after=0,state='scheduled',message='已恢复排队备份，覆盖停机期间遗漏的执行日期' WHERE id=1",
                   (next_time(now,row['hour'],row['minute']),))


class BackupSchedule:
    def __init__(self,data,queue):
        self.data,self.queue=data,queue
        self.stop=threading.Event();self.thread=None
        with closing(self.connect()) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS backup_schedule(
                id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 0,
                hour INTEGER NOT NULL DEFAULT 2,minute INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,
                next_due REAL,retry_after REAL NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'disabled',
                message TEXT NOT NULL DEFAULT '',updated REAL NOT NULL DEFAULT 0,actor_id TEXT);
            INSERT OR IGNORE INTO backup_schedule(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS backup_schedule_runs(
                due REAL PRIMARY KEY,job_id TEXT NOT NULL UNIQUE,created REAL NOT NULL);
            ''')

    def connect(self):return connect(self.data)

    def read(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            row=dict(db.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone())
            last=db.execute('SELECT r.due,j.job_id,j.status,j.stage,j.error,j.updated FROM backup_schedule_runs r JOIN management_jobs j ON j.job_id=r.job_id ORDER BY r.created DESC,r.due DESC LIMIT 1').fetchone()
        return {k:row[k] for k in ('hour','minute','revision','next_due','state','message','updated')} | {
            'enabled':bool(row['enabled']),'timezone':'Asia/Shanghai','retention':'keep_all',
            'server_only':True,'last_run':dict(last) if last else None}

    def save(self,actor,values):
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE');require_actor(db,actor)
            row=db.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone()
            if row['revision']!=values['revision']:raise HTTPException(409,'计划已被其他页面修改，请刷新后再保存')
            now=clock();enabled=values['enabled']
            # Unchanged schedule keeps its due time, including a deferred/catch-up run.
            unchanged=enabled and row['enabled'] and row['hour']==values['hour'] and row['minute']==values['minute']
            due=row['next_due'] if unchanged else next_time(now,values['hour'],values['minute']) if enabled else None
            db.execute('UPDATE backup_schedule SET enabled=?,hour=?,minute=?,revision=revision+1,next_due=?,retry_after=0,state=?,message=?,updated=?,actor_id=? WHERE id=1',
                       (enabled,values['hour'],values['minute'],due,'scheduled' if enabled else 'disabled','',now,actor))
            audit(db,actor,'backup_schedule','daily','complete',f"{'启用' if enabled else '关闭'}每天北京时间 {values['hour']:02d}:{values['minute']:02d}；备份保留在服务器")
        return self.read()

    def tick(self,now=None):
        now=clock() if now is None else now
        # Recover the committed handoff even if the prior process died before start().
        if self.queue.has_pending():self.queue.start()
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone()
            if not row['enabled'] or row['next_due'] is None or row['next_due']>now or row['retry_after']>now:return False
            if db.execute("SELECT 1 FROM management_jobs WHERE status IN ('queued','running')").fetchone():
                db.execute("UPDATE backup_schedule SET state='waiting',message='已有维护任务，完成后补做备份' WHERE id=1")
                return False
            try:free=shutil.disk_usage(self.data).free
            except OSError:free=0
            if free<MIN_FREE:
                db.execute("UPDATE backup_schedule SET state='blocked',message='剩余空间不足1 GiB或无法读取空间，15分钟后重试；不会自动删除旧备份',retry_after=? WHERE id=1",(now+900,))
                return False
            due=row['next_due'];jid=uuid.uuid4().hex
            # SQLite transaction and unique due make simultaneous servers idempotent.
            if not db.execute('SELECT 1 FROM backup_schedule_runs WHERE due=?',(due,)).fetchone():
                db.execute("INSERT INTO management_jobs(job_id,actor_id,kind,status,stage,created,updated) VALUES(?,'system:scheduled-backup','backup','queued','定时备份等待处理',?,?)",(jid,now,now))
                db.execute('INSERT INTO backup_schedule_runs VALUES(?,?,?)',(due,jid,now))
                audit(db,'system:scheduled-backup','backup',jid,'queued','每日备份；错过多天时仅补做一次')
            db.execute("UPDATE backup_schedule SET next_due=?,retry_after=0,state='scheduled',message='' WHERE id=1",(next_time(now,row['hour'],row['minute']),))
        self.queue.start()
        return True

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop.clear();self.thread=threading.Thread(target=self.run,name='ecg-backup-schedule',daemon=True);self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception:log.exception('Backup schedule check failed; retained durable state for retry')
            self.stop.wait(30)

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join()


def add_routes(app,store,require_admin,current_user):
    @app.get('/api/admin/database/backup-schedule')
    def read():require_admin();return store.read()

    @app.put('/api/admin/database/backup-schedule')
    def save(payload:ScheduleInput):
        require_admin();return store.save(current_user()['id'],payload.model_dump())
