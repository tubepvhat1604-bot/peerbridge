"""Bảo hiểm: conftest phải chặn mạng thật; và warmup/snippet/singleton của moderator."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from app.agents.moderator import ModeratorInput, moderate_message, warmup_moderator
from app.agents.moderator import graph as graph_module
from app.agents.moderator.contract import RetrievedSource
from app.agents.moderator.embedding import E5Embedder, get_e5_embedder
from app.agents.moderator.graph import SNIPPET_MAX_CHARS, _snippet, build_moderator_graph, run_moderator
from app.agents.moderator.llm import FakeLLM
from app.agents.moderator.nodes.choose_action import GUIDE_TEMPLATE
from app.agents.moderator.qdrant_retriever import get_client, make_client
from app.agents.moderator.retriever import FakeDocument, FakeRetriever
from app.agents.moderator.settings import ModeratorSettings, get_moderator_settings
from app.enums import ModerationAction


def _payload(message: str) -> ModeratorInput:
    return ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(), message=message, course_id="cs101")


def test_default_settings_are_fake_even_if_dotenv_says_otherwise() -> None:
    settings = get_moderator_settings()

    assert settings.llm_provider == "fake"
    assert settings.retriever_provider == "fake"
    assert not settings.effective_llm_api_key


def test_moderate_message_runs_offline() -> None:
    output = asyncio.run(moderate_message(_payload("Đệ quy là gì?")))

    assert output.action is ModerationAction.ALLOW


def test_real_http_transports_are_blocked() -> None:
    async def call() -> None:
        async with httpx.AsyncClient() as client:
            await client.get("http://example.invalid/")

    with pytest.raises(RuntimeError, match="không được phép"):
        asyncio.run(call())


def test_real_qdrant_connection_is_blocked_but_memory_is_allowed() -> None:
    with pytest.raises(RuntimeError, match="memory"):
        make_client("http://localhost:6333")
    assert make_client(":memory:") is not None


def test_real_sentence_transformer_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="không được phép"):
        E5Embedder("intfloat/multilingual-e5-large")._load()


def test_embedder_and_client_are_process_singletons() -> None:
    assert get_e5_embedder("m") is get_e5_embedder("m")
    assert get_e5_embedder("m") is not get_e5_embedder("other")
    assert get_client(":memory:") is get_client(":memory:")


def test_warmup_succeeds_offline_and_reports_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    assert asyncio.run(warmup_moderator()) is True

    def boom() -> None:
        raise RuntimeError("no graph")

    monkeypatch.setattr(graph_module, "_default_graph", boom)
    assert asyncio.run(warmup_moderator()) is False


def test_warmup_calls_retriever_warmup_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class WarmRetriever(FakeRetriever):
        def warmup(self) -> None:
            calls.append("warmup")

    monkeypatch.setattr(graph_module, "_default_retriever", lambda: WarmRetriever())

    assert asyncio.run(warmup_moderator()) is True
    assert calls == ["warmup"]


def test_output_sources_are_snippets_but_guidance_llm_sees_full_chunk() -> None:
    long_text = "đệ quy " + "chunk " * 200
    retriever = FakeRetriever([FakeDocument(course_id="cs101", source="a.md", chunk_id="a#0", text=long_text)])
    llm = FakeLLM(
        rule=lambda system, _user: (
            {"intent": "SOLUTION_REQUEST", "confidence": 0.9, "risk": 0.4}
            if "phân loại" in system
            else {"guidance": "Hàm đệ quy cần điều kiện dừng nào?"}
        )
    )
    graph = build_moderator_graph(llm, retriever, ModeratorSettings(_env_file=None))

    out = asyncio.run(run_moderator(graph, _payload("đệ quy giải hộ mình")))

    assert out.guidance != GUIDE_TEMPLATE
    assert len(out.retrieved_sources[0].text or "") <= SNIPPET_MAX_CHARS
    assert (out.retrieved_sources[0].text or "").endswith("…")
    assert long_text[:600] in llm.calls[1].user  # LLM nhận chunk đầy đủ (tối đa 700 ký tự), không phải snippet 300


def test_snippet_leaves_short_or_missing_text_untouched() -> None:
    short = RetrievedSource(source="a", chunk_id="a#0", score=1.0, text="ngắn")
    empty = RetrievedSource(source="a", chunk_id="a#0", score=1.0)

    assert _snippet(short) is short
    assert _snippet(empty) is empty
    exact = RetrievedSource(source="a", chunk_id="a#0", score=1.0, text="x" * SNIPPET_MAX_CHARS)
    assert _snippet(exact).text == exact.text
