"""Administrator-only metadata and maintenance. No backup content route."""
from typing import Annotated, Literal
from datetime import date
from fastapi import Query, HTTPException
from pydantic import BaseModel, ConfigDict, AwareDatetime


class MaintenanceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['scan', 'check', 'backup']


def add_routes(app, store, queue, require_admin, current_user):
    @app.get('/api/admin/database')
    def overview():
        require_admin(); return store.overview()

    @app.get('/api/admin/database/records')
    def records(limit: Annotated[int, Query(ge=1, le=100)] = 25,
                offset: Annotated[int, Query(ge=0)] = 0,
                q: Annotated[str, Query(max_length=100)] = '',
                state: Literal['active', 'complete', 'uploading', 'trashed'] = 'active',
                owner_id: Annotated[str | None, Query(max_length=96)] = None,
                device_id: Annotated[str | None, Query(max_length=96)] = None,
                started_from: AwareDatetime | None = None, started_before: AwareDatetime | None = None,
                registered_day: date | None = None):
        require_admin()
        if started_from and started_before and started_from >= started_before:
            raise HTTPException(422, '开始日期必须早于结束日期')
        return store.records(limit=limit, offset=offset, q=q, state=state, owner_id=owner_id,
            device_id=device_id, started_from=started_from, started_before=started_before, registered_day=registered_day)

    @app.post('/api/admin/database/records/{sid}/trash')
    def trash(sid: str):
        require_admin(); return store.change_trash(current_user()['id'], sid, True)

    @app.post('/api/admin/database/records/{sid}/restore')
    def restore(sid: str):
        require_admin(); return store.change_trash(current_user()['id'], sid, False)

    @app.get('/api/admin/database/jobs')
    def jobs():
        require_admin()
        if queue.has_pending(): queue.start()
        return {'jobs': store.jobs()}

    @app.post('/api/admin/database/jobs', status_code=202)
    def enqueue(payload: MaintenanceInput):
        require_admin()
        queue.start()
        result = store.enqueue(current_user()['id'], payload.kind)
        return result

    @app.get('/api/admin/database/backups')
    def backups():
        require_admin(); return {'backups': store.backups()}

    @app.get('/api/admin/database/activity')
    def activity(limit: Annotated[int, Query(ge=1, le=100)] = 50,
                 offset: Annotated[int, Query(ge=0)] = 0):
        require_admin(); return {'events': store.activity(limit, offset)}
