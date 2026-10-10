"""LLMClient gọi API /chat/completions tương thích OpenAI (OpenAI, Groq, Gemini, OpenRouter) bằng httpx."""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field, SecretStr

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
logger = logging.getLogger(__name__)

# Gọi sau mỗi lần LLM trả 200: (model, prompt_tokens, completion_tokens), dùng để ghi sổ chi phí AI.
UsageHook = Callable[[str, int, int], None]
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    """Lỗi gọi LLM; message không bao giờ chứa API key."""


class OpenAILLMConfig(BaseModel):
    """Cấu hình client LLM."""

    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr
    model: str = "gpt-4.1-mini"
    timeout_seconds: float = Field(default=20.0, gt=0)
    temperature: float = Field(default=0.1, ge=0, le=2)
    json_mode: bool = True
    max_retries: int = Field(default=1, ge=0)
    retry_delay_seconds: float = Field(default=0.5, ge=0)


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse JSON object từ text của LLM, gỡ fence ```json nếu có."""
    text = content.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("LLM trả về JSON không hợp lệ") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM trả về JSON không phải object")
    return data


class OpenAICompatibleLLM:
    """Implement LLMClient; mọi lỗi (mạng, HTTP, JSON hỏng) đều raise LLMError để node fallback về rule."""

    def __init__(self, config: OpenAILLMConfig, transport: httpx.AsyncBaseTransport | None = None,
                 usage_hook: UsageHook | None = None) -> None:
        self._config = config
        self._transport = transport
        self._usage_hook = usage_hook

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _post_once(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> httpx.Response:
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self._config.api_key.get_secret_value()}"}
        return await client.post(url, json=payload, headers=headers)

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds, transport=self._transport) as client:
            for attempt in range(self._config.max_retries + 1):
                try:
                    response = await self._post_once(client, payload)
                except httpx.TransportError as exc:
                    if attempt >= self._config.max_retries:
                        raise LLMError(f"Lỗi mạng khi gọi LLM ({type(exc).__name__})") from None
                else:
                    if response.status_code not in RETRYABLE_STATUS or attempt >= self._config.max_retries:
                        return response
                await asyncio.sleep(self._config.retry_delay_seconds)
        raise LLMError("Không gọi được LLM")  # pragma: no cover

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Gọi chat completions và trả JSON object đã parse."""
        response = await self._post(self._payload(system, user))
        if response.status_code != 200:
            raise LLMError(f"LLM trả HTTP {response.status_code}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("Phản hồi LLM sai cấu trúc") from None
        self._report_usage(body)
        if not isinstance(content, str):
            raise LLMError("Phản hồi LLM không có nội dung text")
        return parse_json_object(content)

    def _report_usage(self, body: Any) -> None:
        if self._usage_hook is None:
            return
        try:
            usage = body.get("usage") or {}
            self._usage_hook(self._config.model, int(usage.get("prompt_tokens", 0)),
                             int(usage.get("completion_tokens", 0)))
        except Exception:  # noqa: BLE001 - ghi chi phí là phụ, không được làm hỏng kiểm duyệt
            logger.exception("Không ghi được chi phí LLM của moderator")
