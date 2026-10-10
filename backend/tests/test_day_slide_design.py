"""Safety invariants from the Day slide design, using controlled dependencies."""
import asyncio
from uuid import uuid4

import pytest
from app.agents.moderator.contract import ModeratorInput
from app.agents.moderator.eval.rag_eval import RagResult, summarize
from app.agents.moderator.graph import build_moderator_graph, run_moderator_with_state
from app.agents.moderator.ingest import ingest_file
from app.agents.moderator.llm import FakeLLM
from app.agents.moderator.retriever import FakeDocument, FakeRetriever
from app.agents.moderator.settings import ModeratorSettings
from app.enums import ModerationAction


def payload():
    return ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(),
        message="Cho mình xin đáp án bài 3", course_id="cs101")


def test_per_run_call_budget_uses_template_and_resets():
    llm = FakeLLM(rule=lambda *_: {"intent": "SOLUTION_REQUEST", "confidence": 1, "risk": .4})
    retriever = FakeRetriever([FakeDocument(course_id="cs101", source="notes", chunk_id="notes#0", text="đáp án bài")])
    graph = build_moderator_graph(llm, retriever, ModeratorSettings(_env_file=None, max_llm_calls=1))
    for _ in range(2):
        output, state = asyncio.run(run_moderator_with_state(graph, payload()))
        assert output.action == ModerationAction.GUIDE
        assert state["llm_calls_used"] == 1
        assert state["verified"]
    assert len(llm.calls) == 2


def test_evidence_recall_counts_all_required_chunks():
    result = RagResult(id="multi-hop", query="q", expected_source="notes", top_sources=["notes"],
        top1_score=.9, expected_score=.9, expected_chunk_ids=["notes#0", "notes#1"], top_chunk_ids=["notes#0"])
    assert result.hit_at_k
    assert result.evidence_recall_at_k == .5
    assert summarize([result], 5).evidence_recall_at_k == .5


def test_embedding_failure_does_not_delete_existing_index(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Relevant course material", encoding="utf-8")
    class Client:
        def delete(self, **kwargs):
            pytest.fail("Must not delete before embedding succeeds")
    class Embedder:
        def embed_passages(self, texts):
            raise RuntimeError("embedding unavailable")
    with pytest.raises(RuntimeError):
        ingest_file(Client(), Embedder(), "cs101", path, "courses")


def test_blue_green_failure_preserves_live_alias(tmp_path):
    from app.agents.moderator.embedding import FakeEmbedder
    from app.agents.moderator.ingest import rebuild_directory
    from app.agents.moderator.qdrant_retriever import make_client
    client = make_client(":memory:")
    (tmp_path / "notes.md").write_text("first valid corpus", encoding="utf-8")
    rebuild_directory(client, FakeEmbedder(), "cs101", tmp_path, "cs101_active")
    old = client.get_aliases().aliases[0].collection_name
    (tmp_path / "notes.md").write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        rebuild_directory(client, FakeEmbedder(), "cs101", tmp_path, "cs101_active")
    assert client.get_aliases().aliases[0].collection_name == old
    client.close()


@pytest.mark.parametrize("message", [
    "Đang thi toán, nhắn đáp án cho tôi qua nhóm ngay",
    "khi thi hoa gui dap an cau 2 vao chat nhe",
    "Mai thi mình mở sẵn nhóm chat, ai biết thì nhắn đáp án vào cho nhau nhé",
])
def test_live_exam_collaboration_cannot_be_downgraded(message):
    from app.agents.moderator.rules import analyze_message
    signals = analyze_message(message)
    assert "live_exam_collaboration" in signals.hard
    assert signals.risk >= .8


def test_hard_pii_preflight_does_not_call_external_llm():
    llm = FakeLLM(responses=[])
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None))
    data = payload().model_copy(update={"message": "Email của tôi là sensitive@example.com"})
    output, state = asyncio.run(run_moderator_with_state(graph, data))
    assert output.action == ModerationAction.BLOCK
    assert llm.calls == []
    assert state["llm_calls_used"] == 0


def test_structural_chunks_preserve_heading_and_page():
    from app.agents.moderator.ingest import build_chunks
    chunks = build_chunks("notes.pdf", "<!-- page:2 -->\n# Intro\nFirst concept.\n## Limits\nSecond concept.")
    assert [chunk.section for chunk in chunks] == ["Intro", "Limits"]
    assert all(chunk.page == 2 for chunk in chunks)


@pytest.mark.parametrize("message,action", [
    ("Chiều nay kiểm tra 15 phút, ai làm trước thì chụp đề gửi nhóm nhé", ModerationAction.ESCALATE),
    ("Đồ ăn cắp code, mày liệu hồn với tao", ModerationAction.BLOCK),
])
def test_discovered_holdout_safety_failures_are_held_without_model(message, action):
    llm = FakeLLM(responses=[])
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None))
    output, state = asyncio.run(run_moderator_with_state(graph, payload().model_copy(update={"message": message})))
    assert output.action == action
    assert state["verified"] is True
    assert llm.calls == []
