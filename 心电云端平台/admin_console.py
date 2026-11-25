"""Bounded administrator metadata; no signal values, model output or credentials."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import shutil
import time
from typing import Annotated, Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictBool

from database_management import audit, connect, require_actor

HEARTBEAT_SECONDS = 35
LOCAL_TIME = timezone(timedelta(hours=8))


class GrantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    granted: StrictBool


class AdminConsole:
    def __init__(self, data):
        self.data = data

    @staticmethod
    def account_sql():
        return '''SELECT u.id,u.username,u.is_admin,u.active,a.created_at,a.last_login_at,
            (SELECT COUNT(*) FROM browser_sessions b WHERE b.user_id=u.id AND b.expires>? AND u.active=1) active_sessions,
            (SELECT COUNT(*) FROM sessions s LEFT JOIN session_details sd ON sd.session_id=s.id
             WHERE s.owner_id=u.id AND sd.trashed_at IS NULL) record_count,
            (SELECT COUNT(*) FROM devices d WHERE d.legacy_shared=1 OR EXISTS
             (SELECT 1 FROM device_users g WHERE g.device_id=d.id AND g.user_id=u.id)) device_count
            FROM users u LEFT JOIN user_activity a ON a.user_id=u.id'''

    def accounts(self, *, q='', status='all', role='all', limit=20, offset=0, uid=None):
        clauses, params = ['1=1'], []
        if q.strip(): clauses.append('instr(lower(u.username),lower(?))>0'); params.append(q.strip())
        if status != 'all': clauses.append('u.active=?'); params.append(int(status == 'active'))
        if role != 'all': clauses.append('u.is_admin=?'); params.append(int(role == 'admin'))
        if uid is not None: clauses.append('u.id=?'); params.append(uid)
        where = ' WHERE ' + ' AND '.join(clauses)
        with closing(connect(self.data)) as db:
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*) FROM users u' + where, params).fetchone()[0]
            rows = db.execute(self.account_sql() + where + ' ORDER BY u.username,u.id LIMIT ? OFFSET ?',
                              (time.time(), *params, limit, offset)).fetchall()
            accounts = [{**dict(row), 'active': bool(row['active']), 'is_admin': bool(row['is_admin'])} for row in rows]
        if uid is not None:
            if not accounts: raise HTTPException(404, '账号不存在')
            return {'account': accounts[0]}
        return {'accounts': accounts, 'total': total, 'limit': limit, 'offset': offset}

    @staticmethod
    def device_cte():
        return '''WITH device_status AS (
            SELECT d.id device_id,d.name,d.active,d.legacy_shared,d.created_at,h.seen last_seen,
                CASE WHEN d.active=0 THEN 'disabled' WHEN h.seen IS NULL THEN 'unknown'
                     WHEN h.seen>=? THEN 'online' ELSE 'offline' END connection,
                CASE WHEN d.active=1 AND h.seen>=? AND json_valid(h.payload)
                     THEN COALESCE(json_extract(h.payload,'$.state'),'unknown') ELSE 'unknown' END state,
                (SELECT COUNT(*) FROM device_users g WHERE g.device_id=d.id) explicit_grants,
                (SELECT COUNT(*) FROM sessions s LEFT JOIN session_details sd ON sd.session_id=s.id
                 WHERE s.ingest_device_id=d.id AND sd.trashed_at IS NULL) record_count,
                (SELECT MAX(COALESCE(s.received_at,s.created_at)) FROM sessions s
                 LEFT JOIN session_details sd ON sd.session_id=s.id
                 WHERE s.ingest_device_id=d.id AND sd.trashed_at IS NULL) last_upload_at
            FROM devices d LEFT JOIN device_heartbeats h ON h.device_id=d.id) '''

    def devices(self, *, q='', connection='all', account_id=None, grant='all', limit=20, offset=0, did=None):
        stamp = time.time()
        clauses, params = ['1=1'], []
        if q.strip(): clauses.append("instr(lower(d.name||' '||d.device_id),lower(?))>0"); params.append(q.strip())
        if connection != 'all': clauses.append('d.connection=?'); params.append(connection)
        if did is not None: clauses.append('d.device_id=?'); params.append(did)
        grant_sql = "(d.legacy_shared=1 OR EXISTS(SELECT 1 FROM device_users g WHERE g.device_id=d.device_id AND g.user_id=?))"
        if grant != 'all':
            if not account_id: raise HTTPException(422, '授权筛选需要指定账号')
            clauses.append(grant_sql + ('=1' if grant == 'granted' else '=0')); params.append(account_id)
        where = ' WHERE ' + ' AND '.join(clauses)
        cte_params = (stamp - HEARTBEAT_SECONDS, stamp - HEARTBEAT_SECONDS)
        with closing(connect(self.data)) as db:
            db.execute('BEGIN')
            account = None
            if account_id:
                account = db.execute('SELECT id,username,active FROM users WHERE id=?', (account_id,)).fetchone()
                if account is None: raise HTTPException(404, '账号不存在')
            total = db.execute(self.device_cte() + 'SELECT COUNT(*) FROM device_status d' + where, (*cte_params, *params)).fetchone()[0]
            rows = db.execute(self.device_cte() + 'SELECT d.*,' + grant_sql + ' granted FROM device_status d' + where +
                ' ORDER BY d.name,d.device_id LIMIT ? OFFSET ?', (*cte_params, account_id, *params, limit, offset)).fetchall()
            items = [{**dict(row), 'active': bool(row['active']), 'legacy_shared': bool(row['legacy_shared']),
                      'granted': bool(row['granted']) if account_id else None} for row in rows]
            if did is not None:
                if not items: raise HTTPException(404, '设备不存在')
                item = items[0]
                item['user_ids'] = [r[0] for r in db.execute('SELECT user_id FROM device_users WHERE device_id=? ORDER BY user_id', (did,))]
                records = db.execute('''SELECT s.id session_id,COALESCE(sd.name,'') name,s.complete,s.created_at,s.received_at
                    FROM sessions s LEFT JOIN session_details sd ON sd.session_id=s.id
                    WHERE s.ingest_device_id=? AND sd.trashed_at IS NULL
                    ORDER BY s.created_at DESC,s.id DESC LIMIT 5''', (did,)).fetchall()
                return {'device': item, 'recent_records': [dict(r) for r in records], 'measured_at': stamp}
        return {'devices': items, 'account': dict(account) if account else None, 'total': total,
                'limit': limit, 'offset': offset, 'measured_at': stamp}

    def overview(self):
        stamp = time.time()
        local = datetime.fromtimestamp(stamp, LOCAL_TIME)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        bounds = [v.astimezone(timezone.utc).isoformat() for v in (start, start + timedelta(days=1))]
        active = ' FROM sessions s LEFT JOIN session_details sd ON sd.session_id=s.id WHERE sd.trashed_at IS NULL'
        latest_jobs = ''' FROM (SELECT session_id,kind,status,updated,job_id,
                ROW_NUMBER() OVER(PARTITION BY session_id,kind ORDER BY created DESC,job_id DESC) position
                FROM analysis_jobs) j JOIN sessions s ON s.id=j.session_id
            LEFT JOIN session_details sd ON sd.session_id=s.id WHERE j.position=1 AND sd.trashed_at IS NULL'''
        with closing(connect(self.data)) as db:
            db.execute('BEGIN')
            devices = dict(db.execute(self.device_cte() + 'SELECT connection,COUNT(*) FROM device_status GROUP BY connection',
                           (stamp - HEARTBEAT_SECONDS, stamp - HEARTBEAT_SECONDS)).fetchall())
            accounts = {'total': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                        'active': db.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]}
            records = {'active': db.execute('SELECT COUNT(*)' + active).fetchone()[0],
                       'unassigned': db.execute('SELECT COUNT(*)' + active + ' AND s.owner_id IS NULL').fetchone()[0],
                       'uploading': db.execute('SELECT COUNT(*)' + active + ' AND s.complete=0').fetchone()[0],
                       'today_registered': db.execute('SELECT COUNT(*)' + active +
                           ' AND julianday(s.created_at)>=julianday(?) AND julianday(s.created_at)<julianday(?)', bounds).fetchone()[0]}
            analysis = dict(db.execute('SELECT j.status,COUNT(*)' + latest_jobs + ' GROUP BY j.status').fetchall())
            problems = db.execute('SELECT j.session_id,j.kind,j.status,j.updated' + latest_jobs +
                                 " AND j.status='failed' ORDER BY j.updated DESC,j.job_id DESC LIMIT 8").fetchall()
            backup = db.execute("SELECT job_id,updated FROM management_jobs WHERE kind='backup' AND status='complete' ORDER BY updated DESC,job_id DESC LIMIT 1").fetchone()
            maintenance = dict(db.execute('SELECT status,COUNT(*) FROM management_jobs GROUP BY status').fetchall())
        try:
            usage = shutil.disk_usage(self.data)
            disk = {'free_bytes': usage.free, 'total_bytes': usage.total}
        except OSError:
            disk = {'free_bytes': None, 'total_bytes': None}
        return {'measured_at': stamp, 'day': {'date': start.date().isoformat(), 'timezone': 'Asia/Shanghai'},
                'devices': devices, 'accounts': accounts, 'records': records, 'analysis': analysis,
                'analysis_problems': [dict(r) for r in problems], 'maintenance': maintenance, 'disk': disk,
                'latest_backup': dict(backup) if backup else None}

    def set_grant(self, actor, uid, did, granted):
        with closing(connect(self.data)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            require_actor(db, actor)
            user = db.execute('SELECT active FROM users WHERE id=?', (uid,)).fetchone()
            device = db.execute('SELECT active,legacy_shared FROM devices WHERE id=?', (did,)).fetchone()
            if user is None or device is None: raise HTTPException(404, '账号或设备不存在')
            if device['legacy_shared']: raise HTTPException(409, '旧版共享设备需要在设备配置中明确转换授权名单')
            if granted and (not user['active'] or not device['active']): raise HTTPException(409, '请先恢复账号及设备，再添加授权')
            existing = bool(db.execute('SELECT 1 FROM device_users WHERE device_id=? AND user_id=?', (did, uid)).fetchone())
            if granted: db.execute('INSERT OR IGNORE INTO device_users VALUES(?,?)', (did, uid))
            else: db.execute('DELETE FROM device_users WHERE device_id=? AND user_id=?', (did, uid))
            if existing != granted: audit(db, actor, 'grant' if granted else 'revoke_grant', did, detail='账号 ' + uid)
        return {'device_id': did, 'user_id': uid, 'granted': granted}


def add_routes(app, data, require_admin, current_user):
    store = AdminConsole(data)
    prefix = '/api/admin/console'

    @app.get(prefix + '/overview')
    def overview():
        require_admin(); return store.overview()

    @app.get(prefix + '/devices')
    def devices(q: Annotated[str, Query(max_length=100)] = '',
                connection: Literal['all', 'online', 'offline', 'unknown', 'disabled'] = 'all',
                account_id: Annotated[str | None, Query(max_length=96)] = None,
                grant: Literal['all', 'granted', 'ungranted'] = 'all',
                limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0, le=1000000)] = 0):
        require_admin(); return store.devices(q=q, connection=connection, account_id=account_id, grant=grant, limit=limit, offset=offset)

    @app.get(prefix + '/devices/{did}')
    def device(did: str):
        require_admin(); return store.devices(did=did)

    @app.get(prefix + '/accounts')
    def accounts(q: Annotated[str, Query(max_length=32)] = '', status: Literal['all', 'active', 'disabled'] = 'all',
                 role: Literal['all', 'user', 'admin'] = 'all', limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 offset: Annotated[int, Query(ge=0, le=1000000)] = 0):
        require_admin(); return store.accounts(q=q, status=status, role=role, limit=limit, offset=offset)

    @app.get(prefix + '/accounts/{uid}')
    def account(uid: str):
        require_admin(); return store.accounts(uid=uid)

    @app.put(prefix + '/accounts/{uid}/devices/{did}')
    def grant(uid: str, did: str, payload: GrantInput):
        require_admin(); return store.set_grant(current_user()['id'], uid, did, payload.granted)
