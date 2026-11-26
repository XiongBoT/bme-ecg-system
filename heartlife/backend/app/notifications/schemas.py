from __future__ import annotations

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: str
    type: str
    target_type: str
    target_id: str
    target_available: bool
    summary: str
    is_read: bool
    read_at: str | None
    created_at: str


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int
