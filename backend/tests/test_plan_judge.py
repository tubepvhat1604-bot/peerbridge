import asyncio

import pytest
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.judge import judge_plan
from app.agents.plan_coach.llm import FakeLLM
from app.agents.plan_coach.scheduler import schedule, template_tasks


@pytest.mark.parametrize("invalid", [0, 6, True, "5"])
def test_judge_rejects_out_of_range_or_non_integer_scores(invalid):
    ctx = synthetic_context()
    plan = schedule(ctx, template_tasks(ctx)).plans[0]
    raw = {
        "goal_fit": invalid,
        "feasibility": 4,
        "specificity": 4,
        "schedule_accuracy": 4,
        "if_then_accuracy": 4,
        "rationale": "Fake response for schema validation only",
    }
    with pytest.raises(ValueError):
        asyncio.run(judge_plan(FakeLLM([raw]), ctx.members[0], plan))


def test_judge_protocol_records_provenance_without_claiming_human_score():
    ctx = synthetic_context()
    plan = schedule(ctx, template_tasks(ctx)).plans[0]
    raw = dict.fromkeys(["goal_fit", "feasibility", "specificity", "schedule_accuracy", "if_then_accuracy"], 3)
    raw["rationale"] = "Test fixture for schema/provenance only, not an evaluation score"
    result = asyncio.run(judge_plan(FakeLLM([raw]), ctx.members[0], plan))
    assert result["scores"] == raw and result["provider_mode"] == "fake"
    assert result["human_rating"] is False and result["latency_ms"] >= 0
    assert result["prompt_version"] == "plan-coach-rubric-v1"


def test_judge_timeout_is_reported_instead_of_manufacturing_score():
    ctx = synthetic_context()
    plan = schedule(ctx, template_tasks(ctx)).plans[0]

    class SlowJudge(FakeLLM):
        async def complete_json(self, *args):
            await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        asyncio.run(judge_plan(SlowJudge([]), ctx.members[0], plan, timeout=0.01))
