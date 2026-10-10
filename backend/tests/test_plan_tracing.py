import json
from uuid import uuid4

import httpx
import pytest
from app.agents.plan_coach.llm import PlanSettings
from app.agents.plan_coach.tracing import LangSmithTrace, NoopTrace, emit_trace, make_trace, metadata
from pydantic import SecretStr


def test_external_trace_allowlist_removes_keys_chat_messages_provider_details_and_usage_strings():
    secret = "never-export-secret"
    body = {
        "prompt_version": "plan-v2",
        "model": "FakeLLM",
        "provider_mode": "fake",
        "message": "private chat",
        "api_key": secret,
        "raw": {"key": secret},
        "usage": {"total_tokens": 12, "secret": secret},
        "attempts": [
            {
                "attempt": 1,
                "latency_ms": 4,
                "errors": [{"code": "TASK_SCHEMA", "message": secret}],
                "usage": {"completion_tokens": 6},
            }
        ],
        "validation_errors": [{"code": "PREREQUISITE_ORDER", "message": secret}],
    }
    trace_id, intervention_id = str(uuid4()), str(uuid4())
    result = metadata(
        body, {"db_trace_id": trace_id, "intervention_id": intervention_id, "plan_ids": [1, 2], "user_id": 101}
    )
    assert secret not in str(result) and "private chat" not in str(result) and "user_id" not in result
    assert result["usage"] == {"total_tokens": 12}
    assert result["attempts"][0]["error_codes"] == ["TASK_SCHEMA"]
    assert result["validator_error_codes"] == ["PREREQUISITE_ORDER"]
    assert result["db_trace_id"] == trace_id and result["intervention_id"] == intervention_id


def test_langsmith_explicit_metadata_trace_is_confirmed_only_after_readback():
    packets = []
    ids = []

    def server(request):
        packets.append((request.method, json.loads(request.content) if request.content else None))
        if request.method == "POST":
            ids.append(json.loads(request.content)["id"])
        return httpx.Response(200, json={"id": ids[0]} if request.method == "GET" else {})

    settings = PlanSettings(_env_file=None, trace_api_key=SecretStr("private-trace-key"), trace_verify=True)
    result = LangSmithTrace(settings, httpx.MockTransport(server)).emit(
        "coach", {"mode": "v1_fallback", "action": "replan", "text": "private-message", "error": "TimeoutError"}
    )
    assert result["status"] == "CONFIRMED" and result["external_confirmed"]
    assert [method for method, _ in packets] == ["POST", "PATCH", "GET"]
    assert "private-trace-key" not in str(packets) and "private-message" not in str(packets)
    assert packets[0][1]["inputs"] == {} and packets[0][1]["extra"]["metadata"]["fallback"]


def test_langsmith_ack_without_readback_is_not_reported_as_confirmed():
    settings = PlanSettings(_env_file=None, trace_api_key=SecretStr("fake-key"))
    result = LangSmithTrace(settings, httpx.MockTransport(lambda _: httpx.Response(200))).emit("planner", {})
    assert result["status"] == "ACCEPTED_UNVERIFIED" and not result["external_confirmed"]


@pytest.mark.parametrize("case", ["missing", "placeholder", "disabled"])
def test_no_config_or_disabled_adapter_is_noop_and_never_exports(case):
    settings = PlanSettings(
        _env_file=None,
        trace_api_key=SecretStr("fake-key" if case == "disabled" else "your-key" if case == "placeholder" else ""),
        trace_provider="none" if case == "disabled" else "auto",
    )
    assert isinstance(make_trace(settings), NoopTrace)
    assert emit_trace(settings, "planner", {"api_key": "private"})["status"] == "NOT_CONFIGURED"


def test_provider_error_never_exports_response_body_or_raises():
    settings = PlanSettings(_env_file=None, trace_api_key=SecretStr("fake-key"))
    result = LangSmithTrace(settings, httpx.MockTransport(lambda _: httpx.Response(403, text="private-response"))).emit(
        "planner", {}
    )
    assert result["status"] == "FAILED" and "private-response" not in str(result)


def test_literal_secrets_in_allowed_fields_are_removed_from_export():
    packets = []

    def server(request):
        packets.append(request.content.decode())
        return httpx.Response(200)

    settings = PlanSettings(
        _env_file=None,
        trace_api_key=SecretStr("trace-secret"),
        llm_api_key=SecretStr("llm-secret"),
        vision_adapter_key=SecretStr("vision-secret"),
        trace_project="trace-secret",
    )
    LangSmithTrace(settings, httpx.MockTransport(server)).emit(
        "planner", {"model": "vendor/llm-secret", "prompt_version": "vision-secret", "provider_mode": "trace-secret"}
    )
    assert not any(secret in str(packets) for secret in ("trace-secret", "llm-secret", "vision-secret"))
