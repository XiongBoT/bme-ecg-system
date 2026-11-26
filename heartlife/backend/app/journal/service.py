from __future__ import annotations

from datetime import date
import json
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock, user_local_date
from app.core.errors import AppError
from app.db.models import JournalEntry, User
from app.journal.schemas import JournalUpsertRequest


def serialize_journal(entry: JournalEntry) -> dict:
    try:
        tags = json.loads(entry.symptom_tags_json or "[]")
        if not isinstance(tags, list):
            tags = []
    except (ValueError, TypeError):
        tags = []

    return {
        "id": entry.id,
        "local_date": entry.local_date.isoformat(),
        "sleep_minutes": entry.sleep_minutes,
        "activity_minutes": entry.activity_minutes,
        "mood": entry.mood,
        "symptom_tags": tags,
        "note": entry.note,
        "is_demo": entry.is_demo,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def list_user_journals(
    db: Session,
    user: User,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict]:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(422, "INVALID_DATE_RANGE", "起始日期不能晚于结束日期")

    stmt = select(JournalEntry).where(JournalEntry.user_id == user.id)
    if from_date is not None:
        stmt = stmt.where(JournalEntry.local_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(JournalEntry.local_date <= to_date)
    stmt = stmt.order_by(desc(JournalEntry.local_date))

    entries = db.scalars(stmt).all()
    return [serialize_journal(entry) for entry in entries]


def get_user_journal_by_date(db: Session, user: User, local_date: date) -> dict:
    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.user_id == user.id,
            JournalEntry.local_date == local_date,
        )
    )
    if entry is None:
        raise AppError(404, "NOT_FOUND", "该日期尚未记录健康日记")
    return serialize_journal(entry)


def upsert_user_journal(
    db: Session,
    user: User,
    local_date: date,
    payload: JournalUpsertRequest,
    clock: Clock,
) -> dict:
    today_user_local = user_local_date(clock, user.timezone)
    if local_date > today_user_local:
        raise AppError(422, "FUTURE_DATE_FORBIDDEN", "不能记录未来日期的日记")

    now = clock.now()
    tags_json = json.dumps(payload.symptom_tags, ensure_ascii=False)

    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.user_id == user.id,
            JournalEntry.local_date == local_date,
        )
    )
    if entry is not None:
        entry.sleep_minutes = payload.sleep_minutes
        entry.activity_minutes = payload.activity_minutes
        entry.mood = payload.mood
        entry.symptom_tags_json = tags_json
        entry.note = payload.note
        entry.updated_at = now
        db.commit()
        db.refresh(entry)
        return serialize_journal(entry)

    entry = JournalEntry(
        user_id=user.id,
        local_date=local_date,
        sleep_minutes=payload.sleep_minutes,
        activity_minutes=payload.activity_minutes,
        mood=payload.mood,
        symptom_tags_json=tags_json,
        note=payload.note,
        is_demo=False,
        created_at=now,
        updated_at=now,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        entry = db.scalar(
            select(JournalEntry).where(
                JournalEntry.user_id == user.id,
                JournalEntry.local_date == local_date,
            )
        )
        if entry is None:
            raise
        entry.sleep_minutes = payload.sleep_minutes
        entry.activity_minutes = payload.activity_minutes
        entry.mood = payload.mood
        entry.symptom_tags_json = tags_json
        entry.note = payload.note
        entry.updated_at = now
        db.commit()

    db.refresh(entry)
    return serialize_journal(entry)


def delete_user_journal(db: Session, user: User, local_date: date) -> None:
    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.user_id == user.id,
            JournalEntry.local_date == local_date,
        )
    )
    if entry is None:
        raise AppError(404, "NOT_FOUND", "该日期尚未记录健康日记")
    db.delete(entry)
    db.commit()
