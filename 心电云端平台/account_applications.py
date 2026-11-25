"""Public account requests; only an authenticated administrator can activate them."""
from contextlib import closing
import hashlib
import re
import time
import uuid

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from auth_store import password_hash


class ApplicationInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=3,max_length=32)
    password:str=Field(min_length=5,max_length=128)
    password_confirm:str=Field(min_length=5,max_length=128)
    note:str=Field(default='',max_length=200)


def add_routes(app,connect,require_admin,auth_enabled):
    with closing(connect()) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS account_applications(
            id TEXT PRIMARY KEY, username TEXT NOT NULL, password_hash TEXT,
            note TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, reviewed_at REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS pending_application_username ON account_applications(username) WHERE status='pending';
        CREATE TABLE IF NOT EXISTS application_limits(bucket TEXT PRIMARY KEY, started REAL NOT NULL, attempts INTEGER NOT NULL);
        ''')

    @app.post('/api/account-applications',status_code=202)
    def apply(payload:ApplicationInput,request:Request):
        if not auth_enabled:raise HTTPException(503,'当前服务未开启账号申请')
        username=payload.username.strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}',username):raise HTTPException(422,'账号须为3–32位字母、数字、横线或下划线')
        if payload.password!=payload.password_confirm:raise HTTPException(422,'两次密码不一致')
        now=time.time();bucket=hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest()
        # Commit throttling before hashing, including rejected duplicate requests.
        with closing(connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM application_limits WHERE started<?',(now-3600,))
            rate=db.execute('SELECT attempts FROM application_limits WHERE bucket=?',(bucket,)).fetchone()
            if rate and rate['attempts']>=5:raise HTTPException(429,'申请过于频繁，请一小时后再试')
            db.execute('INSERT INTO application_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1',(bucket,now))
        with closing(connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone() or db.execute("SELECT 1 FROM account_applications WHERE username=? AND status='pending'",(username,)).fetchone():
                raise HTTPException(409,'该账号已存在或正在审核，请使用其他账号；若已提交，请等待管理员审核')
            if db.execute("SELECT COUNT(*) FROM account_applications WHERE status='pending'").fetchone()[0]>=200:raise HTTPException(429,'待审核申请较多，请联系项目管理员')
            app_id=uuid.uuid4().hex
            db.execute('INSERT INTO account_applications VALUES(?,?,?,?,?,?,NULL)',
                       (app_id,username,password_hash(payload.password),payload.note.strip(),'pending',now))
            return dict(id=app_id,username=username,status='pending',message='申请已提交。管理员通过后，使用申请时的账号和密码登录。')

    @app.get('/api/admin/account-applications')
    def pending():
        require_admin()
        with closing(connect()) as db:
            rows=db.execute("SELECT id,username,note,created_at,status FROM account_applications WHERE status='pending' ORDER BY created_at LIMIT 200").fetchall()
            return {'applications':[dict(row) for row in rows]}

    def review(app_id,approve):
        require_admin()
        with closing(connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM account_applications WHERE id=?',(app_id,)).fetchone()
            if not row:raise HTTPException(404,'申请不存在')
            target='approved' if approve else 'rejected'
            if row['status']==target:return {'status':target}
            if row['status']!='pending':raise HTTPException(409,'该申请已经处理，请刷新列表')
            if approve:
                if db.execute('SELECT 1 FROM users WHERE username=?',(row['username'],)).fetchone():raise HTTPException(409,'该账号已被创建，请拒绝此申请并核对账号')
                uid=uuid.uuid4().hex
                db.execute('INSERT INTO users VALUES(?,?,?,0,1)',(uid,row['username'],row['password_hash']))
                db.execute('INSERT INTO user_activity(user_id,created_at) VALUES(?,?)',(uid,time.time()))
            # No retained password hashes for reviewed requests.
            db.execute('UPDATE account_applications SET status=?,reviewed_at=?,password_hash=NULL WHERE id=?',(target,time.time(),app_id))
            return {'status':target,'username':row['username']}

    @app.post('/api/admin/account-applications/{app_id}/approve')
    def approve(app_id:str):return review(app_id,True)

    @app.post('/api/admin/account-applications/{app_id}/reject')
    def reject(app_id:str):return review(app_id,False)
