"""Agent Contract của Socratic Moderator: input/output cố định giữa Người 1 và Người 2."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ...enums import ModerationAction
from .socratic import SocraticSession


class ChatTurn(BaseModel):
    """Một lượt chat trong lịch sử hội thoại."""

    sender_id: UUID
    content: str = Field(min_length=1)
    timestamp: datetime | None = None


class RetrievedSource(BaseModel):
    """Một đoạn tài liệu môn học được RAG truy xuất."""

    source: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    score: float
    text: str | None = None
    source_hash: str | None = None
    page: int | None = None
    section: str | None = None
    embedding_model: str | None = None


class ModeratorInput(BaseModel):
    """Đầu vào của agent cho mỗi tin nhắn cần kiểm duyệt."""

    session_id: UUID
    message_id: UUID
    sender_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=1)
    conversation_history: list[ChatTurn] = Field(default_factory=list)
    room_topic: str = ""
    socratic_session: SocraticSession | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be blank")
        return stripped


class ModeratorOutput(BaseModel):
    """Quyết định kiểm duyệt của agent."""

    action: ModerationAction
    risk_score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    guidance: str | None = None
    needs_human_review: bool = False
    retrieved_sources: list[RetrievedSource] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_review_flag(self) -> "ModeratorOutput":
        if self.action == ModerationAction.ESCALATE and not self.needs_human_review:
            raise ValueError("ESCALATE requires needs_human_review to be True")
        return self
