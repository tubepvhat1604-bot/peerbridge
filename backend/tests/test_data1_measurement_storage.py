import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.db import SCHEMA as LEGACY_SCHEMA
from app.matching.schema import initialize_matching
from app.metrics.adapters import FixtureMeasurementSource, InputUnavailableError, UnavailableMeasurementSource
from app.metrics.contracts import DailyJobRequest, MeasurementInput, PairContext
from app.metrics.repository import MetricsRepository
from app.metrics.schema import initialize_metrics
from app.metrics.service import MeasurementService, MetricError
from app.metrics.time import STUDY_ZONE
from test_data1_measurement import DAY, NOW, START, checkin, facts, plan


def initialize(connection):
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(LEGACY_SCHEMA)
    initialize_matching(connection)
    initialize_metrics(connection)


def seed_pair(connection, pair_id=1, a=1, b=2, status="active", started_at=START):
    for user_id in (a, b):
        connection.execute("INSERT OR IGNORE INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                           (user_id, f"metrics-{user_id}@example.edu", "test-hash", START.isoformat()))
    connection.execute("INSERT INTO connection_requests(id,requester_id,recipient_id,status,created_at) VALUES(?,?,?,'MATCHED',?)",
                       (pair_id, a, b, START.isoformat()))
    connection.execute("INSERT INTO peer_matches(id,connection_request_id,user_a_id,user_b_id,created_at) VALUES(?,?,?,?,?)",
                       (pair_id, pair_id, a, b, START.isoformat()))
    connection.execute("""INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status)
                          VALUES(?,?,?,'complementary','fixture','{}','{}','invitation',?,?)""",
                       (pair_id, a, b, started_at.isoformat(), status))
    if status == "active":
        connection.executemany("INSERT INTO pair_memberships(user_id,pair_id) VALUES(?,?)", [(a, pair_id), (b, pair_id)])


def pair_input(repository, pair_id=1):
    context = repository.context(pair_id)
    return MeasurementInput(pair=context, source_revision="storage.1", plans_ready=True, history_complete=True,
                            plan_items=[plan().model_copy(update={"pair_id": pair_id, "user_id": context.user_a}),
                                        plan("b", 2).model_copy(update={"pair_id": pair_id, "user_id": context.user_b})],
                            checkins=[checkin().model_copy(update={"pair_id": pair_id, "user_id": context.user_a}),
                                      checkin("cb", 2, "b").model_copy(update={"pair_id": pair_id, "user_id": context.user_b})])


@pytest.fixture
def setup():
    connection = sqlite3.connect(":memory:")
    initialize(connection)
    seed_pair(connection)
    connection.commit()
    repo = MetricsRepository(connection)
    source = FixtureMeasurementSource({1: facts(checkins=[checkin(), checkin("cb", 2, "b")])})
    service = MeasurementService(repo, source, clock=lambda: NOW)
    yield connection, repo, source, service
    connection.close()


def test_snapshot_create_repeat_update_and_streak_persistence(setup):
    connection, _, source, service = setup
    first, written = service.recompute(1)
    assert written == "created" and first.pair_score == 1 and first.streak == 1
    assert service.recompute(1) == (first, "unchanged")
    source.inputs[1].checkins.pop()
    changed, written = service.recompute(1)
    assert written == "updated" and changed.pair_score == 0 and changed.gap == 1 and changed.streak == 0
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 1
    assert connection.execute("SELECT streak FROM pairs").fetchone()[0] == 0


def test_job_retry_summary_and_no_duplicates(setup):
    connection, _, _, service = setup
    first = service.daily(DailyJobRequest())
    assert first.study_date == DAY and first.pairs_processed == 1 and first.snapshots_created == 1
    second = service.daily(DailyJobRequest())
    assert second.snapshots_unchanged == 1 and second.snapshots_created == second.snapshots_updated == 0
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 1


def test_job_processes_multiple_pairs_skips_ended_missing_and_invalid_and_paginates(setup):
    connection, repo, source, service = setup
    for pair_id in range(2, 6):
        seed_pair(connection, pair_id, pair_id * 2 - 1, pair_id * 2, "ended" if pair_id == 3 else "active")
    source.inputs[2] = pair_input(repo, 2)
    source.inputs[5] = pair_input(repo, 5)
    source.inputs[5].plan_items[0].concept_id = "fake.concept"
    first = service.daily(DailyJobRequest(limit=2))
    assert first.pairs_processed == first.snapshots_created == 2 and first.next_after_pair_id == 2
    rest = service.daily(DailyJobRequest(after_pair_id=2))
    assert rest.pairs_seen == 3 and rest.skipped == 3 and rest.pairs_processed == 0
    assert rest.skip_reasons == {"inactive_or_ineligible": 1, "input_unavailable": 1, "invalid_input": 1}
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 2


def test_missing_production_adapter_does_not_seed_fake_snapshots(setup):
    connection, repo, _, _ = setup
    service = MeasurementService(repo, UnavailableMeasurementSource(), clock=lambda: NOW)
    assert service.daily(DailyJobRequest()).skip_reasons == {"input_unavailable": 1}
    with pytest.raises(InputUnavailableError):
        service.recompute(1)
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 0


def test_job_clock_cutoff_and_future_date_rejected(setup):
    _, _, _, service = setup
    service.clock = lambda: NOW.replace(hour=19, minute=59)  # 02:59 next calendar day in HCM
    assert service.daily(DailyJobRequest()).study_date == DAY
    service.clock = lambda: NOW.replace(hour=20, minute=0)
    assert service.daily(DailyJobRequest()).study_date == DAY + timedelta(days=1)
    with pytest.raises(MetricError, match="Future"):
        service.daily(DailyJobRequest(study_date=DAY + timedelta(days=2)))


def test_job_skips_day_before_pair_start(setup):
    _, _, _, service = setup
    result = service.daily(DailyJobRequest(study_date=START.date() - timedelta(days=1)))
    assert result.skip_reasons == {"before_pair_start": 1}


def test_ineligible_pair_membership_and_ended_pair_do_not_refresh(setup):
    connection, _, _, service = setup
    connection.execute("DELETE FROM pair_memberships WHERE user_id=2")
    with pytest.raises(MetricError, match="active pair"):
        service.recompute(1)
    assert service.daily(DailyJobRequest()).skip_reasons == {"inactive_or_ineligible": 1}


def test_transaction_failure_rolls_back_snapshot_and_streak_even_if_caught(setup, monkeypatch):
    connection, repo, _, service = setup
    original = repo.sync_streak

    def broken(context):
        original(context)
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(repo, "sync_streak", broken)
    with pytest.raises(RuntimeError, match="injected"):
        service.recompute(1)
    connection.commit()
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 0
    assert connection.execute("SELECT streak FROM pairs").fetchone()[0] == 0


def test_historical_recompute_does_not_overwrite_current_streak_and_history_sorted(setup):
    connection, repo, source, service = setup
    source.inputs[1].checkins += [checkin("prev-a", at=NOW - timedelta(days=1)),
                                 checkin("prev-b", 2, "b", NOW - timedelta(days=1))]
    service.recompute(1)
    service.recompute(1, DAY - timedelta(days=1))
    assert connection.execute("SELECT streak FROM pairs").fetchone()[0] == 2
    history = repo.history(repo.context(1), 90)
    assert [m.study_date for m in history] == [DAY, DAY - timedelta(days=1)]
    assert repo.history(repo.context(1), 90, before=DAY)[0].streak == 1


def test_reactivated_pair_never_reads_previous_cycle_metrics_and_stale_source_rejected(setup):
    connection, repo, source, service = setup
    service.recompute(1)
    new_start = NOW - timedelta(hours=1)
    connection.execute("UPDATE pairs SET started_at=?,streak=0 WHERE id=1", (new_start.isoformat(),))
    with pytest.raises(MetricError, match="No measurement"):
        service.current(1)
    with pytest.raises(ValueError, match="generation"):
        service.recompute(1)
    source.inputs[1].pair = PairContext(pair_id=1, user_a=1, user_b=2, started_at=new_start)
    assert service.recompute(1)[1] == "updated"
    assert repo.history(repo.context(1), 90)[0].pair_started_at == new_start


def test_custom_adapter_cannot_spoof_context(setup):
    _, repo, _, _ = setup

    class WrongSource:
        def load(self, pair, known_at):
            result = facts()
            result.pair.pair_id = 99
            return result

    with pytest.raises(ValueError, match="stale or foreign"):
        MeasurementService(repo, WrongSource(), clock=lambda: NOW).recompute(1)


def test_equivalent_offset_pair_timestamp_uses_authoritative_lifecycle_key(setup):
    connection, repo, source, service = setup
    source.inputs[1].pair.started_at = START.astimezone(STUDY_ZONE)
    result, _ = service.recompute(1)
    assert service.current(1) == result
    assert repo.history(repo.context(1), 1) == [result]
    assert connection.execute("SELECT pair_started_at FROM pair_metrics_daily").fetchone()[0] == START.isoformat()


def test_vision_hook_uses_same_engine_refreshes_historical_and_current(setup):
    connection, _, source, service = setup
    late = checkin("late-a", at=NOW - timedelta(days=1))
    late.finalized_at = NOW
    source.inputs[1].checkins.append(late)
    result = service.after_finalized_checkin(late)
    assert result == service.current(1)
    assert result.pair_score == 1
    assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 2


def test_vision_trigger_without_committed_source_evidence_cannot_inject_workload(setup):
    _, _, source, service = setup
    source.inputs[1].checkins = []
    result = service.after_finalized_checkin(checkin())
    assert result.pair_score == 0 and result.streak == 0
    with pytest.raises(MetricError, match="finalized"):
        service.after_finalized_checkin(checkin(status="needs_confirm"))


def test_snapshot_sql_constraints_and_shared_peer_identity(setup):
    connection, _, _, service = setup
    service.recompute(1)
    assert connection.execute("SELECT m.pair_id FROM pair_metrics_daily m JOIN peer_matches p ON p.id=m.pair_id").fetchone()[0] == 1
    for assignment in ("pair_score=9", "gap=9", "risk_a=1.1", "streak=-1"):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(f"UPDATE pair_metrics_daily SET {assignment}")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO pair_metrics_daily SELECT * FROM pair_metrics_daily")


def test_concurrent_recomputations_create_one_daily_row(tmp_path):
    path = tmp_path / "concurrent.db"
    connection = sqlite3.connect(path)
    initialize(connection)
    seed_pair(connection)
    connection.commit()
    connection.close()

    def run(_):
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            service = MeasurementService(MetricsRepository(conn), FixtureMeasurementSource({1: facts()}), clock=lambda: NOW)
            _, state = service.recompute(1)
            conn.commit()
            return state
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ["created", "unchanged"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 1
