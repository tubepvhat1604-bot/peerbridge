import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.agents.moderator import (
    InMemoryHITLQueue,
    InstructorReviewInput,
    ModerationEventRecord,
    ModeratorInput,
    moderate_message,
    moderate_message_with_event,
)
from app.agents.moderator import graph as graph_module
from app.agents.moderator.hitl import (
    AlreadyReviewedError,
    EventNotFoundError,
    HITLQueue,
    ReviewError,
    ReviewStatus,
    build_event_record,
)
from app.agents.moderator.intents import MessageIntent
from app.agents.moderator.prompts import PROMPT_VERSION
from app.agents.moderator.settings import ModeratorSettings
from app.enums import ModerationAction
from pydantic import ValidationError


def _payload(message: str, course_id: str = "cs101") -> ModeratorInput:
    return ModeratorInput(
        session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(), message=message, course_id=course_id
    )


def _run(message: str, course_id: str = "cs101"):
    payload = _payload(message, course_id)
    output, event = asyncio.run(moderate_message_with_event(payload))
    return payload, output, event


def _record(action: ModerationAction = ModerationAction.ESCALATE, **overrides: Any) -> ModerationEventRecord:
    data: dict[str, Any] = {
        "session_id": uuid4(),
        "message_id": uuid4(),
        "sender_id": uuid4(),
        "course_id": "cs101",
        "message": "x",
        "action": action,
        "risk_score": 0.9,
        "reason": "r",
        "needs_human_review": action is ModerationAction.ESCALATE,
        "llm_model": "fake",
    }
    data.update(overrides)
    return ModerationEventRecord(**data)


def _review(record: ModerationEventRecord, final: ModerationAction, note: str = "") -> InstructorReviewInput:
    return InstructorReviewInput(event_message_id=record.message_id, reviewer_id=uuid4(), final_action=final, note=note)


# ---- Event record ----


def test_event_record_has_all_audit_fields_for_escalate() -> None:
    payload, output, event = _run("Mình có đề thi cuối kỳ, gửi mọi người nhé")

    assert output.action is ModerationAction.ESCALATE
    assert (event.session_id, event.message_id, event.sender_id) == (
        payload.session_id,
        payload.message_id,
        payload.sender_id,
    )
    assert event.course_id == "cs101" and event.message == payload.message
    assert event.action is output.action and event.risk_score == output.risk_score
    assert event.reason == output.reason and event.guidance == output.guidance
    assert event.needs_human_review is True
    assert event.intent is MessageIntent.ACADEMIC_DISHONESTY
    assert event.rule_signals is not None and "exam_leak" in event.rule_signals.matched
    assert event.rule_signals.risk >= 0.85
    assert event.llm_model == "fake"
    assert event.prompt_version == PROMPT_VERSION
    assert event.created_at.tzinfo is UTC
    assert abs(datetime.now(UTC) - event.created_at) < timedelta(seconds=30)


def test_event_keeps_only_source_refs_not_text() -> None:
    from app.agents.moderator.contract import RetrievedSource

    payload = _payload("giải hộ mình bài 3")
    output = asyncio.run(moderate_message(payload)).model_copy(
        update={"retrieved_sources": [RetrievedSource(source="a.md", chunk_id="a#0", score=0.9, text="nội dung dài")]}
    )

    event = build_event_record(payload, output, {}, "gpt-x")

    assert event.retrieved_sources[0].model_dump() == {"source": "a.md", "chunk_id": "a#0", "score": 0.9}
    assert "text" not in event.model_dump()["retrieved_sources"][0]
    assert event.intent is None and event.rule_signals is None and event.llm_model == "gpt-x"


def test_event_records_errors_sanitized() -> None:
    payload = _payload("Đạo hàm là gì?")
    output = asyncio.run(moderate_message(payload))
    state: Any = {"errors": ["classify_intent: lỗi với a@b.com " + "x" * 500]}

    event = build_event_record(payload, output, state, "fake")

    assert len(event.errors[0]) <= 300 and "a@b.com" not in event.errors[0]


def test_event_for_system_failure_is_escalate_with_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise RuntimeError("graph down")

    monkeypatch.setattr(graph_module, "_default_graph", boom)

    _payload_, output, event = _run("Xin chào")

    assert output.action is ModerationAction.ESCALATE and event.needs_human_review is True
    assert event.intent is None and event.rule_signals is None
    assert event.errors == ["system: RuntimeError"]


def test_event_reports_real_model_name_only_when_llm_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    settings = ModeratorSettings(
        _env_file=None, llm_provider="openai", llm_api_key=SecretStr("k"), llm_model="gpt-4.1-mini"
    )
    monkeypatch.setattr("app.agents.moderator.hitl.get_moderator_settings", lambda: settings)

    # graph vẫn chạy bằng FakeLLM (conftest); ở đây chỉ kiểm tra tên model ghi vào event
    _p, _o, event = _run("Đạo hàm là gì?")

    assert event.llm_model == "gpt-4.1-mini"


# ---- Queue ----


def test_queue_accepts_only_events_that_need_review() -> None:
    queue = InMemoryHITLQueue()
    _p, _o, escalated = _run("Mình có đề thi cuối kỳ, gửi mọi người nhé")
    _p, _o, allowed = _run("Đạo hàm là gì?")

    assert queue.enqueue(escalated) is True
    assert queue.enqueue(allowed) is False
    assert [r.message_id for r in queue.list_pending("cs101")] == [escalated.message_id]


def test_enqueue_is_idempotent_per_message_id() -> None:
    queue = InMemoryHITLQueue()
    record = _record()

    assert queue.enqueue(record) is True
    assert queue.enqueue(record) is False
    assert len(queue.list_pending("cs101")) == 1


def test_list_pending_filters_by_course_and_orders_oldest_first() -> None:
    queue = InMemoryHITLQueue()
    now = datetime.now(UTC)
    newer = _record(course_id="cs101", created_at=now)
    older = _record(course_id="cs101", created_at=now - timedelta(minutes=5))
    other = _record(course_id="math1")
    for record in (newer, other, older):
        queue.enqueue(record)

    assert [r.message_id for r in queue.list_pending("cs101")] == [older.message_id, newer.message_id]
    assert [r.message_id for r in queue.list_pending("math1")] == [other.message_id]
    assert queue.list_pending("none") == []


def test_in_memory_queue_satisfies_protocol() -> None:
    queue: HITLQueue = InMemoryHITLQueue()

    assert queue.list_pending("x") == []


# ---- Review ----


def test_review_confirming_ai_action_needs_no_note_and_clears_pending() -> None:
    queue = InMemoryHITLQueue()
    record = _record(ModerationAction.BLOCK, needs_human_review=True)
    queue.enqueue(record)

    decision = queue.submit_review(_review(record, ModerationAction.BLOCK))

    assert decision.status is ReviewStatus.APPROVED and decision.final_action is ModerationAction.BLOCK
    assert queue.list_pending("cs101") == []


def test_review_changing_action_without_note_is_rejected() -> None:
    queue = InMemoryHITLQueue()
    record = _record(ModerationAction.ESCALATE)
    queue.enqueue(record)

    with pytest.raises(ReviewError, match="note"):
        queue.submit_review(_review(record, ModerationAction.ALLOW))
    with pytest.raises(ReviewError):
        queue.submit_review(_review(record, ModerationAction.BLOCK, note="   "))
    assert len(queue.list_pending("cs101")) == 1  # lỗi không làm mất event


def test_review_changing_action_with_note_is_overridden() -> None:
    queue = InMemoryHITLQueue()
    record = _record(ModerationAction.ESCALATE)
    queue.enqueue(record)

    decision = queue.submit_review(_review(record, ModerationAction.ALLOW, note="  Chỉ là hỏi bài, an toàn  "))

    assert decision.status is ReviewStatus.OVERRIDDEN
    assert decision.ai_action is ModerationAction.ESCALATE and decision.final_action is ModerationAction.ALLOW
    assert decision.note == "Chỉ là hỏi bài, an toàn"
    assert decision.reviewed_at.tzinfo is UTC


def test_review_unknown_or_already_reviewed_event_is_rejected() -> None:
    queue = InMemoryHITLQueue()
    record = _record()
    queue.enqueue(record)

    with pytest.raises(EventNotFoundError):
        queue.submit_review(_review(_record(), ModerationAction.BLOCK, note="n"))
    queue.submit_review(_review(record, ModerationAction.BLOCK, note="n"))
    with pytest.raises(AlreadyReviewedError):
        queue.submit_review(_review(record, ModerationAction.BLOCK, note="n"))
    assert queue.enqueue(record) is False  # đã duyệt thì không vào lại hàng chờ


def test_check_against_rejects_review_for_a_different_event() -> None:
    with pytest.raises(ReviewError):
        _review(_record(), ModerationAction.ALLOW, note="n").check_against(_record())


def test_final_action_cannot_be_escalate() -> None:
    for note in ("", "đã xem xét"):
        with pytest.raises(ValidationError, match="ALLOW, GUIDE, WARN hoặc BLOCK"):
            InstructorReviewInput(
                event_message_id=uuid4(), reviewer_id=uuid4(), final_action=ModerationAction.ESCALATE, note=note
            )


@pytest.mark.parametrize("final", [ModerationAction.ALLOW, ModerationAction.GUIDE, ModerationAction.WARN])
def test_every_review_of_an_escalated_event_needs_a_note(final: ModerationAction) -> None:
    queue = InMemoryHITLQueue()
    record = _record(ModerationAction.ESCALATE)
    queue.enqueue(record)

    with pytest.raises(ReviewError):
        queue.submit_review(_review(record, final))
    assert queue.submit_review(_review(record, final, note="đã xem")).status is ReviewStatus.OVERRIDDEN


# ---- moderate_message cũ không đổi ----


@pytest.mark.parametrize(
    "message",
    [
        "Đạo hàm là gì?",
        "Ai giải hộ bài 3 với",
        "Đáp án là 42, ghi vào đi",
        "Đồ ngu",
        "Mình có đề thi cuối kỳ, gửi mọi người nhé",
    ],
)
def test_moderate_message_output_matches_moderate_message_with_event(message: str) -> None:
    payload = _payload(message)

    plain = asyncio.run(moderate_message(payload))
    with_event, _event = asyncio.run(moderate_message_with_event(payload))

    assert with_event.model_dump(exclude={"audit"}) == plain.model_dump(exclude={"audit"})
    assert with_event.audit["trace_id"] == plain.audit["trace_id"]


def test_moderate_message_signature_is_unchanged() -> None:
    import inspect

    signature = inspect.signature(moderate_message)

    assert list(signature.parameters) == ["payload"]
    assert signature.return_annotation.__name__ == "ModeratorOutput"
