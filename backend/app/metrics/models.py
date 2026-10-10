from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PairMetricRecord(Base):
    __tablename__ = "pair_metrics_daily"
    __table_args__ = (
        CheckConstraint("pacing_a >= 0"), CheckConstraint("pacing_b >= 0"),
        CheckConstraint("pair_score >= 0"), CheckConstraint("gap >= 0"),
        CheckConstraint("risk_a BETWEEN 0 AND 1"), CheckConstraint("risk_b BETWEEN 0 AND 1"),
        CheckConstraint("streak >= 0"), CheckConstraint("pair_score = min(pacing_a,pacing_b)"),
        CheckConstraint("gap = abs(pacing_a-pacing_b)"), Index("idx_pair_metrics_date", "date", "pair_id"),
    )
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    pacing_a: Mapped[float] = mapped_column(Float, nullable=False)
    pacing_b: Mapped[float] = mapped_column(Float, nullable=False)
    pair_score: Mapped[float] = mapped_column(Float, nullable=False)
    gap: Mapped[float] = mapped_column(Float, nullable=False)
    risk_a: Mapped[float | None] = mapped_column(Float)
    risk_b: Mapped[float | None] = mapped_column(Float)
    streak: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pair_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
