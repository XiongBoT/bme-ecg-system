from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.deps import get_clock, get_current_auth, get_current_user, get_db, get_settings
from app.core.errors import AppError
from app.db.models import User, UserSession
from app.ecg.client import EcgClient, get_ecg_client
from app.ecg.service import unlink
from app.privacy.schemas import DeleteAccountRequest
from app.privacy.service import delete_user_account_atomic, export_user_data, validate_account_deletion

router = APIRouter(tags=["privacy"])


@router.get("/me/export")
def api_export_my_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    if request.query_params:
        raise AppError(422, "VALIDATION_ERROR", "导出接口不接受额外查询参数")
    return export_user_data(db, user, clock)


@router.post("/me/delete")
def api_delete_my_account(
    payload: DeleteAccountRequest,
    response: Response,
    auth: tuple[UserSession, User] = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    upstream: EcgClient = Depends(get_ecg_client),
) -> dict:
    _, user = auth
    uid = user.id
    validate_account_deletion(user, payload)
    result = unlink(db, uid, settings, clock, upstream)
    if result["revocation_pending"]:
        raise AppError(503, "ECG_REVOCATION_PENDING", "心电授权尚未确认撤销，请稍后重试注销或先在心电平台撤销关联")
    delete_user_account_atomic(db, user, payload, clock)
    response.delete_cookie(key=settings.session_cookie_name, path=settings.cookie_path)
    response.delete_cookie(key=settings.csrf_cookie_name, path=settings.cookie_path)
    return {"status": "deleted"}
