import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.agents.moderator.contract import ModeratorInput, RetrievedSource
from app.agents.moderator.graph import _build_retriever, build_moderator_graph, run_moderator
from app.agents.moderator.llm import FakeLLM
from app.agents.moderator.local_retriever import LocalRetriever, tokenize
from app.agents.moderator.nodes.retrieve_context import retrieve_context
from app.agents.moderator.prompts import CLASSIFY_SYSTEM_PROMPT, source_label
from app.agents.moderator.settings import ModeratorSettings
from app.enums import ModerationAction

AICB_DIR = Path(__file__).resolve().parents[1] / "data" / "courses"

SLIDES = """# RAG Pipeline

<!-- page:1 -->
Mục Tiêu Ngày 8
Giải thích được RAG như một pipeline gồm indexing, retrieval, re-ranking và generation

<!-- page:5 -->
Chunking tệ: cắt giữa một bảng hoặc điều khoản, chunk quá to chứa nhiều ý làm retrieval kém

<!-- page:12 -->
Reranking: chấm lại top-k bằng cross-encoder để đưa đoạn đúng lên đầu trước khi generation
"""


def _corpus(tmp_path: Path) -> Path:
    course = tmp_path / "aicb"
    course.mkdir()
    (course / "RAG Pipeline.md").write_text(SLIDES, encoding="utf-8")
    (course / "Guardrails.md").write_text(
        "# Guardrails\n\n<!-- page:3 -->\nPrompt injection: kẻ tấn công chèn lệnh vào dữ liệu đầu vào\n", encoding="utf-8")
    return tmp_path


def _search(retriever: LocalRetriever, query: str, course: str = "aicb", top_k: int = 3) -> list[RetrievedSource]:
    return asyncio.run(retriever.search(query, course, top_k))


def test_tokenize_drops_diacritics_and_function_words() -> None:
    assert tokenize("Rerank để làm gì?") == tokenize("rerank de lam gi") == ["rerank"]


def test_finds_matching_slide_with_page_number(tmp_path: Path) -> None:
    results = _search(LocalRetriever(_corpus(tmp_path)), "reranking cross-encoder la gi")

    assert results[0].source == "RAG Pipeline.md"
    assert results[0].page == 12
    assert 0 < results[0].score <= 1


def test_query_without_diacritics_matches(tmp_path: Path) -> None:
    results = _search(LocalRetriever(_corpus(tmp_path)), "chunk qua to thi sao")

    assert results and results[0].page == 5


def test_overview_slide_ranks_below_content_slide(tmp_path: Path) -> None:
    results = _search(LocalRetriever(_corpus(tmp_path), min_score=0), "retrieval reranking generation")

    assert results[0].page == 12


def test_unrelated_query_and_unknown_course_return_nothing(tmp_path: Path) -> None:
    retriever = LocalRetriever(_corpus(tmp_path))

    assert _search(retriever, "bánh mì phô mai") == []
    assert _search(retriever, "reranking", course="cs101") == []
    assert _search(retriever, "reranking", course="../aicb") == []
    assert _search(retriever, "reranking", top_k=0) == []


def test_source_label_uses_lesson_title_and_slide() -> None:
    source = RetrievedSource(source="RAG Pipeline - Truy xuất.md", chunk_id="x#1", score=1, page=12)

    assert source_label(source) == "bài RAG Pipeline - Truy xuất, slide 12"
    assert source_label(source.model_copy(update={"page": None})) == "bài RAG Pipeline - Truy xuất"


def test_unassigned_room_uses_default_course(tmp_path: Path) -> None:
    payload = ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(),
                             message="prompt injection là gì", course_id="__no_authorized_course__")
    retriever = LocalRetriever(_corpus(tmp_path))
    state = {"input": payload, "errors": []}

    assert asyncio.run(retrieve_context(state, retriever, 3))["retrieved_sources"] == []
    found = asyncio.run(retrieve_context(state, retriever, 3, default_course_id="aicb"))["retrieved_sources"]
    assert found[0].source == "Guardrails.md"


def test_build_retriever_local_provider(tmp_path: Path) -> None:
    settings = ModeratorSettings(_env_file=None, retriever_provider="local", rag_corpus_dir=str(_corpus(tmp_path)))

    assert isinstance(_build_retriever(settings), LocalRetriever)


def _guide_llm() -> FakeLLM:
    def rule(system: str, _user: str) -> dict[str, Any]:
        if system == CLASSIFY_SYSTEM_PROMPT:
            return {"intent": "CONCEPT_QUESTION", "confidence": 0.6, "risk": 0.0, "reason": "fake"}
        return {"guidance": "Bạn nghĩ vì sao cần chấm lại các đoạn đã tìm được trước khi trả lời?"}

    return FakeLLM(rule=rule)


def test_guidance_gets_slide_citation(tmp_path: Path) -> None:
    graph = build_moderator_graph(_guide_llm(), LocalRetriever(_corpus(tmp_path)), ModeratorSettings(_env_file=None))
    payload = ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(),
                             message="Ai giải hộ bài reranking cross-encoder với", course_id="aicb")

    out = asyncio.run(run_moderator(graph, payload))

    assert out.action is ModerationAction.GUIDE
    assert out.guidance.endswith("(Xem bài RAG Pipeline, slide 12)")


def test_guidance_without_sources_has_no_citation(tmp_path: Path) -> None:
    graph = build_moderator_graph(_guide_llm(), LocalRetriever(_corpus(tmp_path)), ModeratorSettings(_env_file=None))
    payload = ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(),
                             message="Ai giải hộ bài 3 với", course_id="aicb")

    out = asyncio.run(run_moderator(graph, payload))

    assert out.action is ModerationAction.GUIDE
    assert "Xem bài" not in out.guidance


@pytest.mark.skipif(not (AICB_DIR / "aicb").is_dir(), reason="Slide giảng viên AICB không kèm trong repo công khai")
def test_shipped_aicb_corpus_loads_and_answers() -> None:
    results = _search(LocalRetriever(AICB_DIR), "prompt injection phòng chống thế nào")

    assert results
    assert all(r.page for r in results)
    assert not any("Day" in r.source for r in results)
