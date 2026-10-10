from datetime import UTC, date, datetime, timedelta
from math import inf, nan

import pytest
from app.metrics.adapters import InputUnavailableError
from app.metrics.config import RISK_WEIGHTS, MeasurementConfig
from app.metrics.contracts import (
    FinalizedCheckin,
    LearnerProgress,
    MeasurementInput,
    PairContext,
    PlanWorkload,
    RiskObservation,
)
from app.metrics.engine import compute_metrics, dropout_risk, pacing, pair_streak
from app.metrics.time import study_date, study_day_end
from pydantic import ValidationError

DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
START = datetime(2026, 9, 1, 6, tzinfo=UTC)


def plan(item_id="a", user=1, minutes=60, due=DAY, **kwargs):
    return PlanWorkload(id=item_id, user_id=user, pair_id=1, concept_id="sql.join",
                        estimated_minutes=minutes, due_date=due, **kwargs)


def checkin(checkin_id="c", user=1, item="a", at=NOW, status="done", **kwargs):
    return FinalizedCheckin(id=checkin_id, user_id=user, pair_id=1, plan_item_id=item,
                            created_at=at, finalized_at=at if status == "done" else None, status=status, **kwargs)


def facts(items=None, checkins=None, **kwargs):
    return MeasurementInput(pair=PairContext(pair_id=1, user_a=1, user_b=2, started_at=START),
                            source_revision="fixture.1", plans_ready=True, history_complete=True,
                            plan_items=items if items is not None else [plan(), plan("b", 2)],
                            checkins=checkins or [], **kwargs)


@pytest.mark.parametrize("timestamp,expected", [
    ("2026-10-06T02:59:59+07:00", "2026-10-05"),
    ("2026-10-06T03:00:00+07:00", "2026-10-06"),
    ("2026-10-06T03:00:01+07:00", "2026-10-06"),
    ("2026-10-05T20:00:00+00:00", "2026-10-06"),
    ("2026-11-01T02:00:00+07:00", "2026-10-31"),
    ("2027-01-01T02:00:00+07:00", "2026-12-31"),
    ("2026-10-06T04:00:00+08:00", "2026-10-06"),
])
def test_study_day_boundaries(timestamp, expected):
    assert study_date(datetime.fromisoformat(timestamp)).isoformat() == expected


def test_naive_business_time_rejected_and_exclusive_day_end():
    with pytest.raises(ValueError, match="timezone"):
        study_date(datetime(2026, 10, 6))
    assert study_day_end(DAY).isoformat() == "2026-10-07T03:00:00+07:00"
    assert study_date(study_day_end(DAY) - timedelta(microseconds=1)) == DAY
    assert study_date(study_day_end(DAY)) == DAY + timedelta(days=1)


def test_workload_ratio_uses_minutes_instead_of_task_count():
    result = compute_metrics(facts([plan(minutes=90), plan("a2", minutes=30), plan("b", 2)], [checkin()]), DAY, NOW)
    assert result.learner_a.completed_minutes == 90
    assert result.learner_a.due_minutes == 120
    assert result.pacing_a == .75
    assert result.pair_score == 0 and result.gap == .75


@pytest.mark.parametrize("a,b", [(1, 1), (1, .5), (.2, .8), (0, 0), (2, .5), (.7, 1)])
def test_pair_score_gap_invariants_and_lagging_member(a, b):
    items = [plan(minutes=100), plan("b", 2, minutes=100),
             plan("ac", minutes=100 * a, due=DAY + timedelta(days=1)) if a else plan("ac", cancelled=True),
             plan("bc", 2, minutes=100 * b, due=DAY + timedelta(days=1)) if b else plan("bc", 2, cancelled=True)]
    evidence = ([checkin(item="ac")] if a else []) + ([checkin("d", 2, "bc")] if b else [])
    result = compute_metrics(facts(items, evidence), DAY, NOW)
    assert result.pacing_a == a and result.pacing_b == b
    assert result.pair_score == min(a, b)
    assert result.gap == abs(a - b)
    assert result.lagging_member == (1 if a < b else 2 if b < a else None)


def test_early_completed_future_work_is_credited_without_cap():
    items = [plan(), plan("early", minutes=120, due=DAY + timedelta(days=2))]
    result = compute_metrics(facts(items, [checkin(), checkin("early-c", item="early")]), DAY, NOW)
    assert result.learner_a.completed_minutes == 180
    assert result.learner_a.due_minutes == 60
    assert result.pacing_a == 3


@pytest.mark.parametrize("items", [[], [plan(due=DAY + timedelta(days=1))], [plan(cancelled=True)]])
def test_no_due_workload_neutral_and_explicitly_flagged(items):
    result = compute_metrics(facts(items), DAY, NOW)
    assert result.pacing_a == 1
    assert result.learner_a.due_minutes == 0
    assert result.learner_a.has_due_workload is False
    assert result.risk_a.components["pacing_deficit"] is None
    assert 1 not in result.low_pacing_members


def test_overdue_incomplete_and_today_included_future_excluded():
    result = pacing(1, [plan(due=DAY - timedelta(days=4)), plan("today", minutes=30),
                        plan("future", minutes=90, due=DAY + timedelta(days=1))], set(), DAY)
    assert result.due_minutes == 90 and result.completed_minutes == 0 and result.pacing == 0


def test_duplicate_checkins_plan_records_and_completion_timestamp_count_once():
    item = plan(completed_at=NOW)
    evidence = [checkin(), checkin(), checkin("second"), checkin("third")]
    result = compute_metrics(facts([item, item, plan("b", 2)], evidence), DAY, NOW)
    assert result.learner_a.completed_minutes == 60 and result.pacing_a == 1
    assert result.streak == 0
    assert compute_metrics(facts([item, item, plan("b", 2)], evidence), DAY, NOW) == result


@pytest.mark.parametrize("status", ["processing", "needs_confirm", "not_study", "failed"])
def test_non_finalized_done_never_counts(status):
    result = compute_metrics(facts(checkins=[checkin(status=status)]), DAY, NOW)
    assert result.pacing_a == 0 and result.streak == 0


def test_unlinked_done_counts_presence_not_workload():
    result = compute_metrics(facts(checkins=[checkin(item=None), checkin("unknown", item="missing"),
                                           checkin("b", 2, None)]), DAY, NOW)
    assert result.pacing_a == 0 and result.pacing_b == 0
    assert result.streak == 1 and result.unlinked_done_checkins == 3


def test_historical_day_uses_created_at_finalization_known_at_and_exclusive_end():
    before = datetime.fromisoformat("2026-10-07T02:59:59+07:00")
    boundary = before + timedelta(seconds=1)
    evidence = [FinalizedCheckin(id="late", user_id=1, pair_id=1, plan_item_id="a", status="done",
                               created_at=before, finalized_at=boundary + timedelta(hours=1)),
                checkin("at-boundary", 2, "b", boundary)]
    early = compute_metrics(facts(checkins=evidence), DAY, before)
    assert early.pacing_a == early.pacing_b == 0
    later = compute_metrics(facts(checkins=evidence), DAY, boundary + timedelta(hours=2))
    assert later.pacing_a == 1 and later.pacing_b == 0


def test_pair_reactivation_ignores_previous_cycle_and_future_completion():
    source = facts(checkins=[checkin(at=START - timedelta(days=1)), checkin("future", at=NOW + timedelta(days=1))])
    result = compute_metrics(source, DAY, NOW)
    assert result.pacing_a == 0


@pytest.mark.parametrize("bad", ["foreign_pair", "foreign_member", "cross_member_link", "duplicate_plan", "duplicate_checkin", "unknown_concept"])
def test_invalid_source_facts_rejected(bad):
    source = facts(checkins=[checkin()])
    if bad == "foreign_pair":
        source.plan_items[0].pair_id = 99
    elif bad == "foreign_member":
        source.checkins[0].user_id = 99
    elif bad == "cross_member_link":
        source.checkins[0].plan_item_id = "b"
    elif bad == "duplicate_plan":
        source.plan_items.append(plan(minutes=45))
    elif bad == "duplicate_checkin":
        source.checkins.append(checkin(item=None))
    else:
        source.plan_items[0].concept_id = "unknown.fake"
    with pytest.raises((ValueError, KeyError)):
        compute_metrics(source, DAY, NOW)


@pytest.mark.parametrize("field", ["plans_ready", "history_complete"])
def test_incomplete_inputs_do_not_fabricate_metrics(field):
    source = facts()
    setattr(source, field, False)
    with pytest.raises(InputUnavailableError):
        compute_metrics(source, DAY, NOW)


@pytest.mark.parametrize("minutes", [0, -1, inf, nan])
def test_invalid_workload_rejected(minutes):
    with pytest.raises(ValidationError):
        plan(minutes=minutes)


@pytest.mark.parametrize("day", [date(2026, 8, 31), date(2026, 10, 7)])
def test_unobserved_dates_rejected(day):
    with pytest.raises(ValueError):
        compute_metrics(facts(), day, NOW)


@pytest.mark.parametrize("a,b,expected", [
    ({DAY}, {DAY}, 1), ({DAY, DAY - timedelta(days=1)}, {DAY, DAY - timedelta(days=1)}, 2),
    ({DAY - timedelta(days=1)}, {DAY - timedelta(days=1)}, 1),
    ({DAY}, {DAY - timedelta(days=1)}, 0), (set(), set(), 0),
])
def test_mutual_streak_once_per_study_day_and_open_day_grace(a, b, expected):
    assert pair_streak(a, b, DAY) == expected


def test_missing_day_breaks_streak_and_repeated_checkins_do_not_inflate():
    records = [checkin("a1"), checkin("a2"), checkin("b1", 2, "b"), checkin("b2", 2, "b")]
    assert compute_metrics(facts(checkins=records), DAY, NOW).streak == 1
    assert pair_streak({DAY - timedelta(days=2)}, {DAY - timedelta(days=2)}, DAY) == 0


@pytest.mark.parametrize("ratio,expected", [(.699, True), (.7, False), (.701, False)])
def test_low_pacing_strict_threshold(ratio, expected):
    source = facts([plan(minutes=100), plan("credit", minutes=ratio * 100, due=DAY + timedelta(days=1))],
                   [checkin(item="credit"), checkin("b", 2, None)])
    result = compute_metrics(source, DAY, NOW)
    assert (1 in result.low_pacing_members) is expected


@pytest.mark.parametrize("ratio,expected", [(.7, False), (.6999, True), (.7001, False)])
def test_gap_strict_threshold_and_binary_float_boundary(ratio, expected):
    source = facts([plan(minutes=100), plan("credit", minutes=ratio * 100, due=DAY + timedelta(days=1))],
                   [checkin(item="credit"), checkin("b", 2, None)])
    assert compute_metrics(source, DAY, NOW).gap_exceeds_threshold is expected


def test_absence_attention_exact_two_day_boundary():
    for missing, expected in [(1, []), (2, [1, 2])]:
        result = compute_metrics(facts([], [checkin(at=NOW - timedelta(days=missing), item=None),
                                           checkin("b", 2, None, NOW - timedelta(days=missing))]), DAY, NOW)
        assert result.absent_members == expected


def progress(ratio=0, due=True):
    return LearnerProgress(user_id=1, completed_minutes=ratio * 100, due_minutes=100 if due else 0,
                           pacing=ratio, has_due_workload=due, plan_item_count=1)


def test_risk_exact_all_six_components_and_weights():
    previous = {DAY - timedelta(days=n) for n in range(7, 14)}
    result = dropout_risk(progress(), previous, set(), DAY - timedelta(days=20), DAY, False, True)
    assert dict(RISK_WEIGHTS) == {"absence": .25, "frequency_decline": .15, "pacing_deficit": .25,
                                 "partner_inactivity": .15, "reminder_nonresponse": .1, "theta_stagnation": .1}
    assert all(value == 1 for value in result.components.values())
    assert result.score == 1 and result.observed_weight == 1 and result.upper_bound == 1
    assert result.reasons == list(RISK_WEIGHTS)


@pytest.mark.parametrize("absence,normalized", [(0, 0), (2, 2 / 7), (7, 1), (9, 1)])
def test_risk_absence_saturation(absence, normalized):
    result = dropout_risk(progress(1), {DAY - timedelta(days=absence)}, {DAY}, DAY - timedelta(days=10), DAY)
    assert result.components["absence"] == normalized
    assert result.score == pytest.approx(.25 * normalized)


@pytest.mark.parametrize("ratio,deficit", [(0, 1), (.5, .5), (.7, .3), (1, 0), (2, 0)])
def test_risk_pacing_component(ratio, deficit):
    result = dropout_risk(progress(ratio), {DAY}, {DAY}, DAY, DAY)
    assert result.components["pacing_deficit"] == pytest.approx(deficit)
    assert result.score == pytest.approx(.25 * deficit)


@pytest.mark.parametrize("responded,stagnant,expected", [(True, False, 0), (False, False, .1), (True, True, .1), (False, True, .2)])
def test_risk_explicit_optional_observations(responded, stagnant, expected):
    result = dropout_risk(progress(1), {DAY}, {DAY}, DAY, DAY, responded, stagnant)
    assert result.score == expected


def test_risk_missing_optional_unknown_not_synthetic_false_and_upper_bound():
    result = dropout_risk(progress(1, due=False), {DAY}, {DAY}, DAY, DAY)
    assert result.components["frequency_decline"] is None
    assert result.components["reminder_nonresponse"] is None
    assert result.components["theta_stagnation"] is None
    assert result.score == 0 and result.observed_weight == .4
    assert result.upper_bound == .6


def test_risk_frequency_unique_days_decline_and_increase():
    previous = {DAY - timedelta(days=n) for n in range(7, 11)}
    current = {DAY, DAY - timedelta(days=1)}
    result = dropout_risk(progress(1), previous | current, {DAY}, DAY - timedelta(days=20), DAY)
    assert result.components["frequency_decline"] == .5
    assert result.score == .075
    assert dropout_risk(progress(1), {DAY}, {DAY}, DAY - timedelta(days=20), DAY).components["frequency_decline"] is None
    assert dropout_risk(progress(1), previous | {DAY - timedelta(days=n) for n in range(7)}, {DAY},
                        DAY - timedelta(days=20), DAY).components["frequency_decline"] == 0


@pytest.mark.parametrize("partner_absence,expected", [(1, 0), (2, 1)])
def test_risk_partner_activity_boundary(partner_absence, expected):
    result = dropout_risk(progress(1), {DAY}, {DAY - timedelta(days=partner_absence)}, DAY, DAY)
    assert result.components["partner_inactivity"] == expected


def test_risk_uses_only_latest_known_observation():
    source = facts([], [checkin(item=None), checkin("b", 2, None)], risk_observations=[
        RiskObservation(user_id=1, observed_at=NOW - timedelta(days=1), latest_reminder_responded=False),
        RiskObservation(user_id=1, observed_at=NOW, latest_reminder_responded=True, theta_stagnant=False),
        RiskObservation(user_id=1, observed_at=NOW + timedelta(days=1), latest_reminder_responded=False, theta_stagnant=True)])
    result = compute_metrics(source, DAY, NOW)
    assert result.risk_a.components["reminder_nonresponse"] == 0
    assert result.risk_a.components["theta_stagnation"] == 0
    assert 0 <= result.risk_a.score <= result.risk_a.upper_bound <= 1


@pytest.mark.parametrize("kwargs", [{"low_pacing_threshold": nan}, {"low_pacing_threshold": 2},
                                  {"gap_threshold": inf}, {"gap_threshold": -1},
                                  {"absence_saturation_days": 0}, {"frequency_window_days": 1.5}])
def test_invalid_metric_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        MeasurementConfig(**kwargs)


def test_direct_pacing_deduplicates_and_rejects_conflicting_items_and_overflow():
    item = plan()
    assert pacing(1, [item, item], {item.id}, DAY).completed_minutes == 60
    with pytest.raises(ValueError, match="duplicate"):
        pacing(1, [item, plan(minutes=30)], {item.id}, DAY)
    with pytest.raises(ValueError, match="finite"):
        pacing(1, [plan(minutes=1e308), plan("huge", minutes=1e308)], set(), DAY)


def test_conflicting_and_foreign_risk_observations_rejected():
    source = facts(risk_observations=[RiskObservation(user_id=99, observed_at=NOW)])
    with pytest.raises(ValueError, match="Foreign"):
        compute_metrics(source, DAY, NOW)
    source.risk_observations = [RiskObservation(user_id=1, observed_at=NOW, theta_stagnant=True),
                                RiskObservation(user_id=1, observed_at=NOW, theta_stagnant=False)]
    with pytest.raises(ValueError, match="Conflicting"):
        compute_metrics(source, DAY, NOW)


def test_naive_source_timestamps_and_unfinalized_done_rejected():
    with pytest.raises(ValidationError):
        PairContext(pair_id=1, user_a=1, user_b=2, started_at=datetime(2026, 10, 6))
    with pytest.raises(ValidationError, match="finalization"):
        FinalizedCheckin(id="bad", pair_id=1, user_id=1, status="done", created_at=NOW)
    with pytest.raises(ValidationError, match="precede"):
        FinalizedCheckin(id="bad", pair_id=1, user_id=1, status="done", created_at=NOW,
                         finalized_at=NOW - timedelta(seconds=1))
