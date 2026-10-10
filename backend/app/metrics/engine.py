from datetime import date, datetime, timedelta
from math import isclose, isfinite
from typing import TypeVar

from ..onboarding.catalog import get_concept
from .adapters import InputUnavailableError
from .config import DEFAULT_CONFIG, RISK_WEIGHTS, MeasurementConfig
from .contracts import DropoutRisk, LearnerProgress, MeasurementInput, PairMetrics, PlanWorkload, RiskFeature
from .time import require_aware, study_date, study_day_end

T = TypeVar("T")


def distinct_records(records: list[T]) -> list[T]:
    by_id = {}
    for record in records:
        key = getattr(record, "id")
        if key in by_id and record != by_id[key]:
            raise ValueError("Conflicting duplicate source record")
        by_id[key] = record
    return list(by_id.values())


def pacing(user_id: int, items: list[PlanWorkload], completed_ids: set[str], day: date) -> LearnerProgress:
    active = [item for item in distinct_records(items) if item.user_id == user_id and not item.cancelled]
    completed = sum(item.estimated_minutes for item in active if item.id in completed_ids)
    due = sum(item.estimated_minutes for item in active if item.due_date <= day)
    if not isfinite(completed) or not isfinite(due):
        raise ValueError("Workload sum must remain finite")
    # No due workload is neutral, explicitly flagged; early completed future work is credited, with no ratio cap.
    ratio = completed / due if due else 1.0
    return LearnerProgress(user_id=user_id, completed_minutes=completed, due_minutes=due, pacing=ratio,
                           has_due_workload=due > 0, plan_item_count=len(active))


def pair_streak(days_a: set[date], days_b: set[date], day: date) -> int:
    mutual = days_a & days_b
    cursor = day if day in mutual else day - timedelta(days=1)
    result = 0
    while cursor in mutual:
        result += 1
        cursor -= timedelta(days=1)
    return result


def dropout_risk(progress: LearnerProgress, days: set[date], partner_days: set[date], start: date,
                 day: date, reminder_responded: bool | None = None, theta_stagnant: bool | None = None,
                 config: MeasurementConfig = DEFAULT_CONFIG) -> DropoutRisk:
    last = max(days) if days else start
    absence = max(0, (day - last).days)
    window = config.frequency_window_days
    current_count = len([d for d in days if day - timedelta(days=window - 1) <= d <= day])
    previous_count = len([d for d in days if day - timedelta(days=2 * window - 1) <= d < day - timedelta(days=window - 1)])
    enough_history = (day - start).days >= 2 * window - 1
    decline = max(0, (previous_count - current_count) / previous_count) if enough_history and previous_count else None
    partner_last = max(partner_days) if partner_days else start
    components: dict[RiskFeature, float | None] = {
        "absence": min(1.0, absence / config.absence_saturation_days),
        "frequency_decline": decline,
        "pacing_deficit": max(0.0, 1 - progress.pacing) if progress.has_due_workload else None,
        "partner_inactivity": float((day - partner_last).days >= config.absence_attention_days),
        "reminder_nonresponse": float(not reminder_responded) if reminder_responded is not None else None,
        "theta_stagnation": float(theta_stagnant) if theta_stagnant is not None else None,
    }
    observed_weight = sum(RISK_WEIGHTS[key] for key, value in components.items() if value is not None)
    weighted = sum(RISK_WEIGHTS[key] * value for key, value in components.items() if value is not None)
    return DropoutRisk(score=weighted if observed_weight else None, observed_weight=observed_weight,
                       upper_bound=min(1.0, weighted + 1 - observed_weight), components=components,
                       reasons=[key for key, value in components.items() if value is not None and value > 0])


def compute_metrics(facts: MeasurementInput, day: date, known_at: datetime,
                    config: MeasurementConfig = DEFAULT_CONFIG) -> PairMetrics:
    require_aware(known_at)
    if not facts.plans_ready or not facts.history_complete:
        raise InputUnavailableError("Confirmed plan and complete check-in history are required")
    pair = facts.pair
    if pair.started_at > known_at or day < study_date(pair.started_at) or day > study_date(known_at):
        raise ValueError("Study date is outside the pair's observed lifetime")
    members = {pair.user_a, pair.user_b}
    items = distinct_records(facts.plan_items)
    checkins = distinct_records(facts.checkins)
    for item in items:
        get_concept(item.concept_id)
    if any(item.pair_id != pair.pair_id or item.user_id not in members for item in [*items, *checkins]):
        raise ValueError("Foreign pair/member facts cannot enter measurement")
    indexed = {item.id: item for item in items}
    completed: set[str] = set()
    days = {user_id: set() for user_id in members}
    unlinked = 0
    end = study_day_end(day)
    for item in items:
        if (item.completed_at is not None and pair.started_at <= item.completed_at <= known_at
                and item.completed_at < end):
            completed.add(item.id)
    for checkin in checkins:
        if (checkin.status != "done" or checkin.finalized_at is None or checkin.finalized_at > known_at
                or checkin.created_at < pair.started_at or checkin.created_at > known_at or checkin.created_at >= end):
            continue
        days[checkin.user_id].add(study_date(checkin.created_at))
        linked = indexed.get(checkin.plan_item_id)
        if linked is None:
            unlinked += 1
        elif linked.user_id != checkin.user_id:
            raise ValueError("Check-in cannot complete another member's plan item")
        else:
            completed.add(linked.id)
    a = pacing(pair.user_a, items, completed, day)
    b = pacing(pair.user_b, items, completed, day)
    observations = {}
    for observation in facts.risk_observations:
        if observation.user_id not in members:
            raise ValueError("Foreign risk observation")
        if pair.started_at <= observation.observed_at <= known_at and observation.observed_at < end:
            old = observations.get(observation.user_id)
            if old is None or observation.observed_at > old.observed_at:
                observations[observation.user_id] = observation
            elif observation.observed_at == old.observed_at and observation != old:
                raise ValueError("Conflicting risk observations")
    start = study_date(pair.started_at)

    def risk(progress: LearnerProgress, partner_id: int) -> DropoutRisk:
        observation = observations.get(progress.user_id)
        return dropout_risk(progress, days[progress.user_id], days[partner_id], start, day,
                            observation.latest_reminder_responded if observation else None,
                            observation.theta_stagnant if observation else None, config)

    low = [p.user_id for p in (a, b) if p.has_due_workload and p.pacing < config.low_pacing_threshold]
    absent = [u for u in sorted(members) if (day - (max(days[u]) if days[u] else start)).days >= config.absence_attention_days]
    gap = abs(a.pacing - b.pacing)
    gap_exceeds = gap > config.gap_threshold and not isclose(gap, config.gap_threshold, rel_tol=0, abs_tol=1e-12)
    return PairMetrics(pair_id=pair.pair_id, pair_started_at=pair.started_at, study_date=day, computed_at=known_at,
                       source_revision=facts.source_revision, learner_a=a, learner_b=b, pacing_a=a.pacing, pacing_b=b.pacing,
                       pair_score=min(a.pacing, b.pacing), gap=gap,
                       lagging_member=a.user_id if a.pacing < b.pacing else b.user_id if b.pacing < a.pacing else None,
                       needs_attention=bool(low or absent or gap_exceeds), low_pacing_members=low, absent_members=absent,
                       gap_exceeds_threshold=gap_exceeds, risk_a=risk(a, b.user_id), risk_b=risk(b, a.user_id),
                       streak=pair_streak(days[a.user_id], days[b.user_id], day), unlinked_done_checkins=unlinked)
