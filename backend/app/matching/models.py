from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PairRecord(Base):
    __tablename__ = "pairs"
    __table_args__ = (
        UniqueConstraint("user_a", "user_b"), CheckConstraint("user_a < user_b"),
        CheckConstraint("match_level IN ('same_outcome','concept_overlap','complementary','shared_commitment')"),
        CheckConstraint("source IN ('automatic','invitation')"), CheckConstraint("status IN ('active','ended')"),
        CheckConstraint("streak >= 0"),
    )
    id: Mapped[int] = mapped_column(ForeignKey("peer_matches.id", ondelete="CASCADE"), primary_key=True)
    user_a: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_b: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    match_level: Mapped[str] = mapped_column(String(32), nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False)
    match_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reranking: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)


class PairMembershipRecord(Base):
    __tablename__ = "pair_memberships"
    __table_args__ = (Index("idx_pair_memberships_pair", "pair_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), nullable=False)


class PairInvitationRecord(Base):
    __tablename__ = "pair_invitations"
    __table_args__ = (
        CheckConstraint("status IN ('pending','used','revoked')"),
        CheckConstraint("target_user_id IS NULL OR target_user_id != owner_user_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pairs.id"))


class PairQueueRecord(Base):
    __tablename__ = "pair_match_queue"
    __table_args__ = (CheckConstraint("status IN ('waiting','paired','cancelled')"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    waiting_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
