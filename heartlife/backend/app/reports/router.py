from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.core.errors import AppError
from app.db.models import User
from app.reports.service import compute_dashboard, compute_weekly_report

router = APIRouter(tags=["reports"])


def _forbid_extra_query_params(request: Request, allowed: set[str]) -> None:
    unexpected = set(request.query_params.keys()) - allowed
    if unexpected:
        raise AppError(422, "VALIDATION_ERROR", "包含不支持的查询参数")


@router.get("/me/dashboard")
def api_get_dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    _forbid_extra_query_params(request, set())
    return compute_dashboard(db, user, clock)


@router.get("/me/weekly-report")
def api_get_weekly_report(
    request: Request,
    week_start: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    _forbid_extra_query_params(request, {"week_start"})
    return compute_weekly_report(db, user, clock, week_start=week_start)
