"""Báo cho bạn cặp: ghi thông báo trong app (chuông + trang Tổng quan, xem app/home/notifications.py).

Lỗi gửi thông báo KHÔNG được làm hỏng check-in.
"""
from __future__ import annotations

import logging

log = logging.getLogger("checkin.notify")
_sent: list[tuple[int, str]] = []  # để test kiểm tra


def notify(user_id: int, message: str, *, kind: str = "checkin", title: str | None = None, page: str = "checkin") -> bool:
    _sent.append((user_id, message))
    from ..home import notifications

    return notifications.add(user_id, kind, title or message, body=message if title else "", page=page)


def sent_messages() -> list[tuple[int, str]]:
    return list(_sent)


def clear_sent() -> None:
    _sent.clear()
