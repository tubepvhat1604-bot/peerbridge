import asyncio
from datetime import datetime, timedelta

import pytest
from app.agents.plan_coach.contract import BusyInterval
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.scheduler import PlanValidationError, schedule, template_tasks, validate_plan
from app.db import database
from test_plans_api import complete, generate, headers, read
from test_plans_api import flow as plan_flow_fixture

flow = plan_flow_fixture


def test_existing_session_busy_time_and_tamper_validation():
    ctx = synthetic_context()
    ctx.busy_intervals = {101: [BusyInterval(start="2030-01-07T19:00:00+07:00", end="2030-01-07T20:00:00+07:00")]}
    output = schedule(ctx, template_tasks(ctx))
    assert output.plans[0].items[0].scheduled_start.hour == 13  # 20:00 local in UTC
    first = output.plans[0].items[0]
    first.scheduled_start -= timedelta(minutes=30)
    first.scheduled_end -= timedelta(minutes=30)
    with pytest.raises(PlanValidationError, match="BUSY_OVERLAP"):
        validate_plan(ctx, output)


def test_validator_checks_task_length_even_after_mutation():
    ctx = synthetic_context()
    output = schedule(ctx, template_tasks(ctx))
    output.plans[0].items[0].est_minutes = 15
    with pytest.raises(PlanValidationError, match="TASK_DURATION"):
        validate_plan(ctx, output)


def test_session_created_after_proposal_prevents_accept(flow):
    client, _, clock, _ = flow
    generate(flow)
    draft = client.post("/api/v1/plans/1/replan", headers=headers(), json={"expected_version": 1}).json()
    item = next(i for i in draft["after"]["items"] if i["status"] == "SCHEDULED")
    with database() as db:
        db.execute(
            "INSERT INTO study_sessions(peer_match_id,learner_id,helper_id,topic,scheduled_start,scheduled_end,created_at,updated_at) VALUES (1,101,102,'SQL',?,?,?,?)",
            (item["scheduled_start"], item["scheduled_end"], clock[0].isoformat(), clock[0].isoformat()),
        )
    decision = client.post(
        f"/api/v1/plans/1/proposals/{draft['id']}/accept", headers=headers(), json={"expected_version": 1}
    )
    assert decision.status_code == 422 and "BUSY_OVERLAP" in decision.text
    assert read(client)["plan"]["plan_version"] == 1


def test_late_event_on_previous_version_keeps_completed_work_when_deferred(flow):
    client, _, clock, _ = flow
    generate(flow)
    previous = read(client)["plan"]
    # Third task is deferred by the reduced budget, but its ID remains stable.
    draft = client.post("/api/v1/plans/1/replan", headers=headers(), json={"expected_version": 1}).json()
    deferred = draft["after"]["deferred_items"][0]
    original = next(i for i in previous["items"] if i["id"] == deferred["id"])
    accepted = client.post(
        f"/api/v1/plans/1/proposals/{draft['id']}/accept", headers=headers(), json={"expected_version": 1}
    )
    assert accepted.status_code == 200, accepted.text
    clock[0] = datetime.fromisoformat(original["scheduled_end"]) + timedelta(minutes=1)
    assert complete(client, original, clock[0], version=1).json()["applied"]
    current = read(client)["plan"]
    done = next(i for i in current["items"] if i["id"] == original["id"])
    assert done["status"] == "COMPLETED" and done["scheduled_start"] == original["scheduled_start"]
    assert not any(i["id"] == original["id"] for i in current["deferred_items"])


def test_initial_concurrent_generation_is_claimed_once(flow):
    from app.agents.plan_coach.contract import GenerateRequest
    from app.agents.plan_coach.llm import FakeLLM
    from app.repositories.plans import PlanError

    _, service, _, ctx = flow
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowFake(FakeLLM):
        async def complete_json(self, system, user):
            entered.set()
            await release.wait()
            return await super().complete_json(system, user)

    fake = SlowFake([{"tasks": [t.model_dump(mode="json") for t in template_tasks(ctx)]}])
    service.llm_factory = lambda *_: fake
    request = GenerateRequest(pair_id=1, members=ctx.members)
    user = {"id": 101, "role": "STUDENT"}

    async def run():
        task = asyncio.create_task(service.generate(request, user, "concurrent"))
        await entered.wait()
        with pytest.raises(PlanError, match="đang được xử lý"):
            await service.generate(request, user, "concurrent")
        release.set()
        return await task

    result = asyncio.run(run())
    assert result["version"] == 1 and len(fake.calls) == 1
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM pb_plans").fetchone()[0] == 2


def test_partner_deadline_expiry_does_not_block_own_replan(flow):
    client, _, clock, ctx = flow
    ctx.members[1].deadline = ctx.planning_start + timedelta(days=1)
    generate(flow)
    clock[0] += timedelta(days=2)
    draft = client.post("/api/v1/plans/1/replan", headers=headers(), json={"expected_version": 1})
    assert draft.status_code == 201, draft.text
    accept = client.post(
        f"/api/v1/plans/1/proposals/{draft.json()['id']}/accept", headers=headers(), json={"expected_version": 1}
    )
    assert accept.status_code == 200, accept.text
    assert read(client, 102)["plan"]["plan_version"] == 1
