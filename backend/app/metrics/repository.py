import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Literal

from .contracts import PairContext, PairMetrics

WriteResult = Literal["created", "updated", "unchanged"]


class MetricsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @contextmanager
    def atomic(self) -> Iterator[None]:
        if not self.connection.in_transaction:
            self.connection.execute("BEGIN IMMEDIATE")
        self.connection.execute("SAVEPOINT data1_metric_write")
        try:
            yield
        except Exception:
            self.connection.execute("ROLLBACK TO data1_metric_write")
            self.connection.execute("RELEASE data1_metric_write")
            raise
        else:
            self.connection.execute("RELEASE data1_metric_write")

    def pair_row(self, pair_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM pairs WHERE id=?", (pair_id,)).fetchone()

    def context(self, pair_id: int) -> PairContext:
        row = self.pair_row(pair_id)
        if row is None:
            raise ValueError("Pair does not exist")
        return PairContext(pair_id=pair_id, user_a=row["user_a"], user_b=row["user_b"], started_at=row["started_at"])

    def eligible(self, pair_id: int) -> bool:
        return self.connection.execute(
            """SELECT 1 FROM pairs p WHERE p.id=? AND p.status='active'
               AND EXISTS(SELECT 1 FROM pair_memberships m WHERE m.user_id=p.user_a AND m.pair_id=p.id)
               AND EXISTS(SELECT 1 FROM pair_memberships m WHERE m.user_id=p.user_b AND m.pair_id=p.id)""",
            (pair_id,)).fetchone() is not None

    def pair_batch(self, after: int, limit: int) -> list[int]:
        return [row["id"] for row in self.connection.execute(
            "SELECT id FROM pairs WHERE id>? ORDER BY id LIMIT ?", (after, limit))]

    def save(self, metrics: PairMetrics) -> WriteResult:
        payload = metrics.model_dump_json()
        key = (metrics.pair_id, metrics.study_date.isoformat())
        row = self.connection.execute("SELECT payload FROM pair_metrics_daily WHERE pair_id=? AND date=?", key).fetchone()
        if row and row["payload"] == payload:
            return "unchanged"
        self.connection.execute(
            """INSERT INTO pair_metrics_daily(pair_id,date,pacing_a,pacing_b,pair_score,gap,risk_a,risk_b,
                 streak,metric_version,pair_started_at,payload,created_at,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(pair_id,date) DO UPDATE SET
                 pacing_a=excluded.pacing_a,pacing_b=excluded.pacing_b,pair_score=excluded.pair_score,gap=excluded.gap,
                 risk_a=excluded.risk_a,risk_b=excluded.risk_b,streak=excluded.streak,metric_version=excluded.metric_version,
                 pair_started_at=excluded.pair_started_at,payload=excluded.payload,computed_at=excluded.computed_at""",
            (*key, metrics.pacing_a, metrics.pacing_b, metrics.pair_score, metrics.gap, metrics.risk_a.score,
             metrics.risk_b.score, metrics.streak, metrics.metric_version, metrics.pair_started_at.isoformat(),
             payload, metrics.computed_at.isoformat(), metrics.computed_at.isoformat()))
        return "updated" if row else "created"

    def sync_streak(self, context: PairContext) -> None:
        latest = self.latest(context)
        if latest is not None:
            self.connection.execute("UPDATE pairs SET streak=? WHERE id=?", (latest.streak, context.pair_id))

    def latest(self, context: PairContext) -> PairMetrics | None:
        items = self.history(context, 1)
        return items[0] if items else None

    def history(self, context: PairContext, limit: int, before: date | None = None) -> list[PairMetrics]:
        rows = self.connection.execute(
            """SELECT payload FROM pair_metrics_daily WHERE pair_id=? AND pair_started_at=?
               AND (? IS NULL OR date<?) ORDER BY date DESC LIMIT ?""",
            (context.pair_id, context.started_at.isoformat(), before.isoformat() if before else None,
             before.isoformat() if before else None, limit)).fetchall()
        return [PairMetrics.model_validate_json(row["payload"]) for row in rows]
