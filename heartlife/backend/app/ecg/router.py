from __future__ import annotations

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.deps import get_clock, get_current_user, get_db, get_rate_limiter, get_settings
from app.core.errors import AppError
from app.core.security import LoginRateLimiter
from app.db.models import User
from app.ecg.client import EcgClient, get_ecg_client
from app.ecg.schemas import LinkRequest
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
