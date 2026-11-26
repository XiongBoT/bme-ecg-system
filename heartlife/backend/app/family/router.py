from __future__ import annotations

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.db.models import User
from app.family.schemas import (
    AcceptFamilyInviteRequest,
    CreateFamilyInviteRequest,
    UpdateFamilyGrantRequest,
)
from app.family.service import (
    accept_family_invite,
    create_family_invite,
    get_shared_family_summary,
    list_family_grants,
    revoke_family_grant,
    update_family_grant_scope,
)

router = APIRouter(tags=["family"])


@router.post("/me/family/invites", status_code=status.HTTP_201_CREATED)
def api_create_family_invite(
    payload: CreateFamilyInviteRequest = Body(default_factory=CreateFamilyInviteRequest),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return create_family_invite(db, user, payload, clock)


@router.post("/me/family/accept")
def api_accept_family_invite(
    payload: AcceptFamilyInviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return accept_family_invite(db, user, payload, clock)


@router.get("/me/family/grants")
def api_list_family_grants(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_family_grants(db, user)


@router.patch("/me/family/grants/{grant_id}")
def api_patch_family_grant(
    grant_id: str,
    payload: UpdateFamilyGrantRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return update_family_grant_scope(db, user, grant_id, payload, clock)


@router.delete("/me/family/grants/{grant_id}")
def api_delete_family_grant(
    grant_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return revoke_family_grant(db, user, grant_id, clock)


@router.get("/family/shared/{granter_id}")
def api_get_shared_family_summary(
    granter_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return get_shared_family_summary(db, user, granter_id, clock)
