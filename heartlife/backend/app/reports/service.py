from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
import json
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.clock import Clock, user_local_date
from app.core.errors import AppError
from app.db.models import (
    Article,
    Checkin,
    JournalEntry,
    Notification,
    Plan,
    PlanVersion,
    Post,
    User,
    UserBlock,
)


def _parse_symptom_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except (ValueError, TypeError):
        pass
    return []


def is_plan_due_from_versions(versions_desc: Sequence[PlanVersion], target_date: date) -> bool:
    """Evaluate whether a plan is due on target_date using its PlanVersion chain (ordered by version_num DESC)."""
    matched: PlanVersion | None = None
    for v in versions_desc:
        if v.effective_from <= target_date and (v.effective_to is None or target_date <= v.effective_to):
            matched = v
            break
    if matched is None or not matched.active:
        return False
    if target_date < matched.start_date:
        return False
    if matched.end_date is not None and target_date > matched.end_date:
        return False
    bit = 1 << (target_date.isoweekday() - 1)
    return bool(matched.weekday_mask & bit)


def is_plan_due_on_date(db: Session, plan_id: str, target_date: date) -> bool:
    """Single-query PlanVersion due helper for a specific plan and target_date."""
    v = db.scalar(
        select(PlanVersion)
        .where(
            PlanVersion.plan_id == plan_id,
            PlanVersion.effective_from <= target_date,
            (PlanVersion.effective_to.is_(None)) | (target_date <= PlanVersion.effective_to),
        )
        .order_by(desc(PlanVersion.version_num))
        .limit(1)
    )
    if v is None:
        return False
    return is_plan_due_from_versions([v], target_date)


def _load_user_plans_and_versions(
    db: Session,
    user_id: str,
) -> tuple[list[Plan], dict[str, list[PlanVersion]]]:
    plans = list(
        db.scalars(
            select(Plan)
            .where(Plan.owner_id == user_id)
            .order_by(Plan.created_at.asc(), Plan.id.asc())
        ).all()
    )
    versions_by_plan: dict[str, list[PlanVersion]] = defaultdict(list)
    if plans:
        plan_ids = [p.id for p in plans]
        all_versions = db.scalars(
            select(PlanVersion)
            .where(PlanVersion.plan_id.in_(plan_ids))
            .order_by(PlanVersion.plan_id.asc(), desc(PlanVersion.version_num))
        ).all()
        for v in all_versions:
            versions_by_plan[v.plan_id].append(v)
    return plans, versions_by_plan


def compute_weekly_report(
    db: Session,
    user: User,
    clock: Clock,
    week_start: date | None = None,
) -> dict:
    today_local = user_local_date(clock, user.timezone)
    current_monday = today_local - timedelta(days=today_local.weekday())

    if week_start is None:
        ws = current_monday
    else:
        if week_start.weekday() != 0:
            raise AppError(422, "INVALID_WEEK_START", "week_start 必须为周一日期 (YYYY-MM-DD)")
        if week_start > current_monday:
            raise AppError(422, "FUTURE_WEEK_FORBIDDEN", "不能查询未来周报")
        ws = week_start

    if ws == current_monday:
        observed_days = (today_local - ws).days + 1
        status = "partial_week"
    else:
        observed_days = 7
        status = "completed_week"

    win_end = ws + timedelta(days=observed_days - 1)
    week_end = ws + timedelta(days=6)

    journals = list(
        db.scalars(
            select(JournalEntry)
            .where(
                JournalEntry.user_id == user.id,
                JournalEntry.local_date >= ws,
                JournalEntry.local_date <= win_end,
            )
            .order_by(JournalEntry.local_date.asc())
        ).all()
    )
    journal_by_date = {j.local_date: j for j in journals}
    journal_days = len(journals)
    journal_coverage_rate = round(journal_days / observed_days, 4)

    sleep_vals = [j.sleep_minutes for j in journals if j.sleep_minutes is not None]
    sleep = {
        "valid_days": len(sleep_vals),
        "mean_minutes": round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None,
    }

    act_vals = [j.activity_minutes for j in journals if j.activity_minutes is not None]
    activity = {
        "valid_days": len(act_vals),
        "total_minutes": sum(act_vals) if act_vals else None,
    }

    mood_distribution: dict[str, int] = {}
    for j in journals:
        if j.mood:
            mood_distribution[j.mood] = mood_distribution.get(j.mood, 0) + 1

    plans, versions_by_plan = _load_user_plans_and_versions(db, user.id)
    completed_pairs: set[tuple[str, date]] = set()
    if plans:
        plan_ids = [p.id for p in plans]
        checkins = db.scalars(
            select(Checkin).where(
                Checkin.plan_id.in_(plan_ids),
                Checkin.local_date >= ws,
                Checkin.local_date <= win_end,
                Checkin.completed.is_(True),
            )
        ).all()
        completed_pairs = {(c.plan_id, c.local_date) for c in checkins}

    total_due = 0
    total_completed = 0
    daily_series: list[dict] = []

    for offset in range(observed_days):
        d = ws + timedelta(days=offset)
        day_due = 0
        day_completed = 0
        for p in plans:
            if is_plan_due_from_versions(versions_by_plan.get(p.id, ()), d):
                day_due += 1
                if (p.id, d) in completed_pairs:
                    day_completed += 1
        total_due += day_due
        total_completed += day_completed

        j = journal_by_date.get(d)
        daily_series.append(
            {
                "date": d.isoformat(),
                "has_journal": j is not None,
                "sleep_minutes": j.sleep_minutes if j is not None else None,
                "activity_minutes": j.activity_minutes if j is not None else None,
                "mood": j.mood if j is not None else None,
                "plans_due": day_due,
                "plans_completed": day_completed,
            }
        )

    plans_summary = {
        "due": total_due,
        "completed": total_completed,
        "completion_rate": round(total_completed / total_due, 4) if total_due > 0 else None,
    }

    return {
        "week_start": ws.isoformat(),
        "week_end": week_end.isoformat(),
        "observed_days": observed_days,
        "status": status,
        "journal_days": journal_days,
        "journal_coverage_rate": journal_coverage_rate,
        "sleep": sleep,
        "activity": activity,
        "plans": plans_summary,
        "mood_distribution": mood_distribution,
        "daily_series": daily_series,
    }


def compute_dashboard(db: Session, user: User, clock: Clock) -> dict:
    today_local = user_local_date(clock, user.timezone)
    current_monday = today_local - timedelta(days=today_local.weekday())

    plans, versions_by_plan = _load_user_plans_and_versions(db, user.id)
    due_plans = [
        p for p in plans if is_plan_due_from_versions(versions_by_plan.get(p.id, ()), today_local)
    ]

    completed_today_ids: set[str] = set()
    if due_plans:
        due_ids = [p.id for p in due_plans]
        today_checkins = db.scalars(
            select(Checkin.plan_id).where(
                Checkin.plan_id.in_(due_ids),
                Checkin.local_date == today_local,
                Checkin.completed.is_(True),
            )
        ).all()
        completed_today_ids = set(today_checkins)

    plan_items = [
        {
            "id": p.id,
            "title": p.title,
            "completed": p.id in completed_today_ids,
        }
        for p in due_plans
    ]
    plans_summary = {
        "due_count": len(plan_items),
        "completed_count": sum(1 for item in plan_items if item["completed"]),
        "items": plan_items,
    }

    today_row = db.scalar(
        select(JournalEntry).where(
            JournalEntry.user_id == user.id,
            JournalEntry.local_date == today_local,
        )
    )
    if today_row is not None:
        today_journal = {
            "recorded": True,
            "local_date": today_row.local_date.isoformat(),
            "sleep_minutes": today_row.sleep_minutes,
            "activity_minutes": today_row.activity_minutes,
            "mood": today_row.mood,
            "symptom_tags": _parse_symptom_tags(today_row.symptom_tags_json),
        }
    else:
        today_journal = {
            "recorded": False,
            "local_date": today_local.isoformat(),
            "sleep_minutes": None,
            "activity_minutes": None,
            "mood": None,
            "symptom_tags": [],
        }

    recent_rows = db.scalars(
        select(JournalEntry)
        .where(JournalEntry.user_id == user.id)
        .order_by(desc(JournalEntry.local_date))
        .limit(5)
    ).all()
    recent_journals = [
        {
            "local_date": r.local_date.isoformat(),
            "sleep_minutes": r.sleep_minutes,
            "activity_minutes": r.activity_minutes,
            "mood": r.mood,
        }
        for r in recent_rows
    ]

    weekly_snapshot = compute_weekly_report(db, user, clock, week_start=current_monday)

    # Strictly public order - NEVER inferred from private journals
    articles = db.scalars(
        select(Article)
        .where(Article.status == "published")
        .order_by(desc(Article.published_at), desc(Article.id))
        .limit(4)
    ).all()
    recommended_articles = [
        {
            "id": a.id,
            "slug": a.slug,
            "title": a.title,
            "summary": a.summary,
            "category": a.category,
            "author_byline": a.author_byline,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a in articles
    ]

    blocked_ids = set(
        db.scalars(select(UserBlock.blocked_id).where(UserBlock.blocker_id == user.id)).all()
    )
    post_stmt = select(Post).where(Post.status == "visible")
    if blocked_ids:
        post_stmt = post_stmt.where(Post.author_id.not_in(blocked_ids))
    posts = list(
        db.scalars(post_stmt.order_by(desc(Post.created_at), desc(Post.id)).limit(4)).all()
    )
    author_map: dict[str, str] = {}
    if posts:
        author_rows = db.execute(
            select(User.id, User.nickname).where(User.id.in_({p.author_id for p in posts}))
        ).all()
        author_map = {uid: nick for uid, nick in author_rows}

    community_highlights = [
        {
            "id": p.id,
            "title": p.title,
            "category": p.category,
            "author_id": p.author_id,
            "author_nickname": author_map.get(p.author_id, ""),
            "created_at": p.created_at.isoformat(),
        }
        for p in posts
    ]

    unread_count = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_id == user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )

    return {
        "today_local": today_local.isoformat(),
        "plans_summary": plans_summary,
        "today_journal": today_journal,
        "recent_journals": recent_journals,
        "weekly_snapshot": weekly_snapshot,
        "recommended_articles": recommended_articles,
        "community_highlights": community_highlights,
        "unread_notifications_count": int(unread_count),
    }
