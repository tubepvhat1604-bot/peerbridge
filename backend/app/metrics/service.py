from collections.abc import Callable, Generator
from datetime import UTC, date, datetime

from fastapi import Depends
from pydantic import ValidationError

from ..db import database
from .adapters import InputUnavailableError, MeasurementSource, get_measurement_source
from .contracts import DailyJobRequest, DailyJobResult, FinalizedCheckin, PairMetrics
from .engine import compute_metrics
from .repository import MetricsRepository, WriteResult
from .time import require_aware, study_date


class MetricError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def utc_clock() -> datetime:
    return datetime.now(UTC)


class MeasurementService:
    def __init__(self, repository: MetricsRepository, source: MeasurementSource,
                 clock: Callable[[], datetime] = utc_clock) -> None:
        self.repository, self.source, self.clock = repository, source, clock

    def authorize(self, pair_id: int, user_id: int) -> None:
        row = self.repository.pair_row(pair_id)
        if row is None:
            raise MetricError(404, "Pair not found")
        if user_id not in (row["user_a"], row["user_b"]):
            raise MetricError(403, "Pair membership required")

    def current(self, pair_id: int) -> PairMetrics:
        if self.repository.pair_row(pair_id) is None:
            raise MetricError(404, "Pair not found")
        snapshot = self.repository.latest(self.repository.context(pair_id))
        if snapshot is None:
            raise MetricError(404, "No measurement snapshot is available")
        return snapshot

    def recompute(self, pair_id: int, day: date | None = None, *, known_at: datetime | None = None
                  ) -> tuple[PairMetrics, WriteResult]:
        """Trusted backend hook; HTTP callers must authorize first. Writes commit with caller transaction."""
        now = require_aware(known_at if known_at is not None else self.clock())
        target = day or study_date(now)
        if target > study_date(now):
            raise MetricError(422, "Future study dates cannot be computed")
        with self.repository.atomic():
            if not self.repository.eligible(pair_id):
                raise MetricError(409, "An active pair with both memberships is required")
            context = self.repository.context(pair_id)
            facts = self.source.load(context, now)
            if facts.pair != context:
                raise ValueError("Measurement source returned stale or foreign pair facts")
            # Datetimes can be equal with different offsets; persisted lifecycle keys use the authoritative representation.
            facts = facts.model_copy(update={"pair": context})
            result = compute_metrics(facts, target, now)
            written = self.repository.save(result)
            self.repository.sync_streak(context)
            return result, written

    def after_finalized_checkin(self, checkin: FinalizedCheckin) -> PairMetrics:
        """Vision calls AFTER authoritative evidence commits; event is a trigger, never the workload source."""
        now = require_aware(self.clock())
        self.authorize(checkin.pair_id, checkin.user_id)
        if checkin.status != "done" or checkin.finalized_at is None or checkin.finalized_at > now:
            raise MetricError(422, "A finalized done check-in is required")
        with self.repository.atomic():
            self.recompute(checkin.pair_id, study_date(checkin.created_at), known_at=now)
            if study_date(checkin.created_at) != study_date(now):
                self.recompute(checkin.pair_id, study_date(now), known_at=now)
            return self.current(checkin.pair_id)

    def daily(self, request: DailyJobRequest) -> DailyJobResult:
        now = require_aware(self.clock())
        target = request.study_date or study_date(now)
        if target > study_date(now):
            raise MetricError(422, "Future study dates cannot be computed")
        result = DailyJobResult(study_date=target)
        batch = self.repository.pair_batch(request.after_pair_id, request.limit + 1)
        if len(batch) > request.limit:
            result.next_after_pair_id = batch[request.limit - 1]
        for pair_id in batch[:request.limit]:
            result.pairs_seen += 1
            reason = None
            if not self.repository.eligible(pair_id):
                reason = "inactive_or_ineligible"
            elif target < study_date(self.repository.context(pair_id).started_at):
                reason = "before_pair_start"
            else:
                try:
                    _, written = self.recompute(pair_id, target, known_at=now)
                except InputUnavailableError:
                    reason = "input_unavailable"
                except (ValueError, ValidationError):
                    reason = "invalid_input"
                else:
                    result.pairs_processed += 1
                    field = f"snapshots_{written}"
                    setattr(result, field, getattr(result, field) + 1)
            if reason:
                result.skipped += 1
                result.skip_reasons[reason] = result.skip_reasons.get(reason, 0) + 1
        return result


def get_measurement_service(source: MeasurementSource = Depends(get_measurement_source)
                            ) -> Generator[MeasurementService, None, None]:
    with database() as connection:
        yield MeasurementService(MetricsRepository(connection), source)
