from __future__ import annotations

from datetime import date, datetime, time
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import EcgLink, User
from app.ecg.client import EcgClient


# A lost response can still have committed upstream. Its code can no longer be
# redeemed after five minutes; retain the reservation until that window closes.
UNCERTAIN_EXCHANGE_SECONDS = 310


def _lock(db: Session) -> None:
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _active_user(db: Session, uid: str) -> User:
    user = db.scalar(select(User).where(User.id == uid).execution_options(populate_existing=True))
    if user is None or user.status != "active":
        raise AppError(401, "UNAUTHORIZED", "请先登录或重新登录")
    return user


def _row(db: Session, uid: str) -> EcgLink | None:
    return db.scalar(select(EcgLink).where(EcgLink.user_id == uid).execution_options(populate_existing=True))


def link_status(db: Session, uid: str, settings: Settings, clock: Clock) -> dict:
    row = _row(db, uid)
    active = bool(row and row.state == "active" and row.expires_at and row.expires_at > clock.now().timestamp())
    return {
        "enabled": settings.is_ecg_integration_enabled,
        "linked": active,
        "ecg_username": row.ecg_username if row else None,
        "expires_at": row.expires_at if row else None,
        "ecg_url": settings.ecg_external_url,
        "revocation_pending": bool(row and not active),
    }


def bind(db: Session, uid: str, code: str, settings: Settings, clock: Clock, upstream: EcgClient) -> dict:
    if not settings.is_ecg_integration_enabled:
        raise AppError(503, "ECG_DISABLED", "心电数据连接尚未启用")
    operation = uuid.uuid4().hex
    _lock(db)
    try:
        _active_user(db, uid)
        if _row(db, uid):
            raise AppError(409, "ECG_ALREADY_LINKED", "已有或正在确认心电关联，请先解除关联")
        db.add(EcgLink(user_id=uid, operation_id=operation, state="binding",
                       cleanup_after=clock.now().timestamp() + UNCERTAIN_EXCHANGE_SECONDS,
                       created_at=clock.now()))
        db.commit()
    except Exception:
        db.rollback()
        raise

    try:
        result = upstream.exchange(code, uid, operation)
    except AppError as exc:
        _lock(db)
        row = _row(db, uid)
        if row and row.operation_id == operation:
            if exc.code in ("ECG_CODE_INVALID", "ECG_ALREADY_LINKED", "ECG_RATE_LIMITED"):
                db.delete(row)  # Definitive rejection did not grant authorization.
            else:
                row.state = "revocation_pending"
        db.commit()
        raise

    _lock(db)
    try:
        _active_user(db, uid)
        row = _row(db, uid)
        if not row or row.operation_id != operation or row.state != "binding":
            raise AppError(409, "ECG_LINK_CHANGED", "关联状态已改变，请重新查看")
        if result.expires_at <= clock.now().timestamp():
            raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的授权已过期")
        row.ecg_user_id = result.ecg_user_id
        row.ecg_username = result.ecg_username
        row.grant_token = result.grant_token
        row.expires_at = result.expires_at
        row.state = "active"
        row.cleanup_after = 0
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            revoked = upstream.revoke_token(uid, result.grant_token)
        except AppError:
            revoked = False
        _lock(db)
        row = _row(db, uid)
        if row and row.operation_id == operation:
            if revoked:
                db.delete(row)
            else:
                row.state = "revocation_pending"
                row.grant_token = result.grant_token
                row.cleanup_after = 0
        db.commit()
        if isinstance(exc, IntegrityError):
            raise AppError(409, "ECG_ALREADY_LINKED", "该心电账号已关联其他心伴账号") from exc
        raise
    return link_status(db, uid, settings, clock)


def unlink(db: Session, uid: str, settings: Settings, clock: Clock, upstream: EcgClient) -> dict:
    _lock(db)
    try:
        row = _row(db, uid)
        if row is None:
            db.commit()
            return {"linked": False, "revocation_pending": False}
        operation = row.operation_id
        token = row.grant_token
        # Hide data before any external I/O. Keep the reservation on failures.
        row.state = "revocation_pending"
        wait_for_exchange = row.cleanup_after > clock.now().timestamp()
        db.commit()
    except Exception:
        db.rollback()
        raise
    if wait_for_exchange:
        return {"linked": False, "revocation_pending": True}
    try:
        revoked = upstream.revoke_token(uid, token) if token else upstream.revoke_subject(uid, operation)
    except AppError:
        revoked = False
    if revoked:
        _lock(db)
        row = _row(db, uid)
        if row and row.operation_id == operation and row.state == "revocation_pending":
            db.delete(row)
        db.commit()
    return {"linked": False, "revocation_pending": not revoked}


def summary(db: Session, uid: str, period: str, anchor: date,
            settings: Settings, clock: Clock, upstream: EcgClient) -> dict:
    user = _active_user(db, uid)
    row = _row(db, uid)
    if not row or row.state != "active" or not row.grant_token:
        raise AppError(409, "ECG_NOT_LINKED", "请先完成心电账号关联")
    if not row.expires_at or row.expires_at <= clock.now().timestamp():
        raise AppError(409, "ECG_LINK_EXPIRED", "心电授权已过期，请解除关联后重新绑定")
    token, operation, expected_owner = row.grant_token, row.operation_id, row.ecg_user_id
    local_anchor = datetime.combine(anchor, time(12), tzinfo=ZoneInfo(user.timezone))
    offset = int(local_anchor.utcoffset().total_seconds() // 60)
    params = {"period": period, "anchor": anchor.isoformat(), "utc_offset_minutes": offset}
    db.rollback()  # No database transaction remains open during network I/O.
    try:
        data = upstream.summary(uid, token, params)
    except AppError as exc:
        if exc.code == "ECG_LINK_EXPIRED":
            _lock(db)
            current = _row(db, uid)
            if current and current.operation_id == operation:
                current.state = "revocation_pending"
            db.commit()
        raise
    if (data.ecg_user.id != expected_owner or data.trends.period != period
            or data.trends.anchor != anchor.isoformat() or data.trends.utc_offset_minutes != offset):
        raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的账号或统计范围不匹配")
    _active_user(db, uid)
    current = _row(db, uid)
    if not current or current.operation_id != operation or current.state != "active":
        raise AppError(409, "ECG_LINK_CHANGED", "心电关联已改变，请刷新页面")
    if not current.expires_at or min(current.expires_at, data.expires_at) <= clock.now().timestamp():
        raise AppError(409, "ECG_LINK_EXPIRED", "心电授权已过期，请解除关联后重新绑定")
    result = data.model_dump()
    public = urlsplit(settings.ecg_external_url or "")
    for record in result["recent_records"]:
        record["report_url"] = urlunsplit((public.scheme, public.netloc, "/", urlencode({"record": record["session_id"]}), ""))
    return result
