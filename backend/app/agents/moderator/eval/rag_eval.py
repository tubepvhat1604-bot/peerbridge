"""RAG eval: hit@k và phân bố score của câu liên quan / không liên quan, từ đó đề xuất RAG_MIN_SCORE.

Chạy (Qdrant + E5 thật, đã ingest demo-course):
    python -m app.agents.moderator.eval.rag_eval
Chạy offline để thử pipeline (FakeEmbedder + Qdrant :memory:, điểm không có ý nghĩa thực):
    python -m app.agents.moderator.eval.rag_eval --fake
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from ..embedding import Embedder, FakeEmbedder, get_e5_embedder
from ..ingest import ingest_directory
from ..qdrant_retriever import QdrantRetriever, QdrantRetrieverConfig, get_client, make_client
from ..retriever import Retriever
from ..settings import get_moderator_settings
from .metrics import percentile
from .run import DEFAULT_OUT_DIR, REPO_ROOT
from .schema import RagQuery, load_rag_queries

DEMO_COURSE_DIR = REPO_ROOT / "backend" / "data" / "courses" / "demo-course"
FAKE_COLLECTION = "rag_eval_fake"


class RagResult(BaseModel):
    """Kết quả truy xuất cho một câu hỏi."""

    id: str
    query: str
    expected_source: str | None
    top_sources: list[str]
    top1_score: float | None
    expected_score: float | None  # score tốt nhất của chunk thuộc expected_source trong top-k, None nếu trượt
    expected_chunk_ids: list[str] = Field(default_factory=list)
    top_chunk_ids: list[str] = Field(default_factory=list)

    @property
    def evidence_recall_at_k(self) -> float | None:
        expected = set(self.expected_chunk_ids)
        return len(expected.intersection(self.top_chunk_ids)) / len(expected) if expected else None

    @property
    def relevant(self) -> bool:
        return self.expected_source is not None

    @property
    def hit_at_1(self) -> bool:
        return self.relevant and bool(self.top_sources) and self.top_sources[0] == self.expected_source

    @property
    def hit_at_k(self) -> bool:
        return self.relevant and self.expected_score is not None


class RagSummary(BaseModel):
    """Tổng hợp RAG eval."""

    k: int
    relevant_count: int
    irrelevant_count: int
    hit_at_1: float
    hit_at_k: float
    relevant_scores: list[float]
    irrelevant_scores: list[float]
    suggested_min_score: float | None
    evidence_recall_at_k: float | None = None


async def evaluate_queries(retriever: Retriever, queries: list[RagQuery], k: int) -> list[RagResult]:
    """Truy xuất top-k cho từng câu (retriever nên có min_score=0 để thấy điểm thô)."""
    results: list[RagResult] = []
    for query in queries:
        sources = await retriever.search(query.query, query.course_id, k)
        expected = [s.score for s in sources if s.source == query.expected_source]
        results.append(
            RagResult(
                id=query.id,
                query=query.query,
                expected_source=query.expected_source,
                top_sources=[s.source for s in sources],
                top1_score=sources[0].score if sources else None,
                expected_score=max(expected) if expected else None,
                expected_chunk_ids=query.expected_chunk_ids,
                top_chunk_ids=[s.chunk_id for s in sources],
            )
        )
    return results


def suggest_threshold(relevant: list[float], irrelevant: list[float]) -> float | None:
    """Ngưỡng tối đa hoá (recall câu liên quan − tỉ lệ câu không liên quan lọt qua); giữa vùng bằng điểm tốt nhất."""
    if not relevant or not irrelevant:
        return None
    values = sorted({*relevant, *irrelevant})
    candidates = [values[0] - 1e-6, *[(a + b) / 2 for a, b in zip(values, values[1:], strict=False)], values[-1] + 1e-6]

    def youden(threshold: float) -> float:
        recall = sum(s >= threshold for s in relevant) / len(relevant)
        leaked = sum(s >= threshold for s in irrelevant) / len(irrelevant)
        return recall - leaked

    scores = [youden(t) for t in candidates]
    best = [t for t, s in zip(candidates, scores, strict=True) if s == max(scores)]
    return round((min(best) + max(best)) / 2, 3)


def summarize(results: list[RagResult], k: int) -> RagSummary:
    """Tính hit@1, hit@k, phân bố score và ngưỡng đề xuất."""
    relevant = [r for r in results if r.relevant]
    irrelevant = [r for r in results if not r.relevant]
    relevant_scores = [r.expected_score for r in relevant if r.expected_score is not None]
    irrelevant_scores = [r.top1_score for r in irrelevant if r.top1_score is not None]
    return RagSummary(
        k=k,
        relevant_count=len(relevant),
        irrelevant_count=len(irrelevant),
        hit_at_1=sum(r.hit_at_1 for r in relevant) / len(relevant) if relevant else 0.0,
        hit_at_k=sum(r.hit_at_k for r in relevant) / len(relevant) if relevant else 0.0,
        relevant_scores=relevant_scores,
        irrelevant_scores=irrelevant_scores,
        suggested_min_score=suggest_threshold(relevant_scores, irrelevant_scores),
        evidence_recall_at_k=(sum(r.evidence_recall_at_k for r in results if r.evidence_recall_at_k is not None)
            / sum(r.evidence_recall_at_k is not None for r in results)) if any(r.expected_chunk_ids for r in results) else None,
    )


def _distribution(scores: list[float]) -> str:
    if not scores:
        return "không có dữ liệu"
    return (
        f"min {min(scores):.3f} | p25 {percentile(scores, 25):.3f} | median {percentile(scores, 50):.3f} | "
        f"p75 {percentile(scores, 75):.3f} | max {max(scores):.3f}"
    )


def render_rag_report(results: list[RagResult], summary: RagSummary, current_min_score: float, label: str) -> str:
    """Báo cáo Markdown của RAG eval."""
    passing = sum(s >= current_min_score for s in summary.relevant_scores)
    leaked = sum(s >= current_min_score for s in summary.irrelevant_scores)
    suggested = "không đủ dữ liệu" if summary.suggested_min_score is None else f"{summary.suggested_min_score:.3f}"
    lines = [
        f"# Báo cáo RAG eval — {label}",
        "",
        f"- Ngày: {date.today().isoformat()}",
        f"- k = {summary.k}; {summary.relevant_count} câu liên quan, {summary.irrelevant_count} câu không liên quan",
        "",
        "| Chỉ số | Giá trị |",
        "|---|---|",
        f"| hit@1 | {summary.hit_at_1:.1%} |",
        f"| hit@{summary.k} | {summary.hit_at_k:.1%} |",
        f"| Evidence Recall@{summary.k} | {summary.evidence_recall_at_k if summary.evidence_recall_at_k is not None else 'unlabeled'} |",
        f"| Score câu liên quan (chunk đúng nguồn) | {_distribution(summary.relevant_scores)} |",
        f"| Score top-1 câu không liên quan | {_distribution(summary.irrelevant_scores)} |",
        f"| **RAG_MIN_SCORE đề xuất** | **{suggested}** |",
        f"| Với RAG_MIN_SCORE hiện tại ({current_min_score}) | {passing}/{len(summary.relevant_scores)} câu liên quan "
        f"qua ngưỡng, {leaked}/{len(summary.irrelevant_scores)} câu không liên quan lọt qua |",
        "",
        "## Chi tiết",
        "",
        "| id | nguồn kỳ vọng | top sources | top-1 score | score nguồn đúng |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        top1 = "—" if r.top1_score is None else f"{r.top1_score:.3f}"
        exp = "—" if r.expected_score is None else f"{r.expected_score:.3f}"
        lines.append(
            f"| {r.id} | {r.expected_source or '(không liên quan)'} | {', '.join(r.top_sources)} | {top1} | {exp} |"
        )
    return "\n".join([*lines, ""])


async def _build_fake_retriever() -> Retriever:
    client, embedder = make_client(":memory:"), FakeEmbedder()
    ingest_directory(client, embedder, "demo-course", DEMO_COURSE_DIR, FAKE_COLLECTION)
    return QdrantRetriever(client, embedder, QdrantRetrieverConfig(collection=FAKE_COLLECTION, min_score=0.0))


def _build_real_retriever() -> Retriever:
    settings = get_moderator_settings()
    embedder: Embedder = get_e5_embedder(settings.embedding_model)
    config = QdrantRetrieverConfig(collection=settings.qdrant_collection, min_score=0.0)
    return QdrantRetriever(get_client(settings.qdrant_url), embedder, config)


async def main_async(fake: bool, k: int | None, out_dir: Path, dataset: Path | None = None) -> Path:
    """Chạy RAG eval, ghi báo cáo và in tóm tắt; trả đường dẫn báo cáo."""
    settings = get_moderator_settings()
    top_k = k or settings.rag_top_k
    retriever = await _build_fake_retriever() if fake else _build_real_retriever()
    results = await evaluate_queries(retriever, load_rag_queries(dataset) if dataset else load_rag_queries(), top_k)
    summary = summarize(results, top_k)
    if fake:
        summary = summary.model_copy(update={"suggested_min_score": None})
    label = "FakeEmbedder (điểm không có ý nghĩa)" if fake else f"{settings.embedding_model} @ {settings.qdrant_url}"
    report = render_rag_report(results, summary, settings.rag_min_score, label)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rag-report-{date.today().isoformat()}{'-fake' if fake else ''}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"-> {path}")
    return path


def main(argv: list[str] | None = None) -> None:
    """CLI."""
    parser = argparse.ArgumentParser(description="RAG eval cho demo-course")
    parser.add_argument("--fake", action="store_true", help="dùng FakeEmbedder + Qdrant :memory: (offline)")
    parser.add_argument("--k", type=int, default=None, help="top-k (mặc định RAG_TOP_K)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dataset", type=Path, help="JSONL with expected evidence chunk IDs")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main_async(args.fake, args.k, args.out_dir, args.dataset))


if __name__ == "__main__":
    main()
