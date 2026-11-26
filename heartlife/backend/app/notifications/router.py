from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.core.errors import AppError
from app.db.models import Challenge, Comment, Notification, Plan, Post, User

router = APIRouter(tags=["notifications"])

UNAVAILABLE_SUMMARY = "该内容当前不可查看"


def _is_target_available(db: Session, notif: Notification, current_user_id: str) -> bool:
    if notif.target_type == "post":
        post = db.get(Post, notif.target_id)
        return post is not None and post.status == "visible"
    if notif.target_type == "comment":
        comment = db.get(Comment, notif.target_id)
        if comment is None or comment.status != "visible":
            return False
        post = db.get(Post, comment.post_id)
        return post is not None and post.status == "visible"
    if notif.target_type == "plan":
        plan = db.get(Plan, notif.target_id)
        return plan is not None and plan.owner_id == current_user_id
    if notif.target_type == "challenge":
        chal = db.get(Challenge, notif.target_id)
        return chal is not None and chal.active
    return False


def _serialize_notification(notif: Notification, target_available: bool) -> dict:
    return {
        "id": notif.id,
        "type": notif.type,
        "target_type": notif.target_type,
        "target_id": notif.target_id,
        "target_available": target_available,
        "summary": notif.summary if target_available else UNAVAILABLE_SUMMARY,
        "is_read": notif.read_at is not None,
        "read_at": notif.read_at.isoformat() if notif.read_at is not None else None,
        "created_at": notif.created_at.isoformat(),
    }


@router.get("/me/notifications")
def api_list_notifications(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    unexpected = set(request.query_params.keys()) - {"limit"}
    if unexpected:
        raise AppError(422, "VALIDATION_ERROR", "包含不支持的查询参数")

    rows = db.scalars(
        select(Notification)
        .where(Notification.recipient_id == user.id)
        .order_by(desc(Notification.created_at), desc(Notification.id))
        .limit(limit)
    ).all()

    items = [
        _serialize_notification(n, _is_target_available(db, n, user.id))
        for n in rows
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
        "items": items,
        "unread_count": int(unread_count),
    }


@router.post("/me/notifications/read-all")
def api_mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    now = clock.now()
    result = db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()
    return {
        "updated_count": int(result.rowcount or 0),
        "unread_count": 0,
    }


@router.post("/me/notifications/{notif_id}/read")
def api_mark_notification_read(
    notif_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    notif = db.scalar(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.recipient_id == user.id,
        )
    )
    if notif is None:
        raise AppError(404, "NOT_FOUND", "通知不存在")

    if notif.read_at is None:
        notif.read_at = clock.now()
        db.commit()
        db.refresh(notif)

    available = _is_target_available(db, notif, user.id)
    return _serialize_notification(notif, available)
