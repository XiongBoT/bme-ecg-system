from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import timezone
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import LoginRateLimiter, hash_token, verify_csrf
from app.db.models import User, UserSession


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_rate_limiter(request: Request) -> LoginRateLimiter:
    return request.app.state.rate_limiter


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _resolve_active_session_and_user(
    request: Request,
    db: Session,
    settings: Settings,
    clock: Clock,
) -> tuple[UserSession, User] | None:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    sess = db.get(UserSession, token_hash)
    if sess is None or sess.revoked_at is not None:
        return None
    exp = sess.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= clock.now():
        return None

    user = db.scalar(select(User).where(User.id == sess.user_id))
    if user is None or user.status != "active":
        return None
    return sess, user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> User | None:
    resolved = _resolve_active_session_and_user(request, db, settings, clock)
    return resolved[1] if resolved else None


def get_current_auth(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> tuple[UserSession, User]:
    resolved = _resolve_active_session_and_user(request, db, settings, clock)
    if not resolved:
        raise AppError(401, "UNAUTHORIZED", "请先登录或重新登录")
    sess, user = resolved
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_header = request.headers.get("X-CSRF-Token")
        if not verify_csrf(sess.csrf_hash, csrf_header):
            raise AppError(403, "CSRF_INVALID", "安全校验未通过，请刷新页面后重试")
    return sess, user


def get_current_user(auth: tuple[UserSession, User] = Depends(get_current_auth)) -> User:
    return auth[1]


def require_role(role: str) -> Callable[..., User]:
    def _dep(user: User = Depends(get_current_user)) -> User:
        if not user.has_role(role):
            raise AppError(403, "FORBIDDEN", "当前账号无此操作权限")
        return user

    return _dep
