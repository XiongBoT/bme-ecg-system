from __future__ import annotations

from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STANDARD_ARTICLE_CATEGORIES: list[str] = [
    "心脏基础知识",
    "设备与指标解读",
    "睡眠与休息",
    "运动与习惯",
    "日常健康",
    "日常记录方法",
    "就医与沟通",
    "隐私与安全",
]

FORBIDDEN_UNVERIFIED_REVIEW_TERMS = ("医生审核", "临床专家审核")


def validate_safe_http_url(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("来源链接不能为空")
    try:
        parsed = urlparse(cleaned)
    except ValueError as exc:
        raise ValueError("来源链接格式不合法") from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("来源链接仅允许 http 或 https 协议")
    if not parsed.hostname:
        raise ValueError("来源链接必须包含有效域名")
    return cleaned


class SourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=500)
    accessed_at: str | None = Field(default=None, max_length=32)

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("来源标题不能为空")
        return cleaned

    @field_validator("url")
    @classmethod
    def clean_url(cls, v: str) -> str:
        return validate_safe_http_url(v)

    @field_validator("accessed_at")
    @classmethod
    def clean_accessed_at(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(..., min_length=1, max_length=80)
    review_type: str = Field(..., min_length=1, max_length=64)
    reviewed_at: str = Field(..., min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=300)
    allow_clinical_label: bool = Field(default=False, exclude=True)

    @field_validator("reviewer", "review_type", "reviewed_at")
    @classmethod
    def clean_required_str(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("审核记录必填字段不能为空")
        return cleaned

    @field_validator("note")
    @classmethod
    def clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()

    @model_validator(mode="after")
    def check_honest_review_type(self) -> ReviewRecord:
        if not self.allow_clinical_label:
            for term in FORBIDDEN_UNVERIFIED_REVIEW_TERMS:
                if term in self.review_type:
                    raise ValueError("未经资质核验不得伪称医生审核或临床专家审核，请标明「课程内容审核」")
        return self


class CreateArticleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(default="", max_length=300)
    category: str = Field(..., min_length=1, max_length=64)
    body: str = Field(..., min_length=1, max_length=50000)
    slug: str | None = Field(default=None, max_length=80)
    author_byline: str = Field(default="HeartLife 科普团队", min_length=1, max_length=80)
    scope_note: str = Field(
        default="仅用于日常健康生活科普参考，不作为个体化临床诊断或用药建议。",
        min_length=1,
        max_length=300,
    )
    sources: list[SourceItem] = Field(default_factory=list, max_length=20)
    review_record: ReviewRecord | None = None

    @field_validator("title", "category", "body", "author_byline", "scope_note")
    @classmethod
    def clean_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("字段内容不能为空")
        return cleaned

    @field_validator("summary")
    @classmethod
    def clean_summary(cls, v: str) -> str:
        return v.strip()

    @field_validator("slug")
    @classmethod
    def clean_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class UpdateArticleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    body: str | None = Field(default=None, min_length=1, max_length=50000)
    author_byline: str | None = Field(default=None, min_length=1, max_length=80)
    scope_note: str | None = Field(default=None, min_length=1, max_length=300)
    sources: list[SourceItem] | None = Field(default=None, max_length=20)
    review_record: ReviewRecord | None = None

    @field_validator("title", "category", "body", "author_byline", "scope_note")
    @classmethod
    def clean_optional_non_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("字段内容不能为空")
        return cleaned

    @field_validator("summary")
    @classmethod
    def clean_optional_summary(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


class PublishArticleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceItem] | None = Field(default=None, max_length=20)
    review_record: ReviewRecord | None = None
