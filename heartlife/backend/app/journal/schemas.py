from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MoodLiteral = Literal["very_good", "good", "neutral", "bad", "very_bad"]


class JournalUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sleep_minutes: int | None = None
    activity_minutes: int | None = None
    mood: MoodLiteral | None = None
    symptom_tags: list[str] = Field(default_factory=list)
    note: str | None = None

    @field_validator("sleep_minutes", "activity_minutes", mode="before")
    @classmethod
    def _reject_bool_minutes(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("分钟数必须为整数")
        return v

    @field_validator("sleep_minutes", "activity_minutes")
    @classmethod
    def _validate_minutes_range(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 0 or v > 1440:
            raise ValueError("时长需在 0 到 1440 分钟之间")
        return v

    @field_validator("symptom_tags")
    @classmethod
    def _validate_symptom_tags(cls, v: list[str]) -> list[str]:
        if len(v) > 10:
            raise ValueError("感受标签最多填写 10 个")
        cleaned_list: list[str] = []
        seen: set[str] = set()
        for raw in v:
            if not isinstance(raw, str):
                raise ValueError("感受标签需为文本")
            cleaned = raw.strip()
            if len(cleaned) < 1 or len(cleaned) > 30:
                raise ValueError("单个感受标签长度需在 1 到 30 个字符之间")
            if cleaned not in seen:
                seen.add(cleaned)
                cleaned_list.append(cleaned)
        return cleaned_list

    @field_validator("note")
    @classmethod
    def _validate_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) > 1000:
            raise ValueError("备注长度不能超过 1000 个字符")
        return v

    @model_validator(mode="after")
    def _ensure_at_least_one_effective_field(self) -> JournalUpsertRequest:
        has_effective = (
            self.sleep_minutes is not None
            or self.activity_minutes is not None
            or self.mood is not None
            or len(self.symptom_tags) > 0
            or (self.note is not None and len(self.note.strip()) > 0)
        )
        if not has_effective:
            raise ValueError("请至少记录一项有效内容")
        return self
