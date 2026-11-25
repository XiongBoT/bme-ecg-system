"""Device identities and explicit user grants; never trust a posted device id."""
from contextlib import closing
import hashlib
import json
import re
import secrets
import time

from fastapi import HTTPException

DEVICE_ID = r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}'


class DeviceStore:
    def __init__(self, connect, legacy_device):
        self.connect = connect
        self.legacy_device = legacy_device
        with closing(connect()) as db, db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS devices(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                legacy_shared INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS device_users(
                device_id TEXT NOT NULL REFERENCES devices(id), user_id TEXT NOT NULL REFERENCES users(id),
                PRIMARY KEY(device_id,user_id));
            CREATE TABLE IF NOT EXISTS device_heartbeats(
                device_id TEXT PRIMARY KEY REFERENCES devices(id), seen REAL NOT NULL, payload TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,1,1,?)', (legacy_device,legacy_device,time.time()))
            db.execute('INSERT OR IGNORE INTO devices SELECT DISTINCT device_id,device_id,1,0,? FROM device_keys', (time.time(),))
            db.execute('INSERT OR IGNORE INTO device_heartbeats SELECT ?,seen,payload FROM device_heartbeat WHERE id=1', (legacy_device,))

    @staticmethod
    def _get(db, did):
        row = db.execute('SELECT * FROM devices WHERE id=?', (did,)).fetchone()
        if not row: raise HTTPException(404, '设备不存在')
        return row

    @staticmethod
    def _users(db, users):
        unique = sorted(set(users))
        for uid in unique:
            if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (uid,)).fetchone():
                raise HTTPException(422, '授权账号不存在或已停用')
        return unique

    @staticmethod
    def _public(db, row, admin=False):
        result = dict(device_id=row['id'], name=row['name'], active=bool(row['active']),
                      legacy_shared=bool(row['legacy_shared']))
        if admin:
            result['user_ids']=[r[0] for r in db.execute('SELECT user_id FROM device_users WHERE device_id=? ORDER BY user_id',(row['id'],))]
            beat=db.execute('SELECT seen,payload FROM device_heartbeats WHERE device_id=?',(row['id'],)).fetchone()
            payload=json.loads(beat['payload']) if beat else {}
            result.update(created_at=row['created_at'], last_seen=beat['seen'] if beat else None,
                          connection=('disabled' if not row['active'] else 'unknown' if not beat else 'online' if time.time()-beat['seen']<=35 else 'offline'),
                          device_info=payload.get('device_info'), free_bytes=payload.get('free_bytes'),
                          remote_ready=bool(payload.get('remote_ready')) and bool(beat) and time.time()-beat['seen']<=35)
            result['record_count']=db.execute('SELECT COUNT(*) FROM sessions WHERE ingest_device_id=?',(row['id'],)).fetchone()[0]
        return result

    def list(self, principal=None, admin=False):
        with closing(self.connect()) as db:
            rows=db.execute('SELECT * FROM devices ORDER BY name,id').fetchall()
            if principal and principal.get('kind')=='user' and not principal.get('is_admin'):
                rows=[r for r in rows if r['legacy_shared'] or db.execute(
                    'SELECT 1 FROM device_users WHERE device_id=? AND user_id=?',(r['id'],principal['id'])).fetchone()]
            return [self._public(db,r,admin) for r in rows]

    def require(self, did):
        with closing(self.connect()) as db:
            row=self._get(db,did)
            if not row['active']:raise HTTPException(403,'设备已停用')
            return self._public(db,row)

    def recipients(self, did):
        with closing(self.connect()) as db:
            row=self._get(db,did)
            if not row['active']:raise HTTPException(403,'设备已停用')
            sql='SELECT id,username FROM users WHERE active=1'
            params=()
            if not row['legacy_shared']:
                sql+=' AND id IN (SELECT user_id FROM device_users WHERE device_id=?)';params=(did,)
            return [dict(r) for r in db.execute(sql+' ORDER BY username',params)]

    def require_recipient(self,did,uid,db=None):
        if uid is None:return
        if db is None:
            with closing(self.connect()) as connection:return self.require_recipient(did,uid,connection)
        row=self._get(db,did)
        user=db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(uid,)).fetchone()
        grant=row['legacy_shared'] or db.execute('SELECT 1 FROM device_users WHERE device_id=? AND user_id=?',(did,uid)).fetchone()
        if not row['active'] or not user or not grant:
            raise HTTPException(403,'该设备未获准为此账号创建记录，请管理员检查设备授权')

    @staticmethod
    def _key(db,did):
        token=secrets.token_urlsafe(32)
        db.execute('DELETE FROM device_keys WHERE device_id=?',(did,))
        db.execute('INSERT INTO device_keys VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),did))
        return dict(device_id=did,token=token)

    def create(self,did,name,user_ids):
        if not re.fullmatch(DEVICE_ID,did):raise HTTPException(422,'设备编号仅允许字母、数字、横线和下划线')
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            users=self._users(db,user_ids)
            if db.execute('SELECT 1 FROM devices WHERE id=?',(did,)).fetchone():raise HTTPException(409,'设备编号已存在')
            db.execute('INSERT INTO devices VALUES(?,?,1,0,?)',(did,name.strip() or did,time.time()))
            db.executemany('INSERT INTO device_users VALUES(?,?)',[(did,u) for u in users])
            return dict(device=self._public(db,self._get(db,did),True),credentials=self._key(db,did))

    def update(self,did,*,name=None,active=None,user_ids=None):
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE');self._get(db,did)
            if user_ids is not None:
                users=self._users(db,user_ids)
                db.execute('DELETE FROM device_users WHERE device_id=?',(did,))
                db.executemany('INSERT INTO device_users VALUES(?,?)',[(did,u) for u in users])
                db.execute('UPDATE devices SET legacy_shared=0 WHERE id=?',(did,))
            if name is not None:db.execute('UPDATE devices SET name=? WHERE id=?',(name.strip() or did,did))
            if active is not None:db.execute('UPDATE devices SET active=? WHERE id=?',(int(active),did))
            return self._public(db,self._get(db,did),True)

    def rotate(self,did):
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE');row=self._get(db,did)
            if not row['active']:raise HTTPException(409,'请先恢复设备，再更新凭据')
            return dict(device=self._public(db,row,True),credentials=self._key(db,did))
