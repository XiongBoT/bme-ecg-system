"""Admin provisioning endpoints. Credentials are returned only at issuance."""
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field
from device_store import DEVICE_ID

UserId=Annotated[str,Field(pattern=r'^[a-f0-9]{32}$')]


class DeviceCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id:str=Field(pattern='^'+DEVICE_ID+'$')
    name:str=Field(default='',max_length=100)
    user_ids:list[UserId]=Field(default_factory=list,max_length=500)


class DeviceUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str|None=Field(default=None,max_length=100)
    active:bool|None=Field(default=None,strict=True)
    user_ids:list[UserId]|None=Field(default=None,max_length=500)
    expected_user_ids:list[UserId]|None=Field(default=None,max_length=500)
    expected_legacy_shared:bool|None=Field(default=None,strict=True)


def add_routes(app,store,require_admin):
    @app.get('/api/admin/devices')
    def list_devices():
        require_admin();return {'devices':store.list(admin=True)}

    @app.post('/api/admin/devices')
    def create_device(payload:DeviceCreate):
        require_admin();return store.create(payload.device_id,payload.name,payload.user_ids)

    @app.patch('/api/admin/devices/{device_id}')
    def update_device(device_id:str,payload:DeviceUpdate):
        require_admin();return store.update(device_id,**payload.model_dump(exclude_none=True))

    @app.post('/api/admin/devices/{device_id}/credentials')
    def rotate_credentials(device_id:str):
        require_admin();return store.rotate(device_id)
