from __future__ import annotations

from datetime import date
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.challenges.schemas import ShareChallengeRequest
from app.core.clock import Clock, user_local_date
from app.core.errors import AppError
from app.db.models import (
    Challenge,
    ChallengeMembership,
    Checkin,
    JournalEntry,
    Plan,
    Post,
    ReadingDailyLog,
    User,
    UserBadge,
)


def serialize_challenge(c: Challenge) -> dict:
    return {
        "id": c.id,
        "slug": c.slug,
        "title": c.title,
        "description": c.description,
        "rule_type": c.rule_type,
        "target_days": c.target_days,
        "start_date": c.start_date.isoformat(),
        "end_date": c.end_date.isoformat(),
        "badge_title": c.badge_title,
    }


def serialize_membership(m: ChallengeMembership) -> dict:
    return {
        "membership_id": m.id,
        "challenge_id": m.challenge_id,
        "status": m.status,
        "joined_date": m.joined_date.isoformat(),
        "left_date": m.left_date.isoformat() if m.left_date else None,
    }


def list_active_challenges(db: Session) -> list[dict]:
    rows = db.scalars(
        select(Challenge)
        .where(Challenge.active.is_(True))
        .order_by(desc(Challenge.start_date), Challenge.id.asc())
    ).all()
    return [serialize_challenge(c) for c in rows]


def join_challenge_idempotent(
    db: Session,
    user: User,
    challenge_id: str,
    clock: Clock,
) -> dict:
    challenge = db.get(Challenge, challenge_id)
    if challenge is None or not challenge.active:
        raise AppError(404, "CHALLENGE_NOT_FOUND", "挑战活动不存在或已下线")

    today_local = user_local_date(clock, user.timezone)
    if today_local > challenge.end_date:
        raise AppError(422, "CHALLENGE_ENDED", "该挑战活动已结束，无法加入")

    existing = db.scalar(
        select(ChallengeMembership).where(
            ChallengeMembership.challenge_id == challenge.id,
            ChallengeMembership.user_id == user.id,
        )
    )
    now = clock.now()
    if existing is not None:
        if existing.status == "active":
            return serialize_membership(existing)
        existing.status = "active"
        existing.joined_date = today_local
        existing.left_date = None
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return serialize_membership(existing)

    membership = ChallengeMembership(
        challenge_id=challenge.id,
        user_id=user.id,
        status="active",
        joined_date=today_local,
        left_date=None,
        created_at=now,
        updated_at=now,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = db.scalar(
            select(ChallengeMembership).where(
                ChallengeMembership.challenge_id == challenge.id,
                ChallengeMembership.user_id == user.id,
            )
        )
        if raced is not None:
            return serialize_membership(raced)
        raise
    db.refresh(membership)
    return serialize_membership(membership)


def leave_challenge(
    db: Session,
    user: User,
    challenge_id: str,
    clock: Clock,
) -> dict:
    membership = db.scalar(
        select(ChallengeMembership).where(
            ChallengeMembership.challenge_id == challenge_id,
            ChallengeMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise AppError(404, "MEMBERSHIP_NOT_FOUND", "尚未加入该挑战")

    if membership.status != "left":
        membership.status = "left"
        membership.left_date = user_local_date(clock, user.timezone)
        membership.updated_at = clock.now()
        db.commit()
        db.refresh(membership)

    return serialize_membership(membership)


def _count_progress_days(
    db: Session,
    user_id: str,
    challenge: Challenge,
    membership: ChallengeMembership,
    today_local: date,
) -> int:
    win_start = max(challenge.start_date, membership.joined_date)
    if membership.status == "active":
        win_end = min(challenge.end_date, today_local)
    else:
        effective_left = membership.left_date or today_local
        win_end = min(challenge.end_date, effective_left, today_local)

    if win_start > win_end:
        return 0

    if challenge.rule_type == "journal_sleep":
        cnt = db.scalar(
            select(func.count(func.distinct(JournalEntry.local_date))).where(
                JournalEntry.user_id == user_id,
                JournalEntry.sleep_minutes.is_not(None),
                JournalEntry.local_date >= win_start,
                JournalEntry.local_date <= win_end,
            )
        )
        return int(cnt or 0)

    if challenge.rule_type == "read_article":
        cnt = db.scalar(
            select(func.count(func.distinct(ReadingDailyLog.local_date))).where(
                ReadingDailyLog.user_id == user_id,
                ReadingDailyLog.local_date >= win_start,
                ReadingDailyLog.local_date <= win_end,
            )
        )
        return int(cnt or 0)

    if challenge.rule_type == "plan_checkin":
        cnt = db.scalar(
            select(func.count(func.distinct(Checkin.local_date)))
            .select_from(Checkin)
            .join(Plan, Plan.id == Checkin.plan_id)
            .where(
                Plan.owner_id == user_id,
                Checkin.completed.is_(True),
                Checkin.local_date >= win_start,
                Checkin.local_date <= win_end,
            )
        )
        return int(cnt or 0)

    return 0


def _ensure_badge_idempotent(
    db: Session,
    user_id: str,
    challenge: Challenge,
    achieved_date: date,
    clock: Clock,
) -> None:
    existing = db.scalar(
        select(UserBadge).where(
            UserBadge.user_id == user_id,
            UserBadge.challenge_id == challenge.id,
        )
    )
    if existing is not None:
        return
    badge = UserBadge(
        user_id=user_id,
        challenge_id=challenge.id,
        badge_title=challenge.badge_title,
        achieved_date=achieved_date,
        created_at=clock.now(),
    )
    try:
        with db.begin_nested():
            db.add(badge)
            db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()


def get_my_challenges_and_badges(
    db: Session,
    user: User,
    clock: Clock,
) -> dict:
    today_local = user_local_date(clock, user.timezone)
    pairs = db.execute(
        select(ChallengeMembership, Challenge)
        .join(Challenge, Challenge.id == ChallengeMembership.challenge_id)
        .where(ChallengeMembership.user_id == user.id)
        .order_by(desc(ChallengeMembership.created_at), desc(ChallengeMembership.id))
    ).all()

    items: list[dict] = []
    for m, c in pairs:
        progress_days = _count_progress_days(db, user.id, c, m, today_local)
        if progress_days >= c.target_days:
            achieved_on = min(today_local, m.left_date or today_local, c.end_date)
            _ensure_badge_idempotent(db, user.id, c, achieved_on, clock)

        items.append(
            {
                "membership_id": m.id,
                "challenge_id": c.id,
                "slug": c.slug,
                "title": c.title,
                "description": c.description,
                "rule_type": c.rule_type,
                "target_days": c.target_days,
                "start_date": c.start_date.isoformat(),
                "end_date": c.end_date.isoformat(),
                "badge_title": c.badge_title,
                "status": m.status,
                "joined_date": m.joined_date.isoformat(),
                "left_date": m.left_date.isoformat() if m.left_date else None,
                "progress_days": progress_days,
                "completed": progress_days >= c.target_days,
            }
        )

    badges = db.scalars(
        select(UserBadge)
        .where(UserBadge.user_id == user.id)
        .order_by(desc(UserBadge.achieved_date), desc(UserBadge.created_at))
    ).all()

    return {
        "items": items,
        "badges": [
            {
                "id": b.id,
                "challenge_id": b.challenge_id,
                "badge_title": b.badge_title,
                "achieved_date": b.achieved_date.isoformat(),
                "created_at": b.created_at.isoformat(),
            }
            for b in badges
        ],
    }


def share_challenge_progress(
    db: Session,
    user: User,
    challenge_id: str,
    payload: ShareChallengeRequest | None,
    clock: Clock,
) -> dict:
    challenge = db.get(Challenge, challenge_id)
    if challenge is None:
        raise AppError(404, "CHALLENGE_NOT_FOUND", "挑战活动不存在")

    membership = db.scalar(
        select(ChallengeMembership).where(
            ChallengeMembership.challenge_id == challenge.id,
            ChallengeMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise AppError(403, "NOT_JOINED", "请先加入该挑战活动")

    today_local = user_local_date(clock, user.timezone)
    progress_days = _count_progress_days(db, user.id, challenge, membership, today_local)
    if progress_days < 1:
        raise AppError(422, "NO_CHALLENGE_PROGRESS", "至少完成 1 天打卡后方可分享进展")

    now = clock.now()
    title = f"完成了「{challenge.title}」阶段打卡"[:120]
    body_lines = [f"我在「{challenge.title}」已累计完成 {progress_days}/{challenge.target_days} 天打卡。"]
    if payload is not None and payload.note and payload.note.strip():
        body_lines.append(payload.note.strip())

    post = Post(
        author_id=user.id,
        category="运动与习惯",
        title=title,
        body="\n".join(body_lines),
        status="visible",
        created_at=now,
        updated_at=now,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return {
        "post": {
            "id": post.id,
            "title": post.title,
            "category": post.category,
            "body": post.body,
            "created_at": post.created_at.isoformat(),
        }
    }
