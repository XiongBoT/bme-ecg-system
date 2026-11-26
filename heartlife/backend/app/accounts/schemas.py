from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.clock import validate_timezone_name

ACCOUNT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,31}$")


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    nickname: str = Field(..., min_length=1, max_length=32)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)

    @field_validator("account")
    @classmethod
    def check_account(cls, v: str) -> str:
        cleaned = v.strip()
        if not ACCOUNT_RE.match(cleaned):
            raise ValueError("账号需为 3-32 位字母、数字、下划线或连字符，且以字母或数字开头")
        return cleaned.lower()

    @field_validator("nickname")
    @classmethod
    def check_nickname(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 32:
            raise ValueError("昵称长度需为 1-32 个字符")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def check_tz(cls, v: str) -> str:
        return validate_timezone_name(v.strip())


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, min_length=1, max_length=32)
    bio: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("nickname")
    @classmethod
    def clean_nick(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("昵称不能为空")
        return cleaned

    @field_validator("bio")
    @classmethod
    def clean_bio(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()

    @field_validator("timezone")
    @classmethod
    def clean_tz(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_timezone_name(v.strip())
