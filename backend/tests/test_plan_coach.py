import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.agents.plan_coach.coach import allowed_actions
from app.agents.plan_coach.contract import MetricSnapshot
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.scheduler import schedule, template_tasks
from app.db import database
from app.services.coach import CoachService, FakeMetricsAdapter, FakeNotification, get_coach_service
from test_plans_api import flow as plan_flow_fixture  # noqa: F401 — pytest fixture dependency
from test_plans_api import generate, headers, read


@pytest.fixture
def flow(plan_flow_fixture):  # noqa: F811 — dependency injected by pytest
    # Reproducible random assignment for branch tests; production uses secrets.randbelow.
    plan_flow_fixture[1].settings.variant_seed = "1"
    plan_flow_fixture[1].settings.trace_provider = "none"
    return plan_flow_fixture


def snapshot(ctx, now, *, pacing=(0.8, 0.8), due=(1, 1), last=None, gap=None, lag=None):
    ids = [m.user_id for m in ctx.members]
    return MetricSnapshot(
        pair_id=ctx.pair_id,
        as_of=now,
        source="synthetic_test_Data1_contract",
        plan_versions={u: 1 for u in ids},
        pacing=dict(zip(ids, pacing)),
        due_count=dict(zip(ids, due)),
        last_checkin={u: last for u in ids},
        gap=gap,
        lagging_user_id=lag,
    )


def test_external_trace_failure_preserves_valid_plan_and_links_intervention(flow, monkeypatch):
    import json

    from app.agents.plan_coach import tracing

    packets = []

    def failed_export(settings, kind, body, links=None):
        packets.append((kind, body, links))
        return {"provider": "langsmith", "status": "FAILED", "external_confirmed": False}

    monkeypatch.setattr(tracing, "emit_trace", failed_export)
    generate(flow)
    client, plans, clock, ctx = flow
    assert len(read(client)["plan"]["items"]) == 3
    assert packets[0][0] == "planner" and len(packets[0][2]["plan_ids"]) == 2
    clock[0] += timedelta(days=2)
    fake = FakeNotification()
    service = CoachService(plans, FakeMetricsAdapter(snapshot(ctx, clock[0], pacing=(0.6, 0.8), last=clock[0])), fake)
    decision = asyncio.run(service.evaluate(1, {"id": 101, "role": "STUDENT", "is_seed": False}))
    kind, body, links = packets[-1]
    assert kind == "coach" and body["model"] == "coach-template-v1" and body["action"] == "replan"
    assert "text" not in body and links["intervention_id"] == decision["id"]
    assert links["db_trace_id"] == decision["trace_id"] and links["proposal_id"] == decision["proposal_id"]
    with database() as db:
        stored = json.loads(db.execute("SELECT body FROM pb_traces WHERE id=?", (decision["trace_id"],)).fetchone()[0])
    assert stored["external_trace"]["status"] == "FAILED"
    assert decision["delivery_status"] == "SIMULATED" and len(fake.calls) == 1


@pytest.mark.parametrize("hour,expected", [(6, "QUIET_HOURS"), (7, "ELIGIBLE"), (21, "ELIGIBLE"), (22, "QUIET_HOURS")])
def test_quiet_hour_boundaries_in_local_timezone(hour, expected):
    ctx = synthetic_context()
    now = ctx.planning_start.replace(hour=hour) + timedelta(days=3)
    plans = {p.user_id: p for p in schedule(ctx, template_tasks(ctx)).plans}
    metrics = snapshot(ctx, now, last=now - timedelta(days=2))
    reason, actions, _ = allowed_actions(ctx, plans, metrics, 101, now)
    assert reason == expected
    assert ("reminder" in actions) == (expected == "ELIGIBLE")


@pytest.mark.parametrize(
    "pace,due,gap,lag,action",
    [
        ((0.6, 0.6), (1, 1), None, None, "pair_replan"),
        ((0.6, 0.8), (1, 1), None, None, "replan"),
        ((0.7, 0.8), (1, 1), 0.31, 101, "offer_support"),
        ((0.7, 0.8), (1, 1), 0.3, 101, "no_action"),
        ((None, 0.8), (0, 1), None, None, "no_action"),
    ],
)
def test_thresholds_and_no_due_work(pace, due, gap, lag, action):
    ctx = synthetic_context()
    # The partner's explicit concept strength is required; no image-derived mastery.
    ctx.members[1].can_help_concept_ids = ["sql.join"]
    now = ctx.planning_start + timedelta(days=1)
    plans = {p.user_id: p for p in schedule(ctx, template_tasks(ctx)).plans}
    metrics = snapshot(ctx, now, pacing=pace, due=due, last=now, gap=gap, lag=lag)
    _, actions, support = allowed_actions(ctx, plans, metrics, 101, now)
    assert actions[0] == action
    if action == "offer_support":
        assert support == "sql.join"


def test_absent_stale_version_mismatch_and_inconsistent_metrics_no_action():
    ctx = synthetic_context()
    now = ctx.planning_start + timedelta(days=1)
    plans = {p.user_id: p for p in schedule(ctx, template_tasks(ctx)).plans}
    assert allowed_actions(ctx, plans, None, 101, now)[1] == ["no_action"]
    m = snapshot(ctx, now, pacing=(0.1, 0.1))
    for bad in (
        m.model_copy(update={"as_of": now - timedelta(hours=25)}),
        m.model_copy(update={"plan_versions": {101: 2, 102: 1}}),
        m.model_copy(update={"due_count": {101: 0, 102: 1}}),
    ):
        assert allowed_actions(ctx, plans, bad, 101, now)[0] == "METRICS_INVALID_OR_STALE"


def test_first_checkin_absent_needs_two_days_since_first_due():
    ctx = synthetic_context()
    plans = {p.user_id: p for p in schedule(ctx, template_tasks(ctx)).plans}
    first_due = plans[101].items[0].scheduled_end
    now = first_due + timedelta(days=2)
    metrics = snapshot(ctx, now)
    assert "reminder" in allowed_actions(ctx, plans, metrics, 101, now)[1]
    before = now - timedelta(minutes=1)
    metrics.as_of = before
    assert "reminder" not in allowed_actions(ctx, plans, metrics, 101, before)[1]


@pytest.mark.parametrize("fail,status", [(False, "SIMULATED"), (True, "FAILED")])
def test_http_coach_records_proposal_delivery_separately_and_dedups(flow, fail, status):
    client, plans, clock, ctx = flow
    generate(flow)
    clock[0] += timedelta(days=2)
    metrics = snapshot(ctx, clock[0], pacing=(0.6, 0.6), last=clock[0] - timedelta(days=3))
    fake = FakeNotification(fail)
    service = CoachService(plans, FakeMetricsAdapter(metrics), fake)
    from app.main import app

    app.dependency_overrides[get_coach_service] = lambda: service
    try:
        decision = client.post("/api/v1/coach/1/evaluate", headers=headers()).json()
        assert decision["action"] == "pair_replan"
        assert decision["proposal_id"] > 0 and not decision["sent"]
        assert decision["delivery_status"] == status
        assert read(client)["plan"]["plan_version"] == 1
        assert client.post("/api/v1/coach/1/evaluate", headers=headers()).json()["reason"] == "DAILY_LIMIT"
        assert len(fake.calls) == 1
        assert client.get("/api/v1/coach/1", headers=headers(103)).status_code == 403
        with database() as db:
            assert db.execute("SELECT COUNT(*) FROM pb_delivery_attempts").fetchone()[0] == 1
            assert db.execute("SELECT variant FROM pb_variants").fetchone()[0] == "ai"
            assert decision["message_source"] == "template"  # Feature flag still off.
    finally:
        app.dependency_overrides.pop(get_coach_service, None)


@pytest.mark.parametrize("v2", [False, True])
def test_concurrent_coach_reserves_once_without_real_notification(flow, v2):
    _, plans, clock, ctx = flow
    generate(flow)
    clock[0] += timedelta(days=2)
    fake = FakeNotification()
    selector = None
    if v2:
        from app.agents.plan_coach.graph import CoachSelector
        from app.agents.plan_coach.llm import FakeLLM

        plans.settings.coach_v2_enabled = True
        selector = CoachSelector(
            FakeLLM(
                [{"action": "reminder", "message": "Bạn có thể chọn một việc nhỏ trong Plan và check-in khi sẵn sàng."}]
                * 4
            )
        )
    service = CoachService(
        plans, FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))), fake, selector
    )
    user = {"id": 101, "role": "STUDENT", "is_seed": False}
    with ThreadPoolExecutor(max_workers=4) as pool:
        decisions = list(pool.map(lambda _: asyncio.run(service.evaluate(1, user)), range(4)))
    assert sum(d["action"] == "reminder" for d in decisions) == 1
    assert len(fake.calls) == 1
    assert all(not d["sent"] for d in decisions)


def test_unavailable_metrics_do_not_create_synthetic_product_data(flow):
    _, plans, _, _ = flow
    generate(flow)
    decision = asyncio.run(CoachService(plans).evaluate(1, {"id": 101, "role": "STUDENT"}))
    assert decision["reason"] == "METRICS_UNAVAILABLE" and not decision["sent"]
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_interventions").fetchone()[0] == 0


def test_v2_fake_graph_final_action_is_persisted_in_trace(flow):
    from app.agents.plan_coach.graph import CoachSelector
    from app.agents.plan_coach.llm import FakeLLM

    _, plans, clock, ctx = flow
    generate(flow)
    clock[0] += timedelta(days=2)
    plans.settings.coach_v2_enabled = True
    fake = FakeNotification()
    graph = CoachSelector(
        FakeLLM(
            [{"action": "reminder", "message": "Bạn có thể chọn một việc nhỏ trong Plan và check-in khi sẵn sàng."}]
        )
    )
    service = CoachService(
        plans, FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))), fake, selector=graph
    )
    result = asyncio.run(service.evaluate(1, {"id": 101, "role": "STUDENT"}))
    assert result["selection"]["mode"] == "v2" and result["variant"] == "ai"
    assert result["selection"]["nodes"][-1] == "save_log" and result["delivery_status"] == "SIMULATED"
    assert result["message_source"] == "ai" and fake.calls[0][1] == result["text"]
    traces = plans.traces(1, {"id": 101, "role": "STUDENT"})["traces"]
    assert any(t["kind"] == "coach" and t["body"].get("selection", {}).get("mode") == "v2" for t in traces)


def test_quiet_hours_are_checked_again_after_slow_selection(flow):
    _, plans, clock, ctx = flow
    generate(flow)
    clock[0] = clock[0].replace(hour=21, minute=59) + timedelta(days=2)
    metrics = snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))
    plans.settings.coach_v2_enabled = True

    class SlowSelector:
        async def select(self, *args):
            clock[0] += timedelta(minutes=2)
            return {
                "mode": "v2",
                "action": "reminder",
                "text": "Bạn có thể chọn một việc nhỏ trong Plan và check-in khi sẵn sàng.",
            }

    fake = FakeNotification()
    result = asyncio.run(
        CoachService(plans, FakeMetricsAdapter(metrics), fake, SlowSelector()).evaluate(
            1, {"id": 101, "role": "STUDENT"}
        )
    )
    assert result["delivery_status"] == "SUPPRESSED_QUIET_HOURS" and not fake.calls


def test_invalid_team_metric_document_is_unavailable(tmp_path):
    from app.services.coach import TeamMetricsAdapter

    path = tmp_path / "invalid-metrics.json"
    path.write_text("[]", encoding="utf-8")
    assert TeamMetricsAdapter(path).load(1) is None


@pytest.mark.parametrize("status", ["PENDING", "NOT_CONFIGURED", "SENT"])
def test_notification_acknowledgement_status_and_daily_dedup(flow, status):
    _, plans, clock, ctx = flow
    generate(flow)
    clock[0] += timedelta(days=2)
    fake = FakeNotification()

    class AckAdapter:
        def send(self, user_id, text, idempotency_key):
            fake.send(user_id, text, idempotency_key)
            return status  # Test-only acknowledgement, never a real delivery.

    service = CoachService(
        plans, FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))), AckAdapter()
    )
    user = {"id": 101, "role": "STUDENT"}
    result = asyncio.run(service.evaluate(1, user))
    assert result["delivery_status"] == status and result["sent"] == (status == "SENT")
    assert fake.calls[0][2] == result["id"]
    assert asyncio.run(service.evaluate(1, user))["reason"] == "DAILY_LIMIT"
    assert len(fake.calls) == 1
    with database() as db:
        assert db.execute("SELECT delivery_status FROM pb_interventions").fetchone()[0] == status
        assert db.execute("SELECT status FROM pb_delivery_attempts").fetchone()[0] == status


def test_unavailable_metric_adapter_is_no_action_without_spending_quota(flow):
    _, plans, _, _ = flow
    generate(flow)

    class OfflineData1:
        def load(self, pair_id):
            raise TimeoutError("private-provider-details")

    fake = FakeNotification()
    result = asyncio.run(CoachService(plans, OfflineData1(), fake).evaluate(1, {"id": 101, "role": "STUDENT"}))
    assert result["action"] == "no_action" and result["reason"] == "METRICS_UNAVAILABLE"
    assert not fake.calls and not result["sent"]
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_interventions").fetchone()[0] == 0
        traces = str([r[0] for r in db.execute("SELECT body FROM pb_traces WHERE kind='coach'")])
        assert "private-provider-details" not in traces


def test_daily_reservation_uses_local_date_after_slow_selection(flow):
    _, plans, clock, ctx = flow
    generate(flow)
    clock[0] = clock[0].replace(hour=21, minute=59) + timedelta(days=2)
    metrics = snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))
    plans.settings.coach_v2_enabled = True

    class DelayedSelector:
        async def select(self, *args):
            clock[0] += timedelta(hours=9, minutes=2)
            return {
                "mode": "v2",
                "action": "reminder",
                "text": "Bạn có thể chọn một việc nhỏ trong Plan và check-in khi sẵn sàng.",
            }

    fake = FakeNotification()
    service = CoachService(plans, FakeMetricsAdapter(metrics), fake, DelayedSelector())
    user = {"id": 101, "role": "STUDENT"}
    result = asyncio.run(service.evaluate(1, user))
    assert result["delivery_status"] == "SIMULATED" and len(fake.calls) == 1
    with database() as db:
        assert db.execute("SELECT local_date FROM pb_interventions").fetchone()[0] == clock[0].date().isoformat()
    plans.settings.coach_v2_enabled = False
    assert asyncio.run(service.evaluate(1, user))["reason"] == "DAILY_LIMIT"
    assert len(fake.calls) == 1


@pytest.mark.parametrize("selected", [None, {}, {"action": "delete_plan", "mode": "v2"}, {"action": "reminder"}])
def test_malformed_graph_result_falls_back_before_any_action(flow, selected):
    _, plans, clock, ctx = flow
    generate(flow)
    plans.settings.coach_v2_enabled = True
    clock[0] += timedelta(days=2)

    class BrokenSelector:
        async def select(self, *args):
            return selected

    fake = FakeNotification()
    result = asyncio.run(
        CoachService(
            plans,
            FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))),
            fake,
            BrokenSelector(),
        ).evaluate(1, {"id": 101, "role": "STUDENT"})
    )
    assert result["action"] == "reminder" and result["selection"]["mode"] == "v1_fallback"
    assert result["variant"] == "ai" and result["delivery_status"] == "SIMULATED"
    assert len(fake.calls) == 1


def test_pair_variant_survives_unavailable_provider_and_no_action_logs_it(flow):
    import json

    from app.agents.plan_coach.graph import CoachSelector
    from app.agents.plan_coach.llm import FakeLLM

    _, plans, clock, ctx = flow
    generate(flow)
    plans.settings.coach_v2_enabled = True
    user = {"id": 101, "role": "STUDENT"}
    unavailable = asyncio.run(CoachService(plans).evaluate(1, user))
    assert unavailable["variant"] == "ai" and unavailable["delivery_status"] == "NOT_APPLICABLE"
    assert unavailable["evaluated_at"] == clock[0].isoformat()
    clock[0] += timedelta(days=2)
    fake = FakeNotification()
    metrics = FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3)))
    selector = CoachSelector(FakeLLM([{"action": "no_action", "message": ""}]))
    result = asyncio.run(CoachService(plans, metrics, fake, selector).evaluate(1, user))
    assert result["variant"] == "ai" and result["selection"]["mode"] == "v2"
    assert result["action"] == "no_action" and not fake.calls
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_interventions").fetchone()[0] == 0
        traces = [json.loads(r[0]) for r in db.execute("SELECT body FROM pb_traces WHERE kind='coach'")]
        assert all(t["variant"] == "ai" and t["evaluated_at"] and not t["sent"] for t in traces)
    # A missing provider falls back without assigning the pair to the other arm.
    fallback = asyncio.run(CoachService(plans, metrics, fake).evaluate(1, user))
    assert fallback["variant"] == "ai" and fallback["selection"]["mode"] == "v1_fallback"
    partner = asyncio.run(CoachService(plans, metrics, fake).evaluate(1, {"id": 102, "role": "STUDENT"}))
    assert partner["variant"] == "ai" and len(fake.calls) == 2


def test_template_variant_uses_same_code_rules_without_calling_ai(flow):
    _, plans, clock, ctx = flow
    generate(flow)
    plans.settings.coach_v2_enabled = True
    with database() as db:
        db.execute("INSERT INTO pb_variants(pair_id,variant) VALUES (1,'template')")
    clock[0] += timedelta(days=2)

    class MustNotCall:
        async def select(self, *args):
            pytest.fail("Template arm must not invoke the AI selector")

    fake = FakeNotification()
    service = CoachService(
        plans, FakeMetricsAdapter(snapshot(ctx, clock[0], last=clock[0] - timedelta(days=3))), fake, MustNotCall()
    )
    user = {"id": 101, "role": "STUDENT"}
    result = asyncio.run(service.evaluate(1, user))
    assert result["variant"] == "template" and result["selection"]["mode"] == "v1"
    assert result["action"] == "reminder" and not result["sent"]
    assert asyncio.run(service.evaluate(1, user))["reason"] == "DAILY_LIMIT"
    assert len(fake.calls) == 1
