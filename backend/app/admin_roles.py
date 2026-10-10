"""Vai trò Admin (trước đây gọi là giảng viên).

Trong cơ sở dữ liệu vẫn lưu `role='INSTRUCTOR'` để không phải đổi ràng buộc CHECK của bảng `users`;
mọi chỗ hiển thị cho người dùng gọi vai trò này là "Admin". Admin xem và kiểm duyệt được mọi phiên học.

Tài khoản thành Admin khi email nằm trong biến môi trường `ADMIN_EMAILS` (cách nhau bằng dấu phẩy),
hoặc là tài khoản thử `admin@demo.peerbridge` khi bật DEMO_MODE.
"""
from __future__ import annotations

import os
import sqlite3

from .enums import Role

ADMIN_ROLE = Role.INSTRUCTOR
ADMIN_LABEL = "Admin"


def admin_emails() -> set[str]:
    return {email.strip().lower() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()}


def is_admin_email(email: str) -> bool:
    return email.strip().lower() in admin_emails()


def is_admin(user: dict) -> bool:
    return str(user.get("role")) == ADMIN_ROLE.value


def public_role(role: str) -> str:
    """Tên vai trò trả cho giao diện: ADMIN hoặc STUDENT."""
    return "ADMIN" if role == ADMIN_ROLE.value else "STUDENT"


def promote_if_listed(connection: sqlite3.Connection, user_id: int, email: str) -> None:
    """Đưa tài khoản lên Admin nếu email nằm trong ADMIN_EMAILS (gọi khi đăng ký/đăng nhập)."""
    if is_admin_email(email):
        connection.execute("UPDATE users SET role = ? WHERE id = ? AND role != ?",
                           (ADMIN_ROLE.value, user_id, ADMIN_ROLE.value))


def admin_user_ids(connection: sqlite3.Connection) -> list[int]:
    rows = connection.execute("SELECT id FROM users WHERE role = ? AND is_seed = 0", (ADMIN_ROLE.value,)).fetchall()
    return [int(row["id"]) for row in rows]
