from __future__ import annotations

from datetime import timedelta, timezone
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import AppError
from app.core.security import generate_token, hash_token
from app.db.models import FamilyGrant, FamilyInvite, User
from app.family.schemas import (
    AcceptFamilyInviteRequest,
    CreateFamilyInviteRequest,
    UpdateFamilyGrantRequest,
)
from app.reports.service import compute_weekly_report


def _serialize_grant(grant: FamilyGrant, nickname_map: dict[str, str]) -> dict:
    return {
        "id": grant.id,
        "granter_id": grant.granter_id,
        "granter_nickname": nickname_map.get(grant.granter_id, ""),
        "viewer_id": grant.viewer_id,
        "viewer_nickname": nickname_map.get(grant.viewer_id, ""),
        "status": grant.status,
        "share_plan_summary": grant.share_plan_summary,
        "share_weekly_sleep": grant.share_weekly_sleep,
        "share_weekly_activity": grant.share_weekly_activity,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "created_at": grant.created_at.isoformat(),
        "updated_at": grant.updated_at.isoformat(),
    }


def _load_nicknames(db: Session, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = db.execute(select(User.id, User.nickname).where(User.id.in_(user_ids))).all()
    return {uid: nick for uid, nick in rows}


def create_family_invite(
    db: Session,
    user: User,
    payload: CreateFamilyInviteRequest,
    clock: Clock,
) -> dict:
    raw_code = generate_token(16)
    now = clock.now()
    expires_at = now + timedelta(hours=24)

    invite = FamilyInvite(
        granter_id=user.id,
        code_hash=hash_token(raw_code),
        share_plan_summary=payload.share_plan_summary,
        share_weekly_sleep=payload.share_weekly_sleep,
        share_weekly_activity=payload.share_weekly_activity,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    return {
        "invite_id": invite.id,
        "invite_code": raw_code,
        "expires_at": invite.expires_at.isoformat(),
        "share_plan_summary": invite.share_plan_summary,
        "share_weekly_sleep": invite.share_weekly_sleep,
        "share_weekly_activity": invite.share_weekly_activity,
    }


def accept_family_invite(
    db: Session,
    user: User,
    payload: AcceptFamilyInviteRequest,
    clock: Clock,
) -> dict:
    cleaned = payload.invite_code.strip()
    if not cleaned:
        raise AppError(422, "VALIDATION_ERROR", "邀请码不能为空")

    invite = db.scalar(select(FamilyInvite).where(FamilyInvite.code_hash == hash_token(cleaned)))
    if invite is None:
        raise AppError(404, "INVITE_NOT_FOUND", "邀请码无效或不存在")

    if invite.used_at is not None:
        raise AppError(409, "INVITE_ALREADY_USED", "该邀请码已被使用")

    exp = invite.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    now = clock.now()
    if exp <= now:
        raise AppError(422, "INVITE_EXPIRED", "邀请码已过期")

    if invite.granter_id == user.id:
        raise AppError(422, "SELF_INVITE_FORBIDDEN", "不能接受自己发出的关怀邀请")

    granter = db.scalar(select(User).where(User.id == invite.granter_id, User.status == "active"))
    if granter is None:
        raise AppError(404, "GRANTER_NOT_FOUND", "邀请发起人不存在")

    invite.used_at = now
    invite.used_by_id = user.id

    grant = db.scalar(
        select(FamilyGrant).where(
            FamilyGrant.granter_id == invite.granter_id,
            FamilyGrant.viewer_id == user.id,
        )
    )
    if grant is None:
        grant = FamilyGrant(
            granter_id=invite.granter_id,
            viewer_id=user.id,
            status="active",
            share_plan_summary=invite.share_plan_summary,
            share_weekly_sleep=invite.share_weekly_sleep,
            share_weekly_activity=invite.share_weekly_activity,
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(grant)
    else:
        grant.status = "active"
        grant.revoked_at = None
        grant.share_plan_summary = invite.share_plan_summary
        grant.share_weekly_sleep = invite.share_weekly_sleep
        grant.share_weekly_activity = invite.share_weekly_activity
        grant.updated_at = now

    db.commit()
    db.refresh(grant)
    nicknames = {granter.id: granter.nickname, user.id: user.nickname}
    return _serialize_grant(grant, nicknames)


def list_family_grants(db: Session, user: User) -> dict:
    by_me = list(
        db.scalars(
            select(FamilyGrant)
            .where(FamilyGrant.granter_id == user.id, FamilyGrant.status == "active")
            .order_by(desc(FamilyGrant.updated_at))
        ).all()
    )
    to_me = list(
        db.scalars(
            select(FamilyGrant)
            .where(FamilyGrant.viewer_id == user.id, FamilyGrant.status == "active")
            .order_by(desc(FamilyGrant.updated_at))
        ).all()
    )

    all_ids = {user.id}
    for g in by_me + to_me:
        all_ids.add(g.granter_id)
        all_ids.add(g.viewer_id)
    nicknames = _load_nicknames(db, all_ids)

    return {
        "granted_by_me": [_serialize_grant(g, nicknames) for g in by_me],
        "granted_to_me": [_serialize_grant(g, nicknames) for g in to_me],
    }


def update_family_grant_scope(
    db: Session,
    user: User,
    grant_id: str,
    payload: UpdateFamilyGrantRequest,
    clock: Clock,
) -> dict:
    grant = db.get(FamilyGrant, grant_id)
    if grant is None or grant.status != "active":
        raise AppError(404, "GRANT_NOT_FOUND", "关怀授权不存在")

    if grant.granter_id != user.id:
        raise AppError(403, "FORBIDDEN", "仅授权发起人可修改共享范围")

    if payload.share_plan_summary is not None:
        grant.share_plan_summary = payload.share_plan_summary
    if payload.share_weekly_sleep is not None:
        grant.share_weekly_sleep = payload.share_weekly_sleep
    if payload.share_weekly_activity is not None:
        grant.share_weekly_activity = payload.share_weekly_activity

    grant.updated_at = clock.now()
    db.commit()
    db.refresh(grant)
    nicknames = _load_nicknames(db, {grant.granter_id, grant.viewer_id})
    return _serialize_grant(grant, nicknames)


def revoke_family_grant(
    db: Session,
    user: User,
    grant_id: str,
    clock: Clock,
) -> dict:
    grant = db.get(FamilyGrant, grant_id)
    if grant is None:
        raise AppError(404, "GRANT_NOT_FOUND", "关怀授权不存在")

    if user.id not in (grant.granter_id, grant.viewer_id):
        raise AppError(403, "FORBIDDEN", "无权撤销该关怀授权")

    now = clock.now()
    grant.status = "revoked"
    grant.revoked_at = now
    grant.updated_at = now
    db.commit()
    db.refresh(grant)
    return {
        "id": grant.id,
        "status": grant.status,
        "revoked_at": grant.revoked_at.isoformat(),
    }


def get_shared_family_summary(
    db: Session,
    viewer: User,
    granter_id: str,
    clock: Clock,
) -> dict:
    grant = db.scalar(
        select(FamilyGrant).where(
            FamilyGrant.granter_id == granter_id,
            FamilyGrant.viewer_id == viewer.id,
            FamilyGrant.status == "active",
        )
    )
    if grant is None:
        raise AppError(403, "FORBIDDEN", "未获得该亲友的有效关怀授权")

    granter = db.scalar(select(User).where(User.id == granter_id, User.status == "active"))
    if granter is None:
        raise AppError(404, "NOT_FOUND", "用户不存在")

    report = compute_weekly_report(db, granter, clock, week_start=None)

    # Strictly return ONLY granter_nickname + explicitly enabled summary aggregates
    response: dict[str, object] = {
        "granter_id": granter.id,
        "granter_nickname": granter.nickname,
        "week_start": report["week_start"],
        "observed_days": report["observed_days"],
    }
    if grant.share_plan_summary:
        response["plan_summary"] = report["plans"]
    if grant.share_weekly_sleep:
        response["weekly_sleep"] = report["sleep"]
    if grant.share_weekly_activity:
        response["weekly_activity"] = report["activity"]

    return response
