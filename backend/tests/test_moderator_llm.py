import asyncio
import json
import logging

import httpx
import pytest
from app.agents.moderator import graph as graph_module
from app.agents.moderator.openai_llm import LLMError, OpenAICompatibleLLM, OpenAILLMConfig, parse_json_object
from app.agents.moderator.settings import ModeratorSettings
from pydantic import SecretStr

SECRET = "sk-super-secret-123"


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _llm(handler, **overrides) -> OpenAICompatibleLLM:
    config = OpenAILLMConfig(api_key=SecretStr(SECRET), retry_delay_seconds=0, **overrides)
    return OpenAICompatibleLLM(config, transport=httpx.MockTransport(handler))


def _run(llm: OpenAICompatibleLLM) -> dict:
    return asyncio.run(llm.complete_json("sys", "user"))


def test_parses_plain_json_and_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _completion('{"intent": "X", "confidence": 0.9}')

    result = _run(_llm(handler, base_url="https://api.groq.com/openai/v1/", model="m1"))

    request = seen[0]
    body = json.loads(request.content)
    assert result == {"intent": "X", "confidence": 0.9}
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "m1"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] <= 0.2
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_json_mode_can_be_disabled() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _completion("{}")

    _run(_llm(handler, json_mode=False))

    assert "response_format" not in bodies[0]


@pytest.mark.parametrize("content", ['```json\n{"a": 1}\n```', '```\n{"a": 1}\n```', '  {"a": 1}  '])
def test_parse_json_object_strips_fences(content: str) -> None:
    assert parse_json_object(content) == {"a": 1}


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_parse_json_object_raises_on_bad_json(content: str) -> None:
    with pytest.raises(LLMError):
        parse_json_object(content)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retries_once_on_retryable_status(status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status) if len(calls) == 1 else _completion('{"ok": true}')

    assert _run(_llm(handler)) == {"ok": True}
    assert len(calls) == 2


def test_retries_once_on_network_error_then_raises() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(LLMError):
        _run(_llm(handler))
    assert len(calls) == 2


def test_gives_up_after_retry_on_persistent_5xx() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(LLMError, match="500"):
        _run(_llm(handler))
    assert len(calls) == 2


def test_does_not_retry_client_errors() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, text=f"bad key {SECRET}")

    with pytest.raises(LLMError) as excinfo:
        _run(_llm(handler))
    assert len(calls) == 1
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize("response", [_completion("```json\n{broken"), httpx.Response(200, json={"choices": []})])
def test_raises_on_broken_json_or_structure(response: httpx.Response) -> None:
    with pytest.raises(LLMError):
        _run(_llm(lambda _request: response))


def test_key_not_in_exception_chain_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {SECRET}", request=request)

    with caplog.at_level(logging.DEBUG), pytest.raises(LLMError) as excinfo:
        _run(_llm(handler))

    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert SECRET not in caplog.text
    assert SECRET not in repr(OpenAILLMConfig(api_key=SecretStr(SECRET)))


def test_settings_key_falls_back_to_openai_api_key() -> None:
    assert ModeratorSettings(_env_file=None, openai_api_key=SecretStr("k2")).effective_llm_api_key == "k2"
    both = ModeratorSettings(_env_file=None, llm_api_key=SecretStr("k1"), openai_api_key=SecretStr("k2"))
    assert both.effective_llm_api_key == "k1"


def test_build_llm_openai_without_key_falls_back_to_fake(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(graph_module.logger, "disabled", False)
    settings = ModeratorSettings(_env_file=None, llm_provider="openai")

    with pytest.raises(ValueError, match="requires an API key"):
        graph_module._build_llm(settings)


def test_build_llm_openai_with_key_returns_real_client(caplog: pytest.LogCaptureFixture) -> None:
    settings = ModeratorSettings(_env_file=None, llm_provider="openai", llm_api_key=SecretStr(SECRET))

    llm = graph_module._build_llm(settings)

    assert isinstance(llm, OpenAICompatibleLLM)
    assert SECRET not in caplog.text
