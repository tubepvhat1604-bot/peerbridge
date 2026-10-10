"""Interface LLM của moderator và bản FakeLLM chạy không cần API key."""

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel

LLMRule = Callable[[str, str], dict[str, Any]]


class LLMClient(Protocol):
    """Client LLM trả về JSON đã parse."""

    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class LLMCall(BaseModel):
    """Một lần gọi FakeLLM, dùng để test kiểm tra."""

    system: str
    user: str


class FakeLLM:
    """LLM giả: trả response định sẵn theo thứ tự hoặc theo hàm rule."""

    def __init__(self, responses: Sequence[dict[str, Any]] | None = None, rule: LLMRule | None = None) -> None:
        if responses is not None and rule is not None:
            raise ValueError("Provide either responses or rule, not both")
        self._responses = list(responses or [])
        self._rule = rule
        self.calls: list[LLMCall] = []

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Ghi lại lần gọi rồi trả response kế tiếp hoặc kết quả của rule."""
        self.calls.append(LLMCall(system=system, user=user))
        if self._rule is not None:
            return self._rule(system, user)
        if not self._responses:
            raise RuntimeError("FakeLLM has no more scripted responses")
        return self._responses.pop(0)


def neutral_fake_llm() -> FakeLLM:
    """FakeLLM mặc định: confidence 0 và risk 0, nên quyết định hoàn toàn do rule."""
    payload = {"intent": "CONCEPT_QUESTION", "confidence": 0.0, "risk": 0.0, "reason": "fake llm"}
    return FakeLLM(rule=lambda _system, _user: dict(payload))
