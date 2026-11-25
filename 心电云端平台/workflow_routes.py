"""Browser-account-only task center, review and operations endpoints."""
from contextlib import closing
from typing import Annotated, Literal
from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    auto_model: StrictBool = False
    auto_physiology: StrictBool = False


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['pending','viewed','suspected_interference']
    note: str = Field(default='', max_length=1000)
    revision: int = Field(ge=0)
    context: str = Field(pattern=r'^[a-f0-9]{64}$')


def add_routes(app, store, identity, find_session, require_admin):
    def user():
        who = identity()
        if who.get('kind') != 'user': raise HTTPException(403, '请使用本人账号登录')
        return who['id']

    @app.get('/api/workflow/preferences')
    def preferences(): return store.preferences(user())

    @app.put('/api/workflow/preferences')
    def save_preferences(payload: Preferences): return store.preferences(user(), payload.model_dump())

    @app.get('/api/workflow/tasks')
    def tasks(limit: Annotated[int, Query(ge=1, le=100)] = 25, offset: Annotated[int, Query(ge=0)] = 0,
              stage: Literal['all','uploading','processing','attention','results','ready'] = 'all'):
        return store.tasks(user(), limit, offset, stage)

    @app.get('/api/sessions/{sid}/review')
    def review(sid: str):
        uid = user()
        with closing(store.connect()) as db:
            db.execute('BEGIN'); find_session(db, sid, active=True)
            return store.review(db, sid, uid)

    @app.put('/api/sessions/{sid}/review')
    def save_review(sid: str, payload: Review):
        uid = user()
        with closing(store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE'); find_session(db, sid, active=True)
            return store.review(db, sid, uid, payload.model_dump())

    @app.get('/api/admin/operations')
    def operations():
        require_admin(); return store.operations()
