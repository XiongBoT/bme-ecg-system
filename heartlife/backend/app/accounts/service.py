from __future__ import annotations

from datetime import timedelta
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.schemas import LoginRequest, RegisterRequest, UpdateProfileRequest
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    LoginRateLimiter,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.models import Post, User, UserSession


def serialize_me(user: User) -> dict:
    return {
        "id": user.id,
        "account": user.account,
        "nickname": user.nickname,
        "bio": user.bio,
        "timezone": user.timezone,
        "roles": user.role_list,
        "is_demo": user.is_demo,
        "created_at": user.created_at.isoformat(),
    }


def serialize_public_profile(db: Session, user: User) -> dict:
    recent_posts = db.scalars(
        select(Post)
        .where(Post.author_id == user.id, Post.status == "visible")
        .order_by(desc(Post.created_at), desc(Post.id))
        .limit(10)
    ).all()
    return {
        "id": user.id,
        "nickname": user.nickname,
        "bio": user.bio,
        "is_demo": user.is_demo,
        "created_at": user.created_at.isoformat(),
        "recent_posts": [
            {
                "id": p.id,
                "title": p.title,
                "category": p.category,
                "created_at": p.created_at.isoformat(),
            }
            for p in recent_posts
        ],
    }


def register_user(db: Session, payload: RegisterRequest, clock: Clock) -> User:
    existing = db.scalar(select(User).where(User.account == payload.account))
    if existing is not None:
        raise AppError(409, "ACCOUNT_EXISTS", "该账号已被注册")

    now = clock.now()
    user = User(
        account=payload.account,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
        bio="",
        timezone=payload.timezone,
        roles="member",
        status="active",
        is_demo=False,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "ACCOUNT_EXISTS", "该账号已被注册") from exc
    db.refresh(user)
    return user


def authenticate_and_create_session(
    db: Session,
    payload: LoginRequest,
    *,
    client_ip: str,
    settings: Settings,
    clock: Clock,
    rate_limiter: LoginRateLimiter,
) -> tuple[User, str, str]:
    normalized_account = payload.account.strip().lower()
    rl_key = f"{client_ip}:{normalized_account}"

    if not rate_limiter.check_allowed(rl_key, clock):
        raise AppError(429, "RATE_LIMITED", "登录尝试次数过多，请稍后再试")

    user = db.scalar(select(User).where(User.account == normalized_account))
    if user is None or user.status != "active" or not verify_password(payload.password, user.password_hash):
        rate_limiter.record_failure(rl_key, clock)
        raise AppError(401, "INVALID_CREDENTIALS", "账号或密码错误")

    rate_limiter.reset(rl_key)

    now = clock.now()
    raw_session = generate_token(32)
    csrf_token = generate_token(24)
    sess = UserSession(
        id_hash=hash_token(raw_session),
        user_id=user.id,
        csrf_token=csrf_token,
        csrf_hash=hash_token(csrf_token),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        created_at=now,
    )
    db.add(sess)
    db.commit()
    return user, raw_session, csrf_token


def update_user_profile(
    db: Session,
    user: User,
    payload: UpdateProfileRequest,
    clock: Clock,
) -> User:
    if payload.nickname is not None:
        user.nickname = payload.nickname
    if payload.bio is not None:
        user.bio = payload.bio
    if payload.timezone is not None:
        user.timezone = payload.timezone
    user.updated_at = clock.now()
    db.commit()
    db.refresh(user)
    return user


def revoke_all_user_sessions(db: Session, user_id: str, clock: Clock) -> int:
    now = clock.now()
    active_sessions = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    ).all()
    for s in active_sessions:
        s.revoked_at = now
    db.commit()
    return len(active_sessions)
