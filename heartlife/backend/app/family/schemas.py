from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateFamilyInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_plan_summary: bool = True
    share_weekly_sleep: bool = False
    share_weekly_activity: bool = False


class AcceptFamilyInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str = Field(..., min_length=1, max_length=128)


class UpdateFamilyGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_plan_summary: bool | None = None
    share_weekly_sleep: bool | None = None
    share_weekly_activity: bool | None = None
