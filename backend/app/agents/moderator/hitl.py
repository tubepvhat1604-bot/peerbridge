"""Interface HITL (Human-In-The-Loop) của moderator: DTO audit event, DTO review của giảng viên, hàng chờ.

Chỉ định nghĩa interface/DTO. Lưu DB (bảng MODERATION_EVENT / INSTRUCTOR_REVIEW) và API là việc của service layer.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ...enums import ModerationAction
from .contract import ModeratorInput, ModeratorOutput
from .graph import moderate_default_with_state
from .intents import MessageIntent
from .output_guard import sanitize_reason
from .prompts import PROMPT_VERSION
from .settings import ModeratorSettings, get_moderator_settings
from .state import ModeratorState


class SourceRef(BaseModel):
    """Tham chiếu tài liệu đã retrieve (không lưu text để event gọn và không nhân bản tài liệu)."""

    source: str
    chunk_id: str
    score: float


class RuleSignalsRecord(BaseModel):
    """Tín hiệu rule đã khớp (bản serializable của RuleSignals)."""

    intent: MessageIntent | None = None
    risk: float = 0.0
    matched: list[str] = Field(default_factory=list)
    hard: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)


class ModerationEventRecord(BaseModel):
    """Một lần kiểm duyệt để lưu audit vào MODERATION_EVENT. Khoá nghiệp vụ: message_id."""

    session_id: UUID
    message_id: UUID
    sender_id: UUID
    course_id: str
    message: str
    action: ModerationAction
    risk_score: float = Field(ge=0, le=1)
    reason: str
    intent: MessageIntent | None = None
    rule_signals: RuleSignalsRecord | None = None
    guidance: str | None = None
    retrieved_sources: list[SourceRef] = Field(default_factory=list)
    needs_human_review: bool = False
    errors: list[str] = Field(default_factory=list)
    llm_model: str
    prompt_version: str = PROMPT_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewError(ValueError):
    """Review của giảng viên không hợp lệ."""


class EventNotFoundError(KeyError):
    """Không có event chờ duyệt với message_id này."""


class AlreadyReviewedError(RuntimeError):
    """Event đã được duyệt, không duyệt lại."""


class InstructorReviewInput(BaseModel):
    """Quyết định của giảng viên cho một event. event_message_id = message_id của event."""

    event_message_id: UUID
    reviewer_id: UUID
    final_action: ModerationAction
    note: str = ""

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def final_action_must_be_decisive(self) -> "InstructorReviewInput":
        if self.final_action is ModerationAction.ESCALATE:
            raise ValueError("final_action của giảng viên chỉ được là ALLOW, GUIDE, WARN hoặc BLOCK")
        return self

    def check_against(self, record: ModerationEventRecord) -> None:
        """Đổi action so với AI đề xuất thì bắt buộc có note. Raise ReviewError nếu sai."""
        if record.message_id != self.event_message_id:
            raise ReviewError("review không thuộc event này")
        if self.final_action is not record.action and not self.note:
            raise ReviewError(f"cần note khi đổi action từ {record.action.value} sang {self.final_action.value}")


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"  # giảng viên giữ nguyên action AI đề xuất
    OVERRIDDEN = "OVERRIDDEN"  # giảng viên đổi action


class FinalDecision(BaseModel):
    """Trạng thái cuối của một event sau review; service layer dùng để lưu INSTRUCTOR_REVIEW và áp dụng."""

    message_id: UUID
    status: ReviewStatus
    ai_action: ModerationAction
    final_action: ModerationAction
    reviewer_id: UUID
    note: str
    reviewed_at: datetime


class HITLQueue(Protocol):
    """Hàng chờ giảng viên duyệt. Triển khai thật (DB) do service layer cung cấp."""

    def enqueue(self, record: ModerationEventRecord) -> bool:
        """Đưa event vào hàng chờ nếu needs_human_review; trả True nếu thực sự được thêm mới."""
        ...

    def list_pending(self, course_id: str) -> list[ModerationEventRecord]:
        """Event chờ duyệt của môn học, cũ nhất trước."""
        ...

    def submit_review(self, review: InstructorReviewInput) -> FinalDecision:
        """Ghi quyết định cuối. Raise EventNotFoundError / AlreadyReviewedError / ReviewError."""
        ...


class InMemoryHITLQueue:
    """Hàng chờ trong bộ nhớ cho test/demo."""

    def __init__(self) -> None:
        self._pending: dict[UUID, ModerationEventRecord] = {}
        self._decisions: dict[UUID, FinalDecision] = {}

    def enqueue(self, record: ModerationEventRecord) -> bool:
        """Chỉ nhận event needs_human_review; message_id trùng thì bỏ qua."""
        if not record.needs_human_review:
            return False
        if record.message_id in self._pending or record.message_id in self._decisions:
            return False
        self._pending[record.message_id] = record
        return True

    def list_pending(self, course_id: str) -> list[ModerationEventRecord]:
        """Event chưa duyệt của course_id, sắp theo created_at tăng dần."""
        items = [r for r in self._pending.values() if r.course_id == course_id]
        return sorted(items, key=lambda record: record.created_at)

    def submit_review(self, review: InstructorReviewInput) -> FinalDecision:
        """Kiểm tra review, bỏ event khỏi hàng chờ và trả FinalDecision."""
        if review.event_message_id in self._decisions:
            raise AlreadyReviewedError(str(review.event_message_id))
        record = self._pending.get(review.event_message_id)
        if record is None:
            raise EventNotFoundError(str(review.event_message_id))
        review.check_against(record)
        overridden = review.final_action is not record.action
        decision = FinalDecision(
            message_id=record.message_id,
            status=ReviewStatus.OVERRIDDEN if overridden else ReviewStatus.APPROVED,
            ai_action=record.action,
            final_action=review.final_action,
            reviewer_id=review.reviewer_id,
            note=review.note,
            reviewed_at=datetime.now(UTC),
        )
        del self._pending[record.message_id]
        self._decisions[record.message_id] = decision
        return decision


def _llm_model_name(settings: ModeratorSettings) -> str:
    """Tên model thực sự dùng; 'fake' nếu đang chạy FakeLLM (kể cả khi thiếu key)."""
    if settings.llm_provider == "fake" or not settings.effective_llm_api_key:
        return "fake"
    return settings.llm_model


def build_event_record(
    payload: ModeratorInput, output: ModeratorOutput, state: ModeratorState, llm_model: str
) -> ModerationEventRecord:
    """Dựng audit event từ input, output và state cuối của graph."""
    signals = state.get("rule_signals")
    return ModerationEventRecord(
        session_id=payload.session_id,
        message_id=payload.message_id,
        sender_id=payload.sender_id,
        course_id=payload.course_id,
        message=payload.message,
        action=output.action,
        risk_score=output.risk_score,
        reason=output.reason,
        intent=state.get("intent"),
        rule_signals=(
            RuleSignalsRecord(
                intent=signals.intent,
                risk=signals.risk,
                matched=list(signals.matched),
                hard=list(signals.hard),
                soft=list(signals.soft),
            )
            if signals
            else None
        ),
        guidance=output.guidance,
        retrieved_sources=[
            SourceRef(source=s.source, chunk_id=s.chunk_id, score=s.score) for s in output.retrieved_sources
        ],
        needs_human_review=output.needs_human_review,
        errors=[sanitize_reason(error) for error in state.get("errors", [])],
        llm_model=llm_model,
    )


async def moderate_message_with_event(payload: ModeratorInput) -> tuple[ModeratorOutput, ModerationEventRecord]:
    """Như moderate_message (cùng graph), kèm ModerationEventRecord để service layer lưu audit."""
    output, state = await moderate_default_with_state(payload)
    return output, build_event_record(payload, output, state, _llm_model_name(get_moderator_settings()))
