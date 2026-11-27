"""Opt-in HeartLife integration: owner-bound summaries and explicit acquisition consent.

The service secret identifies the one configured HeartLife deployment. It is
never a general ECG credential. Grants and pairing codes are stored as hashes;
all data reads additionally require a grant and its immutable HeartLife subject.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone as utc_timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from health_routes import (MeasurementRequest, TREND_QUERY, create_measurement,
                           public_measurement, read_trends, reconcile_measurements)


CODE_TTL = 300
GRANT_TTL = 30 * 86400
SCOPE = 'summary:read'
AUDIENCE = 'heartlife'
SUBJECT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
OPERATION = re.compile(r'^[a-f0-9]{32}$')
TOKEN = re.compile(r'^[A-Za-z0-9_-]{32,128}$')
MACHINE_ROUTES = frozenset({
    ('POST', '/api/heartlife/exchange'),
    ('GET', '/api/heartlife/summary'),
    ('GET', '/api/heartlife/devices'),
    ('GET', '/api/heartlife/measurements'),
    ('POST', '/api/heartlife/measurements'),
    ('GET', '/api/heartlife/weekly-summary'),
    ('DELETE', '/api/heartlife/grant'),
    ('DELETE', '/api/heartlife/subject-grant'),
})


def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def safe_heartlife_url(raw):
    """A fixed HTTPS application root; no user-controlled navigation target."""
    value = (raw or '').strip()
    if not value or any(c.isspace() or ord(c) < 32 for c in value) or any(c in value for c in ('\\', '?', '#')):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username is not None or
                url.password is not None or url.query or url.fragment or
                url.port not in (None, 443) or url.path not in ('', '/', '/heartlife', '/heartlife/')):
            return None
    except ValueError:
        return None
    return value.rstrip('/')


def revoke_owner(db, owner_id):
    """Called inside the same account mutation transaction (including CLI use)."""
    # Account tools can open a pre-integration DB without running create_app.
    for table in ('heartlife_codes', 'heartlife_grants'):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            db.execute(f'DELETE FROM {table} WHERE owner_id=?', (owner_id,))


class ExchangeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=32, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    subject_id: str = Field(min_length=1, max_length=96, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    operation_id: str = Field(min_length=32, max_length=32, pattern=r'^[a-f0-9]{32}$')


class CodeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    measurement_allowed: StrictBool = False


def envelope(grant, **data):
    return dict(ecg_user=dict(id=grant['owner_id'], username=grant['username']),
                expires_at=grant['expires_at'], measurement_allowed=bool(grant['measurement_allowed']), **data)


def weekly_summary(db, owner_id, week_start, timezone, observed_days):
    """One indexed owner scan; local midnight boundaries also cover DST weeks."""
    try:
        first = date.fromisoformat(week_start)
        if first.weekday() != 0:
            raise ValueError('not Monday')
        dates = [first + timedelta(days=i) for i in range(8)]
        tz = ZoneInfo(timezone)
        start, end = [datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(utc_timezone.utc)
                      for day in (first, dates[observed_days])]
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        raise HTTPException(422, '心电统计日期或时区无效')
    buckets = [dict(date=day.isoformat(), records=0, duration_s=0., hr_mean=None,
                    hr_records=0, _weight=0., _sum=0.) for day in dates[:7]]
    for row in db.execute(TREND_QUERY, (owner_id, start.isoformat(), end.isoformat())):
        meta = json.loads(row['metadata'])
        local_date = datetime.fromisoformat(meta['started_utc'].replace('Z', '+00:00')).astimezone(tz).date()
        bucket = buckets[(local_date - first).days]
        bucket['records'] += 1
        bucket['duration_s'] += row['sample_count'] / 360
        details = json.loads(row['details']) if row['details'] else {}
        hr = (details.get('analysis_stats') or {}).get('hr')
        if hr:
            bucket['_weight'] += hr['window_samples']
            bucket['_sum'] += hr['mean'] * hr['window_samples']
            bucket['hr_records'] += 1
    weight = sum(row['_weight'] for row in buckets)
    total_duration_s = round(sum(row['duration_s'] for row in buckets), 1)
    hr_mean = round(sum(row['_sum'] for row in buckets) / weight, 1) if weight else None
    for bucket in buckets:
        weighted_sum, bucket_weight = bucket.pop('_sum'), bucket.pop('_weight')
        bucket['hr_mean'] = round(weighted_sum / bucket_weight, 1) if bucket_weight else None
        bucket['duration_s'] = round(bucket['duration_s'], 1)
    return dict(week_start=week_start, week_end=dates[6].isoformat(), timezone=timezone,
                observed_days=observed_days, total_records=sum(row['records'] for row in buckets),
                total_duration_s=total_duration_s, hr_mean=hr_mean,
                hr_records=sum(row['hr_records'] for row in buckets), daily_series=buckets)


MEASUREMENT_MESSAGES = {
    'queued': '等待终端开始采集', 'accepted': '终端正在准备采集',
    'recording': '正在采集，请保持设备连接', 'uploading': '采集已结束，正在上传记录',
    'completed': '记录已上传，分析状态见下方',
    'expired': '设备未及时接收，请确认终端后重新发起',
    'failed': '测量未完成，请到终端检查设备与本地记录',
}


def bridge_measurement(db, workflow, owner_id, row):
    item = public_measurement(row)
    item['message'] = MEASUREMENT_MESSAGES.get(row['status'], '请到原心电工作台查看测量状态')
    item['report'] = {'model': 'not_started', 'physiology': 'not_started'}
    # A device-provided session id is not evidence that a usable report exists.
    session = db.execute('''SELECT s.* FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id
        WHERE s.id=? AND s.owner_id=? AND s.ingest_device_id=? AND s.complete=1 AND d.trashed_at IS NULL''',
                         (row['session_id'], owner_id, row['device_id'])).fetchone()
    if session is None:
        item['session_id'] = None
        return item
    manifest = json.dumps([dict(chunk) for chunk in db.execute(
        'SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session['id'],))])
    for kind in item['report']:
        job = db.execute('''SELECT source_digest,status FROM analysis_jobs WHERE session_id=? AND kind=?
            ORDER BY created DESC,job_id DESC LIMIT 1''', (session['id'], kind)).fetchone()
        state = workflow.task_status(session['id'], kind, job['source_digest'], job['status'],
                                     session['metadata'], session['complete'], manifest) if job else 'not_started'
        intent = db.execute('SELECT status FROM workflow_intents WHERE session_id=? AND kind=?',
                            (session['id'], kind)).fetchone()
        if intent and intent['status'] == 'pending' and state not in ('queued', 'running'):
            state = 'queued'
        elif intent and intent['status'] == 'blocked' and not job:
            state = 'failed'
        item['report'][kind] = {'complete': 'completed', 'not_configured': 'failed', 'stale': 'not_started'}.get(
            state, state if state in ('queued', 'running', 'failed', 'ineligible') else 'not_started')
    return item


class HeartLifeBridge:
    def __init__(self, connect, auth_enabled):
        self.connect = connect
        self.auth_enabled = auth_enabled
        self.url = safe_heartlife_url(os.getenv('ECG_HEARTLIFE_URL'))
        self.secret = os.getenv('ECG_HEARTLIFE_CLIENT_SECRET', '')
        self.enabled = bool(auth_enabled and self.url and 32 <= len(self.secret) <= 1024)
        with closing(connect()) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS heartlife_codes(
                code_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                measurement_allowed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS heartlife_grants(
                token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                subject_id TEXT NOT NULL UNIQUE, audience TEXT NOT NULL, scope TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL, operation_id TEXT NOT NULL,
                measurement_allowed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS heartlife_exchange_attempts(
                bucket TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL);
            ''')
            if 'operation_id' not in {row['name'] for row in db.execute('PRAGMA table_info(heartlife_grants)')}:
                db.execute("ALTER TABLE heartlife_grants ADD COLUMN operation_id TEXT NOT NULL DEFAULT ''")
            for table in ('heartlife_codes', 'heartlife_grants'):
                if 'measurement_allowed' not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN measurement_allowed INTEGER NOT NULL DEFAULT 0')
            db.commit()

    @property
    def public_url(self):
        return self.url if self.enabled else None

    def require_enabled(self):
        if not self.enabled:
            raise HTTPException(503, '心伴连接尚未启用')

    def require_client(self, request):
        self.require_enabled()
        key = request.headers.get('X-HeartLife-Key', '')
        if len(key) > 1024 or not hmac.compare_digest(key.encode(), self.secret.encode()):
            raise HTTPException(401, '心伴服务认证失败')

    @staticmethod
    def subject(request):
        subject = request.headers.get('X-HeartLife-Subject', '')
        if not SUBJECT.fullmatch(subject):
            raise HTTPException(401, '心伴授权已失效，请重新绑定')
        return subject

    @staticmethod
    def token(request):
        authorization = request.headers.get('Authorization', '')
        if not authorization.startswith('Bearer ') or not TOKEN.fullmatch(authorization[7:]):
            raise HTTPException(401, '心伴授权已失效，请重新绑定')
        return authorization[7:]

    def require_grant(self, request, db, *, measurement=False):
        self.require_client(request)
        subject = self.subject(request)
        raw = self.token(request)
        row = db.execute('''SELECT g.*, u.username FROM heartlife_grants g
            JOIN users u ON u.id=g.owner_id WHERE g.token_hash=? AND g.subject_id=?
            AND g.audience=? AND g.scope=? AND g.expires_at>? AND u.active=1''',
                         (digest(raw), subject, AUDIENCE, SCOPE, time.time())).fetchone()
        if row is None:
            raise HTTPException(401, '心伴授权已失效，请重新绑定')
        if measurement and not row['measurement_allowed']:
            raise HTTPException(403, '当前关联仅可查看摘要，请在心电平台重新授权测量')
        return row

    def exchange_limit(self, request):
        # Persist across worker restarts; only the configured client reaches here.
        bucket = digest(request.client.host if request.client else 'unknown')
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM heartlife_exchange_attempts WHERE started_at<=?', (now-300,))
            row = db.execute('SELECT attempts FROM heartlife_exchange_attempts WHERE bucket=?', (bucket,)).fetchone()
            if row and row['attempts'] >= 20:
                raise HTTPException(429, '绑定尝试次数较多，请五分钟后再试')
            db.execute('''INSERT INTO heartlife_exchange_attempts VALUES(?,?,1)
                ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1''', (bucket, now))


def add_routes(app, connect, identity, auth_enabled, devices, workflow):
    bridge = HeartLifeBridge(connect, auth_enabled)

    def user(db):
        who = identity.get()
        if not auth_enabled or who.get('kind') != 'user':
            raise HTTPException(403, '请使用个人账号登录')
        row = db.execute('''SELECT u.id,u.username FROM users u JOIN browser_sessions s ON s.user_id=u.id
            WHERE u.id=? AND u.active=1 AND s.csrf=? AND s.expires>?''',
                         (who['id'], who['csrf_token'], time.time())).fetchone()
        if row is None:
            raise HTTPException(401, '账号已停用')
        return row

    @app.get('/api/heartlife/link')
    def link_status():
        with closing(connect()) as db:
            who = user(db)
            row = db.execute('SELECT subject_id,expires_at,measurement_allowed FROM heartlife_grants WHERE owner_id=? AND expires_at>?',
                             (who['id'], time.time())).fetchone()
            return dict(enabled=bridge.enabled, heartlife_url=bridge.public_url, linked=bool(row),
                        subject_id=row['subject_id'] if row else None, expires_at=row['expires_at'] if row else None,
                        measurement_allowed=bool(row and row['measurement_allowed']))

    @app.post('/api/heartlife/link-code')
    def make_code(payload: CodeInput | None = None):
        bridge.require_enabled()
        now = time.time()
        raw = secrets.token_urlsafe(24)
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            who = user(db)
            db.execute('DELETE FROM heartlife_grants WHERE expires_at<=?', (now,))
            if db.execute('SELECT 1 FROM heartlife_grants WHERE owner_id=?', (who['id'],)).fetchone():
                raise HTTPException(409, '已关联心伴账号，请先解除旧关联')
            db.execute('DELETE FROM heartlife_codes WHERE owner_id=? OR expires_at<=?', (who['id'], now))
            allowed = bool(payload and payload.measurement_allowed)
            db.execute('INSERT INTO heartlife_codes(code_hash,owner_id,created_at,expires_at,measurement_allowed) VALUES(?,?,?,?,?)',
                       (digest(raw), who['id'], now, now+CODE_TTL, int(allowed)))
        return dict(code=raw, expires_at=now+CODE_TTL, heartlife_url=bridge.public_url, measurement_allowed=allowed)

    @app.delete('/api/heartlife/link')
    def unlink():
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            revoke_owner(db, user(db)['id'])
        return {'revoked': True}

    @app.post('/api/heartlife/exchange')
    def exchange(payload: ExchangeInput, request: Request):
        bridge.require_client(request)
        bridge.exchange_limit(request)
        raw = secrets.token_urlsafe(32)
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            row = db.execute('''SELECT c.owner_id,c.measurement_allowed,u.username FROM heartlife_codes c
                JOIN users u ON u.id=c.owner_id WHERE code_hash=? AND expires_at>? AND u.active=1''',
                             (digest(payload.code), now)).fetchone()
            if row is None:
                raise HTTPException(401, '绑定码无效、已使用或已过期，请重新生成')
            db.execute('DELETE FROM heartlife_grants WHERE expires_at<=?', (now,))
            if db.execute('SELECT 1 FROM heartlife_grants WHERE owner_id=? OR subject_id=?',
                          (row['owner_id'], payload.subject_id)).fetchone():
                raise HTTPException(409, '账号已有心伴关联，请先解除旧关联')
            db.execute('''INSERT INTO heartlife_grants(token_hash,owner_id,subject_id,audience,scope,created_at,
                expires_at,operation_id,measurement_allowed) VALUES(?,?,?,?,?,?,?,?,?)''',
                       (digest(raw), row['owner_id'], payload.subject_id, AUDIENCE, SCOPE, now, now+GRANT_TTL,
                        payload.operation_id, row['measurement_allowed']))
            db.execute('DELETE FROM heartlife_codes WHERE code_hash=?', (digest(payload.code),))
        return dict(grant_token=raw, ecg_user_id=row['owner_id'], ecg_username=row['username'], expires_at=now+GRANT_TTL,
                    measurement_allowed=bool(row['measurement_allowed']))

    @app.get('/api/heartlife/summary')
    def summary(request: Request, period: Literal['day', 'month', 'year'],
                anchor: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'),
                utc_offset_minutes: int = Query(default=480, ge=-720, le=840)):
        with closing(connect()) as db:
            # The grant and result share a read snapshot. No caller-supplied owner.
            db.execute('BEGIN')
            grant = bridge.require_grant(request, db)
            trends = read_trends(db, grant['owner_id'], period, anchor, utc_offset_minutes)
            rows = db.execute('''SELECT s.id,s.metadata,s.sample_count,m.details FROM sessions s
                LEFT JOIN session_details d ON d.session_id=s.id
                LEFT JOIN measurement_summaries m ON m.session_id=s.id
                WHERE s.owner_id=? AND s.complete=1 AND d.trashed_at IS NULL
                AND json_extract(s.metadata,'$.source')='serial'
                ORDER BY julianday(json_extract(s.metadata,'$.started_utc')) DESC,s.id DESC LIMIT 5''',
                              (grant['owner_id'],))
            recent = []
            for row in rows:
                meta = json.loads(row['metadata'])
                details = json.loads(row['details']) if row['details'] else {}
                hr = (details.get('analysis_stats') or {}).get('hr')
                recent.append(dict(session_id=row['id'], started_utc=meta['started_utc'],
                                   duration_s=round(row['sample_count']/360, 1), hr_mean=hr['mean'] if hr else None))
            return envelope(grant, recent_records=recent, trends=trends)

    @app.get('/api/heartlife/devices')
    def available_devices(request: Request):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            grant = bridge.require_grant(request, db, measurement=True)
            reconcile_measurements(db)
            rows = db.execute('''SELECT d.*,h.seen,h.payload FROM devices d
                LEFT JOIN device_heartbeats h ON h.device_id=d.id WHERE d.active=1
                AND (d.legacy_shared=1 OR EXISTS(SELECT 1 FROM device_users u WHERE u.device_id=d.id AND u.user_id=?))
                ORDER BY d.name,d.id''', (grant['owner_id'],)).fetchall()
            busy = {r[0] for r in db.execute("SELECT device_id FROM measurement_requests WHERE status IN ('queued','accepted','recording','uploading')")}
            result, now = [], time.time()
            for row in rows:
                devices.require_recipient(row['id'], grant['owner_id'], db)
                info = json.loads(row['payload']) if row['payload'] else {}
                online = row['seen'] is not None and now-row['seen'] <= 35
                ready = online and info.get('state') == 'standby' and bool(info.get('remote_ready')) and row['id'] not in busy
                reason = ('可以发起测量' if ready else '设备离线，请先启动采集终端' if not online else
                          '该设备已有测量任务，请等待完成' if row['id'] in busy else '终端未就绪，请在设备上检查连接与当前操作')
                result.append(dict(device_id=row['id'], label=row['name'], online=online, ready=ready, reason=reason))
            return envelope(grant, devices=result)

    @app.post('/api/heartlife/measurements', status_code=202)
    def request_measurement(payload: MeasurementRequest, request: Request):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            grant = bridge.require_grant(request, db, measurement=True)
            row = create_measurement(db, devices, grant['owner_id'], payload)
            return envelope(grant, measurement=bridge_measurement(db, workflow, grant['owner_id'], row))

    @app.get('/api/heartlife/measurements')
    def list_measurements(request: Request):
        with closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            grant = bridge.require_grant(request, db, measurement=True)
            reconcile_measurements(db)
            rows = db.execute('SELECT * FROM measurement_requests WHERE owner_id=? ORDER BY created_at DESC,id DESC LIMIT 10',
                              (grant['owner_id'],)).fetchall()
            return envelope(grant, measurements=[bridge_measurement(db, workflow, grant['owner_id'], row) for row in rows])

    @app.get('/api/heartlife/weekly-summary')
    def read_weekly_summary(request: Request, week_start: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'),
                            timezone: str = Query(min_length=1, max_length=64),
                            observed_days: int = Query(ge=1, le=7)):
        with closing(connect()) as db:
            db.execute('BEGIN')
            grant = bridge.require_grant(request, db)
            return envelope(grant, **weekly_summary(db, grant['owner_id'], week_start, timezone, observed_days))

    @app.delete('/api/heartlife/grant')
    def revoke_grant(request: Request):
        bridge.require_client(request)
        subject, raw = bridge.subject(request), bridge.token(request)
        with closing(connect()) as db, db:
            db.execute('DELETE FROM heartlife_grants WHERE token_hash=? AND subject_id=?', (digest(raw), subject))
        return {'revoked': True}

    @app.delete('/api/heartlife/subject-grant')
    def revoke_subject_grant(request: Request):
        bridge.require_client(request)
        subject = bridge.subject(request)
        operation = request.headers.get('X-HeartLife-Operation', '')
        if not OPERATION.fullmatch(operation):
            raise HTTPException(401, '心伴连接操作已失效')
        # Recovery after a lost exchange response: the configured deployment may
        # revoke its own subject's association, but cannot read data without token.
        with closing(connect()) as db, db:
            db.execute('DELETE FROM heartlife_grants WHERE subject_id=? AND audience=? AND operation_id=?',
                       (subject, AUDIENCE, operation))
        return {'revoked': True}

    return bridge
