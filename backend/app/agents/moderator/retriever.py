"""Interface Retriever của moderator và bản FakeRetriever lưu tài liệu trong bộ nhớ."""

import re
from typing import Protocol

from pydantic import BaseModel

from .contract import RetrievedSource


class Retriever(Protocol):
    """Truy xuất đoạn tài liệu liên quan theo môn học."""

    async def search(self, query: str, course_id: str, top_k: int) -> list[RetrievedSource]: ...


class FakeDocument(BaseModel):
    """Một đoạn tài liệu trong FakeRetriever."""

    course_id: str
    source: str
    chunk_id: str
    text: str


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


class FakeRetriever:
    """Retriever giả: lọc theo course_id, xếp hạng theo độ trùng từ khoá."""

    def __init__(self, documents: list[FakeDocument] | None = None) -> None:
        self._documents = list(documents or [])

    def add_document(self, document: FakeDocument) -> None:
        """Thêm một đoạn tài liệu vào kho."""
        self._documents.append(document)

    async def search(self, query: str, course_id: str, top_k: int) -> list[RetrievedSource]:
        """Trả tối đa top_k đoạn có score = tỉ lệ từ khoá của query xuất hiện trong đoạn."""
        query_tokens = _tokens(query)
        if not query_tokens or top_k <= 0:
            return []
        scored: list[RetrievedSource] = []
        for doc in self._documents:
            if doc.course_id != course_id:
                continue
            overlap = len(query_tokens & _tokens(doc.text))
            if overlap:
                scored.append(
                    RetrievedSource(
                        source=doc.source,
                        chunk_id=doc.chunk_id,
                        score=overlap / len(query_tokens),
                        text=doc.text,
                    )
                )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]
