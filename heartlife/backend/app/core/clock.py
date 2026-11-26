from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Clock(Protocol):
    def now(self) -> datetime:
        """Return timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    def __init__(self, initial: datetime | None = None) -> None:
        if initial is None:
            self._now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
        elif initial.tzinfo is None:
            self._now = initial.replace(tzinfo=timezone.utc)
        else:
            self._now = initial.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            self._now = dt.replace(tzinfo=timezone.utc)
        else:
            self._now = dt.astimezone(timezone.utc)

    def advance(self, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now


def validate_timezone_name(tz_name: str) -> str:
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f"Invalid timezone: {tz_name}") from exc
    return tz_name


def user_local_now(clock: Clock, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        tz = ZoneInfo("Asia/Shanghai")
    return clock.now().astimezone(tz)


def user_local_date(clock: Clock, tz_name: str) -> date:
    return user_local_now(clock, tz_name).date()
