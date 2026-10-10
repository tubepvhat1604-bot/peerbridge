import asyncio
from typing import Any

from app.agents.moderator import ModeratorInput, ModeratorOutput
from app.enums import ModerationAction
from app.schemas import ModerationResult
from app.services.moderation_agent import (
    DEFAULT_COURSE_ID,
    LangGraphModerationAgent,
    MockModerationAgent,
    ModerationAgentProtocol,
    SocraticModeratorService,
    get_moderation_agent,
)


def test_mock_moderation_agent_returns_default_allow_result() -> None:
    agent = MockModerationAgent()

    result = asyncio.run(agent.moderate("session-1", "Can you help me reason this out?", {}))

    assert result.model_dump(mode="json") == {
        "action": "ALLOW",
        "risk_score": 0.0,
        "reason": "mock moderation",
        "guidance": None,
        "needs_human_review": False,
        "retrieved_sources": [],
        "audit": {},
    }
    assert isinstance(agent, ModerationAgentProtocol)
    assert isinstance(get_moderation_agent(), LangGraphModerationAgent)
    assert isinstance(get_moderation_agent(), ModerationAgentProtocol)


def test_langgraph_moderation_agent_invokes_moderator_contract_with_backend_context() -> None:
    calls: list[ModeratorInput] = []

    async def fake_moderate(payload: ModeratorInput) -> ModeratorOutput:
        calls.append(payload)
        return ModeratorOutput(
            action=ModerationAction.GUIDE,
            risk_score=0.45,
            reason="intent=SOLUTION_REQUEST, risk=0.45",
            guidance="Bạn đã thử hướng nào rồi?",
            needs_human_review=False,
        )

    agent = LangGraphModerationAgent(fake_moderate)

    result = asyncio.run(
        agent.moderate(
            session_id="7",
            message="  Cho mình xin đáp án bài 2  ",
            context={"message_id": 99, "sender_id": 42, "course_id": "cs101"},
        )
    )

    assert result == ModerationResult(
        action=ModerationAction.GUIDE,
        risk_score=0.45,
        reason="intent=SOLUTION_REQUEST, risk=0.45",
        guidance="Bạn đã thử hướng nào rồi?",
        needs_human_review=False,
    )
    assert len(calls) == 1
    assert calls[0].message == "Cho mình xin đáp án bài 2"
    assert calls[0].course_id == "cs101"
    assert str(calls[0].session_id) != "7"
    assert str(calls[0].message_id) != "99"
    assert str(calls[0].sender_id) != "42"


def test_langgraph_moderation_agent_defaults_course_id_for_study_room_context() -> None:
    calls: list[ModeratorInput] = []

    async def fake_moderate(payload: ModeratorInput) -> ModeratorOutput:
        calls.append(payload)
        return ModeratorOutput(action=ModerationAction.ALLOW, risk_score=0.0, reason="safe")

    agent = LangGraphModerationAgent(fake_moderate)

    result = asyncio.run(agent.moderate("session-1", "Đệ quy là gì?", {"message_id": 1, "sender_id": 2}))

    assert result.action is ModerationAction.ALLOW
    assert calls[0].course_id == DEFAULT_COURSE_ID


def test_default_agent_invokes_langgraph_moderator_entrypoint(monkeypatch: Any) -> None:
    calls: list[ModeratorInput] = []

    async def fake_moderate(payload: ModeratorInput) -> ModeratorOutput:
        calls.append(payload)
        return ModeratorOutput(action=ModerationAction.ALLOW, risk_score=0.0, reason="safe")

    monkeypatch.setattr("app.services.moderation_agent.moderate_message", fake_moderate)

    result = asyncio.run(
        get_moderation_agent().moderate(
            session_id="5",
            message="Đạo hàm là gì?",
            context={"message_id": 10, "sender_id": 12},
        )
    )

    assert result.action is ModerationAction.ALLOW
    assert len(calls) == 1
    assert calls[0].course_id == DEFAULT_COURSE_ID


class SwappedModerationAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: dict[str, Any],
    ) -> ModerationResult:
        self.calls.append({"session_id": session_id, "message": message, "context": context})
        return ModerationResult(
            action=ModerationAction.GUIDE,
            risk_score=0.4,
            reason="custom moderation",
            guidance="Ask a Socratic follow-up.",
            needs_human_review=False,
        )


def test_socratic_moderator_service_can_swap_agent_implementation() -> None:
    agent = SwappedModerationAgent()
    service = SocraticModeratorService(agent)

    result = asyncio.run(
        service.moderate(
            session_id="session-2",
            message="Give me the final answer.",
            context={"topic": "limits"},
        )
    )

    assert result.action is ModerationAction.GUIDE
    assert result.guidance == "Ask a Socratic follow-up."
    assert agent.calls == [
        {
            "session_id": "session-2",
            "message": "Give me the final answer.",
            "context": {"topic": "limits"},
        }
    ]
