from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock, user_local_date, user_local_now
from app.core.errors import AppError
from app.db.models import Checkin, Notification, Plan, PlanVersion, User
from app.notifications.service import create_notification_idempotent
from app.plans.schemas import CreatePlanRequest, UpdatePlanRequest

PLAN_TEMPLATES: list[dict[str, object]] = [
    {
        "key": "sleep_log",
        "title": "每日记录睡眠",
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "suggested_reminder": "21:30",
    },
    {
        "key": "read_knowledge",
        "title": "阅读一篇健康科普",
        "weekdays": [1, 3, 5, 7],
        "suggested_reminder": "20:00",
    },
    {
        "key": "walk_habit",
        "title": "晚饭后温和散步",
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "suggested_reminder": "19:30",
    },
    {
        "key": "relax_breathing",
        "title": "睡前五分钟平缓呼吸",
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "suggested_reminder": "22:00",
    },
]


def weekdays_to_mask(weekdays: list[int]) -> int:
    if not weekdays:
        raise ValueError("weekdays cannot be empty")
    mask = 0
    for d in weekdays:
        if isinstance(d, bool) or not isinstance(d, int) or d < 1 or d > 7:
            raise ValueError(f"Invalid weekday: {d}")
        mask |= 1 << (d - 1)
    return mask


def mask_to_weekdays(mask: int) -> list[int]:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


def get_effective_version(versions: list[PlanVersion], target_date: date) -> PlanVersion | None:
    for v in sorted(versions, key=lambda item: item.version_num, reverse=True):
        if v.effective_from <= target_date and (v.effective_to is None or target_date <= v.effective_to):
            return v
    return None


def is_plan_due_on_date(versions: list[PlanVersion], target_date: date) -> bool:
    v = get_effective_version(versions, target_date)
    if v is None:
        return False
    if not v.active:
        return False
    if target_date < v.start_date:
        return False
    if v.end_date is not None and target_date > v.end_date:
        return False
    bit = 1 << (target_date.isoweekday() - 1)
    return bool(v.weekday_mask & bit)


def calculate_streak(
    due_dates_asc: list[date],
    completed_dates: set[date],
    today_local: date,
) -> int:
    streak = 0
    for d in reversed(due_dates_asc):
        if d > today_local:
            continue
        if d == today_local and d not in completed_dates:
            continue
        if d in completed_dates:
            streak += 1
        else:
            break
    return streak


def _compute_due_dates_up_to(versions: list[PlanVersion], today_local: date) -> list[date]:
    if not versions:
        return []
    earliest = min(max(v.effective_from, v.start_date) for v in versions)
    if earliest > today_local:
        return []
    due_dates: list[date] = []
    cursor = earliest
    one_day = timedelta(days=1)
    while cursor <= today_local:
        if is_plan_due_on_date(versions, cursor):
            due_dates.append(cursor)
        cursor += one_day
    return due_dates


def _load_plan_versions(db: Session, plan_id: str) -> list[PlanVersion]:
    return list(
        db.scalars(
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id)
            .order_by(PlanVersion.version_num.asc())
        ).all()
    )


def _load_completed_dates(db: Session, plan_id: str) -> set[date]:
    rows = db.scalars(
        select(Checkin.local_date).where(
            Checkin.plan_id == plan_id,
            Checkin.completed.is_(True),
        )
    ).all()
    return set(rows)


def serialize_plan(
    plan: Plan,
    versions: list[PlanVersion],
    completed_dates: set[date],
    today_local: date,
) -> dict:
    ordered_versions = sorted(versions, key=lambda v: v.version_num)
    latest = ordered_versions[-1]
    due_dates_asc = _compute_due_dates_up_to(ordered_versions, today_local)
    today_due = is_plan_due_on_date(ordered_versions, today_local)
    today_completed = today_local in completed_dates
    streak = calculate_streak(due_dates_asc, completed_dates, today_local)

    return {
        "id": plan.id,
        "plan_id": plan.id,
        "title": plan.title,
        "template_key": plan.template_key,
        "active": plan.active,
        "weekdays": mask_to_weekdays(latest.weekday_mask),
        "start_date": latest.start_date.isoformat(),
        "end_date": latest.end_date.isoformat() if latest.end_date else None,
        "reminder_enabled": plan.reminder_enabled,
        "reminder_time": plan.reminder_time,
        "version_num": latest.version_num,
        "today_due": today_due,
        "today_completed": today_completed,
        "completed": today_completed,
        "streak": streak,
        "total_completed": len(completed_dates),
        "is_demo": plan.is_demo,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }


def list_plan_templates() -> list[dict[str, object]]:
    return [dict(item) for item in PLAN_TEMPLATES]


def create_user_plan(
    db: Session,
    user: User,
    payload: CreatePlanRequest,
    clock: Clock,
) -> dict:
    today_local = user_local_date(clock, user.timezone)
    eff_start = payload.start_date or today_local
    if payload.end_date is not None and payload.end_date < eff_start:
        raise AppError(422, "INVALID_DATE_RANGE", "结束日期不能早于开始日期")

    now = clock.now()
    mask = weekdays_to_mask(payload.weekdays)

    plan = Plan(
        owner_id=user.id,
        title=payload.title,
        template_key=payload.template_key,
        active=True,
        reminder_enabled=payload.reminder_enabled,
        reminder_time=payload.reminder_time,
        is_demo=False,
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.flush()

    version = PlanVersion(
        plan_id=plan.id,
        version_num=1,
        effective_from=min(eff_start, today_local),
        effective_to=None,
        weekday_mask=mask,
        active=True,
        start_date=eff_start,
        end_date=payload.end_date,
        reminder_time=payload.reminder_time,
        created_at=now,
    )
    db.add(version)
    db.commit()
    db.refresh(plan)
    db.refresh(version)

    return serialize_plan(plan, [version], set(), today_local)


def _get_owned_plan(db: Session, user: User, plan_id: str) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.id == plan_id, Plan.owner_id == user.id))
    if plan is None:
        raise AppError(404, "NOT_FOUND", "计划不存在")
    return plan


def update_user_plan(
    db: Session,
    user: User,
    plan_id: str,
    payload: UpdatePlanRequest,
    clock: Clock,
) -> dict:
    plan = _get_owned_plan(db, user, plan_id)
    versions = _load_plan_versions(db, plan.id)
    if not versions:
        raise AppError(404, "NOT_FOUND", "计划版本不存在")

    today_local = user_local_date(clock, user.timezone)
    next_day = today_local + timedelta(days=1)
    now = clock.now()
    fields_set = payload.model_fields_set

    latest = versions[-1]
    new_mask = weekdays_to_mask(payload.weekdays) if "weekdays" in fields_set and payload.weekdays else latest.weekday_mask
    new_end_date = payload.end_date if "end_date" in fields_set else latest.end_date
    new_active = payload.active if "active" in fields_set and payload.active is not None else plan.active
    new_reminder_time = payload.reminder_time if "reminder_time" in fields_set else plan.reminder_time

    if new_end_date is not None and new_end_date < latest.start_date:
        raise AppError(422, "INVALID_DATE_RANGE", "结束日期不能早于计划开始日期")

    if "title" in fields_set and payload.title is not None:
        plan.title = payload.title
    if "active" in fields_set and payload.active is not None:
        plan.active = payload.active
    if "reminder_enabled" in fields_set and payload.reminder_enabled is not None:
        plan.reminder_enabled = payload.reminder_enabled
    if "reminder_time" in fields_set:
        plan.reminder_time = payload.reminder_time
    plan.updated_at = now

    version_fields = {"weekdays", "end_date", "active", "reminder_time"}
    if fields_set & version_fields:
        future_ver = next((v for v in versions if v.effective_from == next_day), None)
        if future_ver is not None:
            future_ver.weekday_mask = new_mask
            future_ver.active = new_active
            future_ver.end_date = new_end_date
            future_ver.reminder_time = new_reminder_time
        else:
            open_ver = next((v for v in reversed(versions) if v.effective_to is None), latest)
            if open_ver.effective_from <= today_local:
                open_ver.effective_to = today_local
                new_ver = PlanVersion(
                    plan_id=plan.id,
                    version_num=latest.version_num + 1,
                    effective_from=next_day,
                    effective_to=None,
                    weekday_mask=new_mask,
                    active=new_active,
                    start_date=open_ver.start_date,
                    end_date=new_end_date,
                    reminder_time=new_reminder_time,
                    created_at=now,
                )
                db.add(new_ver)
                versions.append(new_ver)
            else:
                open_ver.weekday_mask = new_mask
                open_ver.active = new_active
                open_ver.end_date = new_end_date
                open_ver.reminder_time = new_reminder_time

    db.commit()
    db.refresh(plan)
    refreshed_versions = _load_plan_versions(db, plan.id)
    completed_dates = _load_completed_dates(db, plan.id)
    return serialize_plan(plan, refreshed_versions, completed_dates, today_local)


def list_user_plans(db: Session, user: User, clock: Clock) -> list[dict]:
    today_local = user_local_date(clock, user.timezone)
    plans = db.scalars(
        select(Plan)
        .where(Plan.owner_id == user.id)
        .order_by(Plan.created_at.asc(), Plan.id.asc())
    ).all()
    if not plans:
        return []

    plan_ids = [p.id for p in plans]
    all_versions = db.scalars(
        select(PlanVersion)
        .where(PlanVersion.plan_id.in_(plan_ids))
        .order_by(PlanVersion.version_num.asc())
    ).all()
    versions_by_plan: dict[str, list[PlanVersion]] = {pid: [] for pid in plan_ids}
    for v in all_versions:
        versions_by_plan[v.plan_id].append(v)

    all_checkins = db.execute(
        select(Checkin.plan_id, Checkin.local_date).where(
            Checkin.plan_id.in_(plan_ids),
            Checkin.completed.is_(True),
        )
    ).all()
    completed_by_plan: dict[str, set[date]] = {pid: set() for pid in plan_ids}
    for pid, c_date in all_checkins:
        completed_by_plan[pid].add(c_date)

    return [
        serialize_plan(p, versions_by_plan[p.id], completed_by_plan[p.id], today_local)
        for p in plans
        if versions_by_plan[p.id]
    ]


def poll_and_emit_plan_reminders(db: Session, user: User, clock: Clock) -> int:
    now_local = user_local_now(clock, user.timezone)
    today_d = now_local.date()
    hhmm = now_local.strftime("%H:%M")

    candidate_plans = db.scalars(
        select(Plan).where(
            Plan.owner_id == user.id,
            Plan.active.is_(True),
            Plan.reminder_enabled.is_(True),
            Plan.reminder_time.is_not(None),
        )
    ).all()
    if not candidate_plans:
        return 0

    generated = 0
    now_utc = clock.now()
    for plan in candidate_plans:
        if plan.reminder_time is None or hhmm < plan.reminder_time:
            continue

        versions = _load_plan_versions(db, plan.id)
        if not is_plan_due_on_date(versions, today_d):
            continue

        done_today = db.scalar(
            select(Checkin.id).where(
                Checkin.plan_id == plan.id,
                Checkin.local_date == today_d,
                Checkin.completed.is_(True),
            )
        )
        if done_today is not None:
            continue

        dedup_key = f"plan_reminder:{plan.id}:{today_d.isoformat()}"
        existing_notif = db.scalar(
            select(Notification.id).where(
                Notification.recipient_id == user.id,
                Notification.dedup_key == dedup_key,
            )
        )
        if existing_notif is not None:
            continue

        notif = create_notification_idempotent(
            db,
            recipient_id=user.id,
            notif_type="plan_reminder",
            target_type="plan",
            target_id=plan.id,
            summary=f"今日计划待完成：{plan.title}",
            dedup_key=dedup_key,
            created_at=now_utc,
        )
        if notif is not None:
            generated += 1

    if generated > 0:
        db.commit()
    return generated


def get_today_plans_view(db: Session, user: User, clock: Clock) -> dict:
    today_local = user_local_date(clock, user.timezone)
    all_plans = list_user_plans(db, user, clock)
    due_items = [item for item in all_plans if item["today_due"]]
    due_count = len(due_items)
    completed_count = sum(1 for item in due_items if item["today_completed"])
    return {
        "date": today_local.isoformat(),
        "due_count": due_count,
        "completed_count": completed_count,
        "items": due_items,
    }


def upsert_plan_checkin(
    db: Session,
    user: User,
    plan_id: str,
    local_date: date,
    clock: Clock,
) -> dict:
    plan = _get_owned_plan(db, user, plan_id)
    today_local = user_local_date(clock, user.timezone)
    if local_date > today_local:
        raise AppError(422, "FUTURE_DATE_FORBIDDEN", "不能对未来日期打卡")

    versions = _load_plan_versions(db, plan.id)
    if not is_plan_due_on_date(versions, local_date):
        raise AppError(422, "DATE_NOT_DUE", "该日期不在计划排期内，无法打卡")

    now = clock.now()
    existing = db.scalar(
        select(Checkin).where(
            Checkin.plan_id == plan.id,
            Checkin.local_date == local_date,
        )
    )
    if existing is not None:
        if not existing.completed:
            existing.completed = True
            existing.updated_at = now
            db.commit()
    else:
        checkin = Checkin(
            plan_id=plan.id,
            local_date=local_date,
            completed=True,
            updated_at=now,
        )
        db.add(checkin)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raced = db.scalar(
                select(Checkin).where(
                    Checkin.plan_id == plan.id,
                    Checkin.local_date == local_date,
                )
            )
            if raced is not None and not raced.completed:
                raced.completed = True
                raced.updated_at = now
                db.commit()

    completed_dates = _load_completed_dates(db, plan.id)
    plan_data = serialize_plan(plan, versions, completed_dates, today_local)
    return {
        "plan_id": plan.id,
        "local_date": local_date.isoformat(),
        "completed": True,
        "streak": plan_data["streak"],
        "total_completed": plan_data["total_completed"],
        "today_due": plan_data["today_due"],
        "today_completed": plan_data["today_completed"],
        "plan": plan_data,
    }


def delete_plan_checkin(
    db: Session,
    user: User,
    plan_id: str,
    local_date: date,
    clock: Clock,
) -> dict:
    plan = _get_owned_plan(db, user, plan_id)
    today_local = user_local_date(clock, user.timezone)
    versions = _load_plan_versions(db, plan.id)

    existing = db.scalar(
        select(Checkin).where(
            Checkin.plan_id == plan.id,
            Checkin.local_date == local_date,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.commit()

    completed_dates = _load_completed_dates(db, plan.id)
    plan_data = serialize_plan(plan, versions, completed_dates, today_local)
    return {
        "plan_id": plan.id,
        "local_date": local_date.isoformat(),
        "completed": False,
        "streak": plan_data["streak"],
        "total_completed": plan_data["total_completed"],
        "today_due": plan_data["today_due"],
        "today_completed": plan_data["today_completed"],
        "plan": plan_data,
    }
