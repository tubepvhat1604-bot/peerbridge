"""Phiên SQLAlchemy cho các bảng của AI Vision, dùng chung engine/database của app."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import DeclarativeBase, Session

from ..database import get_engine, get_session_factory


class Base(DeclarativeBase):
    pass


def session_factory():
    return get_session_factory()


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def initialize_checkin_tables() -> None:
    """Tạo bảng vi_* nếu chưa có (runtime SQLite). Postgres dùng migration Alembic."""
    from . import models  # noqa: F401

    Base.metadata.create_all(get_engine())
