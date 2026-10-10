from datetime import timedelta

import pytest
from app.agents.plan_coach.reports import reminder_report
from app.db import database
from test_plans_api import complete, generate, read
from test_plans_api import flow as plan_flow_fixture

flow = plan_flow_fixture


def test_24h_report_excludes_simulated_and_keeps_immature_observations_pending(flow):
    _, _, clock, _ = flow
    now = clock[0]
    with database() as db:
        for n, status in enumerate(["SENT", "SIMULATED", "FAILED", "PENDING", "RESERVED", "NOT_CONFIGURED"]):
            db.execute(
                "INSERT INTO pb_interventions(id,pair_id,user_id,local_date,action,variant,decision,delivery_status,created_at) VALUES (?,1,101,?,'reminder','template','{}',?,?)",
                (str(n), f"fake-day-{n}", status, now.isoformat()),
            )
            db.execute(
                "INSERT INTO pb_delivery_attempts(intervention_id,status,created_at) VALUES (?,?,?)",
                (str(n), status, now.isoformat()),
            )
        pending = reminder_report(db, now + timedelta(hours=23))
        assert pending["sent_count"] == 1 and pending["pending_count"] == 1 and pending["matured_count"] == 0
        matured = reminder_report(db, now + timedelta(hours=24))
        assert matured["pending_count"] == 0 and matured["matured_count"] == 1
        assert matured["observations"][0]["status"] == "no_checkin_24h"
        assert pending["by_variant"]["template"]["checkin_24h_rate"] is None
        assert matured["by_variant"]["template"]["checkin_24h_rate"] == 0


def test_24h_report_uses_first_completion_and_ignores_replay_after_send(flow):
    client, _, clock, _ = flow
    generate(flow)
    item = read(client)["plan"]["items"][0]
    clock[0] += timedelta(days=2)
    assert complete(client, item, clock[0] - timedelta(hours=1)).status_code == 200
    sent = clock[0]
    clock[0] += timedelta(hours=1)
    assert complete(client, item, clock[0], event="replay-new-id").json()["applied"] is False
    with database() as db:
        db.execute(
            "INSERT INTO pb_interventions VALUES ('report',1,101,'report-day','reminder','ai','{}','SENT',?)",
            (sent.isoformat(),),
        )
        db.execute(
            "INSERT INTO pb_delivery_attempts(intervention_id,status,created_at) VALUES ('report','SENT',?)",
            (sent.isoformat(),),
        )
        report = reminder_report(db, sent + timedelta(hours=24))
        assert report["checkin_24h_count"] == 0
        assert report["by_variant"]["ai"]["checkin_24h_rate"] == 0


@pytest.mark.parametrize("offset,responded", [(0, True), (24, True), (24.01, False)])
def test_24h_completion_window_and_pending_before_maturity(flow, offset, responded):
    client, _, clock, _ = flow
    generate(flow)
    item = read(client)["plan"]["items"][0]
    clock[0] += timedelta(days=2)
    sent = clock[0]
    clock[0] += timedelta(hours=offset)
    assert complete(client, item, clock[0]).status_code == 200
    with database() as db:
        db.execute(
            "INSERT INTO pb_interventions VALUES ('report',1,101,'report-day','reminder','ai','{}','SENT',?)",
            (sent.isoformat(),),
        )
        db.execute(
            "INSERT INTO pb_delivery_attempts(intervention_id,status,created_at) VALUES ('report','SENT',?)",
            (sent.isoformat(),),
        )
        early = reminder_report(db, sent + timedelta(hours=23, minutes=59))
        assert early["pending_count"] == 1 and early["checkin_24h_count"] == 0
        report = reminder_report(db, sent + timedelta(hours=24))
        assert report["checkin_24h_count"] == int(responded)


def test_eval_synthetic_modes_report_partial_and_repair_without_quality_scores():
    import asyncio

    from app.agents.plan_coach.eval import dataset, run_eval

    records = dataset()
    assert len(records) == 10 and sum(r["split"] == "holdout" for r in records) == 3
    report = asyncio.run(run_eval("fake", records[:3]))
    assert report["accepted"] == 2 and report["rejected"] == 1
    assert report["initial_generation_errors"] == 2 and report["repaired_successfully"] == 2
    assert report["partial_plans"] == 1
    assert report["accepted_personal_plans"] == 4 and report["partial_personal_plans"] == 1
    assert report["rates"]["rejection_pair_rate"] == 1 / 3
    assert report["rates"]["initial_generation_error_rate"] == 1
    assert report["rates"]["partial_personal_plan_rate"] == 0.25
    assert report["rates"]["hard_pass_among_accepted_rate"] == 1
    assert len(report["prompt_sha256"]) == 64 and report["human_rating_count"] == 0
    assert report["human_rubric_average"] is None and not report["quality_target_verified"]
