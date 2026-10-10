import asyncio
import json
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from app.agents.moderator import ModeratorInput, ModeratorOutput, moderate_message
from app.agents.moderator import graph as graph_module
from app.agents.moderator.contract import ChatTurn, RetrievedSource
from app.agents.moderator.settings import ModeratorSettings
from app.enums import ModerationAction
from pydantic import ValidationError


def _input(**overrides: object) -> ModeratorInput:
    data: dict[str, object] = {
        "session_id": uuid4(),
        "message_id": uuid4(),
        "sender_id": uuid4(),
        "message": "  Bài 3 làm sao vậy?  ",
        "course_id": "course-id",
        "conversation_history": [{"sender_id": str(uuid4()), "content": "Chào bạn"}],
    }
    data.update(overrides)
    return ModeratorInput(**data)


def test_input_accepts_valid_payload_and_strips_message() -> None:
    payload = _input()

    assert payload.message == "Bài 3 làm sao vậy?"
    assert payload.conversation_history[0].timestamp is None


def test_input_defaults_history_to_empty() -> None:
    payload = ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(), message="hi", course_id="c")

    assert payload.conversation_history == []


@pytest.mark.parametrize("field", ["session_id", "message_id", "sender_id"])
def test_input_rejects_non_uuid_ids(field: str) -> None:
    with pytest.raises(ValidationError):
        _input(**{field: "not-a-uuid"})


def test_input_rejects_empty_course_id() -> None:
    with pytest.raises(ValidationError):
        _input(course_id="")


def test_input_rejects_message_over_2000_chars() -> None:
    with pytest.raises(ValidationError):
        _input(message="a" * 2001)


def test_ids_are_uuid_and_serialize_to_strings() -> None:
    payload = _input()

    assert isinstance(payload.session_id, UUID)
    assert json.loads(payload.model_dump_json())["session_id"] == str(payload.session_id)


def test_input_rejects_blank_message() -> None:
    with pytest.raises(ValidationError):
        _input(message="   ")


def test_chat_turn_accepts_timestamp() -> None:
    turn = ChatTurn(sender_id=uuid4(), content="hi", timestamp=datetime(2026, 1, 1))

    assert turn.timestamp is not None


def test_output_accepts_valid_payload() -> None:
    output = ModeratorOutput(
        action=ModerationAction.GUIDE,
        risk_score=0.4,
        reason="Cần gợi ý",
        guidance="Bạn đã thử bước đầu chưa?",
        retrieved_sources=[RetrievedSource(source="lecture1.pdf", chunk_id="c1", score=0.8)],
    )

    assert output.action is ModerationAction.GUIDE
    assert output.retrieved_sources[0].text is None
    assert output.needs_human_review is False


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_output_rejects_risk_score_out_of_range(score: float) -> None:
    with pytest.raises(ValidationError):
        ModeratorOutput(action=ModerationAction.ALLOW, risk_score=score, reason="x")


def test_output_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        ModeratorOutput(action="DELETE", risk_score=0.1, reason="x")


def test_escalate_requires_human_review() -> None:
    with pytest.raises(ValidationError):
        ModeratorOutput(action=ModerationAction.ESCALATE, risk_score=0.9, reason="x", needs_human_review=False)


def test_escalate_with_human_review_is_valid() -> None:
    output = ModeratorOutput(action=ModerationAction.ESCALATE, risk_score=0.9, reason="x", needs_human_review=True)

    assert output.needs_human_review is True


def test_moderate_message_stub_returns_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic: không phụ thuộc .env (LLM/retriever thật) của máy chạy test.
    monkeypatch.setattr(graph_module, "get_moderator_settings", lambda: ModeratorSettings(_env_file=None))
    graph_module._default_graph.cache_clear()
    output = asyncio.run(moderate_message(_input()))

    assert output.action is ModerationAction.ALLOW
    assert output.risk_score == 0.0
    assert output.needs_human_review is False
    assert output.guidance is None
    assert output.retrieved_sources == []
    graph_module._default_graph.cache_clear()
