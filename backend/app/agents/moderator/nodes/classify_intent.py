"""Node classify_intent: rule + 1 lần gọi LLM (intent + risk), gộp theo tầng HARD/SOFT của rule.

Cách gộp (xem rules.py để biết rule nào HARD/SOFT):
  - Có tín hiệu HARD (gồm prompt_injection)      -> mức nghiêm trọng hơn giữa rule và LLM (LLM không bao giờ hạ được).
  - Chỉ có SOFT, LLM hợp lệ và confidence >= 0.7 -> dùng intent và risk của LLM (ghi vào reason nếu LLM hạ tín hiệu SOFT).
  - LLM lỗi / confidence thấp, hoặc không có rule -> như cũ: LLM chỉ được nâng (confidence >= 0.5), rule vẫn giữ nguyên.
"""

from pydantic import BaseModel, Field

from ..intents import INTENT_SEVERITY, MessageIntent, most_severe
from ..llm import LLMClient
from ..prompts import CLASSIFY_SYSTEM_PROMPT, build_classify_user_prompt
from ..rules import RuleSignals, analyze_message
from ..state import ModeratorState

# LLM có confidence thấp hơn mức này thì không được đổi intent.
LLM_MIN_CONFIDENCE = 0.5
# Chỉ khi confidence >= mức này LLM mới được ghi đè tín hiệu SOFT của rule.
SOFT_OVERRIDE_MIN_CONFIDENCE = 0.7
DEFAULT_INTENT = MessageIntent.CONCEPT_QUESTION


class ClassificationResult(BaseModel):
    """JSON hợp lệ mà LLM phải trả: intent + rủi ro trong cùng một lần gọi."""

    intent: MessageIntent
    confidence: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    reason: str = ""


def _join(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _overrides_soft(signals: RuleSignals, result: ClassificationResult | None) -> bool:
    return bool(
        result is not None and signals.soft and not signals.hard and result.confidence >= SOFT_OVERRIDE_MIN_CONFIDENCE
    )


def _lowers_soft(signals: RuleSignals, result: ClassificationResult) -> bool:
    """LLM đưa ra intent hoặc risk nhẹ hơn tín hiệu SOFT của rule."""
    rule_intent = signals.intent or DEFAULT_INTENT
    return INTENT_SEVERITY[result.intent] < INTENT_SEVERITY[rule_intent] or result.risk < signals.risk


def merge_intent(signals: RuleSignals, result: ClassificationResult | None) -> tuple[MessageIntent, bool, str]:
    """Trả (intent, soft_overridden, reason) theo bảng gộp ở docstring module."""
    rule_reason = f"rules: {', '.join(signals.matched)}" if signals.matched else ""
    if result is not None and _overrides_soft(signals, result):
        note = f"llm hạ tín hiệu SOFT ({', '.join(signals.soft)}): " if _lowers_soft(signals, result) else "llm: "
        return result.intent, True, _join(rule_reason, note + result.reason)
    candidates = [signals.intent] if signals.intent else []
    reason = rule_reason
    if result is not None and result.confidence >= LLM_MIN_CONFIDENCE:
        candidates.append(result.intent)
        reason = _join(reason, f"llm: {result.reason}")
    return most_severe(candidates) or DEFAULT_INTENT, False, reason


async def classify_intent(state: ModeratorState, llm: LLMClient) -> dict:
    """Trả intent, llm_risk, soft_overridden, rule_signals, reason, errors."""
    payload = state["input"]
    signals = analyze_message(payload.message)
    errors = list(state.get("errors", []))
    result: ClassificationResult | None = None
    try:
        raw = await llm.complete_json(
            CLASSIFY_SYSTEM_PROMPT, build_classify_user_prompt(payload.message, payload.conversation_history)
        )
        result = ClassificationResult.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - LLM lỗi không được làm hỏng graph
        errors.append(f"classify_intent: {type(exc).__name__}: {exc}")
    intent, soft_overridden, reason = merge_intent(signals, result)
    return {
        "intent": intent,
        "llm_risk": result.risk if result else None,
        "soft_overridden": soft_overridden,
        "rule_signals": signals,
        "reason": reason,
        "errors": errors,
        "classification_unavailable": result is None,
    }
