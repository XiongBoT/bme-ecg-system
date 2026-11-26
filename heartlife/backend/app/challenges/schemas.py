from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShareChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=300)
