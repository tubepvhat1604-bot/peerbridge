"""Lọc trước + trần chi phí AI của moderator phòng học."""

import asyncio
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.agents.moderator.contract import ModeratorInput
from app.agents.moderator.graph import build_moderator_graph, run_moderator
from app.agents.moderator.llm import FakeLLM
from app.agents.moderator.openai_llm import OpenAICompatibleLLM, OpenAILLMConfig
from app.agents.moderator.prefilter import needs_llm
from app.agents.moderator.prompts import CLASSIFY_SYSTEM_PROMPT
from app.agents.moderator.retriever import FakeRetriever
from app.agents.moderator.rules import analyze_message
from app.agents.moderator.settings import ModeratorSettings
from app.agents.moderator.socratic import SocraticSession
from app.enums import ModerationAction
from pydantic import SecretStr

SETTINGS = ModeratorSettings(_env_file=None)


def _payload(message: str, socratic: SocraticSession | None = None) -> ModeratorInput:
    return ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(), message=message,
                          course_id="cs101", conversation_history=[], socratic_session=socratic)


def _llm(intent: str = "SOLUTION_REQUEST") -> FakeLLM:
    def rule(system: str, _user: str) -> dict[str, Any]:
        if system == CLASSIFY_SYSTEM_PROMPT:
            return {"intent": intent, "confidence": 0.9, "risk": 0.1, "reason": "fake"}
        return {"guidance": "Bạn thử nghĩ xem bước đầu tiên là gì?"}

    return FakeLLM(rule=rule)


def _run(llm: FakeLLM, message: str, settings: ModeratorSettings = SETTINGS, budget=None, socratic=None):
    graph = build_moderator_graph(llm, FakeRetriever(), settings, budget_left=budget)
    return asyncio.run(run_moderator(graph, _payload(message, socratic)))


@pytest.mark.parametrize("message", ["ok", "hihi", "Mai 8h tối học nhé", "Cảm ơn cậu nhiều", "oke luôn 👍", "để mai nhé"])
def test_small_talk_skips_llm(message: str) -> None:
    assert needs_llm(message, analyze_message(message)) is False


@pytest.mark.parametrize("message", [
    "Bài 3 làm sao vậy",
    "cho mình xin dap an",
    "x = 5 đúng không",
    "Giải thích JOIN giúp mình",
    "Câu này ra 42 hả?",
    "a" * 81,
    "dòng 1\ndòng 2",
    "copy cho mình đi",
    "đề thi hôm qua",
])
def test_study_or_risky_messages_still_use_llm(message: str) -> None:
    assert needs_llm(message, analyze_message(message)) is True


def test_rule_signal_or_active_socratic_session_always_uses_llm() -> None:
    assert needs_llm("ok", analyze_message("ok"), socratic_active=True) is True
    assert needs_llm("cheat", analyze_message("cheat")) is True


def test_prefiltered_message_is_allowed_without_llm_and_audited() -> None:
    llm = _llm("HARMFUL")

    output = _run(llm, "Mai 8h tối học nhé")

    assert output.action is ModerationAction.ALLOW
    assert llm.calls == []
    assert output.audit["prefiltered"] is True and output.audit["llm_calls_used"] == 0


def test_prefilter_can_be_turned_off() -> None:
    llm = _llm("SOCIAL")

    _run(llm, "Mai 8h tối học nhé", ModeratorSettings(_env_file=None, moderation_prefilter_enabled=False))

    assert len(llm.calls) == 1


def test_study_question_still_gets_socratic_guidance() -> None:
    llm = _llm("SOLUTION_REQUEST")

    output = _run(llm, "Giải bài 3 giúp mình")

    assert output.action is ModerationAction.GUIDE and output.guidance
    assert len(llm.calls) == 2


def test_budget_exhausted_uses_rules_only_and_never_escalates_by_default() -> None:
    llm = _llm("SOLUTION_REQUEST")

    output = _run(llm, "Giải thích JOIN giúp mình", budget=lambda: 0.0)

    assert llm.calls == []
    assert output.action is ModerationAction.ALLOW
    assert output.audit["ai_budget_exhausted"] is True


def test_budget_exhausted_still_applies_rules() -> None:
    llm = _llm()

    blocked = _run(llm, "Đồ ngu", budget=lambda: 0.0)
    guided = _run(llm, "Cho xin đáp án bài 3", budget=lambda: 0.0)

    assert blocked.action is ModerationAction.BLOCK
    assert guided.action is ModerationAction.GUIDE and guided.guidance  # template, không gọi LLM
    assert llm.calls == []


def test_budget_exhausted_inside_socratic_session_uses_template_guidance() -> None:
    llm = _llm()
    session = SocraticSession(active=True, session_id="1", sender_id="2", original_question="Bài 3 làm sao",
                              topic="SQL", turn_count=1, last_guidance="Bạn đã thử gì?")

    output = _run(llm, "mình chưa biết", budget=lambda: 0.0, socratic=session)

    assert output.action is ModerationAction.GUIDE and output.guidance
    assert llm.calls == []


def test_openai_client_reports_token_usage() -> None:
    seen: list[tuple[str, int, int]] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}],
                                         "usage": {"prompt_tokens": 120, "completion_tokens": 30}})

    llm = OpenAICompatibleLLM(OpenAILLMConfig(api_key=SecretStr("k"), model="gpt-4.1-mini"),
                              transport=httpx.MockTransport(handler), usage_hook=lambda *a: seen.append(a))

    assert asyncio.run(llm.complete_json("s", "u")) == {"ok": True}
    assert seen == [("gpt-4.1-mini", 120, 30)]


def test_usage_hook_failure_does_not_break_moderation() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": 1}"}}]})

    def broken(*_args):
        raise RuntimeError("db down")

    llm = OpenAICompatibleLLM(OpenAILLMConfig(api_key=SecretStr("k")), transport=httpx.MockTransport(handler),
                              usage_hook=broken)

    assert asyncio.run(llm.complete_json("s", "u")) == {"ok": 1}
