from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import get_clock, get_current_user, get_db
from app.db.models import User
from app.journal.schemas import JournalUpsertRequest
from app.journal.service import (
    delete_user_journal,
    get_user_journal_by_date,
    list_user_journals,
    upsert_user_journal,
)

router = APIRouter(tags=["journal"])


@router.get("/me/journals")
def api_list_my_journals(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = list_user_journals(db, current_user, from_date=from_date, to_date=to_date)
    return {"items": items}


@router.get("/me/journals/{local_date}")
def api_get_my_journal(
    local_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return get_user_journal_by_date(db, current_user, local_date)


@router.put("/me/journals/{local_date}")
def api_put_my_journal(
    local_date: date,
    payload: JournalUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return upsert_user_journal(db, current_user, local_date, payload, clock)


@router.delete("/me/journals/{local_date}")
def api_delete_my_journal(
    local_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    delete_user_journal(db, current_user, local_date)
    return {"status": "deleted", "local_date": local_date.isoformat()}
