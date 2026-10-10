"""Node assess_risk: risk_score cuối cùng do code tính; không gọi LLM thêm.

- LLM đã ghi đè tín hiệu SOFT (soft_overridden)  -> risk_score = risk của LLM.
- Còn lại                                        -> max(rule_risk, llm_risk): LLM không thể hạ dưới mức rule.
"""

from ..state import ModeratorState


def combine_risk(rule_risk: float, llm_risk: float | None) -> float:
    """risk_score = max(rule_risk, llm_risk) kẹp trong 0..1; LLM không thể hạ dưới mức rule."""
    return min(1.0, max(0.0, rule_risk, llm_risk or 0.0))


def assess_risk(state: ModeratorState) -> dict:
    """Tính risk_score từ rule_signals, llm_risk (None nếu LLM lỗi) và soft_overridden của classify_intent."""
    llm_risk = state.get("llm_risk")
    if state.get("soft_overridden") and llm_risk is not None:
        return {"risk_score": min(1.0, max(0.0, llm_risk))}
    return {"risk_score": combine_risk(state["rule_signals"].risk, llm_risk)}
