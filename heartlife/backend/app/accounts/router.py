from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.schemas import LoginRequest, RegisterRequest, UpdateProfileRequest
from app.accounts.service import (
    authenticate_and_create_session,
    register_user,
    revoke_all_user_sessions,
    serialize_me,
    serialize_public_profile,
    update_user_profile,
)
from app.core.clock import Clock
from app.core.config import Settings
from app.core.deps import get_clock, get_current_auth, get_db, get_rate_limiter, get_settings
from app.core.errors import AppError
from app.core.security import LoginRateLimiter
from app.db.models import User, UserSession

router = APIRouter(tags=["accounts"])


def _set_auth_cookies(response: Response, settings: Settings, raw_session: str, csrf_token: str) -> None:
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_session,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path=settings.cookie_path,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path=settings.cookie_path,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path=settings.cookie_path)
    response.delete_cookie(key=settings.csrf_cookie_name, path=settings.cookie_path)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def api_register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    user = register_user(db, payload, clock)
    return {"user": serialize_me(user)}


@router.post("/auth/login")
def api_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    rate_limiter: LoginRateLimiter = Depends(get_rate_limiter),
) -> dict:
    client_ip = request.client.host if request.client else "127.0.0.1"
    user, raw_session, csrf_token = authenticate_and_create_session(
        db,
        payload,
        client_ip=client_ip,
        settings=settings,
        clock=clock,
        rate_limiter=rate_limiter,
    )
    _set_auth_cookies(response, settings, raw_session, csrf_token)
    return {"user": serialize_me(user), "csrf_token": csrf_token}


@router.post("/auth/logout")
def api_logout(
    response: Response,
    auth: tuple[UserSession, User] = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> dict:
    sess, _ = auth
    sess.revoked_at = clock.now()
    db.commit()
    _clear_auth_cookies(response, settings)
    return {"status": "logged_out"}


@router.get("/me")
def api_get_me(auth: tuple[UserSession, User] = Depends(get_current_auth)) -> dict:
    sess, user = auth
    return {**serialize_me(user), "csrf_token": sess.csrf_token}


@router.patch("/me")
def api_patch_me(
    payload: UpdateProfileRequest,
    auth: tuple[UserSession, User] = Depends(get_current_auth),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    sess, user = auth
    updated = update_user_profile(db, user, payload, clock)
    return {**serialize_me(updated), "csrf_token": sess.csrf_token}


@router.post("/me/revoke-sessions")
def api_revoke_sessions(
    response: Response,
    auth: tuple[UserSession, User] = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> dict:
    _, user = auth
    revoked = revoke_all_user_sessions(db, user.id, clock)
    _clear_auth_cookies(response, settings)
    return {"revoked": revoked}


@router.get("/users/{user_id}")
def api_public_user_profile(
    user_id: str,
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id, User.status == "active"))
    if user is None:
        raise AppError(404, "NOT_FOUND", "用户不存在")
    return serialize_public_profile(db, user)
