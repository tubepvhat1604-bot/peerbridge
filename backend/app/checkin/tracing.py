"""Tracing tùy chọn.

- LangSmith: đặt LANGSMITH_TRACING=true và LANGSMITH_API_KEY; cài `langsmith`.
- Phoenix: SE/PO bật instrumentation cho cả app (openinference); module này không cần làm gì thêm.
Không cài gì thì decorator là no-op.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .config import get_settings

F = TypeVar("F", bound=Callable)


def traced(name: str, run_type: str = "chain") -> Callable[[F], F]:
    def deco(fn: F) -> F:
        if not get_settings().langsmith_tracing:
            return fn
        try:
            from langsmith import traceable  # type: ignore
        except Exception:
            return fn
        return traceable(name=name, run_type=run_type)(fn)  # type: ignore[return-value]

    return deco
