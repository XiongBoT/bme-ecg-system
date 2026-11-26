from __future__ import annotations

from datetime import date
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REMINDER_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _clean_weekdays(v: list[int]) -> list[int]:
    if not isinstance(v, list) or len(v) == 0:
        raise ValueError("请至少选择一个执行星期")
    cleaned: set[int] = set()
    for d in v:
        if isinstance(d, bool) or not isinstance(d, int) or d < 1 or d > 7:
            raise ValueError("星期范围需为 1（周一）至 7（周日）")
        cleaned.add(d)
    return sorted(cleaned)


def _clean_reminder_time(v: str | None) -> str | None:
    if v is None:
        return None
    cleaned = v.strip()
    if not REMINDER_TIME_RE.match(cleaned):
        raise ValueError("提醒时间格式需为 HH:MM（00:00-23:59）")
    return cleaned


class CreatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=100)
    template_key: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    reminder_enabled: bool = False
    reminder_time: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 1 or len(cleaned) > 80:
            raise ValueError("计划标题长度需在 1 到 80 个字符之间")
        return cleaned

    @field_validator("template_key")
    @classmethod
    def _validate_template_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, v: list[int]) -> list[int]:
        return _clean_weekdays(v)

    @field_validator("reminder_time")
    @classmethod
    def _validate_reminder(cls, v: str | None) -> str | None:
        return _clean_reminder_time(v)

    @model_validator(mode="after")
    def _validate_date_order(self) -> CreatePlanRequest:
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class UpdatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    weekdays: list[int] | None = None
    end_date: date | None = None
    active: bool | None = None
    reminder_enabled: bool | None = None
    reminder_time: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if len(cleaned) < 1 or len(cleaned) > 80:
            raise ValueError("计划标题长度需在 1 到 80 个字符之间")
        return cleaned

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        return _clean_weekdays(v)

    @field_validator("reminder_time")
    @classmethod
    def _validate_reminder(cls, v: str | None) -> str | None:
        return _clean_reminder_time(v)

    @model_validator(mode="after")
    def _forbid_null_non_nullable_fields(self) -> UpdatePlanRequest:
        for non_null_field in ("title", "weekdays", "active", "reminder_enabled"):
            if non_null_field in self.model_fields_set and getattr(self, non_null_field) is None:
                raise ValueError(f"{non_null_field} 不能为空")
        return self
