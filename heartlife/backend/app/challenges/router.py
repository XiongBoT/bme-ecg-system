from __future__ import annotations

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.challenges.schemas import ShareChallengeRequest
from app.challenges.service import (
    get_my_challenges_and_badges,
    join_challenge_idempotent,
    leave_challenge,
    list_active_challenges,
    share_challenge_progress,
)
from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.db.models import User

router = APIRouter(tags=["challenges"])


@router.get("/challenges")
def api_list_challenges(db: Session = Depends(get_db)) -> dict:
    return {"items": list_active_challenges(db)}


@router.put("/challenges/{challenge_id}/membership")
def api_join_challenge(
    challenge_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return join_challenge_idempotent(db, user, challenge_id, clock)


@router.delete("/challenges/{challenge_id}/membership")
def api_leave_challenge(
    challenge_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return leave_challenge(db, user, challenge_id, clock)


@router.get("/me/challenges")
def api_my_challenges(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return get_my_challenges_and_badges(db, user, clock)


@router.post("/me/challenges/{challenge_id}/share", status_code=status.HTTP_201_CREATED)
def api_share_challenge(
    challenge_id: str,
    payload: ShareChallengeRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return share_challenge_progress(db, user, challenge_id, payload, clock)
