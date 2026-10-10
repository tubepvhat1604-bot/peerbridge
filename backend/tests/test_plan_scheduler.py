from datetime import timedelta

import pytest
from app.agents.plan_coach.contract import ItemStatus, PlannerInput
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.scheduler import PlanValidationError, schedule, template_tasks, validate_plan


def run(ctx):
    return schedule(ctx, template_tasks(ctx))


def test_two_independent_goals_with_weekly_budget_and_prerequisites():
    ctx = synthetic_context()
    output = run(ctx)
    for plan in output.plans:
        assert not plan.partial
        assert sum(i.est_minutes for i in plan.items) == 135
        assert len({i.slot_id for i in plan.items}) == 3
        assert all(i.status == ItemStatus.SCHEDULED and i.if_then_text.startswith("Nếu ") for i in plan.items)
        assert all(i.scheduled_end <= j.scheduled_start for i, j in zip(plan.items, plan.items[1:]))
    assert {i.concept_id for i in output.plans[0].items} == {"sql.select", "sql.where", "sql.join"}
    assert {i.concept_id for i in output.plans[1].items} == {"python.variables", "python.conditions", "python.loops"}


@pytest.mark.parametrize("case", ["little_time", "impossible_deadline"])
def test_insufficient_budget_or_deadline_defers_dependents_with_reason(case):
    output = run(synthetic_context(case))
    plan = output.plans[0]
    assert plan.partial and plan.deferred_items
    assert all(i.scheduled_start is None and i.if_then_text is None and i.defer_reason for i in plan.deferred_items)
    assert any(i.defer_reason == "PREREQUISITE_DEFERRED" for i in plan.deferred_items)
    assert plan.warnings


def test_no_common_time_still_schedules_both_personal_plans():
    output = run(synthetic_context("no_shared_time"))
    assert all(not p.partial for p in output.plans)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda c: next(x for x in c.concepts if x.id == "sql.select").prerequisites.append("sql.join"), "PREREQUISITE_CYCLE"),
        (lambda c: c.concepts[0].prerequisites.append("missing"), "UNKNOWN_PREREQUISITE"),
        (lambda c: c.members[0].concept_ids.append("missing"), "UNKNOWN_CONCEPT"),
    ],
)
def test_invalid_concept_graph_rejected_with_specific_code(mutation, code):
    ctx = synthetic_context()
    mutation(ctx)
    with pytest.raises(PlanValidationError) as error:
        run(ctx)
    assert code in {i.code for i in error.value.issues}


def test_removed_prerequisite_task_is_not_silently_ignored():
    ctx = synthetic_context()
    tasks = [t for t in template_tasks(ctx) if t.concept_id != "sql.select"]
    with pytest.raises(PlanValidationError, match="MISSING_TASK"):
        schedule(ctx, tasks)


def test_future_anchor_and_one_work_per_window():
    ctx = synthetic_context()
    ctx.planning_start += timedelta(hours=12)
    output = run(ctx)
    assert all(i.scheduled_start >= ctx.planning_start for p in output.plans for i in p.items)
    assert all(len({i.slot_id for i in p.items}) == len(p.items) for p in output.plans)


def test_validator_rejects_tampered_schedule_and_if_then():
    ctx = synthetic_context()
    output = run(ctx)
    output.plans[0].items[1].scheduled_start = output.plans[0].items[0].scheduled_start
    with pytest.raises(PlanValidationError) as error:
        validate_plan(ctx, output)
    codes = {i.code for i in error.value.issues}
    assert {"OVERLAP", "PREREQUISITE_ORDER", "IF_THEN_MISMATCH"} <= codes


def test_known_concept_satisfies_prerequisite_without_extra_work():
    ctx = synthetic_context()
    ctx.members[0].known_concept_ids += ["sql.select", "sql.where"]
    output = run(ctx)
    assert [i.concept_id for i in output.plans[0].items] == ["sql.join"]


def test_default_and_invalid_timezone_and_naive_anchor():
    raw = synthetic_context().model_dump(mode="json")
    del raw["members"][0]["timezone"]
    assert PlannerInput.model_validate(raw).members[0].timezone == "Asia/Ho_Chi_Minh"
    raw["members"][0]["timezone"] = "invalid/place"
    with pytest.raises(ValueError, match="IANA"):
        PlannerInput.model_validate(raw)
    raw = synthetic_context().model_dump(mode="json")
    raw["planning_start"] = "2030-01-07T08:00:00"
    with pytest.raises(ValueError, match="timezone"):
        PlannerInput.model_validate(raw)


def test_completed_items_preserved_and_reduced_budget_is_enforced():
    ctx = synthetic_context()
    original = run(ctx)
    completed = (
        original.plans[0]
        .items[0]
        .model_copy(update={"status": ItemStatus.COMPLETED, "completed_at": ctx.planning_start})
    )
    ctx.planning_start += timedelta(days=1)
    ctx.horizon_days = 5  # Keep the assertion inside the same local budget week.
    ctx.plan_version = 2
    tasks = template_tasks(ctx, [completed])
    replanned = schedule(
        ctx,
        tasks,
        completed=[completed],
        previous=original.plans[0].items,
        budget_caps={(ctx.members[0].user_id, "2030-01-07"): 45},
    )
    assert replanned.plans[0].items[0].id == completed.id
    assert replanned.plans[0].items[0].scheduled_start == completed.scheduled_start
    assert sum(i.est_minutes for i in replanned.plans[0].items if i.status != ItemStatus.COMPLETED) <= 45
    assert replanned.plans[0].partial
