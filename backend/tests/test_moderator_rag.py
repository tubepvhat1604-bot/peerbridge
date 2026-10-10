import asyncio
from pathlib import Path

import pytest
from app.agents.moderator.embedding import PASSAGE_PREFIX, QUERY_PREFIX, E5Embedder, FakeEmbedder
from app.agents.moderator.ingest import build_chunks, chunk_text, ingest_directory, point_id
from app.agents.moderator.qdrant_retriever import QdrantRetriever, QdrantRetrieverConfig, make_client
from app.agents.moderator.retriever import Retriever
from app.agents.moderator.settings import ModeratorSettings

COLLECTION = "test_collection"
DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "courses" / "demo-course"


def _write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


def _retriever(client, min_score: float = 0.0) -> QdrantRetriever:
    return QdrantRetriever(client, FakeEmbedder(), QdrantRetrieverConfig(collection=COLLECTION, min_score=min_score))


def _count(client) -> int:
    return client.count(COLLECTION, exact=True).count


@pytest.fixture
def client():
    return make_client(":memory:")


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    _write(tmp_path, "recursion.md", "Recursion base case stack overflow function calls itself")
    _write(tmp_path, "loops.txt", "Loops for while iterate range break continue")
    return tmp_path


def test_chunk_text_respects_size_and_overlap() -> None:
    paragraphs = [f"Đoạn {i} " + "từ " * 60 for i in range(6)]
    chunks = chunk_text("\n\n".join(paragraphs), size=800, overlap=150)

    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    tail = chunks[0][-100:].split()[-3:]
    assert all(word in chunks[1] for word in tail)


def test_chunk_text_splits_overlong_paragraph_and_handles_empty() -> None:
    assert chunk_text("   \n\n  ") == []
    chunks = chunk_text("abc " * 1000, size=800, overlap=150)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)


def test_build_chunks_assigns_stable_ids() -> None:
    chunks = build_chunks("a.md", "x\n\ny")
    assert [c.chunk_id for c in chunks] == ["a.md#0"]
    assert point_id("c1", "a.md", "a.md#0") == point_id("c1", "a.md", "a.md#0")
    assert point_id("c1", "a.md", "a.md#0") != point_id("c2", "a.md", "a.md#0")


def test_ingest_is_idempotent_and_replaces_stale_chunks(client, docs: Path) -> None:
    first = ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)
    total = _count(client)
    ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)

    assert first == {"loops.txt": 1, "recursion.md": 1}
    assert _count(client) == total == 2

    _write(docs, "recursion.md", "")
    with pytest.raises(ValueError, match="Empty extraction"):
        ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)
    assert _count(client) == 2


def test_search_filters_by_course_id(client, docs: Path) -> None:
    ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)
    ingest_directory(client, FakeEmbedder(), "math1", docs, COLLECTION)
    retriever: Retriever = _retriever(client)

    results = asyncio.run(retriever.search("recursion loops", "cs101", 10))

    assert {r.source for r in results} == {"recursion.md", "loops.txt"}
    assert asyncio.run(retriever.search("recursion", "unknown", 10)) == []


def test_search_respects_top_k_and_orders_by_score(client, docs: Path) -> None:
    ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)
    retriever = _retriever(client)

    all_results = asyncio.run(retriever.search("recursion base case", "cs101", 10))
    top_one = asyncio.run(retriever.search("recursion base case", "cs101", 1))

    assert len(top_one) == 1
    assert top_one[0].chunk_id == all_results[0].chunk_id == "recursion.md#0"
    assert [r.score for r in all_results] == sorted((r.score for r in all_results), reverse=True)
    assert asyncio.run(retriever.search("recursion", "cs101", 0)) == []


def test_search_applies_min_score(client, docs: Path) -> None:
    ingest_directory(client, FakeEmbedder(), "cs101", docs, COLLECTION)

    strict = asyncio.run(_retriever(client, min_score=0.5).search("recursion base case", "cs101", 10))
    unrelated = asyncio.run(_retriever(client, min_score=0.5).search("bánh mì phô mai", "cs101", 10))

    assert [r.source for r in strict] == ["recursion.md"]
    assert unrelated == []


def test_search_does_not_create_missing_collection_or_load_embeddings(client) -> None:
    class UnavailableEmbedder:
        def embed_query(self, text):
            raise AssertionError("Missing corpus must not load an embedding model")

    retriever = QdrantRetriever(client, UnavailableEmbedder(), QdrantRetrieverConfig(collection=COLLECTION))
    retriever.warmup()
    assert asyncio.run(retriever.search("anything", "cs101", 4)) == []
    assert not client.collection_exists(COLLECTION)

    # The same retriever can see an approved corpus ingested later.
    from app.agents.moderator.qdrant_retriever import ensure_collection
    ensure_collection(client, COLLECTION, 256)
    retriever._embedder = FakeEmbedder()
    assert asyncio.run(_retriever(client).search("anything", "cs101", 4)) == []
    assert asyncio.run(retriever.search("anything", "cs101", 4)) == []


def test_demo_course_materials_ingest_and_retrieve(client) -> None:
    ingest_directory(client, FakeEmbedder(), "demo-course", DEMO_DIR, COLLECTION)

    results = asyncio.run(_retriever(client).search("trường hợp cơ sở đệ quy", "demo-course", 1))

    assert results[0].source == "de-quy.md"


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    embedder = FakeEmbedder()
    vector = embedder.embed_query("Đệ quy là gì")

    assert vector == embedder.embed_query("Đệ quy là gì")
    assert len(vector) == embedder.dimension
    assert sum(x * x for x in vector) == pytest.approx(1.0)


def test_e5_embedder_uses_required_prefixes_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bool]] = []

    class StubModel:
        def encode(self, texts: list[str], normalize_embeddings: bool) -> list[list[float]]:
            calls.append((texts, normalize_embeddings))
            return [[1.0, 0.0] for _ in texts]

    embedder = E5Embedder("stub")
    monkeypatch.setattr(embedder, "_load", lambda: StubModel())

    embedder.embed_query("xin chào")
    embedder.embed_passages(["a", "b"])

    assert calls[0] == ([QUERY_PREFIX + "xin chào"], True)
    assert calls[1] == ([PASSAGE_PREFIX + "a", PASSAGE_PREFIX + "b"], True)
    assert embedder.embed_passages([]) == []


def test_default_settings_keep_fake_retriever() -> None:
    settings = ModeratorSettings(_env_file=None)

    assert settings.retriever_provider == "fake"
    assert settings.rag_top_k == 4
    assert settings.qdrant_collection
