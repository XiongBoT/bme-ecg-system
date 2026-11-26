from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import json
from sqlalchemy import delete, desc, or_, select, text, update
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import AppError
from app.core.security import verify_password
from app.db.models import (
    AssistantAuditLog,
    Bookmark,
    ChallengeMembership,
    Checkin,
    Comment,
    EcgLink,
    FamilyGrant,
    FamilyInvite,
    JournalEntry,
    Notification,
    Plan,
    PlanVersion,
    Post,
    PostTag,
    Reaction,
    ReadingDailyLog,
    ReadingHistory,
    TopicFollow,
    User,
    UserBadge,
    UserBlock,
    UserSession,
)
from app.privacy.schemas import DeleteAccountRequest
from app.reports.service import compute_weekly_report

# Hook solely for testing atomic rollback when an unexpected failure occurs mid-transaction (T-0704)
_DELETION_TEST_HOOK: Callable[[], None] | None = None


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except (ValueError, TypeError):
        pass
    return []


def export_user_data(db: Session, user: User, clock: Clock) -> dict:
    journals = db.scalars(
        select(JournalEntry)
        .where(JournalEntry.user_id == user.id)
        .order_by(desc(JournalEntry.local_date))
    ).all()

    plans = list(
        db.scalars(
            select(Plan)
            .where(Plan.owner_id == user.id)
            .order_by(Plan.created_at.asc(), Plan.id.asc())
        ).all()
    )

    versions_by_plan: dict[str, list[PlanVersion]] = defaultdict(list)
    checkins_by_plan: dict[str, list[Checkin]] = defaultdict(list)
    if plans:
        plan_ids = [p.id for p in plans]
        for v in db.scalars(
            select(PlanVersion)
            .where(PlanVersion.plan_id.in_(plan_ids))
            .order_by(PlanVersion.version_num.asc())
        ).all():
            versions_by_plan[v.plan_id].append(v)
        for c in db.scalars(
            select(Checkin)
            .where(Checkin.plan_id.in_(plan_ids))
            .order_by(Checkin.local_date.asc())
        ).all():
            checkins_by_plan[c.plan_id].append(c)

    weekly_report = compute_weekly_report(db, user, clock, week_start=None)

    return {
        "exported_at": clock.now().isoformat(),
        "profile": {
            "nickname": user.nickname,
            "bio": user.bio,
            "timezone": user.timezone,
            "created_at": user.created_at.isoformat(),
        },
        "journals": [
            {
                "local_date": j.local_date.isoformat(),
                "sleep_minutes": j.sleep_minutes,
                "activity_minutes": j.activity_minutes,
                "mood": j.mood,
                "symptom_tags": _parse_tags(j.symptom_tags_json),
                "note": j.note,
                "created_at": j.created_at.isoformat(),
                "updated_at": j.updated_at.isoformat(),
            }
            for j in journals
        ],
        "plans": [
            {
                "id": p.id,
                "title": p.title,
                "template_key": p.template_key,
                "active": p.active,
                "reminder_enabled": p.reminder_enabled,
                "reminder_time": p.reminder_time,
                "created_at": p.created_at.isoformat(),
                "versions": [
                    {
                        "version_num": v.version_num,
                        "effective_from": v.effective_from.isoformat(),
                        "effective_to": v.effective_to.isoformat() if v.effective_to else None,
                        "weekday_mask": v.weekday_mask,
                        "active": v.active,
                        "start_date": v.start_date.isoformat(),
                        "end_date": v.end_date.isoformat() if v.end_date else None,
                    }
                    for v in versions_by_plan.get(p.id, [])
                ],
                "checkins": [
                    {
                        "local_date": c.local_date.isoformat(),
                        "completed": c.completed,
                    }
                    for c in checkins_by_plan.get(p.id, [])
                ],
            }
            for p in plans
        ],
        "current_weekly_report": weekly_report,
    }


def validate_account_deletion(user: User, payload: DeleteAccountRequest) -> None:
    if payload.confirm_text != "DELETE":
        raise AppError(422, "CONFIRM_TEXT_INVALID", "请输入大写 DELETE 以确认注销账号")

    if not verify_password(payload.password, user.password_hash):
        raise AppError(401, "INVALID_PASSWORD", "当前登录密码校验未通过")


def delete_user_account_atomic(
    db: Session,
    user: User,
    payload: DeleteAccountRequest,
    clock: Clock,
) -> None:
    validate_account_deletion(user, payload)

    uid = user.id
    now = clock.now()

    try:
        # Serialize with binding reservation. No external HTTP call is made here.
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        db.refresh(user)
        if user.status != "active":
            raise AppError(401, "UNAUTHORIZED", "账号已失效")
        validate_account_deletion(user, payload)
        if db.get(EcgLink, uid) is not None:
            raise AppError(409, "ECG_LINK_CHANGED", "心电关联状态已改变，请先解除关联后重试注销")
        plan_ids = list(db.scalars(select(Plan.id).where(Plan.owner_id == uid)).all())
        if plan_ids:
            db.execute(delete(Checkin).where(Checkin.plan_id.in_(plan_ids)))
            db.execute(delete(PlanVersion).where(PlanVersion.plan_id.in_(plan_ids)))
            db.execute(delete(Plan).where(Plan.owner_id == uid))

        db.execute(delete(UserSession).where(UserSession.user_id == uid))
        db.execute(delete(JournalEntry).where(JournalEntry.user_id == uid))
        db.execute(delete(Bookmark).where(Bookmark.user_id == uid))
        db.execute(delete(Reaction).where(Reaction.user_id == uid))
        db.execute(delete(ReadingHistory).where(ReadingHistory.user_id == uid))
        db.execute(delete(ReadingDailyLog).where(ReadingDailyLog.user_id == uid))
        db.execute(delete(Notification).where(Notification.recipient_id == uid))
        db.execute(delete(ChallengeMembership).where(ChallengeMembership.user_id == uid))
        db.execute(delete(UserBadge).where(UserBadge.user_id == uid))
        db.execute(delete(TopicFollow).where(TopicFollow.user_id == uid))
        db.execute(
            delete(UserBlock).where(
                or_(UserBlock.blocker_id == uid, UserBlock.blocked_id == uid)
            )
        )
        db.execute(
            delete(FamilyInvite).where(
                or_(FamilyInvite.granter_id == uid, FamilyInvite.used_by_id == uid)
            )
        )
        db.execute(
            delete(FamilyGrant).where(
                or_(FamilyGrant.granter_id == uid, FamilyGrant.viewer_id == uid)
            )
        )
        db.execute(
            update(AssistantAuditLog)
            .where(AssistantAuditLog.user_id == uid)
            .values(user_id=None)
        )

        post_ids = list(db.scalars(select(Post.id).where(Post.author_id == uid)).all())
        if post_ids:
            db.execute(delete(PostTag).where(PostTag.post_id.in_(post_ids)))

        db.execute(
            update(Post)
            .where(Post.author_id == uid)
            .values(
                status="hidden",
                title="[已注销内容]",
                body="[账号已注销]",
                updated_at=now,
            )
        )
        db.execute(
            update(Comment)
            .where(Comment.author_id == uid)
            .values(
                status="hidden",
                body="[账号已注销]",
                updated_at=now,
            )
        )

        if _DELETION_TEST_HOOK is not None:
            _DELETION_TEST_HOOK()

        user.status = "deleted"
        user.account = f"deleted_{uid}"
        user.password_hash = "!"
        user.nickname = "已注销用户"
        user.bio = ""
        user.updated_at = now

        db.commit()
    except Exception:
        db.rollback()
        raise
