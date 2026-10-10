import asyncio
from typing import Any

import pytest
from app.agents.moderator.llm import FakeLLM, LLMClient
from app.agents.moderator.retriever import FakeDocument, FakeRetriever, Retriever
from app.agents.moderator.settings import ModeratorSettings


def _docs() -> list[FakeDocument]:
    return [
        FakeDocument(course_id="cs101", source="w1.pdf", chunk_id="a", text="Binary search halves the array"),
        FakeDocument(course_id="cs101", source="w2.pdf", chunk_id="b", text="Sorting arrays with quicksort"),
        FakeDocument(course_id="cs101", source="w3.pdf", chunk_id="c", text="Graph traversal with BFS"),
        FakeDocument(course_id="math1", source="m1.pdf", chunk_id="d", text="Binary search proof by induction"),
    ]


def test_fake_llm_returns_scripted_responses_in_order_and_records_calls() -> None:
    llm = FakeLLM(responses=[{"a": 1}, {"b": 2}])

    first = asyncio.run(llm.complete_json("sys1", "user1"))
    second = asyncio.run(llm.complete_json("sys2", "user2"))

    assert (first, second) == ({"a": 1}, {"b": 2})
    assert [(c.system, c.user) for c in llm.calls] == [("sys1", "user1"), ("sys2", "user2")]


def test_fake_llm_raises_when_script_exhausted() -> None:
    llm = FakeLLM(responses=[])

    with pytest.raises(RuntimeError):
        asyncio.run(llm.complete_json("s", "u"))
    assert len(llm.calls) == 1


def test_fake_llm_uses_rule_function() -> None:
    def rule(system: str, user: str) -> dict[str, Any]:
        return {"echo": user.upper()}

    llm = FakeLLM(rule=rule)

    assert asyncio.run(llm.complete_json("s", "hi")) == {"echo": "HI"}
    assert llm.calls[0].user == "hi"


def test_fake_llm_rejects_responses_and_rule_together() -> None:
    with pytest.raises(ValueError):
        FakeLLM(responses=[{}], rule=lambda s, u: {})


def test_fake_llm_satisfies_protocol() -> None:
    client: LLMClient = FakeLLM(responses=[])

    assert client is not None


def test_fake_retriever_filters_by_course_and_ranks_by_keyword_overlap() -> None:
    retriever: Retriever = FakeRetriever(_docs())

    results = asyncio.run(retriever.search("binary array sorting", "cs101", top_k=5))

    assert [r.chunk_id for r in results] == ["a", "b"]
    assert results[0].score > results[1].score
    assert results[0].text is not None


def test_fake_retriever_respects_top_k() -> None:
    retriever = FakeRetriever(_docs())

    results = asyncio.run(retriever.search("binary search array sorting", "cs101", top_k=1))

    assert len(results) == 1


def test_fake_retriever_returns_empty_for_unknown_course_or_no_match() -> None:
    retriever = FakeRetriever(_docs())

    assert asyncio.run(retriever.search("binary", "other", top_k=3)) == []
    assert asyncio.run(retriever.search("zzz", "cs101", top_k=3)) == []
    assert asyncio.run(retriever.search("binary", "cs101", top_k=0)) == []


def test_fake_retriever_add_document() -> None:
    retriever = FakeRetriever()
    retriever.add_document(FakeDocument(course_id="c", source="s", chunk_id="x", text="hello world"))

    assert [r.chunk_id for r in asyncio.run(retriever.search("hello", "c", top_k=3))] == ["x"]


def test_settings_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("QDRANT_URL", "EMBEDDING_MODEL", "RISK_ESCALATE_THRESHOLD", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    defaults = ModeratorSettings(_env_file=None)

    assert defaults.qdrant_url == "http://localhost:6333"
    assert defaults.llm_provider == "fake"

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("RISK_ESCALATE_THRESHOLD", "0.6")

    overridden = ModeratorSettings(_env_file=None)
    assert overridden.llm_provider == "openai"
    assert overridden.risk_escalate_threshold == 0.6


def test_settings_reject_invalid_provider_and_threshold() -> None:
    with pytest.raises(ValueError):
        ModeratorSettings(_env_file=None, llm_provider="gemini")
    with pytest.raises(ValueError):
        ModeratorSettings(_env_file=None, risk_escalate_threshold=1.5)


def test_settings_ignore_unrelated_env_file_keys(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER")  # conftest đặt fake; ở đây cần kiểm tra đọc từ env_file
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=x\nJWT_SECRET=y\nLLM_PROVIDER=openai\n", encoding="utf-8")

    settings = ModeratorSettings(_env_file=env_file)

    assert settings.llm_provider == "openai"
