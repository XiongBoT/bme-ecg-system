"""Owner-scoped waveform interval notes, independent of raw data and model labels."""
from contextlib import closing
import json
import time
from typing import Annotated, Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class AnnotationInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    start_sample: int=Field(ge=0,le=2**53-1,strict=True)
    end_sample: int=Field(ge=0,le=2**53-1,strict=True)
    kind: Literal['note','suspected_interference','attention']
    note: str=Field(default='',max_length=500)
    revision: int=Field(ge=0,strict=True)
    deleted: StrictBool=False


def add_routes(app, connect, identity, find_session):
    with closing(connect()) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS annotations(
            id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),owner_id TEXT NOT NULL,
            start_sample INTEGER NOT NULL,end_sample INTEGER NOT NULL,kind TEXT NOT NULL,note TEXT NOT NULL,
            revision INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS annotations_record ON annotations(session_id,owner_id,deleted,start_sample,id);
        CREATE TABLE IF NOT EXISTS annotation_events(
            id INTEGER PRIMARY KEY,annotation_id TEXT NOT NULL,owner_id TEXT NOT NULL,revision INTEGER NOT NULL,
            details TEXT NOT NULL,created REAL NOT NULL);
        ''')

    def owner(db,sid):
        who=identity()
        if who.get('kind')!='user':raise HTTPException(403,'请使用本人账号登录')
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(who['id'],)).fetchone():
            raise HTTPException(403,'登录已失效')
        return who['id'],find_session(db,sid,active=True)

    def public(row):
        return {k:row[k] for k in ('id','session_id','start_sample','end_sample','kind','note','revision','created','updated')} | {'deleted':bool(row['deleted'])}

    @app.get('/api/sessions/{sid}/annotations')
    def listing(sid: str, include_deleted: bool=False,
                limit: Annotated[int,Query(ge=1,le=100)]=25,offset: Annotated[int,Query(ge=0)]=0):
        with closing(connect()) as db:
            db.execute('BEGIN');uid,_=owner(db,sid)
            where=' WHERE session_id=? AND owner_id=?'+('' if include_deleted else ' AND deleted=0')
            total=db.execute('SELECT COUNT(*) FROM annotations'+where,(sid,uid)).fetchone()[0]
            rows=db.execute('SELECT * FROM annotations'+where+' ORDER BY start_sample,id LIMIT ? OFFSET ?',(sid,uid,limit,offset)).fetchall()
            return {'annotations':[public(r) for r in rows],'total':total,'limit':limit,'offset':offset}

    @app.put('/api/sessions/{sid}/annotations/{aid}')
    def save(sid: str, aid: str, payload: AnnotationInput):
        if len(aid)!=32 or any(c not in '0123456789abcdef' for c in aid):raise HTTPException(422,'标注编号无效')
        with closing(connect()) as db,db:
            db.execute('BEGIN IMMEDIATE');uid,session=owner(db,sid)
            if not session['complete']:raise HTTPException(409,'请等记录上传完成后再标注')
            bounds=db.execute('SELECT MIN(first_id),MAX(last_id) FROM chunks WHERE session_id=?',(sid,)).fetchone()
            if (bounds[0] is None or payload.start_sample<bounds[0] or payload.end_sample>bounds[1]
                    or payload.start_sample>payload.end_sample or payload.end_sample-payload.start_sample>=60*360):
                raise HTTPException(422,'标注须在已保存的记录范围内，且不超过60秒')
            row=db.execute('SELECT * FROM annotations WHERE id=?',(aid,)).fetchone()
            if row and (row['session_id']!=sid or row['owner_id']!=uid):raise HTTPException(404,'标注不存在')
            if (row['revision'] if row else 0)!=payload.revision:raise HTTPException(409,'标注已被修改，请刷新后再操作')
            if not row and payload.deleted:raise HTTPException(409,'不能撤下尚未保存的标注')
            if not row and db.execute('SELECT COUNT(*) FROM annotations WHERE session_id=? AND owner_id=?',(sid,uid)).fetchone()[0]>=1000:
                raise HTTPException(409,'该记录已有1000条标注，请编辑已有标注')
            now=time.time();revision=payload.revision+1
            if row:
                db.execute('UPDATE annotations SET start_sample=?,end_sample=?,kind=?,note=?,revision=?,deleted=?,updated=? WHERE id=?',
                           (payload.start_sample,payload.end_sample,payload.kind,payload.note,revision,payload.deleted,now,aid))
            else:
                db.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (aid,sid,uid,payload.start_sample,payload.end_sample,payload.kind,payload.note,revision,False,now,now))
            result=public(db.execute('SELECT * FROM annotations WHERE id=?',(aid,)).fetchone())
            db.execute('INSERT INTO annotation_events(annotation_id,owner_id,revision,details,created) VALUES(?,?,?,?,?)',
                       (aid,uid,revision,json.dumps(result,ensure_ascii=False),now))
            return result
