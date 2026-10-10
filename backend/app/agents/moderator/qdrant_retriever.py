"""QdrantRetriever: truy xuất tài liệu môn học từ Qdrant, lọc theo course_id."""

import asyncio
import warnings
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from .contract import RetrievedSource
from .embedding import Embedder

DEFAULT_COLLECTION = "course_materials"


def make_client(url: str) -> Any:
    """Tạo QdrantClient (import lười); url ':memory:' cho test."""
    from qdrant_client import QdrantClient

    return QdrantClient(location=url) if url == ":memory:" else QdrantClient(url=url)


@lru_cache
def get_client(url: str) -> Any:
    """QdrantClient dùng chung theo url (mỗi tiến trình 1 client)."""
    return make_client(url)


def ensure_collection(client: Any, collection: str, dimension: int) -> None:
    """Tạo collection cosine nếu chưa có, kèm index payload cho course_id và source."""
    from qdrant_client import models

    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )
    with warnings.catch_warnings():  # Qdrant local (:memory:) cảnh báo payload index không có tác dụng
        warnings.simplefilter("ignore", UserWarning)
        for field in ("course_id", "source"):
            client.create_payload_index(collection, field, models.PayloadSchemaType.KEYWORD)


class QdrantRetrieverConfig(BaseModel):
    """Tham số truy xuất."""

    collection: str = DEFAULT_COLLECTION
    min_score: float = Field(default=0.0, ge=0, le=1)


class QdrantRetriever:
    """Implement Retriever bằng Qdrant + Embedder."""

    def __init__(self, client: Any, embedder: Embedder, config: QdrantRetrieverConfig | None = None) -> None:
        self._client = client
        self._embedder = embedder
        self._config = config or QdrantRetrieverConfig()
        self._ready = False

    def warmup(self) -> None:
        """Warm an existing corpus; read paths must never provision collections."""
        if self._ensure_ready():
            self._embedder.embed_query("warmup")

    def _ensure_ready(self) -> bool:
        if not self._ready:
            if not self._client.collection_exists(self._config.collection):
                return False
            self._ready = True
        return True

    def _search_sync(self, query: str, course_id: str, top_k: int) -> list[RetrievedSource]:
        from qdrant_client import models

        if not self._ensure_ready():
            return []
        response = self._client.query_points(
            collection_name=self._config.collection,
            query=self._embedder.embed_query(query),
            query_filter=models.Filter(
                must=[models.FieldCondition(key="course_id", match=models.MatchValue(value=course_id))]
            ),
            limit=top_k,
            score_threshold=self._config.min_score,
            with_payload=True,
        )
        return [
            RetrievedSource(
                source=point.payload["source"],
                chunk_id=point.payload["chunk_id"],
                score=point.score,
                text=point.payload.get("text"),
                source_hash=point.payload.get("source_hash"),
                page=point.payload.get("page"),
                section=point.payload.get("section"),
                embedding_model=point.payload.get("embedding_model"),
            )
            for point in response.points
        ]

    async def search(self, query: str, course_id: str, top_k: int) -> list[RetrievedSource]:
        """Trả tối đa top_k đoạn của course_id có cosine >= min_score, điểm giảm dần."""
        if not query.strip() or top_k <= 0:
            return []
        return await asyncio.to_thread(self._search_sync, query, course_id, top_k)
