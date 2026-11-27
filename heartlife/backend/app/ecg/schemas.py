from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=22, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ExchangeResult(BaseModel):
    grant_token: str = Field(min_length=22, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ecg_user_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ecg_username: str = Field(min_length=3, max_length=32)
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    measurement_allowed: StrictBool = False


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
    measurement_allowed: StrictBool = False


class GrantResult(BaseModel):
    ecg_user: EcgUser
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    measurement_allowed: StrictBool = False


class DeviceSummary(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    label: str = Field(max_length=128)
    online: StrictBool
    ready: StrictBool
    reason: str = Field(max_length=160)


class DevicesResult(GrantResult):
    devices: list[DeviceSummary] = Field(max_length=1000)


class MeasurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    duration_s: Literal[60, 180, 300]
    request_key: str = Field(pattern=r"^[a-f0-9-]{32,36}$")


ReportState = Literal["not_started", "queued", "running", "completed", "failed", "ineligible"]


class ReportStatus(BaseModel):
    model: ReportState
    physiology: ReportState


class MeasurementSummary(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    device_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    duration_s: Literal[60, 180, 300]
    status: Literal["queued", "accepted", "recording", "uploading", "completed", "failed", "expired"]
    created_at: float = Field(ge=0, allow_inf_nan=False)
    expires_at: float = Field(ge=0, allow_inf_nan=False)
    updated_at: float = Field(ge=0, allow_inf_nan=False)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    message: str = Field(max_length=160)
    report: ReportStatus


class MeasurementsResult(GrantResult):
    measurements: list[MeasurementSummary] = Field(max_length=10)


class MeasurementResult(GrantResult):
    measurement: MeasurementSummary


class DailySummary(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    records: int = Field(ge=0)
    duration_s: float = Field(ge=0, allow_inf_nan=False)
    hr_mean: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hr_records: int = Field(ge=0)


class WeeklySummaryResult(GrantResult):
    week_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    week_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str = Field(min_length=1, max_length=128)
    observed_days: int = Field(ge=1, le=7)
    total_records: int = Field(ge=0)
    total_duration_s: float = Field(ge=0, allow_inf_nan=False)
    hr_mean: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hr_records: int = Field(ge=0)
    daily_series: list[DailySummary] = Field(min_length=7, max_length=7)
