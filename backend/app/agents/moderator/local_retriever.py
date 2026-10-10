"""LocalRetriever: tìm tài liệu môn học bằng BM25 trên file trong data/courses, không cần Qdrant hay torch.

Mỗi thư mục con của corpus_dir là một course_id; mỗi file .md/.txt là một bài.
Dùng trên server nhẹ (Render) nơi không chạy được Qdrant + mô hình embedding.
"""

import math
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from .contract import RetrievedSource
from .ingest import build_chunks
from .rules import normalize_text

BM25_K1 = 1.5
BM25_B = 0.75
# Từ chức năng tiếng Việt (đã bỏ dấu): khớp ở mọi slide nên chỉ làm nhiễu xếp hạng.
STOPWORDS = frozenset(
    "la gi cho cua va the nao minh ban toi vay thi de lam sao khong co duoc mot nhung cac voi trong khi di nay do "
    "hay ma neu nhe a oi ah u em anh chi cau bai tap hieu biet giup hoi ve tu den nhu nen can phai se da dang "
    "rat qua nua cung con chua ra vao len xuong duoi tren".split()
)
# Slide mở/kết bài liệt kê mọi từ khoá của bài nên hay lên đầu; hạ điểm để ưu tiên slide nội dung.
_OVERVIEW_SLIDE = re.compile(r"^(?:Mục Tiêu|Nội Dung Bài Học|Tổng kết|Tiếp theo & Bài tập|Deliverable)", re.IGNORECASE)
OVERVIEW_PENALTY = 0.5


def tokenize(text: str) -> list[str]:
    """Từ không dấu, chữ thường, bỏ từ 1 ký tự: câu gõ không dấu vẫn khớp slide có dấu."""
    return [token for token in re.findall(r"\w+", normalize_text(text)) if len(token) > 1 and token not in STOPWORDS]


class _Chunk(BaseModel):
    source: str
    chunk_id: str
    text: str
    page: int | None
    section: str | None
    tokens: Counter
    length: int
    weight: float = 1.0


class _CourseIndex:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self.chunks = chunks
        self.average_length = sum(c.length for c in chunks) / len(chunks) if chunks else 0.0
        document_frequency = Counter(token for c in chunks for token in c.tokens)
        total = len(chunks)
        self.idf = {t: math.log(1 + (total - df + 0.5) / (df + 0.5)) for t, df in document_frequency.items()}
        self.max_idf = math.log(1 + (total + 0.5) / 0.5) if total else 0.0

    def bm25(self, chunk: _Chunk, query: list[str]) -> float:
        norm = BM25_K1 * (1 - BM25_B + BM25_B * chunk.length / self.average_length)
        return chunk.weight * sum(self.idf[t] * chunk.tokens[t] * (BM25_K1 + 1) / (chunk.tokens[t] + norm)
                   for t in query if t in chunk.tokens)

    def coverage(self, chunk: _Chunk, query: list[str]) -> float:
        """Tỉ lệ (theo idf) từ khoá của câu hỏi có trong đoạn, 0..1: dùng làm score và để lọc đoạn lạc đề."""
        weights = {t: self.idf.get(t, self.max_idf) for t in query}
        total = sum(weights.values())
        return sum(w for t, w in weights.items() if t in chunk.tokens) / total if total else 0.0


def _load_course(directory: Path) -> _CourseIndex:
    chunks = []
    for path in sorted(p for p in directory.iterdir() if p.suffix.lower() in {".md", ".txt"}):
        for chunk in build_chunks(path.name, path.read_text(encoding="utf-8")):
            if chunk.page is None and chunk.text.lstrip().startswith("#") and "\n" not in chunk.text.strip():
                continue  # dòng tiêu đề bài đứng riêng, không có nội dung
            tokens = tokenize(chunk.text)
            weight = OVERVIEW_PENALTY if _OVERVIEW_SLIDE.match(chunk.text.lstrip()) else 1.0
            chunks.append(_Chunk(source=path.name, chunk_id=chunk.chunk_id, text=chunk.text, page=chunk.page,
                                 section=chunk.section, tokens=Counter(tokens), length=len(tokens), weight=weight))
    return _CourseIndex(chunks)


class LocalRetriever:
    """Retriever đọc corpus từ đĩa một lần cho mỗi course_id, xếp hạng BM25."""

    def __init__(self, corpus_dir: Path, min_score: float = 0.35) -> None:
        self._corpus_dir = Path(corpus_dir)
        self._min_score = min_score
        self._courses: dict[str, _CourseIndex] = {}

    def _course(self, course_id: str) -> _CourseIndex | None:
        if course_id not in self._courses:
            directory = self._corpus_dir / course_id
            # course_id đến từ DB; chặn "../" để không đọc ngoài corpus_dir.
            if not re.fullmatch(r"[\w.-]+", course_id) or course_id.startswith(".") or not directory.is_dir():
                return None
            self._courses[course_id] = _load_course(directory)
        return self._courses[course_id]

    def warmup(self, course_ids: list[str] | None = None) -> None:
        """Nạp sẵn index (mặc định mọi khoá trong corpus_dir)."""
        if course_ids is None:
            course_ids = [p.name for p in self._corpus_dir.iterdir() if p.is_dir()] if self._corpus_dir.is_dir() else []
        for name in course_ids:
            self._course(name)

    async def search(self, query: str, course_id: str, top_k: int) -> list[RetrievedSource]:
        """Trả tối đa top_k đoạn, score = độ phủ từ khoá (0..1), bỏ đoạn dưới min_score."""
        index = self._course(course_id)
        terms = list(dict.fromkeys(tokenize(query)))
        if index is None or not index.chunks or not terms or top_k <= 0:
            return []
        ranked = sorted(((index.bm25(c, terms), c) for c in index.chunks), key=lambda item: item[0], reverse=True)
        results = []
        for bm25, chunk in ranked:
            if bm25 <= 0 or len(results) >= top_k:
                break
            score = index.coverage(chunk, terms)
            if score >= self._min_score:
                results.append(RetrievedSource(source=chunk.source, chunk_id=chunk.chunk_id, score=round(score, 4),
                                               text=chunk.text, page=chunk.page, section=chunk.section,
                                               embedding_model="bm25"))
        return results
