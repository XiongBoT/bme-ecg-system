from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Notification


def create_notification_idempotent(
    db: Session,
    *,
    recipient_id: str,
    notif_type: str,
    target_type: str,
    target_id: str,
    summary: str,
    dedup_key: str,
    created_at: datetime,
    actor_id: str | None = None,
) -> Notification | None:
    """Create an in-app notification idempotently.
    Self-triggered comment/reply notifications are suppressed automatically.
    """
    if actor_id is not None and actor_id == recipient_id and notif_type in ("post_comment", "comment_reply"):
        return None

    existing = db.scalar(
        select(Notification).where(
            Notification.recipient_id == recipient_id,
            Notification.dedup_key == dedup_key,
        )
    )
    if existing is not None:
        return existing

    notif = Notification(
        recipient_id=recipient_id,
        type=notif_type,
        target_type=target_type,
        target_id=target_id,
        summary=summary[:200],
        dedup_key=dedup_key[:128],
        created_at=created_at,
    )
    try:
        with db.begin_nested():
            db.add(notif)
            db.flush()
        return notif
    except IntegrityError:
        return db.scalar(
            select(Notification).where(
                Notification.recipient_id == recipient_id,
                Notification.dedup_key == dedup_key,
            )
        )
