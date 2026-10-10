import asyncio

import httpx
import pytest
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.llm import CompatibleLLM, FakeLLM, PlannerFailureError, PlanSettings, divide_tasks
from app.agents.plan_coach.scheduler import template_tasks
from pydantic import SecretStr


def good(ctx):
    return {"tasks": [t.model_dump() for t in template_tasks(ctx)]}


def test_repairs_schema_and_missing_prerequisite_then_succeeds():
    ctx = synthetic_context()
    missing = good(ctx)
    missing["tasks"] = [t for t in missing["tasks"] if t["concept_id"] != "sql.select"]
    llm = FakeLLM([{"bad": True}, missing, good(ctx)])
    tasks, trace = asyncio.run(divide_tasks(ctx, llm))
    assert len(tasks) == 6 and len(llm.calls) == 3 and trace["repairs"] == 2
    assert trace["attempts"][1]["errors"][0]["code"] == "MISSING_TASK"
    assert "TASK_SCHEMA" in llm.calls[1][1]
    assert "MISSING_TASK" in llm.calls[2][1] and "sql.select" in llm.calls[2][1]
    assert trace["prompt_version"] and trace["model"] == "FakeLLM" and trace["latency_ms"] >= 0


def test_exhausted_repair_is_controlled_and_does_not_leak_raw_response():
    llm = FakeLLM([{"secret": "do-not-log"}] * 3)
    with pytest.raises(PlannerFailureError) as error:
        asyncio.run(divide_tasks(synthetic_context(), llm))
    assert len(llm.calls) == 3
    assert "do-not-log" not in str(error.value.trace)
    assert len(error.value.trace["unplanned_concepts"]) == 6


@pytest.mark.parametrize(
    "field,value,code",
    [("concept_id", "invented.concept", "UNEXPECTED_TASK"), ("resource_ids", ["invented-source"], "UNKNOWN_RESOURCE")],
)
def test_invented_concept_or_resource_requires_repair(field, value, code):
    ctx = synthetic_context()
    invalid = good(ctx)
    invalid["tasks"][0][field] = value
    llm = FakeLLM([invalid, good(ctx)])
    _, trace = asyncio.run(divide_tasks(ctx, llm))
    assert len(llm.calls) == 2 and trace["repairs"] == 1
    assert code in {e["code"] for e in trace["attempts"][0]["errors"]}
    assert code in llm.calls[1][1]


def test_no_generated_url_or_schedule_allowed():
    ctx = synthetic_context()
    bad = good(ctx)
    bad["tasks"][0]["scheduled_start"] = "2030-01-01"
    with pytest.raises(PlannerFailureError):
        asyncio.run(divide_tasks(ctx, FakeLLM([bad] * 3)))
    bad = good(ctx)
    bad["tasks"][0]["action"] = "Read https://invented.test"
    with pytest.raises(PlannerFailureError, match="INLINE_URL"):
        asyncio.run(divide_tasks(ctx, FakeLLM([bad] * 3)))


def test_real_provider_protocol_with_mock_transport_records_usage_not_key():
    ctx = synthetic_context()

    def response(request):
        import json

        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(good(ctx))}}], "usage": {"total_tokens": 123}}
        )

    llm = CompatibleLLM(PlanSettings(llm_api_key=SecretStr("test-secret-never-log")), httpx.MockTransport(response))
    _, trace = asyncio.run(divide_tasks(ctx, llm))
    assert trace["attempts"][0]["usage"]["total_tokens"] == 123
    assert trace["attempts"][0]["cost"] is None
    assert "test-secret-never-log" not in str(trace)


def test_provider_timeout_stops_after_two_repairs_without_leaking_transport_details():
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("provider-secret-do-not-log", request=request)

    llm = CompatibleLLM(
        PlanSettings(_env_file=None, llm_api_key=SecretStr("test-key-do-not-log")),
        httpx.MockTransport(timeout),
    )
    with pytest.raises(PlannerFailureError) as failure:
        asyncio.run(divide_tasks(synthetic_context(), llm))
    trace = failure.value.trace
    assert len(requests) == 3 and trace["repairs"] == 2
    assert all(a["errors"][0]["code"] == "LLM_UNAVAILABLE" for a in trace["attempts"])
    assert "provider-secret-do-not-log" not in str(trace) and "test-key-do-not-log" not in str(trace)
