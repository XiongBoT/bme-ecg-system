"""Local account/session store. Passwords and bearer secrets are never stored raw."""
from contextlib import closing
import hashlib
import hmac
import re
import secrets
import time
import uuid

from fastapi import HTTPException

from heartlife_bridge import revoke_owner as revoke_heartlife_owner

COOKIE = 'ecg_session'
SESSION_SECONDS = 8 * 3600


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + hashed


class AuthStore:
    def __init__(self, connect):
        self.connect = connect
        with closing(connect()) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS browser_sessions(token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS device_keys(token_hash TEXT PRIMARY KEY, device_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts(bucket TEXT PRIMARY KEY, started REAL NOT NULL, failures INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS user_activity(user_id TEXT PRIMARY KEY REFERENCES users(id),
                created_at REAL, last_login_at REAL);
            CREATE INDEX IF NOT EXISTS browser_sessions_user_expiry ON browser_sessions(user_id, expires);
            ''')
        self.dummy_hash = password_hash('not-an-account-password')

    @staticmethod
    def public(row):
        return dict(id=row['id'], username=row['username'], is_admin=bool(row['is_admin']), active=bool(row['active']))

    def users(self):
        with closing(self.connect()) as db:
            return [self.public(row) for row in db.execute('SELECT * FROM users ORDER BY username')]

    def admin_users(self):
        """Administrative metadata only; never used for device recipient lists."""
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT u.*, a.created_at, a.last_login_at,
                (SELECT COUNT(*) FROM browser_sessions s
                 WHERE s.user_id=u.id AND s.expires>? AND u.active=1) AS active_sessions
                FROM users u LEFT JOIN user_activity a ON a.user_id=u.id ORDER BY u.username''', (time.time(),))
            return [dict(self.public(row), created_at=row['created_at'], last_login_at=row['last_login_at'],
                         active_sessions=row['active_sessions']) for row in rows]

    def create_user(self, username, password, admin=False):
        username = username.strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', username):
            raise ValueError('账号使用 3–32 位字母、数字、横线或下划线')
        if not 5 <= len(password) <= 128:
            raise ValueError('密码须为 5–128 个字符')
        encoded = password_hash(password)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise ValueError('账号已存在')
            uid = uuid.uuid4().hex
            db.execute('INSERT INTO users VALUES(?,?,?,?,1)', (uid, username, encoded, int(admin)))
            db.execute('INSERT INTO user_activity(user_id,created_at) VALUES(?,?)', (uid, time.time()))
            return self.public(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

    def create_device_key(self, device_id):
        token = secrets.token_urlsafe(32)
        with closing(self.connect()) as db, db:
            if not db.execute('SELECT 1 FROM devices WHERE id=?',(device_id,)).fetchone():
                raise ValueError('请先在设备管理中创建该设备')
            db.execute('DELETE FROM device_keys WHERE device_id=?', (device_id,))
            db.execute('INSERT INTO device_keys VALUES(?,?)', (digest(token), device_id))
        return token

    def change_password(self, uid, current_password, new_password):
        if not 5 <= len(new_password) <= 128:
            raise HTTPException(422, '密码须为 5–128 个字符')
        encoded = password_hash(new_password)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone()
            if not row:
                raise HTTPException(401, '账号已失效，请重新登录')
            bucket, now = 'password:' + uid, time.time()
            attempts = db.execute('SELECT * FROM login_attempts WHERE bucket=?', (bucket,)).fetchone()
            if attempts and now-attempts['started'] < 300 and attempts['failures'] >= 5:
                raise HTTPException(429, '旧密码尝试次数较多，请五分钟后再试')
            expected = row['password_hash']
            if not hmac.compare_digest(password_hash(current_password, expected.split(':')[0]), expected):
                if not attempts or now-attempts['started'] >= 300:
                    db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,1)', (bucket, now))
                else:
                    db.execute('UPDATE login_attempts SET failures=failures+1 WHERE bucket=?', (bucket,))
                db.commit()
                raise HTTPException(403, '旧密码不正确')
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, uid))
            db.execute('DELETE FROM browser_sessions WHERE user_id=?', (uid,))
            db.execute('DELETE FROM login_attempts WHERE bucket=?', (bucket,))
            revoke_heartlife_owner(db, uid)

    @staticmethod
    def managed_user(db, uid):
        row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not row:
            raise HTTPException(404, '账号不存在')
        if row['is_admin']:
            raise HTTPException(409, '此处仅管理普通账号；管理员请使用本人修改密码')
        return row

    def revoke_user_sessions(self, uid):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.managed_user(db, uid)
            count = db.execute('SELECT COUNT(*) FROM browser_sessions WHERE user_id=? AND expires>?',
                               (uid, time.time())).fetchone()[0]
            db.execute('DELETE FROM browser_sessions WHERE user_id=?', (uid,))
            revoke_heartlife_owner(db, uid)
            return {'revoked_sessions': count}

    def manage_user(self, uid, *, active=None, new_password=None):
        if new_password is not None and not 5 <= len(new_password) <= 128:
            raise HTTPException(422, '密码须为 5–128 个字符')
        encoded = password_hash(new_password) if new_password is not None else None
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.managed_user(db, uid)
            if active is not None:
                db.execute('UPDATE users SET active=? WHERE id=?', (int(active), uid))
            if encoded is not None:
                db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, uid))
            if encoded is not None or active is False:
                db.execute('DELETE FROM browser_sessions WHERE user_id=?', (uid,))
                revoke_heartlife_owner(db, uid)
            return self.public(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

    def login(self, username, password, client):
        username = username.strip().lower()
        buckets = ['ip:' + client, 'user:' + username]
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for bucket in buckets:
                row = db.execute('SELECT * FROM login_attempts WHERE bucket=?', (bucket,)).fetchone()
                if row and now-row['started'] < 300 and row['failures'] >= (20 if bucket.startswith('ip:') else 5):
                    raise HTTPException(429, '尝试次数较多，请五分钟后再试')
                if not row or now-row['started'] >= 300:
                    db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,1)', (bucket, now))
                else:
                    db.execute('UPDATE login_attempts SET failures=failures+1 WHERE bucket=?', (bucket,))
            row = db.execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
        expected = row['password_hash'] if row else self.dummy_hash
        valid = hmac.compare_digest(password_hash(password, expected.split(':')[0]), expected)
        if not row or not valid:
            raise HTTPException(401, '账号或密码不正确')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT * FROM users WHERE id=? AND active=1', (row['id'],)).fetchone()
            if not latest or latest['password_hash'] != expected:
                raise HTTPException(401, '账号状态已改变，请重新登录')
            db.execute('DELETE FROM login_attempts WHERE bucket=?', ('user:' + username,))
            db.execute('DELETE FROM browser_sessions WHERE expires<?', (now,))
            db.execute('INSERT INTO browser_sessions VALUES(?,?,?,?)', (digest(token), row['id'], csrf, now+SESSION_SECONDS))
            db.execute('''INSERT INTO user_activity(user_id,last_login_at) VALUES(?,?)
                ON CONFLICT(user_id) DO UPDATE SET last_login_at=excluded.last_login_at''', (row['id'], time.time()))
        return token, dict(user=self.public(row), csrf_token=csrf)

    def authenticate(self, request):
        key = request.headers.get('x-api-key')
        cookie = request.cookies.get(COOKIE)
        with closing(self.connect()) as db:
            if key:
                row = db.execute('SELECT k.device_id FROM device_keys k JOIN devices d ON d.id=k.device_id '
                                 'WHERE k.token_hash=? AND d.active=1', (digest(key),)).fetchone()
                if row: return dict(kind='device', device_id=row['device_id'], token_hash=digest(key))
            if cookie:
                row = db.execute('SELECT u.*,s.csrf FROM browser_sessions s JOIN users u ON u.id=s.user_id '
                                 'WHERE s.token_hash=? AND s.expires>? AND u.active=1', (digest(cookie), time.time())).fetchone()
                if row: return dict(kind='user', **self.public(row), csrf_token=row['csrf'])
        return None

    def logout(self, request):
        with closing(self.connect()) as db, db:
            db.execute('DELETE FROM browser_sessions WHERE token_hash=?', (digest(request.cookies.get(COOKIE, '')),))

    def require_user(self, uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone()
        if not row: raise HTTPException(422, '所属账号不存在或已停用')
        return self.public(row)
