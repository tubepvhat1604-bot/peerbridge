"""Thông báo trong app: lưu trong bảng `notifications`, hiện ở chuông và trang Tổng quan.

Các phần khác gọi `add(...)` (check-in của bạn cặp, cảm xúc, bình luận, lời nhắc, lời mời kết nối).
Lỗi khi ghi thông báo không bao giờ làm hỏng thao tác chính.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from ..db import database

log = logging.getLogger("home.notifications")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    page TEXT NOT NULL DEFAULT 'dashboard',
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC);
"""

KINDS = {"checkin", "reaction", "comment", "nudge", "connection_request", "connection_accepted", "plan", "system"}


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def add(user_id: int, kind: str, title: str, body: str = "", page: str = "dashboard",
        connection: sqlite3.Connection | None = None) -> bool:
    """Ghi một thông báo. Truyền `connection` khi đang trong một giao dịch sqlite khác để tránh khóa."""
    if kind not in KINDS:
        kind = "system"
    row = (int(user_id), kind, title[:160], body[:300], page[:40], now_iso())
    sql = "INSERT INTO notifications(user_id,kind,title,body,page,created_at) VALUES (?,?,?,?,?,?)"
    try:
        if connection is not None:
            connection.execute(sql, row)
        else:
            with database() as db:
                db.execute(sql, row)
        return True
    except Exception:  # thông báo là phụ, không được làm hỏng luồng chính
        log.exception("Không ghi được thông báo cho %s", user_id)
        return False


def recent(user_id: int, limit: int = 20) -> list[dict]:
    with database() as db:
        rows = db.execute(
            "SELECT id,kind,title,body,page,created_at,read_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, max(1, min(limit, 50))),
        ).fetchall()
    return [dict(r) for r in rows]


def unread_count(user_id: int) -> int:
    with database() as db:
        return db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (user_id,)).fetchone()[0]


def mark_read(user_id: int, ids: list[int] | None = None) -> int:
    with database() as db:
        if ids:
            marks = ",".join("?" * len(ids))
            cur = db.execute(
                f"UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL AND id IN ({marks})",
                (now_iso(), user_id, *ids),
            )
        else:
            cur = db.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (now_iso(), user_id))
        return cur.rowcount
