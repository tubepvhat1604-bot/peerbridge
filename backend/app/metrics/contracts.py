from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from ..onboarding.contracts import StrictModel
from .time import require_aware

METRIC_VERSION = "data1.metrics.v1"
PACING_VERSION = "workload_ratio.v1"
RISK_VERSION = "dropout.manual.v0.1"
Nonnegative = Annotated[float, Field(ge=0)]
UnitScore = Annotated[float, Field(ge=0, le=1)]
RiskFeature = Literal["absence", "frequency_decline", "pacing_deficit", "partner_inactivity",
                      "reminder_nonresponse", "theta_stagnation"]


class PairContext(StrictModel):
    pair_id: int = Field(gt=0)
    user_a: int = Field(gt=0)
    user_b: int = Field(gt=0)
    started_at: datetime

    _aware = field_validator("started_at")(require_aware)

    @model_validator(mode="after")
    def different_members(self) -> "PairContext":
        if self.user_a >= self.user_b:
            raise ValueError("Pair members must be ordered distinct IDs")
        return self


class PlanWorkload(StrictModel):
    """Adapter DTO; does not create a planner table or infer completion from un-timestamped status."""
    id: str = Field(min_length=1, max_length=120)
    user_id: int = Field(gt=0)
    pair_id: int = Field(gt=0)
    concept_id: str
    estimated_minutes: float = Field(gt=0)
    due_date: date
    cancelled: bool = False
    completed_at: datetime | None = None

    @field_validator("completed_at")
    @classmethod
    def aware_completion(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class FinalizedCheckin(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    user_id: int = Field(gt=0)
    pair_id: int = Field(gt=0)
    plan_item_id: str | None = Field(default=None, max_length=120)
    status: Literal["processing", "needs_confirm", "done", "not_study", "failed"]
    created_at: datetime
    finalized_at: datetime | None = None

    _created_aware = field_validator("created_at")(require_aware)

    @model_validator(mode="after")
    def finalization(self) -> "FinalizedCheckin":
        if self.finalized_at is not None:
            require_aware(self.finalized_at)
            if self.finalized_at < self.created_at:
                raise ValueError("Finalization cannot precede check-in creation")
        if self.status == "done" and self.finalized_at is None:
            raise ValueError("Done evidence requires an explicit finalization timestamp")
        return self


class RiskObservation(StrictModel):
    user_id: int = Field(gt=0)
    observed_at: datetime
    latest_reminder_responded: bool | None = None
    theta_stagnant: bool | None = None

    _aware = field_validator("observed_at")(require_aware)


class MeasurementInput(StrictModel):
    pair: PairContext
    source_revision: str = Field(min_length=1, max_length=120)
    plans_ready: bool
    history_complete: bool
    plan_items: list[PlanWorkload]
    checkins: list[FinalizedCheckin]
    risk_observations: list[RiskObservation] = Field(default_factory=list)


class LearnerProgress(StrictModel):
    version: str = PACING_VERSION
    user_id: int = Field(gt=0)
    completed_minutes: Nonnegative
    due_minutes: Nonnegative
    pacing: Nonnegative
    has_due_workload: bool
    plan_item_count: int = Field(ge=0)


class DropoutRisk(StrictModel):
    version: str = RISK_VERSION
    score: UnitScore | None
    observed_weight: UnitScore
    upper_bound: UnitScore
    components: dict[RiskFeature, UnitScore | None]
    reasons: list[RiskFeature]


class MetricValues(StrictModel):
    metric_version: str = METRIC_VERSION
    pair_id: int = Field(gt=0)
    pair_started_at: datetime
    study_date: date
    computed_at: datetime
    source_revision: str
    learner_a: LearnerProgress
    learner_b: LearnerProgress
    pacing_a: Nonnegative
    pacing_b: Nonnegative
    pair_score: Nonnegative
    gap: Nonnegative
    lagging_member: int | None
    needs_attention: bool
    low_pacing_members: list[int]
    absent_members: list[int]
    gap_exceeds_threshold: bool
    streak: int = Field(ge=0)
    unlinked_done_checkins: int = Field(ge=0)


class PairMetrics(MetricValues):
    risk_a: DropoutRisk
    risk_b: DropoutRisk

    @model_validator(mode="after")
    def invariants(self) -> "PairMetrics":
        require_aware(self.computed_at)
        require_aware(self.pair_started_at)
        if self.pacing_a != self.learner_a.pacing or self.pacing_b != self.learner_b.pacing:
            raise ValueError("Pacing must agree with learner measurements")
        if self.pair_score != min(self.pacing_a, self.pacing_b) or self.gap != abs(self.pacing_a - self.pacing_b):
            raise ValueError("Pair score/gap invariants failed")
        return self


class RiskSummary(StrictModel):
    version: str
    score: UnitScore | None
    observed_weight: UnitScore
    upper_bound: UnitScore


class MetricView(MetricValues):
    """Member API omits private reminder/theta observations and internal risk components."""
    risk_a: RiskSummary
    risk_b: RiskSummary

    @classmethod
    def from_metrics(cls, metrics: PairMetrics) -> "MetricView":
        data = metrics.model_dump()
        for field in ("risk_a", "risk_b"):
            data[field] = {key: value for key, value in data[field].items() if key not in ("components", "reasons")}
        return cls.model_validate(data)


class MetricHistory(StrictModel):
    metric_version: str = METRIC_VERSION
    pair_id: int
    items: list[MetricView]


class DailyJobRequest(StrictModel):
    study_date: date | None = None
    after_pair_id: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class DailyJobResult(StrictModel):
    metric_version: str = METRIC_VERSION
    study_date: date
    pairs_seen: int = 0
    pairs_processed: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    snapshots_unchanged: int = 0
    skipped: int = 0
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    next_after_pair_id: int | None = None
