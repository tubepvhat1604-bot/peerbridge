from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ConceptRecord(Base):
    __tablename__ = "concepts"
    __table_args__ = (CheckConstraint("domain IN ('sql', 'python', 'ai')", name="ck_concepts_domain"),)

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisites: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    catalog_version: Mapped[str] = mapped_column(String(40), nullable=False)


class OnboardingRecord(Base):
    __tablename__ = "onboarding_profiles"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_onboarding_revision"),
        CheckConstraint("status IN ('draft', 'confirmed')", name="ck_onboarding_status"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    mappings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserConceptRecord(Base):
    __tablename__ = "user_concepts"
    __table_args__ = (
        CheckConstraint("role IN ('need', 'offer')", name="ck_user_concepts_role"),
        CheckConstraint("self_level IN ('unknown', 'learning', 'strong')", name="ck_user_concepts_level"),
        CheckConstraint("n_attempts >= 0", name="ck_user_concepts_attempts"),
        Index("idx_user_concepts_concept", "concept_id", "role"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    self_level: Mapped[str] = mapped_column(String(16), nullable=False)
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    n_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
