"""Fixture dùng chung: test không bao giờ gọi mạng thật, không phụ thuộc .env của máy chạy test."""

import sys
import types
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

LOCAL_QDRANT = ":memory:"


def _clear_moderator_caches() -> None:
    from app.agents.moderator import graph
    from app.agents.moderator.embedding import get_e5_embedder
    from app.agents.moderator.qdrant_retriever import get_client
    from app.agents.moderator.settings import get_moderator_settings

    for cached in (
        get_moderator_settings,
        graph._default_graph,
        graph._default_retriever,
        get_e5_embedder,
        get_client,
    ):
        cached.cache_clear()


def _forbid(name: str) -> Any:
    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"Test không được phép dùng {name} thật (dùng fake/mock)")

    return blocked


def _block_qdrant_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from qdrant_client import QdrantClient

    original_init = QdrantClient.__init__

    def guarded_init(self: Any, *args: Any, **kwargs: Any) -> None:
        location = kwargs.get("location", args[0] if args else None)
        if location != LOCAL_QDRANT or any(kwargs.get(key) for key in ("url", "host", "port", "path")):
            raise RuntimeError("Test chỉ được dùng QdrantClient(':memory:'), không kết nối Qdrant thật")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(QdrantClient, "__init__", guarded_init)


def _block_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Không import thư viện nặng (torch): thay bằng stub nếu chưa nạp.
    module = sys.modules.get("sentence_transformers")
    if module is None:
        module = types.ModuleType("sentence_transformers")
        monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(module, "SentenceTransformer", _forbid("SentenceTransformer"), raising=False)


@pytest.fixture(autouse=True)
def _offline_moderator(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("RETRIEVER_PROVIDER", "fake")
    # Biến môi trường rỗng thắng giá trị trong .env => không có key thật (cả moderator lẫn agent chung app/agents).
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    # httpx.MockTransport (dùng trong test LLM) và TestClient của FastAPI không đi qua 2 transport thật này.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _forbid("httpx.AsyncHTTPTransport"))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _forbid("httpx.HTTPTransport"))
    _block_qdrant_network(monkeypatch)
    _block_sentence_transformers(monkeypatch)
    _clear_moderator_caches()
    yield
    monkeypatch.undo()  # trả lại hàm bị test patch trước khi cache_clear
    _clear_moderator_caches()
