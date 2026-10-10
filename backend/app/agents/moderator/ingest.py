"""Ingest tài liệu môn học (.md/.txt/.pdf) vào Qdrant.

Chạy: python -m app.agents.moderator.ingest --course-id <id> --path <thư mục>
"""

import argparse
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .embedding import Embedder
from .qdrant_retriever import DEFAULT_COLLECTION, ensure_collection

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}
_ID_NAMESPACE = uuid.UUID("6f1c1d0e-5a39-4b0e-9c57-3c0a7b1d2f10")


class Chunk(BaseModel):
    """Một đoạn tài liệu đã cắt."""

    chunk_id: str
    text: str
    page: int | None = None
    section: str | None = None


def _split_long(paragraph: str, size: int) -> list[str]:
    """Cắt đoạn dài hơn size theo ranh giới từ."""
    pieces: list[str] = []
    current = ""
    for word in paragraph.split():
        if current and len(current) + 1 + len(word) > size:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(text: str, overlap: int) -> str:
    """Lấy ~overlap ký tự cuối của text, bắt đầu ở ranh giới từ."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chia văn bản theo đoạn thành chunk ~size ký tự, chunk sau lặp lại ~overlap ký tự cuối chunk trước."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units = [piece for p in paragraphs for piece in (_split_long(p, size) if len(p) > size else [p])]
    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 2 + len(unit) > size:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            current = f"{tail}\n\n{unit}" if tail and len(tail) + 2 + len(unit) <= size else unit
        else:
            current = f"{current}\n\n{unit}" if current else unit
    if current:
        chunks.append(current)
    return chunks


def read_document(path: Path) -> str:
    """Đọc nội dung text của file .md/.txt/.pdf."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader  # lazy

        pages = [page.extract_text() or "" for page in PdfReader(path).pages]
        if any(not text.strip() for text in pages):
            raise ValueError("PDF has pages without extractable text; manual extraction review required")
        return "\n\n".join(f"<!-- page:{i} -->\n{text}" for i, text in enumerate(pages, 1))
    return path.read_text(encoding="utf-8")


def point_id(course_id: str, source: str, chunk_id: str) -> str:
    """UUID ổn định theo (course_id, source, chunk_id) để ingest lại không trùng."""
    return str(uuid.uuid5(_ID_NAMESPACE, f"{course_id}\x1f{source}\x1f{chunk_id}"))


def build_chunks(source: str, text: str) -> list[Chunk]:
    """Cắt text và gán chunk_id dạng '<tên-file>#<số thứ tự>'."""
    chunks = []
    page = None
    section = None
    for unit in re.split(r"(?m)(?=^#{1,6} |^<!-- page:\d+ -->)", text):
        marker = re.match(r"<!-- page:(\d+) -->", unit)
        if marker:
            page = int(marker.group(1))
            unit = unit[marker.end():].strip()
        heading = re.match(r"#{1,6}\s+([^\n]+)", unit)
        if heading:
            section = heading.group(1)
        for piece in chunk_text(unit):
            chunks.append(Chunk(chunk_id=f"{source}#{len(chunks)}", text=piece, page=page, section=section))
    return chunks


def ingest_file(client: Any, embedder: Embedder, course_id: str, path: Path, collection: str) -> int:
    """Ingest một file: xoá chunk cũ của file đó rồi upsert chunk mới. Trả số chunk."""
    from qdrant_client import models

    source = path.name
    text = read_document(path)
    chunks = build_chunks(source, text)
    if not chunks:
        raise ValueError("Empty extraction requires manual review; existing index retained")
    vectors = embedder.embed_passages([c.text for c in chunks])
    points = [
        models.PointStruct(id=point_id(course_id, source, c.chunk_id), vector=vector,
            payload={"course_id": course_id, "source": source, "chunk_id": c.chunk_id,
                     "text": c.text, "source_hash": hashlib.sha256(text.encode('utf-8')).hexdigest(),
                     "page": c.page, "section": c.section,
                     "embedding_model": getattr(embedder, "model_name", type(embedder).__name__)})
        for c, vector in zip(chunks, vectors, strict=True)
    ]
    client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key="course_id", match=models.MatchValue(value=course_id)),
                    models.FieldCondition(key="source", match=models.MatchValue(value=source)),
                ]
            )
        ),
    )
    client.upsert(
        collection_name=collection,
        points=points,
    )
    return len(chunks)


def ingest_directory(
    client: Any, embedder: Embedder, course_id: str, path: Path, collection: str = DEFAULT_COLLECTION
) -> dict[str, int]:
    """Ingest mọi file được hỗ trợ trong thư mục; trả {tên file: số chunk}."""
    ensure_collection(client, collection, embedder.dimension)
    files = sorted(f for f in path.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES)
    return {f.name: ingest_file(client, embedder, course_id, f, collection) for f in files}


def rebuild_directory(client: Any, embedder: Embedder, course_id: str, path: Path, alias: str) -> dict[str, int]:
    """Build an isolated full-course collection, then atomically switch its alias.

    Use one alias per course. Previous collections are retained for explicit rollback.
    Never delete the live collection, including on extraction/upsert failures.
    """
    from qdrant_client import models
    staging = f"{alias}__{uuid.uuid4().hex}"
    result = ingest_directory(client, embedder, course_id, path, staging)
    if not result or not sum(result.values()):
        raise ValueError("Refusing to activate an empty corpus")
    existing = {item.alias_name for item in client.get_aliases().aliases}
    operations = []
    if alias in existing:
        operations.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
    operations.append(models.CreateAliasOperation(create_alias=models.CreateAlias(collection_name=staging, alias_name=alias)))
    client.update_collection_aliases(change_aliases_operations=operations)
    return result


def main(argv: list[str] | None = None) -> None:
    """CLI: ingest thư mục tài liệu vào Qdrant theo settings (qdrant_url, embedding_model)."""
    from .embedding import E5Embedder
    from .qdrant_retriever import make_client
    from .settings import get_moderator_settings

    parser = argparse.ArgumentParser(description="Ingest tài liệu môn học vào Qdrant")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--rebuild-alias", help="Build full course snapshot and atomically activate this dedicated alias")
    args = parser.parse_args(argv)
    settings = get_moderator_settings()
    ingest = rebuild_directory if args.rebuild_alias else ingest_directory
    result = ingest(
        make_client(settings.qdrant_url),
        E5Embedder(settings.embedding_model),
        args.course_id,
        args.path,
        args.rebuild_alias or settings.qdrant_collection,
    )
    for name, count in result.items():
        print(f"{name}: {count} chunk")
    print(f"Xong: {sum(result.values())} chunk từ {len(result)} file (course_id={args.course_id})")


if __name__ == "__main__":
    main()
