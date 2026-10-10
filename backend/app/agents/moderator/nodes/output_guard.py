"""Node output_guard: guidance xấu bị thay bằng template an toàn; action và retrieved_sources giữ nguyên."""

from pydantic import BaseModel, StrictBool

from ....enums import ModerationAction
from ..llm import LLMClient
from ..output_guard import check_output
from ..prompts import JUDGE_SYSTEM_PROMPT, build_judge_user_prompt
from ..state import ModeratorState
from .choose_action import template_guidance


class JudgeResult(BaseModel):
    """JSON hợp lệ mà LLM judge phải trả."""

    reveals_answer: StrictBool
    reason: str = ""


async def _judge_violations(state: ModeratorState, guidance: str, llm: LLMClient) -> list[str]:
    """Hỏi LLM 1 lần; lỗi hoặc JSON sai thì coi như không đạt."""
    try:
        raw = await llm.complete_json(JUDGE_SYSTEM_PROMPT, build_judge_user_prompt(state["input"].message, guidance))
        result = JudgeResult.model_validate(raw)
    except Exception:  # noqa: BLE001 - judge lỗi => fail-safe dùng template
        return ["judge_error"]
    return ["judge_reject"] if result.reveals_answer else []


async def output_guard(state: ModeratorState, llm: LLMClient, judge_enabled: bool) -> dict:
    """Kiểm tra guidance bằng check_output (và LLM judge nếu bật, chỉ cho GUIDE); vi phạm thì dùng template."""
    guidance = state.get("guidance")
    if not guidance:
        return {}
    template = template_guidance(state["action"], state["intent"])
    if guidance == template:
        return {}  # template do code viết, đã an toàn (không bị luật Socratic áp vào lời cảnh báo WARN)
    violations = check_output(guidance, state).violations
    if judge_enabled and not violations and state["action"] is ModerationAction.GUIDE:
        violations = await _judge_violations(state, guidance, llm)
    if not violations:
        return {}
    errors = [*state.get("errors", []), f"output_guard: {', '.join(violations)}"]
    return {"guidance": template, "errors": errors}
