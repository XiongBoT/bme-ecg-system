from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=22, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ExchangeResult(BaseModel):
    grant_token: str = Field(min_length=22, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ecg_user_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ecg_username: str = Field(min_length=3, max_length=32)
    expires_at: float = Field(gt=0, allow_inf_nan=False)


class EcgUser(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    username: str = Field(min_length=3, max_length=32)


class RecordSummary(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    started_utc: str = Field(max_length=40)
    duration_s: float = Field(ge=0, allow_inf_nan=False)
    hr_mean: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TrendBucket(BaseModel):
    index: int = Field(ge=0, le=31)
    label: str = Field(max_length=32)
    records: int = Field(ge=0)
    duration_s: float = Field(ge=0, allow_inf_nan=False)
    hr_mean: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hr_records: int = Field(ge=0)


class Trends(BaseModel):
    period: Literal["day", "month", "year"]
    anchor: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    utc_offset_minutes: int = Field(ge=-720, le=840)
    buckets: list[TrendBucket] = Field(max_length=31)
    total_records: int = Field(ge=0)
    total_duration_s: float = Field(ge=0, allow_inf_nan=False)
    note: str = Field(max_length=500)


class SummaryResult(BaseModel):
    ecg_user: EcgUser
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    recent_records: list[RecordSummary] = Field(max_length=5)
    trends: Trends
