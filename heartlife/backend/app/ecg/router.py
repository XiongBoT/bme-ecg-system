from __future__ import annotations

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.deps import get_clock, get_current_user, get_db, get_rate_limiter, get_settings
from app.core.errors import AppError
from app.core.security import LoginRateLimiter
from app.db.models import User
from app.ecg.client import EcgClient, get_ecg_client
from app.ecg.schemas import LinkRequest, MeasurementRequest
from app.ecg import service


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/me/ecg", tags=["ecg"], dependencies=[Depends(no_store)])


@router.get("/link")
def get_link(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock)) -> dict:
    return service.link_status(db, user.id, settings, clock)


@router.post("/link")
def create_link(payload: LinkRequest, user: User = Depends(get_current_user),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                clock: Clock = Depends(get_clock), upstream: EcgClient = Depends(get_ecg_client),
                limiter: LoginRateLimiter = Depends(get_rate_limiter)) -> dict:
    key = "ecg-link:" + user.id
    if not limiter.check_allowed(key, clock):
        raise AppError(429, "ECG_RATE_LIMITED", "绑定尝试较多，请稍后再试")
    limiter.record_failure(key, clock)
    result = service.bind(db, user.id, payload.code, settings, clock, upstream)
    limiter.reset(key)
    return result


@router.delete("/link")
def delete_link(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
                upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    return service.unlink(db, user.id, settings, clock, upstream)


@router.get("/summary")
def get_summary(period: Literal["day", "month", "year"], anchor: date = Query(),
                user: User = Depends(get_current_user), db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
                upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    return service.summary(db, user.id, period, anchor, settings, clock, upstream)


def _query(request: Request, allowed: set[str]) -> None:
    if set(request.query_params) - allowed:
        raise AppError(422, "VALIDATION_ERROR", "包含不支持的查询参数")
    if any(len(request.query_params.getlist(key)) > 1 for key in allowed):
        raise AppError(422, "VALIDATION_ERROR", "查询参数不能重复")


@router.get("/devices")
def get_devices(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
                upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    _query(request, set())
    return service.devices(db, user.id, settings, clock, upstream)


@router.get("/measurements")
def get_measurements(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
                     upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    _query(request, set())
    return service.measurements(db, user.id, settings, clock, upstream)


@router.post("/measurements", status_code=202)
def create_measurement(request: Request, payload: MeasurementRequest, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                       clock: Clock = Depends(get_clock), upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    _query(request, set())
    return service.create_measurement(db, user.id, payload, settings, clock, upstream)


@router.get("/weekly-summary")
def get_weekly_summary(request: Request, week_start: date | None = Query(default=None),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
                       upstream: EcgClient = Depends(get_ecg_client)) -> dict:
    _query(request, {"week_start"})
    return service.weekly_summary(db, user.id, week_start, settings, clock, upstream)
