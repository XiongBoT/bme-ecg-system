"""Account-scoped trends and explicit, bounded remote acquisition requests."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import calendar
import json
import time
import uuid
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


TREND_INDEX = 'sessions_owner_started_serial_complete'
TREND_INDEX_SQL = '''CREATE INDEX IF NOT EXISTS sessions_owner_started_serial_complete
    ON sessions(owner_id, julianday(json_extract(metadata,'$.started_utc')))
    WHERE complete=1 AND json_extract(metadata,'$.source')='serial' '''
TREND_QUERY = """SELECT s.metadata,s.sample_count,m.details FROM sessions s
    LEFT JOIN session_details d ON d.session_id=s.id
    LEFT JOIN measurement_summaries m ON m.session_id=s.id
    WHERE s.owner_id=? AND s.complete=1 AND d.trashed_at IS NULL
    AND json_extract(s.metadata,'$.source')='serial'
    AND julianday(json_extract(s.metadata,'$.started_utc'))>=julianday(?)
    AND julianday(json_extract(s.metadata,'$.started_utc'))<julianday(?)"""


class MeasurementRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
    duration_s: Literal[60, 180, 300]
    request_key: str = Field(pattern=r'^[a-f0-9-]{32,36}$')


class MeasurementUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['recording', 'uploading', 'failed']
    session_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
    message: str = Field(default='', max_length=160)


def initialize(connect):
    with closing(connect()) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS measurement_requests(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            device_id TEXT NOT NULL REFERENCES devices(id), request_key TEXT NOT NULL,
            duration_s INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
            expires_at REAL NOT NULL, updated_at REAL NOT NULL, session_id TEXT, message TEXT NOT NULL,
            UNIQUE(owner_id, request_key));
        CREATE INDEX IF NOT EXISTS measurement_device_status ON measurement_requests(device_id,status);
        ''')
        # Match the query's UTC conversion exactly: ISO offsets cannot be sorted
        # lexicographically. SQLite maintains this partial index on writes, so
        # completion/ownership changes need no application-side cache invalidation.
        db.execute(TREND_INDEX_SQL)
        db.commit()


def period_bounds(period, anchor, offset):
    tz = timezone(timedelta(minutes=offset))
    day = date.fromisoformat(anchor)
    if period == 'day':
        first, last, count = day, day+timedelta(days=1), 24
    elif period == 'month':
        first = day.replace(day=1)
        count = calendar.monthrange(day.year, day.month)[1]
        last = first+timedelta(days=count)
    else:
        first, last, count = date(day.year, 1, 1), date(day.year+1, 1, 1), 12
    start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(last, datetime.min.time(), tzinfo=tz)
    return start, end, count


def add_routes(app, connect, identity, devices, require_device, auth_enabled):
    initialize(connect)

    def user(db=None):
        who = identity.get()
        if not auth_enabled or who.get('kind') != 'user':
            raise HTTPException(403, '请使用个人账号登录')
        if db is not None and not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (who['id'],)).fetchone():
            raise HTTPException(401, '账号已停用')
        return who

    def reconcile(db):
        now = time.time()
        # Only a manifest-validated, matching owner's record can produce a report link.
        db.execute("UPDATE measurement_requests SET status='completed',message='测量记录已上传，可查看报告',updated_at=? "
                   "WHERE status IN ('recording','uploading') AND EXISTS(SELECT 1 FROM sessions s "
                   "WHERE s.id=measurement_requests.session_id AND s.owner_id=measurement_requests.owner_id "
                   "AND s.ingest_device_id=measurement_requests.device_id AND s.complete=1)", (now,))
        db.execute("UPDATE measurement_requests SET status='expired',message='设备未及时接收，请确认终端后重新发起',updated_at=? "
                   "WHERE status='queued' AND expires_at<?", (now, now))
        db.execute("UPDATE measurement_requests SET status='failed',message='终端长时间未回应，请到终端检查本地记录',updated_at=? "
                   "WHERE status IN ('accepted','recording','uploading') AND updated_at+duration_s+600<?", (now, now))

    def public(row):
        return {k: row[k] for k in ('id','device_id','duration_s','status','created_at','expires_at','updated_at','session_id','message')}

    @app.get('/api/records/trends')
    def trends(period: Literal['day','month','year'], anchor: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'),
               utc_offset_minutes: int = Query(default=480, ge=-720, le=840)):
        who = user()
        try:
            start, end, count = period_bounds(period, anchor, utc_offset_minutes)
        except (ValueError, OverflowError):
            raise HTTPException(422, '日期无效')
        # No waveform or personal result is stored in client preferences.
        buckets = [dict(index=i, label=(f'{i:02d}:00' if period=='day' else str(i+1)), records=0,
                        duration_s=0., hr_mean=None, hr_records=0, _weight=0., _sum=0.) for i in range(count)]
        with closing(connect()) as db:
            rows = db.execute(TREND_QUERY, (who['id'], start.isoformat(), end.isoformat()))
            for row in rows:
                meta = json.loads(row['metadata'])
                stamp = datetime.fromisoformat(meta['started_utc'].replace('Z','+00:00')).astimezone(start.tzinfo)
                i = stamp.hour if period=='day' else stamp.day-1 if period=='month' else stamp.month-1
                bucket = buckets[i]
                bucket['records'] += 1
                bucket['duration_s'] += row['sample_count']/360
                details = json.loads(row['details']) if row['details'] else {}
                hr = (details.get('analysis_stats') or {}).get('hr')
                if hr:
                    bucket['_weight'] += hr['window_samples']
                    bucket['_sum'] += hr['mean']*hr['window_samples']
                    bucket['hr_records'] += 1
        for bucket in buckets:
            bucket['hr_mean'] = round(bucket['_sum']/bucket['_weight'],1) if bucket['_weight'] else None
            bucket['duration_s'] = round(bucket['duration_s'],1)
            del bucket['_sum'], bucket['_weight']
        return dict(period=period, anchor=anchor, utc_offset_minutes=utc_offset_minutes, buckets=buckets,
                    total_records=sum(b['records'] for b in buckets),
                    total_duration_s=round(sum(b['duration_s'] for b in buckets),1),
                    note='按采集开始时间汇总已上传完成且未回收的串口记录；心率来自终端质量合格窗口，缺失不记为0。')

    @app.post('/api/measurements', status_code=202)
    def request_measurement(payload: MeasurementRequest):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            who = user(db)
            devices.require_recipient(payload.device_id, who['id'], db)
            reconcile(db)
            previous = db.execute('SELECT * FROM measurement_requests WHERE owner_id=? AND request_key=?',
                                  (who['id'],payload.request_key)).fetchone()
            if previous:
                if previous['device_id'] != payload.device_id or previous['duration_s'] != payload.duration_s:
                    raise HTTPException(409, '重试参数与原测量不一致')
                return public(previous)
            beat = db.execute('SELECT seen,payload FROM device_heartbeats WHERE device_id=?', (payload.device_id,)).fetchone()
            info = json.loads(beat['payload']) if beat else {}
            if not beat or time.time()-beat['seen'] > 35:
                raise HTTPException(409, '设备离线，请先启动采集终端')
            if info.get('state') != 'standby' or not info.get('remote_ready'):
                raise HTTPException(409, '终端未就绪：请更新终端、选择串口并等待当前操作结束')
            if db.execute("SELECT 1 FROM measurement_requests WHERE device_id=? AND status IN ('queued','accepted','recording','uploading')", (payload.device_id,)).fetchone():
                raise HTTPException(409, '该设备已有测量任务，请等待完成')
            now = time.time(); mid = uuid.uuid4().hex
            db.execute('INSERT INTO measurement_requests VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (mid,who['id'],payload.device_id,payload.request_key,payload.duration_s,'queued',now,now+45,now,None,'等待终端开始采集'))
            return public(db.execute('SELECT * FROM measurement_requests WHERE id=?',(mid,)).fetchone())

    @app.get('/api/measurements')
    def list_measurements():
        with closing(connect()) as db, db:
            who=user(db);reconcile(db)
            rows=db.execute('SELECT * FROM measurement_requests WHERE owner_id=? ORDER BY created_at DESC LIMIT 10',(who['id'],)).fetchall()
            return {'measurements':[public(r) for r in rows]}

    @app.get('/api/device/measurements/next')
    def next_measurement():
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');did=require_device(db);reconcile(db)
            row=db.execute("SELECT * FROM measurement_requests WHERE device_id=? AND status='queued' ORDER BY created_at LIMIT 1",(did,)).fetchone()
            if not row:return {'measurement':None}
            try: devices.require_recipient(did,row['owner_id'],db)
            except HTTPException:
                db.execute("UPDATE measurement_requests SET status='failed',message='账号或设备授权已变更' WHERE id=?",(row['id'],))
                return {'measurement':None}
            owner=db.execute('SELECT username FROM users WHERE id=?',(row['owner_id'],)).fetchone()[0]
            return {'measurement':dict(public(row),owner_id=row['owner_id'],owner_name=owner)}

    @app.post('/api/device/measurements/{mid}/claim')
    def claim(mid: str):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');did=require_device(db);reconcile(db)
            row=db.execute('SELECT * FROM measurement_requests WHERE id=? AND device_id=?',(mid,did)).fetchone()
            if not row:raise HTTPException(404,'测量任务不存在')
            devices.require_recipient(did,row['owner_id'],db)
            if row['status']!='queued':raise HTTPException(409,'任务已被接收或已过期，不得重复采集')
            db.execute("UPDATE measurement_requests SET status='accepted',updated_at=?,message='终端正在准备采集' WHERE id=?",(time.time(),mid))
            return {'accepted':True}

    @app.post('/api/device/measurements/{mid}/status')
    def update(mid: str, payload: MeasurementUpdate):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');did=require_device(db)
            row=db.execute('SELECT * FROM measurement_requests WHERE id=? AND device_id=?',(mid,did)).fetchone()
            if not row:raise HTTPException(404,'测量任务不存在')
            if row['status']=='completed' and payload.status=='uploading' and payload.session_id==row['session_id']:
                # The phone may reconcile completion before the terminal's next acknowledgement.
                return public(row)
            if row['status'] not in ('accepted','recording','uploading'):
                if row['status']==payload.status:return public(row)
                raise HTTPException(409,'测量任务已结束')
            if payload.status=='recording' and row['status']=='uploading':raise HTTPException(409,'不能重新开始已结束的采集')
            if payload.status!='failed' and not payload.session_id:raise HTTPException(422,'缺少采集记录编号')
            if row['session_id'] and payload.session_id and row['session_id']!=payload.session_id:raise HTTPException(409,'测量记录编号不可更换')
            if payload.session_id:
                session=db.execute('SELECT owner_id,ingest_device_id FROM sessions WHERE id=?',(payload.session_id,)).fetchone()
                if session and (session['owner_id']!=row['owner_id'] or session['ingest_device_id']!=did):raise HTTPException(409,'记录归属不匹配')
            db.execute('UPDATE measurement_requests SET status=?,session_id=COALESCE(session_id,?),message=?,updated_at=? WHERE id=?',
                       (payload.status,payload.session_id,payload.message,time.time(),mid))
            reconcile(db)
            return public(db.execute('SELECT * FROM measurement_requests WHERE id=?',(mid,)).fetchone())
