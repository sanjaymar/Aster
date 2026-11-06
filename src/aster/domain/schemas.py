from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeInput(Input):
    subject: str = Field(default="", max_length=200)
    terminology: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=6000)
    language: Literal["zh", "en"] = "zh"


class ProjectInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    domain: str = "research"
    knowledge: KnowledgeInput = Field(default_factory=KnowledgeInput)


class RecordInput(Input):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="note", max_length=80)
    content: str = Field(default="", max_length=200000)
    fields: dict = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)
    status: Literal["draft", "confirmed"] = "draft"
    asset_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("fields")
    @classmethod
    def valid_note_fields(cls, value):
        tags = value.get("tags", [])
        if (
            not isinstance(tags, list)
            or len(tags) > 12
            or any(not isinstance(t, str) or len(t) > 30 for t in tags)
        ):
            raise ValueError("最多12个标签，每个不超过30字符")
        related = value.get("related_record_ids", [])
        if (
            not isinstance(related, list)
            or len(related) > 30
            or any(not isinstance(i, str) for i in related)
        ):
            raise ValueError("最多关联30份文档")
        return value


class ExperimentInput(Input):
    asset_ids: list[str] = Field(default_factory=list, max_length=50)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=100000)
    fields: dict = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)


class ResultInput(Input):
    plan_version_id: str
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=200000)
    conditions: str = Field(default="", max_length=20000)
    fields: dict = Field(default_factory=dict)
    asset_ids: list[str] = Field(default_factory=list, max_length=50)


class RunInput(Input):
    prompt: str = Field(min_length=1, max_length=20000)
    mode: Literal["chat", "reading", "plan", "writing"] = "chat"
    conversation_id: str | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    source_version_ids: list[str] = Field(default_factory=list, max_length=10)
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    response_style: Literal["grounded", "discussion"] = "grounded"
    engine: Literal["pipeline", "harness", "assistant"] = "assistant"
    retrieval_scope: Literal["selected", "project"] = "selected"
    model_profile_id: str | None = Field(default=None, max_length=80)
    skill_id: str | None = Field(default=None, max_length=80)


class SourceInput(Input):
    title: str = Field(min_length=1, max_length=500)
    authors: str = Field(default="", max_length=10000)
    year: str = Field(default="", max_length=20)
    doi: str = Field(default="", max_length=300)


class ConversationInput(Input):
    title: str = Field(min_length=1, max_length=200)


class ResultEditInput(ResultInput):
    expected_revision: int = Field(ge=1)


class AnnotationCommentInput(Input):
    comment: str = Field(default="", max_length=10000)


class ModelInput(Input):
    base_url: str = Field(max_length=500)
    model: str = Field(default="auto", min_length=1, max_length=200)
    max_tokens: int = Field(default=2048, ge=128, le=8192)
    timeout: int = Field(default=180, ge=15, le=600)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        url = urlparse(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("请填写有效的 HTTP 模型地址，凭据通过环境变量配置")
        return value.rstrip("/")


class RetrievalInput(Input):
    query: str = Field(default="", max_length=2000)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    scope: Literal["selected", "project"] = "project"
    top_k: int = Field(default=8, ge=1, le=30)
    strategy: Literal["bm25", "dense", "hybrid"] = "hybrid"
    rerank: bool = True


class ReadingInput(Input):
    reading_status: Literal["unread", "reading", "read"] = "unread"
    starred: bool = False
    tags: list[str] = Field(default_factory=list, max_length=12)
    last_page: int = Field(default=1, ge=1, le=1000)
    last_scroll: float = Field(default=0, ge=0, le=1)
    last_version_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        if any(len(value.strip()) > 30 for value in values):
            raise ValueError("标签不能超过30个字符")
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class AnnotationInput(Input):
    source_span_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=5000)
    rectangles: list[tuple[float, float, float, float]] = Field(
        default_factory=list, max_length=128
    )

    @field_validator("rectangles")
    @classmethod
    def valid_rectangles(cls, values):
        if any(
            any(not 0 <= n <= 1 for n in rect) or rect[2] <= 0 or rect[3] <= 0 for rect in values
        ):
            raise ValueError("标注坐标无效")
        return values

    comment: str = Field(default="", max_length=10000)
