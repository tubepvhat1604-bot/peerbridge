"""State của LangGraph Socratic Moderator."""

from typing import TypedDict

from ...enums import ModerationAction
from .contract import ModeratorInput, RetrievedSource
from .intents import MessageIntent
from .rules import RuleSignals


class ModeratorState(TypedDict, total=False):
    input: ModeratorInput
    intent: MessageIntent
    rule_signals: RuleSignals
    llm_risk: float | None
    soft_overridden: bool
    risk_score: float
    action: ModerationAction
    reason: str
    guidance: str | None
    needs_human_review: bool
    retrieved_sources: list[RetrievedSource]
    errors: list[str]
    classification_unavailable: bool
    llm_calls_used: int
    verified: bool
    stop_reason: str
    node_latency_ms: dict[str, float]
    socratic_finishing: bool
    llm_called: bool
    prefiltered: bool
    ai_budget_exhausted: bool
    grounded_source: RetrievedSource | None
