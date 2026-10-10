"""Embedder cho RAG: E5 thật (sentence-transformers) và FakeEmbedder deterministic cho test."""

import hashlib
import math
import re
import threading
from functools import lru_cache
from typing import Any, Protocol

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


class Embedder(Protocol):
    """Chuyển văn bản thành vector đã chuẩn hoá (norm = 1)."""

    @property
    def dimension(self) -> int: ...

    def embed_query(self, text: str) -> list[float]: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


class E5Embedder:
    """multilingual-e5-large qua sentence-transformers; tải model lười ở lần dùng đầu."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer  # lazy: thư viện nặng, tuỳ chọn

                self._model = SentenceTransformer(self._model_name)
            return self._model

    @property
    def dimension(self) -> int:
        """Số chiều vector của model."""
        model = self._load()
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True)
        return [[float(x) for x in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed câu truy vấn, bắt buộc prefix 'query: '."""
        return self._encode([QUERY_PREFIX + text])[0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed đoạn tài liệu, bắt buộc prefix 'passage: '."""
        if not texts:
            return []
        return self._encode([PASSAGE_PREFIX + text for text in texts])


@lru_cache
def get_e5_embedder(model_name: str) -> E5Embedder:
    """E5Embedder dùng chung theo tên model: model chỉ nạp 1 lần mỗi tiến trình."""
    return E5Embedder(model_name)


class FakeEmbedder:
    """Embedder giả: túi từ băm vào vector cố định chiều, chuẩn hoá. Từ chung -> cosine cao."""

    def __init__(self, dimension: int = 256) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        """Số chiều vector."""
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for word in re.findall(r"\w+", text.casefold()):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector] if norm else vector

    def embed_query(self, text: str) -> list[float]:
        """Embed câu truy vấn."""
        return self._embed(text)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed các đoạn tài liệu."""
        return [self._embed(text) for text in texts]
