from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

COMMUNITY_CATEGORIES: tuple[str, ...] = (
    "日常健康",
    "运动与习惯",
    "睡眠与休息",
    "心脏健康科普交流",
    "设备使用经验",
)

SAFETY_KEYWORDS: tuple[str, ...] = (
    "胸痛",
    "呼吸困难",
    "晕厥",
    "开什么药",
    "几毫克",
    "处方",
    "停药",
)

SAFETY_NOTICE_TEXT = (
    "社区交流不提供个体化诊疗或用药建议；如遇急性不适请立即拨打急救电话或前往正规医院就诊"
)

TargetBookmarkType = Literal["post", "article"]
TargetModerationType = Literal["post", "comment"]
ReportReasonType = Literal["harassment", "spam", "privacy", "misleading_medical", "other"]
ReportDecisionType = Literal["dismissed", "actioned"]


def _validate_and_dedup_tags(tags: list[str]) -> list[str]:
    if len(tags) > 5:
        raise ValueError("标签数量最多为 5 个")
    cleaned: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            raise ValueError("标签必须为字符串")
        t = raw.strip()
        if not t or len(t) > 20:
            raise ValueError("单个标签长度需为 1-20 个字符")
        cleaned.append(t)
    return list(dict.fromkeys(cleaned))


class CreatePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    category: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def check_title(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 80:
            raise ValueError("帖子标题长度需为 1-80 个字符")
        return cleaned

    @field_validator("body")
    @classmethod
    def check_body(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 3000:
            raise ValueError("帖子正文长度需为 1-3000 个字符")
        return cleaned

    @field_validator("category")
    @classmethod
    def check_category(cls, v: str) -> str:
        cleaned = v.strip()
        if cleaned not in COMMUNITY_CATEGORIES:
            raise ValueError("所选话题分类不在社区支持的分类列表中")
        return cleaned

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v: list[str]) -> list[str]:
        return _validate_and_dedup_tags(v)


class UpdatePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    body: str | None = None
    category: str | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def check_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 80:
            raise ValueError("帖子标题长度需为 1-80 个字符")
        return cleaned

    @field_validator("body")
    @classmethod
    def check_body(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 3000:
            raise ValueError("帖子正文长度需为 1-3000 个字符")
        return cleaned

    @field_validator("category")
    @classmethod
    def check_category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if cleaned not in COMMUNITY_CATEGORIES:
            raise ValueError("所选话题分类不在社区支持的分类列表中")
        return cleaned

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_and_dedup_tags(v)


class CreateCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    parent_id: str | None = None
    request_id: str | None = Field(default=None, max_length=64)

    @field_validator("body")
    @classmethod
    def check_body(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 500:
            raise ValueError("评论内容长度需为 1-500 个字符")
        return cleaned

    @field_validator("parent_id")
    @classmethod
    def check_parent_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None

    @field_validator("request_id")
    @classmethod
    def check_request_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if len(cleaned) > 64:
            raise ValueError("request_id 长度不能超过 64 个字符")
        return cleaned or None


class CreateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetModerationType
    target_id: str = Field(..., min_length=1, max_length=64)
    reason: ReportReasonType
    detail: str | None = Field(default="", max_length=500)

    @field_validator("target_id")
    @classmethod
    def check_target_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("举报目标 ID 不能为空")
        return cleaned

    @field_validator("detail")
    @classmethod
    def check_detail(cls, v: str | None) -> str:
        if v is None:
            return ""
        cleaned = v.strip()
        if len(cleaned) > 500:
            raise ValueError("补充说明长度不能超过 500 个字符")
        return cleaned


class ResolveReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReportDecisionType
    hide_target: bool = True
    reason: str

    @field_validator("reason")
    @classmethod
    def check_reason(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("处理说明长度需为 1-200 个字符")
        return cleaned


class ModerationReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str

    @field_validator("reason")
    @classmethod
    def check_reason(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("审核原因长度需为 1-200 个字符")
        return cleaned
