"""Course demo: durable upload and optional, explicitly enabled cloud inference."""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
from contextlib import closing, asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator

from protocol import FS, decode_chunk, signal_origin, valid
from cloud_model.engine import AnalysisService, AnalysisBusy
from physiology_analysis import PhysiologyService, MAX_SAMPLES as MAX_PHYSIOLOGY_SAMPLES
from auth_store import AuthStore, COOKIE, SESSION_SECONDS
from workspace_store import WorkspaceStore
from analysis_tasks import AnalysisQueue, FileLock, QueueFull
import measurement_store
from device_store import DeviceStore
from device_routes import add_routes as add_device_routes
from database_management import DatabaseManager
from database_routes import add_routes as add_database_routes
from workflow_store import WorkflowStore, cancel_record_intents
from workflow_routes import add_routes as add_workflow_routes
from annotations import add_routes as add_annotation_routes
from backup_schedule import BackupSchedule, add_routes as add_backup_schedule_routes
from maintenance_tasks import MaintenanceQueue
from admin_console import add_routes as add_admin_console_routes
from update_routes import add_routes as add_update_routes

ROOT = Path(__file__).resolve().parent
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z')
MAX_BODY = 2 * 1024 * 1024
MODEL = {'model_status': 'not_configured', 'model_result': None}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SessionProvenance(StrictModel):
    """Transfer/clock observations, deliberately separate from acquisition data."""
    kind: Literal['live', 'historical', 'unknown'] = 'unknown'
    clock_status: Literal['ok', 'offset', 'unknown'] = 'unknown'
    clock_offset_seconds: float | None = Field(default=None, strict=True)
    clock_reference: Literal['cloud', 'computer', 'unknown'] = 'unknown'
    clock_checked_at: AwareDatetime | None = None
    origin_device: str | None = Field(default=None, max_length=96)
    note: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def validate_clock_observation(self):
        if self.clock_status != 'unknown':
            if self.clock_offset_seconds is None or self.clock_checked_at is None or self.clock_reference == 'unknown':
                raise ValueError('时钟已检查状态必须包含偏差、检查时间和参考时钟')
            expected = 'ok' if abs(self.clock_offset_seconds) <= 5 else 'offset'
            if self.clock_status != expected:
                raise ValueError('时钟差值在正负5秒内应标为ok，超出应标为offset')
        return self


class SessionInput(StrictModel):
    source: Literal['demo', 'serial', 'replay', 'unknown']
    sample_rate_hz: Literal[360] = 360
    vref_v: float = Field(default=3.3, gt=0, le=10)
    started_utc: AwareDatetime
    source_status: str = Field(default='recording', max_length=40)
    provenance: SessionProvenance | None = None
    owner_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class DetailsInput(StrictModel):
    name: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=1000)


class DeviceInformation(StrictModel):
    model: str = Field(default='', max_length=100)
    platform: str = Field(default='', max_length=100)
    app_version: str = Field(default='', max_length=40)
    serial_port: str = Field(default='', max_length=100)
    sample_rate_hz: Literal[360] = 360
    protocol: str = Field(default='ECG UART 7-byte', max_length=80)


class HeartbeatInput(StrictModel):
    state: Literal['standby', 'acquiring', 'saving', 'error']
    owner_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    session_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
    signal_state: str = Field(default='unknown', max_length=40)
    signal_text: str = Field(default='', max_length=120)
    received: int = Field(default=0, ge=0)
    saved: int = Field(default=0, ge=0)
    free_bytes: int | None = Field(default=None, ge=0)
    pending_uploads: int = Field(default=0, ge=0, le=10000)
    upload_phase: str = Field(default='idle', max_length=40)
    remote_ready: bool = Field(default=False, strict=True)
    device_info: DeviceInformation | None = None


class LoginInput(StrictModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class CreateUserInput(LoginInput):
    is_admin: bool = False


class AssignInput(StrictModel):
    owner_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class NewPasswordInput(StrictModel):
    new_password: str = Field(min_length=5, max_length=128)


class ChangePasswordInput(NewPasswordInput):
    current_password: str = Field(min_length=1, max_length=128)


class UserStateInput(StrictModel):
    active: bool = Field(strict=True)


class ChunkInput(StrictModel):
    payload_base64: str = Field(max_length=1100000)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    sample_count: int = Field(gt=0, le=36000, strict=True)
    first_sample_id: int = Field(ge=0, strict=True)
    last_sample_id: int = Field(ge=0, strict=True)
    received_first_utc: AwareDatetime
    received_last_utc: AwareDatetime


class ManifestItem(StrictModel):
    chunk_id: int = Field(ge=0, le=99999999, strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    sample_count: int = Field(gt=0, strict=True)


class CompleteInput(StrictModel):
    chunks: list[ManifestItem] = Field(max_length=10000)
    sample_count: int = Field(ge=0, strict=True)
    source_status: str = Field(max_length=40)
    measurement_summary: measurement_store.MeasurementSummary | None = None


def create_app(data_dir=None, token=None, device_id=None, auth_enabled=None, cookie_secure=None):
    data = Path(data_dir or os.getenv('ECG_DATA_DIR', ROOT / 'data')).resolve()
    data.mkdir(parents=True, exist_ok=True)
    token = os.getenv('ECG_API_TOKEN', '') if token is None else token
    device_id = device_id or os.getenv('ECG_DEVICE_ID', 'pi2-demo')
    deployment = os.getenv('ECG_DEPLOYMENT', 'local')
    if deployment not in ('local', 'cloud'):
        raise ValueError('部署位置仅支持local或cloud')
    if not ID.fullmatch(device_id):
        raise ValueError('设备编号仅允许字母、数字、横线和下划线')
    database = data / 'cloud.sqlite'
    lock = threading.RLock()
    auth_enabled = os.getenv('ECG_AUTH_REQUIRED', '0') == '1' if auth_enabled is None else auth_enabled
    cookie_secure = os.getenv('ECG_COOKIE_SECURE', '1') == '1' if cookie_secure is None else cookie_secure
    if os.getenv('ECG_PUBLIC_ACCESS') == '1' and not (auth_enabled and cookie_secure):
        raise ValueError('公网入口必须开启账号模式和安全登录 Cookie')
    identity = ContextVar('ecg_identity', default={'kind': 'legacy'})
    model_service = AnalysisService(data, os.getenv('ECG_MODEL', ''))
    physiology_service = PhysiologyService(data)

    def connect():
        db = sqlite3.connect(database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        return db

    with closing(connect()) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
            received_at TEXT, sample_count INTEGER NOT NULL DEFAULT 0,
            valid_count INTEGER NOT NULL DEFAULT 0, complete INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chunks (
            session_id TEXT NOT NULL REFERENCES sessions(id), chunk_id INTEGER NOT NULL,
            sha256 TEXT NOT NULL, sample_count INTEGER NOT NULL, first_id INTEGER NOT NULL,
            last_id INTEGER NOT NULL, valid_count INTEGER NOT NULL, descriptor TEXT NOT NULL,
            PRIMARY KEY(session_id, chunk_id));
        CREATE INDEX IF NOT EXISTS chunk_ranges ON chunks(session_id, first_id, last_id);
        CREATE TABLE IF NOT EXISTS session_provenance (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),
            details TEXT NOT NULL, noted_at TEXT NOT NULL);
        ''')
        measurement_store.initialize(db)
        old = db.execute("SELECT value FROM settings WHERE name='device_id'").fetchone()
        if old and old[0] != device_id:
            raise ValueError('已有数据库属于另一设备，请使用独立数据目录')
        db.execute("INSERT OR IGNORE INTO settings VALUES('device_id', ?)", (device_id,))
        db.commit()

    workspace = WorkspaceStore(connect)
    auth = AuthStore(connect)
    devices = DeviceStore(connect, device_id)
    if os.getenv('ECG_PUBLIC_ACCESS') == '1' and not any(u['active'] and u['is_admin'] for u in auth.users()):
        raise ValueError('公网启动前请先创建管理员账号')
    jobs = AnalysisQueue(data, os.getenv('ECG_MODEL', ''))
    database_manager = DatabaseManager(data, lock, lambda: model_service.active_session)
    maintenance = MaintenanceQueue(data)
    backup_schedule = BackupSchedule(data, maintenance)
    workflow = WorkflowStore(data, jobs, model_service, physiology_service)
    @asynccontextmanager
    async def lifespan(_app):
        if jobs.has_pending(): jobs.start()
        if maintenance.has_pending(): maintenance.start()
        workflow.start()
        backup_schedule.start()
        try: yield
        finally:
            workflow.close()
            backup_schedule.close()
            maintenance.close()
            jobs.close()
    app = FastAPI(title='心电数据工作台', version='1.1.0', docs_url=None if auth_enabled else '/docs', redoc_url=None, lifespan=lifespan)
    app.state.auth = auth
    app.state.devices = devices
    app.state.jobs = jobs
    app.state.database = database_manager
    app.state.maintenance = maintenance
    updates = add_update_routes(app, ROOT)
    app.state.workflow = workflow
    app.state.backup_schedule = backup_schedule

    from heartlife_bridge import MACHINE_ROUTES, add_routes as add_heartlife_routes
    heartlife = add_heartlife_routes(app, connect, identity, auth_enabled)
    app.state.heartlife = heartlife

    @app.middleware('http')
    async def guard(request: Request, call_next):
        who = {'kind': 'legacy'}
        if request.url.path.startswith('/api/'):
            public_update = request.method == 'GET' and request.url.path == '/api/updates'
            machine_route = (request.method, request.url.path) in MACHINE_ROUTES
            if machine_route:
                # Dedicated grant routes never acquire general user/device identity.
                try:
                    heartlife.require_client(request)
                except HTTPException as exc:
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code,
                                        headers={'Cache-Control': 'no-store'})
            elif auth_enabled and not public_update and request.url.path not in ('/api/auth/config', '/api/auth/login', '/api/account-applications'):
                who = auth.authenticate(request)
                if who is None:
                    return JSONResponse({'detail': '请先登录'}, status_code=401)
                if who['kind'] == 'user' and request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), who['csrf_token']):
                        return JSONResponse({'detail': '登录校验已失效，请刷新页面'}, status_code=403)
            elif not auth_enabled and token and not public_update and request.url.path != '/api/auth/config' and not hmac.compare_digest(request.headers.get('x-api-key', ''), token):
                return JSONResponse({'detail': '访问凭证不正确'}, status_code=401)
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '不接受跨站请求'}, status_code=403)
            if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                received = bytearray()
                async for part in request.stream():
                    received.extend(part)
                    if len(received) > MAX_BODY:
                        return JSONResponse({'detail': '请求超过2 MiB限制'}, status_code=413)
                request._body = bytes(received)
        context = identity.set(who)
        try:
            response = await call_next(request)
        finally:
            identity.reset(context)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if who.get('kind') == 'user': response.headers['X-ECG-User'] = who['id']
        return response

    def require_device(db=None):
        who = identity.get()
        if auth_enabled and who['kind'] != 'device':
            raise HTTPException(403, '此操作仅允许已授权采集设备')
        did=who['device_id'] if auth_enabled else device_id
        if auth_enabled:
            if db is None:
                with closing(connect()) as connection:return require_device(connection)
            current=db.execute('SELECT 1 FROM device_keys k JOIN devices d ON d.id=k.device_id '
                'WHERE k.token_hash=? AND k.device_id=? AND d.active=1',(who['token_hash'],did)).fetchone()
            if not current:raise HTTPException(401,'设备凭据已失效或设备已停用')
        else:devices.require(did)
        return did

    def require_admin():
        who = identity.get()
        if not auth_enabled or who['kind'] != 'user' or not who['is_admin']:
            raise HTTPException(403, '需要管理员账号')

    add_device_routes(app,devices,require_admin)
    add_database_routes(app, database_manager, maintenance, require_admin, identity.get)
    add_backup_schedule_routes(app, backup_schedule, require_admin, identity.get)
    add_admin_console_routes(app, data, require_admin, identity.get)

    from health_routes import add_routes as add_health_routes
    add_health_routes(app, connect, identity, devices, require_device, auth_enabled)
    from account_applications import add_routes as add_application_routes
    add_application_routes(app,connect,require_admin,auth_enabled)

    @app.get('/api/auth/config')
    def auth_config():
        return {'enabled': auth_enabled, 'heartlife_url': heartlife.public_url}

    @app.post('/api/auth/login')
    def login(payload: LoginInput, request: Request):
        if not auth_enabled: raise HTTPException(404, '账号模式未启用')
        bearer, result = auth.login(payload.username, payload.password, request.client.host if request.client else 'unknown')
        response = JSONResponse(result)
        response.set_cookie(COOKIE, bearer, max_age=SESSION_SECONDS, httponly=True, secure=cookie_secure, samesite='strict')
        return response

    @app.get('/api/auth/me')
    def me():
        who = identity.get()
        if who['kind'] != 'user': raise HTTPException(403, '需要用户登录')
        return {'user': {k: who[k] for k in ('id', 'username', 'is_admin', 'active')}, 'csrf_token': who['csrf_token']}

    @app.post('/api/auth/logout')
    def logout(request: Request):
        auth.logout(request)
        response = JSONResponse({'ok': True})
        # Server-side revocation is authoritative. A delayed response must not
        # overwrite a newer login cookie established by another browser tab.
        return response

    @app.get('/api/admin/users')
    def users():
        require_admin()
        return {'users': auth.admin_users()}

    @app.post('/api/admin/users/{user_id}/revoke-sessions')
    def revoke_user_sessions(user_id: str):
        require_admin()
        return auth.revoke_user_sessions(user_id)

    @app.post('/api/auth/password')
    def change_password(payload: ChangePasswordInput):
        who = identity.get()
        if who['kind'] != 'user': raise HTTPException(403, '需要用户登录')
        auth.change_password(who['id'], payload.current_password, payload.new_password)
        response = JSONResponse({'ok': True, 'message': '密码已修改，请重新登录'})
        # Do not clear the shared cookie: a newer tab may have logged in while
        # this password-change request was in flight. All old tokens are revoked.
        return response

    @app.post('/api/admin/users/{user_id}/password')
    def reset_password(user_id: str, payload: NewPasswordInput):
        require_admin()
        return auth.manage_user(user_id, new_password=payload.new_password)

    @app.patch('/api/admin/users/{user_id}')
    def set_user_state(user_id: str, payload: UserStateInput):
        require_admin()
        return auth.manage_user(user_id, active=payload.active)

    @app.post('/api/admin/users')
    def create_user(payload: CreateUserInput):
        require_admin()
        try: return auth.create_user(payload.username, payload.password, payload.is_admin)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc

    @app.get('/api/device/recipients')
    def recipients():
        did=require_device()
        return {'users': devices.recipients(did) if auth_enabled else [],
                'auth_required': auth_enabled, 'device_id': did}

    @app.put('/api/device/heartbeat')
    def heartbeat(payload: HeartbeatInput):
        with closing(connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            did=require_device(db)
            if auth_enabled and payload.owner_id: devices.require_recipient(did,payload.owner_id,db)
            if payload.session_id:
                row=db.execute('SELECT ingest_device_id,owner_id FROM sessions WHERE id=?',(payload.session_id,)).fetchone()
                if row and (row['ingest_device_id']!=did or (auth_enabled and row['owner_id']!=payload.owner_id)):
                    raise HTTPException(409,'心跳记录与设备或使用者不一致')
            return workspace.heartbeat(payload.model_dump(),did,db)

    def device_status(item):
        result={**item,**workspace.device(identity.get() if auth_enabled else None,item['device_id'])}
        if not item['active']:result.update(connection='disabled',state='unknown',signal_state='unknown',signal_text='',session_id=None,owner_id=None,received=0,saved=0)
        return result

    @app.get('/api/devices')
    def list_devices():
        who=identity.get()
        if auth_enabled and who['kind']!='user':raise HTTPException(403,'需要用户登录')
        return {'devices':[device_status(d) for d in devices.list(who if auth_enabled else None)]}

    @app.get('/api/device')
    def device():
        who=identity.get()
        if auth_enabled and who['kind']=='device':
            return device_status(devices.require(require_device()))
        visible=devices.list(who if auth_enabled else None)
        item=next((d for d in visible if d['device_id']==device_id),visible[0] if visible else None)
        return device_status(item) if item else dict(device_id=None,connection='unknown',state='unknown')

    def check_id(session_id):
        if not ID.fullmatch(session_id):
            raise HTTPException(400, '无效会话编号')

    def find_session(db, session_id, active=False):
        check_id(session_id)
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '会话不存在')
        if auth_enabled:
            who = identity.get()
            if ((who['kind'] == 'user' and row['owner_id'] != who['id']) or
                (who['kind'] == 'device' and row['ingest_device_id'] != who['device_id'])):
                raise HTTPException(404, '会话不存在')
        if active:
            detail = db.execute('SELECT trashed_at FROM session_details WHERE session_id=?', (session_id,)).fetchone()
            if detail and detail['trashed_at']: raise HTTPException(409, '记录已在回收站，请先恢复')
        return row

    def chunk_path(session_id, chunk_id):
        return data / 'sessions' / session_id / 'chunks' / f'{chunk_id:08d}.bin'

    def read_rows(session_id, row):
        try:
            return decode_chunk(chunk_path(session_id, row['chunk_id']).read_bytes(), row['sha256'])
        except (OSError, ValueError) as exc:
            raise HTTPException(409, f"存储数据块{row['chunk_id']}损坏或缺失，请重新核对源记录") from exc

    def summary(db, row):
        chunks = db.execute('SELECT COUNT(*), MIN(first_id), MAX(last_id) FROM chunks WHERE session_id=?', (row['id'],)).fetchone()
        provenance_row = db.execute('SELECT details FROM session_provenance WHERE session_id=?', (row['id'],)).fetchone()
        provenance = json.loads(provenance_row['details']) if provenance_row else SessionProvenance().model_dump(mode='json')
        detail = db.execute('SELECT name,note,trashed_at FROM session_details WHERE session_id=?', (row['id'],)).fetchone()
        return dict(session_id=row['id'], device_id=row['ingest_device_id'], measurement_summary=measurement_store.read(db, row['id']), **json.loads(row['metadata']),
                    **(dict(detail) if detail else dict(name='', note='', trashed_at=None)), owner_id=row['owner_id'],
                    # First registration is not the time of the first ADC sample.
                    first_uploaded_at=row['created_at'], last_uploaded_at=row['received_at'], provenance=provenance,
                    received_at=row['received_at'], sample_count=row['sample_count'],
                    valid_count=row['valid_count'], chunk_count=chunks[0], first_sample_id=chunks[1],
                    last_sample_id=chunks[2], upload_status='complete' if row['complete'] else 'receiving', **model_service.identity())

    @app.get('/health')
    def health():
        with closing(connect()) as db:
            db.execute('SELECT 1').fetchone()
        return {'ok': True, 'service': 'ecg-course-demo', 'device_id': device_id,
                'deployment': deployment, 'time': now(), 'auth_required': auth_enabled, 'workspace_version': 1, 'health_assistant_version': 1, **model_service.identity()}

    @app.put('/api/sessions/{session_id}')
    def register(session_id: str, payload: SessionInput):
        did=require_device()
        check_id(session_id)
        # Provenance does not change original metadata or model input/cache keys.
        meta = payload.model_dump(mode='json', exclude={'provenance', 'owner_id'})
        if auth_enabled and payload.owner_id: auth.require_user(payload.owner_id)
        with lock, closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');require_device(db)
            existing = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
            if existing:
                find_session(db, session_id, active=True)
                if payload.owner_id is not None and payload.owner_id != existing['owner_id']:
                    raise HTTPException(409, '会话所属账号不能通过补传修改')
                old = json.loads(existing['metadata'])
                if any(old[k] != meta[k] for k in ('source', 'sample_rate_hz', 'vref_v', 'started_utc')):
                    raise HTTPException(409, '同一会话的来源、采样率、电压或起始时间不允许改变')
                if payload.provenance is not None:
                    db.execute('INSERT OR IGNORE INTO session_provenance VALUES(?,?,?)',
                               (session_id, payload.provenance.model_dump_json(), now()))
                return summary(db, existing)
            if auth_enabled: devices.require_recipient(did,payload.owner_id,db)
            db.execute('INSERT INTO sessions(id, metadata, created_at,owner_id,ingest_device_id) VALUES(?,?,?,?,?)',
                       (session_id, json.dumps(meta), now(), payload.owner_id if auth_enabled else None, did))
            if payload.provenance is not None:
                db.execute('INSERT INTO session_provenance VALUES(?,?,?)',
                           (session_id, payload.provenance.model_dump_json(), now()))
            return summary(db, find_session(db, session_id))

    @app.put('/api/sessions/{session_id}/provenance')
    def annotate_provenance(session_id: str, payload: SessionProvenance):
        require_device()
        with lock, closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');require_device(db)
            item = find_session(db, session_id, active=True)
            db.execute('INSERT INTO session_provenance VALUES(?,?,?) '
                       'ON CONFLICT(session_id) DO UPDATE SET details=excluded.details,noted_at=excluded.noted_at',
                       (session_id, payload.model_dump_json(), now()))
            return summary(db, item)

    @app.put('/api/sessions/{session_id}/chunks/{chunk_id}')
    def upload(session_id: str, chunk_id: int, payload: ChunkInput):
        require_device()
        check_id(session_id)
        if not 0 <= chunk_id <= 99999999:
            raise HTTPException(400, '无效数据块编号')
        try:
            raw = base64.b64decode(payload.payload_base64, validate=True)
            rows = decode_chunk(raw, payload.sha256)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if (len(rows) != payload.sample_count or rows[0][0] != payload.first_sample_id
                or rows[-1][0] != payload.last_sample_id or payload.received_last_utc < payload.received_first_utc):
            raise HTTPException(400, '描述信息与原始数据不匹配')
        descriptor = payload.model_dump(mode='json', exclude={'payload_base64'})
        ack = {'session_id': session_id, 'chunk_id': chunk_id, 'sha256': payload.sha256, 'sample_count': len(rows)}
        with lock, closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');require_device(db)
            session = find_session(db, session_id, active=True)
            previous = db.execute('SELECT * FROM chunks WHERE session_id=? AND chunk_id=?', (session_id, chunk_id)).fetchone()
            if previous:
                if previous['descriptor'] != json.dumps(descriptor, sort_keys=True):
                    raise HTTPException(409, '同一数据块编号已有不同内容或描述')
                read_rows(session_id, previous)
                return dict(ack, duplicate=True)
            if session['complete']:
                raise HTTPException(409, '会话已完成，不能追加数据块')
            overlap = db.execute('SELECT 1 FROM chunks WHERE session_id=? AND '
                '((chunk_id < ? AND last_id >= ?) OR (chunk_id > ? AND first_id <= ?)) LIMIT 1',
                (session_id, chunk_id, rows[0][0], chunk_id, rows[-1][0])).fetchone()
            if overlap:
                raise HTTPException(409, '数据块的采样编号重叠或倒序')
            target = chunk_path(session_id, chunk_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(f'.{uuid.uuid4().hex}.tmp')
            try:
                with temp.open('wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
                if os.name != 'nt':
                    fd = os.open(target.parent, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                good = sum(valid(row) for row in rows)
                db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                    (session_id, chunk_id, payload.sha256, len(rows), rows[0][0], rows[-1][0], good,
                     json.dumps(descriptor, sort_keys=True)))
                db.execute('UPDATE sessions SET sample_count=sample_count+?, valid_count=valid_count+?, received_at=? WHERE id=?',
                           (len(rows), good, now(), session_id))
            finally:
                temp.unlink(missing_ok=True)
        return dict(ack, duplicate=False)

    @app.post('/api/sessions/{session_id}/complete')
    def complete(session_id: str, payload: CompleteInput):
        require_device()
        if payload.source_status == 'recording':
            raise HTTPException(400, '源会话尚未停止')
        with lock, closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE');require_device(db)
            row = find_session(db, session_id, active=True)
            actual = db.execute('SELECT * FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,)).fetchall()
            expected = [x.model_dump() for x in payload.chunks]
            manifest = [{k: c[k] for k in ('chunk_id', 'sha256', 'sample_count')} for c in actual]
            if expected != manifest or payload.sample_count != row['sample_count']:
                raise HTTPException(409, '数据块清单或点数未对齐，需继续补传')
            meta = json.loads(row['metadata'])
            real_count = valid_real_count = 0
            for chunk in actual:
                rows = read_rows(session_id, chunk)
                if meta['source'] == 'serial':
                    real_count += sum(r[6] == 0 for r in rows)
                    valid_real_count += sum(r[6] == 0 and valid(r) for r in rows)
            measurement_store.save(db, session_id, payload.measurement_summary,
                sample_count=row['sample_count'], real_count=real_count, valid_real_count=valid_real_count)
            meta['source_status'] = payload.source_status
            db.execute('UPDATE sessions SET complete=1, metadata=? WHERE id=?', (json.dumps(meta), session_id))
            workflow.completed(db, row)
            return summary(db, find_session(db, session_id))

    @app.get('/api/sessions')
    def list_sessions(limit: Annotated[int, Query(ge=1, le=100)] = 100,
                      offset: Annotated[int, Query(ge=0)] = 0, q: Annotated[str, Query(max_length=100)] = '',
                      source: Literal['serial','demo','replay','unknown'] | None = None,
                      started_from: AwareDatetime | None = None, started_before: AwareDatetime | None = None,
                      trashed: bool = False, device_id: Annotated[str | None, Query(max_length=96)] = None):
        who = identity.get()
        if auth_enabled and who['kind'] != 'user': raise HTTPException(403, '设备不能查询全部记录列表')
        if started_from and started_before and started_from >= started_before:
            raise HTTPException(422, '开始日期必须早于结束日期')
        conditions, params = ['d.trashed_at IS NOT NULL' if trashed else 'd.trashed_at IS NULL'], []
        if auth_enabled:
            conditions.append('s.owner_id=?'); params.append(who['id'])
        if q.strip():
            conditions.append("instr(lower(s.id||' '||COALESCE(d.name,'')||' '||COALESCE(d.note,'')),lower(?))>0"); params.append(q.strip())
        if source:
            conditions.append("json_extract(s.metadata,'$.source')=?"); params.append(source)
        if device_id:
            conditions.append('s.ingest_device_id=?'); params.append(device_id)
        for value, op in ((started_from, '>='), (started_before, '<')):
            if value:
                conditions.append("julianday(json_extract(s.metadata,'$.started_utc'))" + op + 'julianday(?)')
                params.append(value.isoformat())
        query = ' FROM sessions s LEFT JOIN session_details d ON d.session_id=s.id WHERE ' + ' AND '.join(conditions)
        with closing(connect()) as db:
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*)' + query, params).fetchone()[0]
            rows = db.execute('SELECT s.*' + query + ' ORDER BY s.created_at DESC,s.id DESC LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
            return {'sessions': [summary(db, row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    @app.patch('/api/sessions/{session_id}/details')
    def edit_details(session_id: str, payload: DetailsInput):
        if auth_enabled and identity.get()['kind'] != 'user': raise HTTPException(403, '需要用户登录')
        with lock, closing(connect()) as db, db:
            item = find_session(db, session_id)
            db.execute('INSERT INTO session_details(session_id,name,note) VALUES(?,?,?) ON CONFLICT(session_id) '
                       'DO UPDATE SET name=excluded.name,note=excluded.note', (session_id, payload.name.strip(), payload.note.strip()))
            return summary(db, item)

    @app.post('/api/sessions/{session_id}/trash')
    def trash(session_id: str):
        if auth_enabled and identity.get()['kind'] != 'user': raise HTTPException(403, '需要用户登录')
        compute = FileLock(data/'.analysis-compute.lock')
        with lock:
            # Check ownership before revealing operational state.
            with closing(connect()) as db: find_session(db, session_id)
            if not compute.acquire(): raise HTTPException(409, '后台正在分析，请稍后再管理记录')
            try:
                with closing(connect()) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    item = find_session(db, session_id)
                    pending = db.execute("SELECT 1 FROM analysis_jobs WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone()
                    if not item['complete'] or pending or model_service.active_session == session_id:
                        raise HTTPException(409, '请等待上传和分析完成后再移入回收站')
                    db.execute('INSERT INTO session_details(session_id,trashed_at) VALUES(?,?) ON CONFLICT(session_id) '
                               'DO UPDATE SET trashed_at=excluded.trashed_at', (session_id, now()))
                    cancel_record_intents(db, session_id)
                    return summary(db, item)
            finally: compute.release()

    @app.post('/api/sessions/{session_id}/restore')
    def restore(session_id: str):
        if auth_enabled and identity.get()['kind'] != 'user': raise HTTPException(403, '需要用户登录')
        with lock, closing(connect()) as db, db:
            item = find_session(db, session_id)
            db.execute('UPDATE session_details SET trashed_at=NULL WHERE session_id=?', (session_id,))
            return summary(db, item)

    @app.get('/api/admin/unassigned-sessions')
    def unassigned():
        require_admin()
        with closing(connect()) as db:
            rows = db.execute('SELECT * FROM sessions WHERE owner_id IS NULL ORDER BY created_at DESC LIMIT 100').fetchall()
            return {'sessions': [summary(db, row) for row in rows]}

    @app.post('/api/admin/sessions/{session_id}/assign')
    def assign(session_id: str, payload: AssignInput):
        require_admin(); check_id(session_id); auth.require_user(payload.owner_id)
        with lock, closing(connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
            if row is None: raise HTTPException(404, '会话不存在')
            if row['owner_id'] is not None: raise HTTPException(409, '记录已有归属，不能再次分配')
            db.execute('UPDATE sessions SET owner_id=? WHERE id=?', (payload.owner_id, session_id))
            return {'ok': True}

    @app.get('/api/sessions/{session_id}')
    def session_detail(session_id: str):
        with closing(connect()) as db:
            result = summary(db, find_session(db, session_id))
            result['chunks'] = [dict(c) for c in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
            return result

    @app.get('/api/sessions/{session_id}/analysis')
    def analysis(session_id: str):
        with closing(connect()) as db:
            db.execute('BEGIN')
            item = find_session(db, session_id)
            metadata = json.loads(item['metadata'])
            manifest = [dict(c) for c in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
            digest = model_service.digest(metadata, item['complete'], manifest)
        result = model_service.read(session_id, digest)
        job = jobs.latest(session_id)
        if job and job['source_digest'] == digest:
            result['task'] = job
            if job['status'] in ('queued','running','failed'):
                result.update(analysis_status=job['status'], message=job['error'] or job['stage'], model_result=None)
        return result

    @app.post('/api/sessions/{session_id}/analysis-jobs', status_code=202)
    def enqueue_analysis(session_id: str, force: bool = False):
        def authorize(db):
            if auth_enabled and identity.get()['kind']=='device':require_device(db)
            return find_session(db,session_id,active=True)
        with lock, closing(connect()) as db:
            db.execute('BEGIN')
            item = authorize(db)
            if not item['complete']: raise HTTPException(409, '请先完成上传和清单校验')
            if model_service.model_status != 'ready': raise HTTPException(409, '模型尚未就绪')
            metadata = json.loads(item['metadata'])
            manifest = [dict(c) for c in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
            digest = model_service.digest(metadata, item['complete'], manifest)
            cached = model_service.read(session_id, digest)['analysis_status'] in ('complete','ineligible')
            total = item['sample_count']
            if total > 1000000: raise HTTPException(409, '心搏分类暂仅支持不超过 100 万采样点的记录')
            db.rollback()
            try: job = jobs.enqueue(session_id, digest, total, force=force, cached=cached, authorize=authorize,
                                   on_enqueued=lambda db, job: workflow.submitted(db, session_id, 'model', job))
            except QueueFull as exc: raise HTTPException(429, str(exc)) from exc
            except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        jobs.start()
        return job

    @app.get('/api/sessions/{session_id}/physiology')
    def physiology(session_id: str, include_series: bool = False):
        with closing(connect()) as db:
            db.execute('BEGIN')
            item = find_session(db, session_id)
            metadata = json.loads(item['metadata'])
            manifest = [dict(c) for c in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
            digest = physiology_service.digest(metadata, item['complete'], manifest)
        result = physiology_service.read(session_id, digest)
        job = jobs.latest(session_id, kind='physiology')
        if job and job['source_digest'] == digest:
            result['task'] = job
            if job['status'] in ('queued','running','failed'):
                # A retry must not present an earlier result as its outcome.
                result = physiology_service.response(session_id, job['status'], job['error'] or job['stage'], digest, task=job)
        if not include_series:
            result.pop('r_peaks', None)
            result.pop('rr_intervals', None)
        return result

    @app.post('/api/sessions/{session_id}/physiology-jobs', status_code=202)
    def enqueue_physiology(session_id: str, force: bool = False):
        def authorize(db):
            if auth_enabled and identity.get()['kind']=='device': require_device(db)
            return find_session(db, session_id, active=True)
        with lock, closing(connect()) as db:
            db.execute('BEGIN')
            item = authorize(db)
            if not item['complete']: raise HTTPException(409, '请先完成上传和清单校验')
            if not physiology_service.ready: raise HTTPException(409, 'QRS/RR 分析依赖尚未就绪')
            total = item['sample_count']
            if total > MAX_PHYSIOLOGY_SAMPLES: raise HTTPException(409, 'QRS/RR 暂仅支持不超过 100 万采样点的记录')
            metadata = json.loads(item['metadata'])
            manifest = [dict(c) for c in db.execute('SELECT chunk_id,sha256,sample_count FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
            digest = physiology_service.digest(metadata, item['complete'], manifest)
            cached = physiology_service.read(session_id, digest)['analysis_status'] in ('complete','ineligible')
            db.rollback()
            try: job = jobs.enqueue(session_id, digest, total, force=force, cached=cached, authorize=authorize, kind='physiology',
                                   on_enqueued=lambda db, job: workflow.submitted(db, session_id, 'physiology', job))
            except QueueFull as exc: raise HTTPException(429, str(exc)) from exc
            except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        jobs.start()
        return job

    @app.get('/api/analysis-jobs/{job_id}')
    def get_job(job_id: str):
        check_id(job_id)
        job = jobs.get(job_id)
        if job is None: raise HTTPException(404, '任务不存在')
        with closing(connect()) as db: find_session(db, job['session_id'])
        return job

    @app.post('/api/sessions/{session_id}/analysis')
    def recompute_analysis(session_id: str):
        compute = FileLock(data/'.analysis-compute.lock')
        with lock:
            with closing(connect()) as db: find_session(db, session_id, active=True)
            if not compute.acquire(): raise HTTPException(409, '后台已有分析任务，请稍后重试')
        try:
            with closing(connect()) as db,db:
                # Committing this short transaction accepts the analysis. Later
                # credential revocation blocks new work, not an accepted job.
                db.execute('BEGIN IMMEDIATE')
                if auth_enabled and identity.get()['kind']=='device':require_device(db)
                item = dict(find_session(db, session_id, active=True))
                metadata = json.loads(item['metadata'])
                chunks = [dict(c) for c in db.execute('SELECT * FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,))]
                manifest = [{k: c[k] for k in ('chunk_id', 'sha256', 'sample_count')} for c in chunks]
                digest = model_service.digest(metadata, item['complete'], manifest)
            def batches():
                for chunk in chunks:
                    yield json.loads(chunk['descriptor']), read_rows(session_id, chunk)
            return model_service.run(session_id, metadata, item['complete'], item['sample_count'], digest, batches())
        except AnalysisBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(409, '模型分析未完成：' + str(exc)) from exc
        finally: compute.release()

    @app.get('/api/sessions/{session_id}/waveform')
    def waveform(session_id: str, seconds: Annotated[int, Query(ge=1, le=60)] = 10,
                 end_sample: Annotated[int | None, Query(ge=0)] = None):
        with closing(connect()) as db:
            item = summary(db, find_session(db, session_id))
            last = item['last_sample_id']
            end = min(last, end_sample) if last is not None and end_sample is not None else last
            start = max(0, end - seconds * FS + 1) if end is not None else 0
            chunks = db.execute('SELECT * FROM chunks WHERE session_id=? AND last_id>=? AND first_id<=? ORDER BY chunk_id',
                               (session_id, start, end if end is not None else -1)).fetchall()
            points = []
            prior = None
            for chunk in chunks:
                for row in read_rows(session_id, chunk):
                    if not start <= row[0] <= end:
                        continue
                    broken = bool(row[5] & 28) or (prior is not None and (row[0] != prior[0]+1 or row[1] != prior[1] or row[6] != prior[6]))
                    points.append([row[0], row[4] if valid(row) else None, row[1], row[5], row[6], broken])
                    prior = row
        return {'session': item, 'start_sample': start, 'end_sample': end, 'points': points}

    @app.get('/api/sessions/{session_id}/export')
    def export(session_id: str):
        # Bound the course export; avoid an unbounded response allocation.
        with closing(connect()) as db:
            session = find_session(db, session_id)
            if session['sample_count'] > 1000000:
                raise HTTPException(413, '当前课程版下载限100万点，请分会话记录')
            meta = json.loads(session['metadata'])
            out = io.StringIO(newline='')
            writer = csv.writer(out)
            writer.writerow(['session_id','source','sample_id','segment_id','segment_index','time_s','segment_time_s',
                'sequence','raw_adc','flags','valid','voltage_v','vref_v','received_first_utc','received_last_utc','mode','signal_origin'])
            for chunk in db.execute('SELECT * FROM chunks WHERE session_id=? ORDER BY chunk_id', (session_id,)):
                d = json.loads(chunk['descriptor'])
                for row in read_rows(session_id, chunk):
                    sample, segment, index, sequence, adc, flags, mode = row
                    writer.writerow([session_id,meta['source'],sample,segment,index,f'{sample/FS:.9f}',f'{index/FS:.9f}',
                        sequence,adc,flags,int(valid(row)),f'{adc*meta["vref_v"]/4095:.9f}' if valid(row) else '',
                        meta['vref_v'],d['received_first_utc'],d['received_last_utc'],'' if mode is None else mode,
                        signal_origin(meta['source'],mode)])
        return Response(out.getvalue().encode('utf-8-sig'), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{session_id}.csv"'})

    add_workflow_routes(app, workflow, identity.get, find_session, require_admin)
    add_annotation_routes(app, connect, identity.get, find_session)

    app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')

    @app.get('/heartlife-connect')
    def heartlife_connect():
        return FileResponse(ROOT / 'web' / 'heartlife-connect.html',
                            headers={'Referrer-Policy': 'no-referrer'})

    @app.get('/tasks')
    def tasks_page():
        return updates.page('tasks.html')

    @app.get('/operations')
    def operations_page():
        return updates.page('operations.html')

    @app.get('/downloads/{filename}')
    def desktop_download(filename: str):
        allowed = {
            'ecg-workspace-windows.zip': ('心电工作台-Windows免安装.zip', 'application/zip'),
            'ecg-workspace-windows.zip.sha256': ('心电工作台-Windows免安装.zip.sha256', 'text/plain'),
        }
        if filename not in allowed:
            raise HTTPException(404, '下载文件不存在')
        name, content_type = allowed[filename]
        folder = ROOT / 'deploy/dist/desktop'
        artifact = folder / name
        if artifact.is_symlink() or not artifact.is_file() or artifact.resolve().parent != folder.resolve():
            raise HTTPException(404, '电脑端下载尚未发布，请先使用网页')
        return FileResponse(artifact, media_type=content_type, filename=name)

    @app.get('/manifest.webmanifest')
    def app_manifest():
        return FileResponse(ROOT / 'web' / 'manifest.webmanifest',media_type='application/manifest+json')

    @app.get('/sw.js')
    def app_worker():
        return FileResponse(ROOT / 'web' / 'sw.js',media_type='application/javascript',
                            headers={'Service-Worker-Allowed':'/'})

    @app.get('/')
    def index():
        return updates.page('index.html')

    @app.get('/devices')
    def device_manager_page():
        return updates.page('device-manager.html')

    @app.get('/admin')
    def admin_console_page():
        return updates.page('admin-overview.html')

    @app.get('/admin/accounts')
    def admin_accounts_page():
        return updates.page('account-manager.html')

    @app.get('/database')
    def database_page():
        return updates.page('database-manager.html')

    return app
