from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., min_length=1, max_length=128)
    confirm_text: str = Field(..., min_length=1, max_length=32)
