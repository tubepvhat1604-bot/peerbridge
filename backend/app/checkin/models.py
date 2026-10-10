"""Các bảng AI Vision sở hữu: vi_checkins, vi_reactions, vi_nudges.

user_id/pair_id là số nguyên, trỏ tới users.id và peer_matches.id của app.
plan_item_id là id (chuỗi) của pb_plan_items do Data 2 sở hữu.
Migration Postgres: alembic/versions/20261006_0011_vision_checkins.py.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")
UUID = Uuid(as_uuid=False)


def new_id() -> str:
    return str(uuid.uuid4())


class CheckinStatus:
    PROCESSING = "processing"
    NEEDS_CONFIRM = "needs_confirm"
    DONE = "done"
    NOT_STUDY = "not_study"
    FAILED = "failed"

    TERMINAL = {DONE, NOT_STUDY}
    ALL = {PROCESSING, NEEDS_CONFIRM, DONE, NOT_STUDY, FAILED}


class Checkin(Base):
    __tablename__ = "vi_checkins"

    # id do client tạo (UUID) để chống gửi trùng.
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    pair_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10), default="photo")  # photo | text
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=CheckinStatus.PROCESSING, index=True)
    # Kết quả AI: is_study, concepts, description, confidence, partner_summary, bridge...
    ai_result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Lựa chọn hiện cho người dùng khi needs_confirm/failed: [{plan_item_id, label, concept_id}]
    options: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    # Mục plan AI đề xuất (trước khi người dùng xác nhận) – dùng để đo AI đúng/sai.
    suggested_plan_item_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    plan_item_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Phiên bản plan lúc gắn mục (cần cho sự kiện hoàn thành gửi Data 2).
    plan_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    # Ngày học theo giờ VN, đã áp quy tắc "trước 3h sáng tính cho hôm trước".
    study_day: Mapped[dt.date] = mapped_column(Date, index=True)

    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reactions: Mapped[list[Reaction]] = relationship(
        back_populates="checkin", cascade="all, delete-orphan", order_by="Reaction.created_at"
    )

    __table_args__ = (Index("ix_vi_checkins_pair_day", "pair_id", "study_day"),)


class Reaction(Base):
    __tablename__ = "vi_reactions"

    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    checkin_id: Mapped[str] = mapped_column(UUID, ForeignKey("vi_checkins.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    checkin: Mapped[Checkin] = relationship(back_populates="reactions")


class Nudge(Base):
    __tablename__ = "vi_nudges"

    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=new_id)
    pair_id: Mapped[int] = mapped_column(Integer, index=True)
    from_user: Mapped[int] = mapped_column(Integer)
    to_user: Mapped[int] = mapped_column(Integer, index=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VisionImage(Base):
    """Ảnh check-in đã nén (~100–200 KB), lưu trong database để được sao lưu cùng dữ liệu."""

    __tablename__ = "vi_images"

    path: Mapped[str] = mapped_column(String(255), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
