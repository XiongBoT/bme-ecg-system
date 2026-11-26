"""Account workflows without modifying raw records or algorithm decisions."""
from contextlib import closing
import hashlib
import json
import logging
from pathlib import Path
import shutil
import threading
import time
import uuid

from fastapi import HTTPException
from analysis_tasks import connect, load_input, QueueFull

log = logging.getLogger(__name__)


class Cancelled(ValueError): pass


def cancel_record_intents(db, sid):
    # Also safe for standalone administration of a database predating workflows.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_intents'").fetchone():
        db.execute("UPDATE workflow_intents SET status='cancelled',message='记录已移入回收站，恢复后请手动提交',updated=? WHERE session_id=? AND status IN ('pending','blocked')", (time.time(), sid))


class WorkflowStore:
    def __init__(self, data, queue, model, physiology):
        self.data, self.queue = Path(data), queue
        self.services = {'model': model, 'physiology': physiology}
        self.stop = threading.Event()
        self.thread = None
        with closing(self.connect()) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS workflow_preferences(
                user_id TEXT PRIMARY KEY REFERENCES users(id),auto_model INTEGER NOT NULL DEFAULT 0,
                auto_physiology INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS workflow_intents(
                id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),owner_id TEXT NOT NULL,
                kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',job_id TEXT,
                message TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,next_try REAL NOT NULL DEFAULT 0,
                UNIQUE(session_id,kind));
            CREATE INDEX IF NOT EXISTS workflow_pending ON workflow_intents(status,next_try);
            CREATE TABLE IF NOT EXISTS record_reviews(
                session_id TEXT PRIMARY KEY REFERENCES sessions(id),owner_id TEXT NOT NULL,
                status TEXT NOT NULL,note TEXT NOT NULL,revision INTEGER NOT NULL,context TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS review_events(
                id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,actor_id TEXT NOT NULL,
                status TEXT NOT NULL,revision INTEGER NOT NULL,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS analysis_session_recent ON analysis_jobs(session_id,kind,created DESC,job_id DESC);
            ''')

    def connect(self): return connect(self.data)

    @staticmethod
    def require_user(db, uid):
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (uid,)).fetchone():
            raise HTTPException(403, '账号已失效，请重新登录')

    def preferences(self, uid, values=None):
        with closing(self.connect()) as db, db:
            if values is not None: db.execute('BEGIN IMMEDIATE')
            self.require_user(db, uid)
            if values is not None:
                db.execute('INSERT INTO workflow_preferences VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET auto_model=excluded.auto_model,auto_physiology=excluded.auto_physiology',
                           (uid, values['auto_model'], values['auto_physiology']))
                for kind in self.services:
                    if not values['auto_'+kind]:
                        db.execute("UPDATE workflow_intents SET status='cancelled',message='已关闭自动分析',updated=? WHERE owner_id=? AND kind=? AND status IN ('pending','blocked')", (time.time(), uid, kind))
            row = db.execute('SELECT auto_model,auto_physiology FROM workflow_preferences WHERE user_id=?', (uid,)).fetchone()
            return {key: bool(row[key]) if row else False for key in ('auto_model','auto_physiology')}

    def completed(self, db, row):
        # Called inside the first successful upload-completion transaction.
        if row['complete'] or not row['owner_id']: return
        pref = db.execute('SELECT p.* FROM workflow_preferences p JOIN users u ON u.id=p.user_id AND u.active=1 WHERE p.user_id=?', (row['owner_id'],)).fetchone()
        for kind in self.services:
            if pref and pref['auto_'+kind]:
                stamp = time.time()
                db.execute('INSERT OR IGNORE INTO workflow_intents(id,session_id,owner_id,kind,created,updated) VALUES(?,?,?,?,?,?)',
                           (uuid.uuid4().hex, row['id'], row['owner_id'], kind, stamp, stamp))

    @staticmethod
    def submitted(db, sid, kind, job):
        # Manual retries supersede a pending/blocked automatic intent atomically.
        db.execute("UPDATE workflow_intents SET status='queued',job_id=?,message='',updated=? WHERE session_id=? AND kind=? AND status IN ('pending','blocked') AND owner_id=(SELECT owner_id FROM sessions WHERE id=?)",
                   (job['job_id'], time.time(), sid, kind, sid))

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop.clear()
        self.thread = threading.Thread(target=self.run, name='ecg-workflow', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join()

    def run(self):
        while not self.stop.is_set():
            try: self.dispatch_once()
            except Exception:
                # Do not print records, paths or credentials in the overview.
                log.error('Automatic workflow dispatch failed; retrying on next cycle')
            self.stop.wait(3)

    def dispatch_once(self):
        with closing(self.connect()) as db:
            intents = [dict(row) for row in db.execute("SELECT * FROM workflow_intents WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 8", (time.time(),))]
        for intent in intents:
            if self.stop.is_set(): break
            sid, kind, uid = intent['session_id'], intent['kind'], intent['owner_id']
            def authorize(db):
                row = db.execute('SELECT i.status,s.owner_id,s.complete,d.trashed_at,u.active,p.auto_model,p.auto_physiology FROM workflow_intents i JOIN sessions s ON s.id=i.session_id LEFT JOIN session_details d ON d.session_id=s.id LEFT JOIN users u ON u.id=i.owner_id LEFT JOIN workflow_preferences p ON p.user_id=i.owner_id WHERE i.id=?', (intent['id'],)).fetchone()
                if (not row or row['status'] != 'pending' or not row['active'] or row['owner_id'] != uid
                        or not row['complete'] or row['trashed_at'] or not row['auto_'+kind]):
                    raise Cancelled('自动分析已取消：设置、归属或记录状态改变')
            def accepted(db, job):
                db.execute("UPDATE workflow_intents SET status='queued',job_id=?,message='',updated=? WHERE id=?", (job['job_id'], time.time(), intent['id']))
            try:
                with closing(self.connect()) as db: authorize(db)
                service = self.services[kind]
                ready = service.model_status == 'ready' if kind == 'model' else service.ready
                if not ready: raise ValueError('分析服务尚未就绪，请联系管理员后手动重试')
                row, meta, chunks, digest = load_input(self.data, sid, service)
                if row['sample_count'] > 1000000: raise ValueError('记录超过 100 万采样点，暂不支持整条分析')
                cached = service.read(sid, digest)['analysis_status'] in ('complete','ineligible')
                self.queue.enqueue(sid, digest, row['sample_count'], cached=cached, authorize=authorize,
                                   kind=kind, job_id=intent['id'], on_enqueued=accepted)
                self.queue.start()
            except QueueFull:
                self._intent_failure(intent['id'], 'pending', '队列繁忙，稍后自动重试', delay=30)
            except Cancelled as exc:
                self._intent_failure(intent['id'], 'cancelled', str(exc))
            except ValueError as exc:
                self._intent_failure(intent['id'], 'blocked', str(exc))
            except Exception:
                self._intent_failure(intent['id'], 'pending', '暂未提交，请稍后查看；记录已安全上传', delay=30)
        # Recover accepted work even if process creation failed after the commit.
        if not self.stop.is_set() and self.queue.has_pending(): self.queue.start()

    def _intent_failure(self, iid, status, message, delay=0):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE workflow_intents SET status=?,message=?,updated=?,next_try=? WHERE id=? AND status='pending'", (status, message, time.time(), time.time()+delay, iid))

    def review_context(self, db, sid):
        row = db.execute('SELECT metadata,complete FROM sessions WHERE id=?', (sid,)).fetchone()
        manifest = [dict(x) for x in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (sid,))]
        result = {'complete': bool(row['complete']), 'analyses': {}}
        for kind, service in self.services.items():
            digest = service.digest(json.loads(row['metadata']), row['complete'], manifest)
            job = db.execute('SELECT job_id,source_digest,status,updated FROM analysis_jobs WHERE session_id=? AND kind=? ORDER BY created DESC,job_id DESC LIMIT 1', (sid,kind)).fetchone()
            cached = service.read(sid, digest)
            if job and job['source_digest'] != digest: job = None
            if kind == 'physiology' and job and job['status'] in ('queued','running','failed'):
                cached = dict(cached, analyzed_at=None, analysis_status=job['status'])
            result['analyses'][kind] = {'digest':digest, 'job':dict(job) if job else None,
                'status':cached['analysis_status'], 'analyzed_at':cached.get('analyzed_at')}
        context = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return context, result

    def review(self, db, sid, uid, values=None):
        self.require_user(db, uid)
        context, basis = self.review_context(db, sid)
        row = db.execute('SELECT * FROM record_reviews WHERE session_id=? AND owner_id=?', (sid,uid)).fetchone()
        revision = row['revision'] if row else 0
        if values is not None:
            if values['revision'] != revision or values['context'] != context:
                raise HTTPException(409, '记录结果或复核已变化，请刷新后重新查看')
            if not basis['complete']: raise HTTPException(409, '请等待上传完成后复核')
            if values['status'] != 'pending' and any(x['job'] and x['job']['status'] in ('queued','running') for x in basis['analyses'].values()):
                raise HTTPException(409, '分析正在进行，请完成后再复核')
            stamp = time.time()
            db.execute('INSERT INTO record_reviews VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET owner_id=excluded.owner_id,status=excluded.status,note=excluded.note,revision=excluded.revision,context=excluded.context,updated=excluded.updated',
                       (sid,uid,values['status'],values['note'],revision+1,context,stamp))
            db.execute('INSERT INTO review_events(session_id,actor_id,status,revision,created) VALUES(?,?,?,?,?)', (sid,uid,values['status'],revision+1,stamp))
            row = db.execute('SELECT * FROM record_reviews WHERE session_id=?', (sid,)).fetchone()
        return {'session_id':sid, 'status':row['status'] if row else 'pending','note':row['note'] if row else '',
                'revision':row['revision'] if row else 0,'context':context,'basis':basis,
                'stale':bool(row and row['context'] != context),'updated':row['updated'] if row else None}

    def tasks(self, uid, limit=25, offset=0, stage='all'):
        # SQL performs filtering/pagination; no waveform or cached results are loaded.
        sql = '''WITH raw_ranked AS (
            SELECT a.*,ROW_NUMBER() OVER(PARTITION BY a.session_id,a.kind ORDER BY a.created DESC,a.job_id DESC) AS rank
            FROM analysis_jobs a JOIN sessions s ON s.id=a.session_id WHERE s.owner_id=?),
        ranked AS (SELECT a.session_id,a.kind,a.rank,a.job_id,a.stage,a.processed,a.total,a.updated,a.error,
            workflow_status(a.session_id,a.kind,a.source_digest,a.status,s.metadata,s.complete,
                (SELECT json_group_array(json_object('chunk_id',c.chunk_id,'sha256',c.sha256,'sample_count',c.sample_count))
                    FROM (SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=s.id ORDER BY chunk_id) c)) AS status
            FROM raw_ranked a JOIN sessions s ON s.id=a.session_id WHERE a.rank=1),
        listing AS (SELECT s.id,s.complete,s.sample_count,s.created_at,d.name,
            CASE WHEN s.complete=0 THEN 'uploading'
            WHEN EXISTS(SELECT 1 FROM ranked a WHERE a.session_id=s.id AND rank=1 AND status IN ('queued','running'))
                OR EXISTS(SELECT 1 FROM workflow_intents i WHERE i.session_id=s.id AND i.status='pending') THEN 'processing'
            WHEN EXISTS(SELECT 1 FROM ranked a WHERE a.session_id=s.id AND rank=1 AND status IN ('failed','not_configured','stale'))
                OR EXISTS(SELECT 1 FROM workflow_intents i WHERE i.session_id=s.id AND i.status='blocked' AND i.job_id IS NULL
                    AND NOT EXISTS(SELECT 1 FROM ranked a WHERE a.session_id=s.id AND a.kind=i.kind)) THEN 'attention'
            WHEN EXISTS(SELECT 1 FROM ranked a WHERE a.session_id=s.id AND rank=1 AND status IN ('complete','ineligible')) THEN 'results'
            ELSE 'ready' END AS stage
            FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE s.owner_id=? AND d.trashed_at IS NULL) '''
        with closing(self.connect()) as db:
            db.create_function('workflow_status', 7, self.task_status)
            db.execute('BEGIN'); self.require_user(db, uid)
            counts = {r['stage']:r['n'] for r in db.execute(sql+'SELECT stage,COUNT(*) n FROM listing GROUP BY stage', (uid,uid))}
            where, params = ('', [uid,uid]) if stage=='all' else (' WHERE stage=?', [uid,uid,stage])
            total = sum(counts.values()) if stage=='all' else counts.get(stage, 0)
            records = []
            page = list(db.execute(sql+'SELECT * FROM listing'+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (*params,limit,offset)))
            page_jobs = {}
            if page:
                ids = [row['id'] for row in page]
                for job in db.execute(sql+'SELECT session_id,job_id,kind,status,stage,processed,total,updated,error FROM ranked WHERE session_id IN ('+','.join('?' for _ in ids)+')', (uid,uid,*ids)):
                    page_jobs.setdefault(job['session_id'], {})[job['kind']] = dict(job)
            for row in page:
                item = dict(row); item['session_id'] = item.pop('id'); sid = item['session_id']; item['complete'] = bool(item['complete'])
                item['jobs'] = {}
                for kind in self.services: item['jobs'][kind] = page_jobs.get(sid, {}).get(kind)
                item['automatic'] = [dict(x) for x in db.execute('SELECT kind,status,message,job_id FROM workflow_intents WHERE session_id=?', (sid,))]
                records.append(item)
        return {'records':records,'total':total,'counts':counts,'limit':limit,'offset':offset,'measured_at':time.time()}

    def task_status(self, sid, kind, digest, status, metadata, complete, manifest):
        if status not in ('complete','ineligible'): return status
        service = self.services[kind]
        current = service.digest(json.loads(metadata), complete, json.loads(manifest))
        if current != digest: return 'stale'
        path = service.path(sid, digest) if kind == 'physiology' else service.directory / (sid+'.json')
        # Detailed result validation remains on the record page; never parse large
        # result caches or waveforms just to render a cross-record task list.
        try: return status if path.is_file() else 'stale'
        except OSError: return 'stale'

    def operations(self):
        stamp = time.time()
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            queue = {r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM analysis_jobs GROUP BY status')}
            uploads = {'pending':db.execute('SELECT COUNT(*) FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE complete=0 AND d.trashed_at IS NULL').fetchone()[0]}
            uploads['stalled'] = db.execute("SELECT COUNT(*) FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE complete=0 AND d.trashed_at IS NULL AND julianday(received_at)<julianday('now','-15 minutes')").fetchone()[0]
            devices = {'online':0,'offline':0,'unknown':0,'disabled':0}
            for row in db.execute('SELECT d.active,h.seen FROM devices d LEFT JOIN device_heartbeats h ON h.device_id=d.id'):
                status = 'disabled' if not row['active'] else 'unknown' if row['seen'] is None else 'online' if stamp-row['seen']<=35 else 'offline'
                devices[status] += 1
            backup = db.execute("SELECT status,updated FROM management_jobs WHERE kind='backup' ORDER BY created DESC LIMIT 1").fetchone()
            last_success = db.execute("SELECT updated FROM management_jobs WHERE kind='backup' AND status='complete' ORDER BY updated DESC LIMIT 1").fetchone()
            schedule = db.execute('SELECT enabled,hour,minute,next_due,retry_after,state FROM backup_schedule WHERE id=1').fetchone()
            failed = db.execute("SELECT COUNT(*) FROM analysis_jobs a JOIN sessions s ON s.id=a.session_id LEFT JOIN session_details d ON d.session_id=s.id WHERE a.status IN ('failed','not_configured') AND d.trashed_at IS NULL AND a.updated>? AND NOT EXISTS(SELECT 1 FROM analysis_jobs b WHERE b.session_id=a.session_id AND b.kind=a.kind AND (b.created>a.created OR (b.created=a.created AND b.job_id>a.job_id)))", (stamp-7*86400,)).fetchone()[0]
            blocked = db.execute("SELECT COUNT(*) FROM workflow_intents i JOIN sessions s ON s.id=i.session_id AND s.owner_id=i.owner_id JOIN users u ON u.id=i.owner_id AND u.active=1 LEFT JOIN session_details d ON d.session_id=s.id WHERE i.status='blocked' AND d.trashed_at IS NULL").fetchone()[0]
        try:
            usage = shutil.disk_usage(self.data)
            disk = {'free_bytes':usage.free,'total_bytes':usage.total}
        except OSError: disk = {'free_bytes':None,'total_bytes':None}
        issues = []
        def issue(code, severity, text, href): issues.append({'code':code,'severity':severity,'text':text,'href':href})
        if disk['free_bytes'] is None: issue('disk_unknown','warning','暂时无法读取磁盘空间','/database')
        elif disk['free_bytes']<max(1024**3, disk['total_bytes']*.1): issue('disk_low','warning','磁盘空间偏低，请检查存储和备份','/database')
        if devices['offline']: issue('devices_offline','info',f"{devices['offline']} 台设备超过 35 秒未上报；不代表设备已断电",'/devices')
        if uploads['stalled']: issue('uploads_stalled','warning',f"{uploads['stalled']} 条未完成上传超过 15 分钟无更新",'/database')
        if failed: issue('analysis_failed','warning',f'{failed} 项最近 7 天的最新分析失败；用户可在本人任务中心重试','/tasks')
        if blocked: issue('automatic_blocked','warning',f'{blocked} 项自动提交被阻止；检查服务配置并让记录本人重试','/tasks')
        if not last_success: issue('backup_missing','warning','尚无成功备份记录，请创建服务器本地备份','/database')
        elif stamp-last_success['updated']>7*86400: issue('backup_old','warning','最近成功备份已超过 7 天，请安排新备份','/database')
        if backup and backup['status'] in ('failed','interrupted'): issue('backup_failed','warning','最近一次备份未完成，请查看维护任务','/database')
        if schedule:
            if not schedule['enabled']: issue('backup_schedule_disabled','info','每日自动备份未启用；请按需要在数据库管理中设置','/database')
            elif schedule['state']=='blocked': issue('backup_schedule_blocked','warning','自动备份受阻，请检查磁盘空间和维护任务','/database')
            elif schedule['next_due'] and stamp-max(schedule['next_due'],schedule['retry_after'])>1800:
                issue('backup_schedule_overdue','warning','自动备份已超过计划时间 30 分钟，请检查服务与维护队列','/database')
        return {'measured_at':stamp,'devices':devices,'uploads':uploads,'queue':queue,'disk':disk,'backup':dict(backup) if backup else None,
                'backup_schedule':dict(schedule) | {'enabled':bool(schedule['enabled']),'timezone':'Asia/Shanghai','retention':'keep_all'} if schedule else None,
                'last_successful_backup':last_success['updated'] if last_success else None,
                'model_status':self.services['model'].model_status,'physiology_ready':self.services['physiology'].ready,'issues':issues}
