from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.db.models import User
from app.plans.schemas import CreatePlanRequest, UpdatePlanRequest
from app.plans.service import (
    create_user_plan,
    delete_plan_checkin,
    get_today_plans_view,
    list_plan_templates,
    list_user_plans,
    poll_and_emit_plan_reminders,
    update_user_plan,
    upsert_plan_checkin,
)

router = APIRouter(tags=["plans"])


@router.get("/plan-templates")
def api_get_plan_templates() -> dict:
    return {"items": list_plan_templates()}


@router.post("/me/plans", status_code=status.HTTP_201_CREATED)
def api_create_plan(
    payload: CreatePlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return create_user_plan(db, current_user, payload, clock)


@router.get("/me/plans")
def api_list_my_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return {"items": list_user_plans(db, current_user, clock)}


@router.patch("/me/plans/{plan_id}")
def api_patch_my_plan(
    plan_id: str,
    payload: UpdatePlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return update_user_plan(db, current_user, plan_id, payload, clock)


@router.get("/me/today")
def api_get_my_today(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    poll_and_emit_plan_reminders(db, current_user, clock)
    return get_today_plans_view(db, current_user, clock)


@router.post("/me/reminders/poll")
def api_poll_my_reminders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    generated = poll_and_emit_plan_reminders(db, current_user, clock)
    return {"generated": generated}


@router.put("/me/plans/{plan_id}/checkins/{local_date}")
def api_put_plan_checkin(
    plan_id: str,
    local_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return upsert_plan_checkin(db, current_user, plan_id, local_date, clock)


@router.delete("/me/plans/{plan_id}/checkins/{local_date}")
def api_delete_plan_checkin(
    plan_id: str,
    local_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return delete_plan_checkin(db, current_user, plan_id, local_date, clock)
