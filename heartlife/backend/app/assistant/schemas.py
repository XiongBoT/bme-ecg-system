from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=500)
    allow_weekly_report: bool = False
    allow_plans: bool = False

    @field_validator("query")
    @classmethod
    def clean_query(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 500:
            raise ValueError("提问内容长度需为 1–500 个字符")
        return cleaned
