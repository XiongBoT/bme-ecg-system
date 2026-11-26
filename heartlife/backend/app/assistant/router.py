from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.assistant.schemas import AssistantChatRequest
from app.assistant.service import handle_assistant_chat
from app.core.clock import Clock
from app.core.config import Settings
from app.core.deps import get_clock, get_current_user, get_db, get_settings
from app.db.models import User

router = APIRouter(tags=["assistant"])


@router.post("/assistant/chat")
def api_assistant_chat(
    payload: AssistantChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> dict:
    override_provider = getattr(request.app.state, "llm_provider", None)
    return handle_assistant_chat(
        db,
        current_user=current_user,
        payload=payload,
        settings=settings,
        clock=clock,
        override_provider=override_provider,
    )
