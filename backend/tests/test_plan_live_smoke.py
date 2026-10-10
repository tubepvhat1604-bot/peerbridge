import asyncio
import json

import httpx
import pytest
from app.agents.plan_coach.fixtures import synthetic_context
from app.agents.plan_coach.live_smoke import BudgetExhaustedError, BudgetLLM, configuration_status, run_smoke
from app.agents.plan_coach.llm import CompatibleLLM, FakeLLM, PlanSettings
from app.agents.plan_coach.scheduler import template_tasks
from pydantic import SecretStr


def good():
    return {"tasks": [t.model_dump(mode="json") for t in template_tasks(synthetic_context())]}


@pytest.mark.parametrize("limit", [0, -1, 11, True])
def test_request_budget_cannot_exceed_user_authorization(limit):
    with pytest.raises(ValueError):
        BudgetLLM(FakeLLM([]), limit)


def test_shared_budget_counts_repairs_and_coach_and_never_persists_bad_plan():
    llm = FakeLLM(
        [
            {"tasks": []},
            good(),
            {"action": "replan", "message": "Bạn có thể xem phương án giảm tải và tự quyết định khi sẵn sàng."},
        ]
    )
    settings = PlanSettings(_env_file=None, trace_provider="none")
    result = asyncio.run(run_smoke(settings, 3, llm))
    assert result["status"] == "PASSED" and result["request_count"] == 3
    assert result["planner"]["trace"]["repairs"] == 1
    assert result["coach"]["message_source"] == "ai"
    assert result["delivery_status"] == "SIMULATED" and result["real_notification_sends"] == 0
    assert result["plan_persisted"] is False


def test_budget_exhaustion_between_planner_and_coach_falls_back_without_extra_request():
    llm = FakeLLM([good()])
    result = asyncio.run(run_smoke(PlanSettings(_env_file=None), 1, llm))
    assert result["status"] == "COACH_FALLBACK" and len(llm.calls) == result["request_count"] == 1
    assert result["coach"]["error"] == "BudgetExhaustedError"


def test_concurrent_calls_share_the_same_hard_budget():
    llm = FakeLLM([{}] * 10)
    budget = BudgetLLM(llm, 2)

    async def calls():
        return await asyncio.gather(*(budget.complete_json("JSON", "{}") for _ in range(8)), return_exceptions=True)

    outcomes = asyncio.run(calls())
    assert len(llm.calls) == len(budget.records) == 2
    assert sum(isinstance(r, BudgetExhaustedError) for r in outcomes) == 6


def test_missing_plan_key_is_reported_without_using_moderator_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "moderator-secret")
    settings = PlanSettings(_env_file=None, llm_api_key=SecretStr(""))
    report = asyncio.run(run_smoke(settings))
    assert report["request_count"] == 0 and report["status"] == "CONFIGURATION_BLOCKED"
    assert "moderator-secret" not in str(report) and not configuration_status(settings)["ready"]


def test_live_protocol_refusal_stops_all_later_attempts_and_strips_details():
    requests = []

    def denied(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "sensitive-provider-body"})

    settings = PlanSettings(_env_file=None, llm_provider="openai_compatible", llm_api_key=SecretStr("private-key"))
    llm = CompatibleLLM(settings, httpx.MockTransport(denied))
    report = asyncio.run(run_smoke(settings, 10, llm))
    assert len(requests) == report["request_count"] == 1
    assert report["status"] == "PLANNER_REJECTED" and not report["plan_persisted"]
    assert "private-key" not in str(report) and "sensitive-provider-body" not in str(report)


@pytest.mark.parametrize("failure", ["bad_json", "timeout", "output_limit", "refusal"])
def test_provider_failure_has_bounded_count_and_controlled_result(failure):
    requests = []

    def response(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private endpoint detail")
        message = {"content": "bad-json"}
        if failure == "refusal":
            message["refusal"] = "private refusal text"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": "length" if failure == "output_limit" else "stop"}],
                "usage": {"total_tokens": 10, "secret": "must-not-export"},
            },
        )

    settings = PlanSettings(_env_file=None, llm_api_key=SecretStr("private-key"))
    result = asyncio.run(run_smoke(settings, 10, CompatibleLLM(settings, httpx.MockTransport(response))))
    assert len(requests) == result["request_count"] == (3 if failure == "bad_json" else 1)
    assert result["status"] == "PLANNER_REJECTED" and not result["plan_persisted"]
    assert "private" not in json.dumps(result) and "must-not-export" not in json.dumps(result)


def test_provider_payload_is_minimal_and_output_is_capped():
    captured = []

    def response(request):
        packet = json.loads(request.content)
        captured.append(packet)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(good())}}]})

    settings = PlanSettings(_env_file=None, llm_api_key=SecretStr("test-key"), llm_max_output_tokens=512)
    from app.agents.plan_coach.llm import divide_tasks

    asyncio.run(divide_tasks(synthetic_context(), CompatibleLLM(settings, httpx.MockTransport(response))))
    assert captured[0]["max_completion_tokens"] == 512
    user = json.loads(captured[0]["messages"][1]["content"])
    assert all(set(member) == {"user_id", "goal"} for member in user["members"])
    assert not any(
        s in captured[0]["messages"][1]["content"] for s in ("availability", "deadline", "location", "timezone")
    )


def test_outer_timeout_halts_budget_before_another_request():
    class Slow:
        mode, model, usage, cost = "fake", "fake", None, None

        async def complete_json(self, system, user):
            await asyncio.sleep(10)

    async def exercise():
        budget = BudgetLLM(Slow(), 10)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(budget.complete_json("", ""), 0.01)
        with pytest.raises(BudgetExhaustedError):
            await budget.complete_json("", "")
        assert len(budget.records) == 1 and budget.records[0]["error_code"] == "TimeoutOrCancelled"

    asyncio.run(exercise())
