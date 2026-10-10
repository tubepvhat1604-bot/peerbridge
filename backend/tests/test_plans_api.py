"""Actual HTTP/SQLite flow, isolated DB and deterministic fake providers only."""

import json
from datetime import timedelta

import pytest
from app.agents.plan_coach.contract import GenerateRequest
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.llm import FakeLLM, PlanSettings
from app.config import get_settings
from app.db import database, init_db
from app.main import app
from app.security import create_token
from app.services.plans import PlanService, get_plan_service
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    monkeypatch.setenv("JWT_SECRET", "plan-tests-only")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "10000")
    get_settings.cache_clear()
    init_db()
    ctx = synthetic_context()
    clock = [ctx.planning_start]
    settings = PlanSettings(
        _env_file=None, llm_provider="fake", vision_adapter_key="test-vision-only", metrics_path=None, catalog_path=None
    )
    service = PlanService(settings, clock=lambda: clock[0])
    app.dependency_overrides[get_plan_service] = lambda: service
    with database() as db:
        for uid in (101, 102, 103):
            db.execute(
                "INSERT INTO users(id,email,password_hash,created_at) VALUES (?,?,?,?)",
                (uid, f"plan{uid}@example.test", "unused", clock[0].isoformat()),
            )
            db.execute(
                "INSERT INTO profiles(user_id,display_name,age,intent,learning_goals,updated_at) VALUES (?,?,22,'conversation',?,?)",
                (uid, f"Person {uid}", json.dumps(["SQL" if uid == 101 else "Python"]), clock[0].isoformat()),
            )
    with TestClient(app) as client:
        created = client.post("/api/v1/connections", headers=headers(101), json={"recipient_id": 102})
        assert created.status_code == 201, created.text
        accepted = client.post(f"/api/v1/connections/{created.json()['id']}/accept", headers=headers(102))
        assert accepted.status_code == 200 and accepted.json()["peer_match_id"] == 1
        yield client, service, clock, ctx
    app.dependency_overrides.pop(get_plan_service, None)
    get_settings.cache_clear()


def headers(uid=101, key="request-1"):
    return {"Authorization": f"Bearer {create_token(uid)}", "Idempotency-Key": key}


def payload(ctx):
    return GenerateRequest(pair_id=ctx.pair_id, members=ctx.members, horizon_days=ctx.horizon_days).model_dump(
        mode="json"
    )


def generate(flow):
    client, _, _, ctx = flow
    response = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert response.status_code == 201, response.text
    return response.json()


def read(client, uid=101):
    response = client.get("/api/v1/plans/1", headers=headers(uid))
    assert response.status_code == 200, response.text
    return response.json()


def complete(client, item, stamp, event="vision-1", version=1):
    body = {
        "event_id": event,
        "plan_item_id": item["id"],
        "user_id": item["user_id"],
        "pair_id": 1,
        "plan_version": version,
        "confirmed_at": stamp.isoformat(),
        "confirmed": True,
    }
    return client.post("/api/v1/plans/events/completion", headers={"X-Vision-Key": "test-vision-only"}, json=body)


def test_generate_persist_read_idempotency_and_privacy(flow):
    client, _, _, ctx = flow
    created = generate(flow)
    repeat = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert repeat.json() == created
    own = read(client)
    assert len(own["plan"]["items"]) == 3
    assert own["provider_mode"] == "fake" and own["catalog_source"] == "demo"
    assert own["partner"]["items"]  # bạn cặp xem được kế hoạch của nhau
    assert client.get("/api/v1/plans/1", headers=headers(103)).status_code == 403
    bad = payload(ctx)
    bad["members"][1]["user_id"] = 103
    assert client.post("/api/v1/plans/generate", headers=headers(), json=bad).status_code == 403
    changed = payload(ctx)
    changed["horizon_days"] = 6
    assert client.post("/api/v1/plans/generate", headers=headers(), json=changed).status_code == 409
    assert client.post("/api/v1/plans/generate", headers=headers(key="new"), json=payload(ctx)).status_code == 409
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 2


def test_invalid_llm_never_persists_and_has_safe_trace(flow):
    client, service, _, ctx = flow
    service.llm_factory = lambda *_: FakeLLM([{}, {}, {}])
    response = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert response.status_code == 422 and "TASK_SCHEMA" in response.text
    failure = response.json()
    assert len(failure["unplanned_concepts"]) == 6
    assert {i["user_id"] for i in failure["unplanned_concepts"]} == {101, 102}
    assert failure["errors"][0]["code"] == "TASK_SCHEMA"
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 0
        stored = db.execute("SELECT id,body FROM pb_traces WHERE kind='planner_error'").fetchone()
        assert stored["id"] == failure["trace_id"]
        trace = json.loads(stored["body"])
        assert trace["repairs"] == 2 and len(trace["attempts"]) == 3
        assert trace["unplanned_concepts"] == failure["unplanned_concepts"]
        assert db.execute("SELECT status FROM pb_plan_requests").fetchone()[0] == "FAILED"


def test_partial_plan_and_profile_availability_adapter(flow):
    client, _, _, ctx = flow
    ctx.members[0].committed_minutes_per_week = 30
    with database() as db:
        db.execute(
            "INSERT INTO availability(profile_user_id,day_of_week,start_time,end_time,timezone,created_at,updated_at) VALUES (101,6,'10:00','11:30','Asia/Ho_Chi_Minh','x','x')"
        )
    generate(flow)
    own = read(client)
    assert own["plan"]["partial"] and len(own["plan"]["deferred_items"]) == 3
    assert "NO_FEASIBLE_SCHEDULE" in [i["code"] for i in own["plan"]["warnings"]]
    with database() as db:
        raw = json.loads(db.execute("SELECT context FROM pb_plans WHERE user_id=101").fetchone()[0])
        assert raw["input"]["members"][0]["availability"][0]["day_of_week"] == 6


def test_checkin_dedup_authorization_and_proposal_staleness(flow):
    client, _, clock, _ = flow
    generate(flow)
    item = read(client)["plan"]["items"][0]
    from datetime import datetime

    clock[0] = datetime.fromisoformat(item["scheduled_end"]) + timedelta(minutes=1)
    before = client.post("/api/v1/plans/1/replan", headers=headers(), json={"expected_version": 1})
    assert before.status_code == 201, before.text
    event = {
        "event_id": "x",
        "plan_item_id": item["id"],
        "user_id": 101,
        "pair_id": 1,
        "plan_version": 1,
        "confirmed_at": clock[0].isoformat(),
        "confirmed": True,
    }
    assert client.post("/api/v1/plans/events/completion", json=event).status_code == 403
    assert complete(client, item, clock[0]).json()["applied"] is True
    assert complete(client, item, clock[0]).json()["duplicate"] is True
    assert complete(client, item, clock[0], event="second").json()["applied"] is False
    event["event_id"] = "vision-1"
    event["plan_item_id"] = "nonexistent"
    assert (
        client.post(
            "/api/v1/plans/events/completion", headers={"X-Vision-Key": "test-vision-only"}, json=event
        ).status_code
        == 409
    )
    accept = client.post(
        f"/api/v1/plans/1/proposals/{before.json()['id']}/accept", headers=headers(), json={"expected_version": 1}
    )
    assert accept.status_code == 409 and "PROGRESS_CHANGED" in accept.text
    assert read(client)["plan"]["items"][0]["status"] == "COMPLETED"


def test_replan_preserves_completed_ids_accepts_once_and_does_not_compound(flow):
    from datetime import datetime

    client, _, clock, _ = flow
    generate(flow)
    initial = read(client)["plan"]
    item = initial["items"][0]
    clock[0] = datetime.fromisoformat(item["scheduled_end"]) + timedelta(minutes=1)
    assert complete(client, item, clock[0]).status_code == 200
    draft = client.post("/api/v1/plans/1/replan", headers=headers(), json={"expected_version": 1})
    assert draft.status_code == 201, draft.text
    proposal = draft.json()
    assert proposal["after"]["items"][0]["id"] == item["id"]
    budget = next(b for b in proposal["budget"] if b["week_start"] == "2030-01-07")
    assert budget == {
        "week_start": "2030-01-07",
        "baseline_minutes": 144,
        "completed_minutes": 30,
        "remaining_minutes": 114,
        "proposed_limit_minutes": 91,
    }
    assert proposal["after"]["items"][0]["status"] == "COMPLETED"
    assert read(client)["plan"]["plan_version"] == 1
    decision = client.post(
        f"/api/v1/plans/1/proposals/{proposal['id']}/accept", headers=headers(), json={"expected_version": 1}
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["applied"]
    assert client.post(
        f"/api/v1/plans/1/proposals/{proposal['id']}/accept", headers=headers(), json={"expected_version": 1}
    ).json()["duplicate"]
    own = read(client)
    assert own["plan"]["plan_version"] == proposal["after"]["plan_version"]
    again = client.post(
        "/api/v1/plans/1/replan", headers=headers(), json={"expected_version": own["plan"]["plan_version"]}
    )
    assert again.status_code == 201, again.text
    assert again.json()["budget"] == proposal["budget"]
    assert sum(i["est_minutes"] for i in again.json()["after"]["items"] if i["status"] == "SCHEDULED") == sum(
        i["est_minutes"] for i in proposal["after"]["items"] if i["status"] == "SCHEDULED"
    )
    reject = client.post(
        f"/api/v1/plans/1/proposals/{again.json()['id']}/reject",
        headers=headers(),
        json={"expected_version": own["plan"]["plan_version"]},
    )
    assert reject.status_code == 200
    assert read(client)["plan"]["plan_version"] == own["plan"]["plan_version"]
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_traces WHERE kind='replan_accepted'").fetchone()[0] == 1


def test_runtime_init_and_migration_share_columns(flow, tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = create_engine(url)
    inspector = inspect(engine)
    with database() as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pb_%'")]
        assert len(names) == 8
        for name in names:
            runtime = {r["name"] for r in db.execute(f"PRAGMA table_info({name})")}
            assert runtime == {c["name"] for c in inspector.get_columns(name)}
    engine.dispose()


def test_invalid_profile_timezone_returns_controlled_error_and_releases_request(flow):
    client, _, _, ctx = flow
    with database() as db:
        db.execute(
            "INSERT INTO availability(profile_user_id,day_of_week,start_time,end_time,timezone,created_at,updated_at) VALUES (101,0,'19:00','20:30','not/a-zone','x','x')"
        )
    response = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert response.status_code == 422 and "PROFILE_PLAN_CONSTRAINTS" in response.text
    with database() as db:
        assert db.execute("SELECT status FROM pb_plan_requests").fetchone()[0] == "FAILED"
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 0


def test_invalid_profile_window_releases_claim_and_same_request_can_recover(flow):
    client, _, _, ctx = flow
    with database() as db:
        db.execute(
            "INSERT INTO availability(profile_user_id,day_of_week,start_time,end_time,timezone,created_at,updated_at) VALUES (101,0,?,?,'Asia/Ho_Chi_Minh','x','x')",
            ("19:00:00+07:00", "20:30:00+07:00"),
        )
    response = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert response.status_code == 422 and "PROFILE_PLAN_CONSTRAINTS" in response.text
    with database() as db:
        assert db.execute("SELECT status FROM pb_plan_requests").fetchone()[0] == "FAILED"
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 0
        db.execute("UPDATE availability SET start_time='19:00',end_time='20:30' WHERE profile_user_id=101")
    response = client.post("/api/v1/plans/generate", headers=headers(), json=payload(ctx))
    assert response.status_code == 201, response.text
    with database() as db:
        assert db.execute("SELECT status FROM pb_plan_requests").fetchone()[0] == "DONE"
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 2


def test_vision_requires_explicit_true_and_does_not_infer_concept_mastery(flow):
    from datetime import datetime

    client, service, clock, _ = flow
    generate(flow)
    item = read(client)["plan"]["items"][0]
    clock[0] = datetime.fromisoformat(item["scheduled_end"])
    event = {
        "event_id": "explicit-vision-confirmation",
        "plan_item_id": item["id"],
        "pair_id": 1,
        "user_id": 101,
        "plan_version": 1,
        "confirmed_at": clock[0].isoformat(),
    }
    with database() as db:
        before = db.execute("SELECT context FROM pb_plans WHERE user_id=101 AND status='ACTIVE'").fetchone()[0]
    for confirmation in ({}, {"confirmed": False}, {"confirmed": 1}):
        response = client.post(
            "/api/v1/plans/events/completion",
            headers={"X-Vision-Key": "test-vision-only"},
            json={**event, **confirmation},
        )
        assert response.status_code == 422, response.text
    event["confirmed"] = True
    assert client.post("/api/v1/plans/events/completion", headers=headers(), json=event).status_code == 403
    wrong_owner = {**event, "user_id": 102}
    assert (
        client.post(
            "/api/v1/plans/events/completion", headers={"X-Vision-Key": "test-vision-only"}, json=wrong_owner
        ).status_code
        == 422
    )
    accepted = client.post("/api/v1/plans/events/completion", headers={"X-Vision-Key": "test-vision-only"}, json=event)
    assert accepted.json()["applied"] is True
    with database() as db:
        after = db.execute("SELECT context FROM pb_plans WHERE user_id=101 AND status='ACTIVE'").fetchone()[0]
        assert after == before
        assert db.execute("SELECT COUNT(*) FROM pb_completion_events").fetchone()[0] == 1
    service.settings.vision_adapter_key = SecretStr("")
    assert client.post("/api/v1/plans/events/completion", json=event).status_code == 503


def test_concurrent_vision_events_complete_item_once_and_keep_history(flow):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime

    from app.agents.plan_coach.contract import CompletionEvent

    client, service, clock, _ = flow
    generate(flow)
    item = read(client)["plan"]["items"][0]
    clock[0] = datetime.fromisoformat(item["scheduled_end"])
    events = [
        CompletionEvent(
            event_id=f"concurrent-{n}",
            plan_item_id=item["id"],
            pair_id=1,
            user_id=101,
            plan_version=1,
            confirmed_at=clock[0],
            confirmed=True,
        )
        for n in (0, 0, 1, 2)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(service.complete, events))
    assert sum(r["applied"] for r in results) == 1
    assert sum(r["duplicate"] for r in results) == 3
    own = read(client)["plan"]
    assert sum(i["status"] == "COMPLETED" for i in own["items"]) == 1
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_completion_events").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM pb_plan_items WHERE completed_at IS NOT NULL").fetchone()[0] == 1
