from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock, user_local_date
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import EcgLink, User
from app.ecg.client import EcgClient
from app.ecg.schemas import MeasurementRequest


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
        "measurement_allowed": bool(active and row.measurement_allowed),
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
        row.measurement_allowed = result.measurement_allowed
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


def _linked_request(db: Session, uid: str, clock: Clock, call, *, control: bool = False):
    """Perform bounded upstream I/O without holding a local transaction open.

    Both the local operation and upstream owner are checked again before any
    result is returned. ECG remains the authority for grant/device permissions.
    """
    _active_user(db, uid)
    row = _row(db, uid)
    if not row or row.state != "active" or not row.grant_token:
        raise AppError(409, "ECG_NOT_LINKED", "请先完成心电账号关联")
    if not row.expires_at or row.expires_at <= clock.now().timestamp():
        raise AppError(409, "ECG_LINK_EXPIRED", "心电授权已过期，请解除关联后重新绑定")
    if control and not row.measurement_allowed:
        raise AppError(403, "ECG_MEASUREMENT_FORBIDDEN", "当前关联仅允许查看，请在心电平台重新授权测量后绑定")
    token, operation, expected_owner = row.grant_token, row.operation_id, row.ecg_user_id
    db.rollback()
    try:
        data = call(token)
    except AppError as exc:
        if exc.code == "ECG_LINK_EXPIRED":
            _lock(db)
            current = _row(db, uid)
            if current and current.operation_id == operation:
                current.state = "revocation_pending"
            db.commit()
        raise
    if data.ecg_user.id != expected_owner or (control and not data.measurement_allowed):
        raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的账号或授权范围不匹配")
    _active_user(db, uid)
    current = _row(db, uid)
    if (not current or current.operation_id != operation or current.state != "active"
            or current.grant_token != token):
        raise AppError(409, "ECG_LINK_CHANGED", "心电关联已改变，请刷新页面；已提交的测量可能仍在执行")
    if not current.expires_at or min(current.expires_at, data.expires_at) <= clock.now().timestamp():
        raise AppError(409, "ECG_LINK_EXPIRED", "心电授权已过期，请解除关联后重新绑定")
    if control and not current.measurement_allowed:
        raise AppError(403, "ECG_MEASUREMENT_FORBIDDEN", "测量授权已改变，请重新确认")
    return data


def devices(db: Session, uid: str, settings: Settings, clock: Clock, upstream: EcgClient) -> dict:
    return _linked_request(db, uid, clock, lambda token: upstream.devices(uid, token), control=True).model_dump()


def _report_url(settings: Settings, session_id: str | None, status: str) -> str | None:
    if not session_id or status != "completed":
        return None
    public = urlsplit(settings.ecg_external_url or "")
    return urlunsplit((public.scheme, public.netloc, "/", urlencode({"record": session_id}), ""))


def measurements(db: Session, uid: str, settings: Settings, clock: Clock, upstream: EcgClient) -> dict:
    result = _linked_request(db, uid, clock, lambda token: upstream.measurements(uid, token), control=True).model_dump()
    for item in result["measurements"]:
        item["report_url"] = _report_url(settings, item["session_id"], item["status"])
    return result


def create_measurement(db: Session, uid: str, payload: MeasurementRequest, settings: Settings,
                       clock: Clock, upstream: EcgClient) -> dict:
    data = _linked_request(db, uid, clock,
        lambda token: upstream.create_measurement(uid, token, payload.model_dump()), control=True)
    if data.measurement.device_id != payload.device_id or data.measurement.duration_s != payload.duration_s:
        raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的测量与请求不匹配，请保留原请求重试")
    result = data.model_dump()
    item = result["measurement"]
    item["report_url"] = _report_url(settings, item["session_id"], item["status"])
    return result


def weekly_summary(db: Session, uid: str, week_start: date | None, settings: Settings,
                   clock: Clock, upstream: EcgClient) -> dict:
    user = _active_user(db, uid)
    tz_name = user.timezone
    today_local = user_local_date(clock, tz_name)
    current_monday = today_local - timedelta(days=today_local.weekday())
    ws = week_start or current_monday
    if ws.weekday() != 0:
        raise AppError(422, "INVALID_WEEK_START", "week_start 必须为周一日期 (YYYY-MM-DD)")
    if ws > current_monday:
        raise AppError(422, "FUTURE_WEEK_FORBIDDEN", "不能查询未来周报")
    observed_days = (today_local - ws).days + 1 if ws == current_monday else 7
    params = {"week_start": ws.isoformat(), "timezone": tz_name, "observed_days": observed_days}
    data = _linked_request(db, uid, clock, lambda token: upstream.weekly_summary(uid, token, params))
    expected_dates = [(ws + timedelta(days=n)).isoformat() for n in range(7)]
    if (data.week_start != ws.isoformat() or data.week_end != expected_dates[-1]
            or data.timezone != tz_name or data.observed_days != observed_days
            or [item.date for item in data.daily_series] != expected_dates):
        raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的周报范围不匹配")
    if (any(item.hr_records > item.records or (not item.hr_records and item.hr_mean is not None)
            for item in data.daily_series)
            or any(item.records or item.duration_s or item.hr_mean is not None or item.hr_records
                   for item in data.daily_series[observed_days:])
            or data.total_records != sum(item.records for item in data.daily_series)
            or data.hr_records != sum(item.hr_records for item in data.daily_series)
            or (not data.hr_records and data.hr_mean is not None)):
        raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回的周报统计不一致")
    if _active_user(db, uid).timezone != tz_name:
        raise AppError(409, "ECG_PERIOD_CHANGED", "账号时区已改变，请重新加载周报")
    return data.model_dump()
