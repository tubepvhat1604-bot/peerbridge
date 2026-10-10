"""Sổ chi phí AI dùng chung (ngoài AI Vision): chia việc trong plan, xếp hạng ghép cặp.

Trần chung `VISION_DAILY_BUDGET_USD` (mặc định 2 USD/ngày) tính cả chi phí AI Vision lẫn các khoản ở đây.
Hết trần thì các phần AI tự quay về cách làm không cần AI (mẫu có sẵn, xếp hạng theo điểm).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from ..db import database

log = logging.getLogger("loop.budget")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    feature TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at);
"""

# USD cho mỗi triệu token vào/ra. Kiểm tra lại trang giá chính thức trước khi báo cáo.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gpt-5-mini": (0.25, 2.0), "gpt-4o-mini": (0.15, 0.60)}


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.40, 1.60))
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


def record(feature: str, model: str, input_tokens: int, output_tokens: int) -> None:
    try:
        with database() as db:
            db.execute(
                "INSERT INTO ai_usage(created_at,feature,model,input_tokens,output_tokens,cost_usd) VALUES (?,?,?,?,?,?)",
                (datetime.now(UTC).isoformat(), feature, model, int(input_tokens), int(output_tokens),
                 cost_of(model, input_tokens, output_tokens)),
            )
    except Exception:
        log.exception("Không ghi được chi phí AI (%s)", feature)


def cost_since(since: datetime) -> dict[str, float]:
    with database() as db:
        rows = db.execute(
            "SELECT feature, SUM(cost_usd) AS c FROM ai_usage WHERE created_at >= ? GROUP BY feature", (since.isoformat(),)
        ).fetchall()
    return {r["feature"]: round(r["c"] or 0, 6) for r in rows}


def budget_left() -> float:
    from ..checkin.stats import budget_left_usd

    return budget_left_usd()


class MeteredLLM:
    """Bọc LLM của Data 2: ghi token vào sổ chi phí sau mỗi lần gọi; hết trần thì không gọi."""

    def __init__(self, inner, feature: str):
        self._inner, self._feature = inner, feature

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def complete_json(self, system: str, user: str) -> dict:
        live = getattr(self._inner, "mode", "") == "live"
        if live and budget_left() <= 0:
            raise ValueError("AI_DAILY_BUDGET_EXCEEDED")
        result = await self._inner.complete_json(system, user)
        if live:
            usage = getattr(self._inner, "usage", None) or {}
            record(self._feature, getattr(self._inner, "model", "unknown"),
                   usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
                   usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        return result
