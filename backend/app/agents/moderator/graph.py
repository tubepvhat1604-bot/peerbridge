"""LangGraph Socratic Moderator: classify_intent -> assess_risk -> choose_action."""

import asyncio
import logging
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr

from ...enums import ModerationAction
from .contract import ModeratorInput, ModeratorOutput, RetrievedSource
from .intents import MessageIntent
from .llm import LLMClient, neutral_fake_llm
from .nodes.assess_risk import assess_risk
from .nodes.choose_action import choose_action
from .nodes.classify_intent import classify_intent, merge_intent
from .nodes.generate_guidance import generate_guidance
from .nodes.output_guard import output_guard
from .nodes.retrieve_context import retrieve_context
from .openai_llm import LLMError, OpenAICompatibleLLM, OpenAILLMConfig
from .output_guard import sanitize_reason
from .prefilter import needs_llm
from .prompts import PROMPT_VERSION, source_label
from .retriever import FakeRetriever, Retriever
from .rules import analyze_message
from .settings import ModeratorSettings, get_moderator_settings
from .socratic import exit_requested
from .state import ModeratorState

logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 300

# Trả số USD còn lại trong trần chi phí AI chung của ngày; <= 0 thì moderator chỉ dùng luật.
BudgetLeft = Callable[[], float]


class BudgetedLLM:
    """Không gọi LLM khi đã hết trần chi phí ngày; node gọi LLM tự quay về luật/template khi nhận LLMError."""

    def __init__(self, inner: LLMClient, budget_left: BudgetLeft) -> None:
        self._inner, self._budget_left = inner, budget_left

    async def complete_json(self, system: str, user: str) -> dict:
        if self._budget_left() <= 0:
            raise LLMError("AI_DAILY_BUDGET_EXCEEDED")
        return await self._inner.complete_json(system, user)


def route_after_action(state: ModeratorState) -> str:
    """Chỉ nhánh GUIDE mới đi qua RAG; mọi action khác kết thúc ngay."""
    return "retrieve_context" if state["action"] is ModerationAction.GUIDE and not state.get("socratic_finishing") else "output_guard"


def build_moderator_graph(llm: LLMClient, retriever: Retriever, settings: ModeratorSettings,
                          budget_left: BudgetLeft | None = None) -> Any:
    """Compile graph: preflight_rules -> [classify_intent] -> assess_risk -> choose_action
    -> [GUIDE: retrieve_context -> generate_guidance] -> output_guard.

    preflight_rules bỏ qua classify_intent (không gọi LLM) khi: luật HARD đã bắt được, hết trần chi phí AI ngày,
    hoặc tin chỉ là chat thường (prefilter.py).
    """
    if budget_left is not None:
        llm = BudgetedLLM(llm, budget_left)

    def _rules_only(signals, reason: str, **extra) -> dict:
        intent, _overridden, rule_reason = merge_intent(signals, None)
        return {"rule_signals": signals, "intent": intent, "llm_risk": None, "soft_overridden": False,
                "classification_unavailable": False, "llm_calls_used": 0,
                "reason": "; ".join(part for part in (rule_reason, reason) if part), **extra}

    def preflight_node(state: ModeratorState) -> dict:
        payload = state["input"]
        signals = analyze_message(payload.message)
        if signals.hard:
            return {"rule_signals": signals, "intent": signals.intent, "llm_risk": None,
                    "soft_overridden": False, "classification_unavailable": False,
                    "llm_calls_used": 0, "reason": f"rules: {', '.join(signals.matched)}"}
        if budget_left is not None and budget_left() <= 0:
            return _rules_only(signals, "hết trần chi phí AI trong ngày, chỉ dùng luật", ai_budget_exhausted=True)
        socratic_active = bool(payload.socratic_session and payload.socratic_session.active)
        if settings.moderation_prefilter_enabled and not needs_llm(payload.message, signals, socratic_active):
            return {**_rules_only(signals, "lọc trước: chat thường, không cần AI"),
                    "intent": MessageIntent.SOCIAL, "prefiltered": True}
        return {"rule_signals": signals}

    async def classify_node(state: ModeratorState) -> dict:
        start = time.perf_counter()
        result = await classify_intent(state, llm)
        return {**result, "llm_calls_used": 1, "node_latency_ms": {**state.get("node_latency_ms", {}),
            "classify_intent": (time.perf_counter() - start) * 1000}}

    def choose_node(state: ModeratorState) -> dict:
        decision = choose_action(state, settings.risk_escalate_threshold)
        session = state["input"].socratic_session
        if not session or not session.active or decision["action"] not in {ModerationAction.ALLOW, ModerationAction.GUIDE}:
            return decision
        if exit_requested(state["input"].message):
            return {**decision, "action": ModerationAction.ALLOW, "guidance": None,
                    "reason": "Socratic session ended by learner", "socratic_finishing": True}
        finishing = session.turn_count + 1 >= settings.max_socratic_turns
        return {**decision, "action": ModerationAction.GUIDE,
                "guidance": "Bạn thử tự làm bước tiếp theo từ gợi ý vừa rồi được không? Nếu còn vướng, hãy hỏi bạn học hoặc xem lại phần tài liệu liên quan nhé." if finishing else decision["guidance"],
                "reason": "continuing Socratic session", "socratic_finishing": finishing}

    async def retrieve_node(state: ModeratorState) -> dict:
        start = time.perf_counter()
        result = await retrieve_context(state, retriever, settings.rag_top_k, settings.rag_default_course_id)
        return {**result, "node_latency_ms": {**state.get("node_latency_ms", {}),
            "retrieve_context": (time.perf_counter() - start) * 1000}}

    async def guidance_node(state: ModeratorState) -> dict:
        if state.get("socratic_finishing"):
            return {}
        used = state.get("llm_calls_used", 0)
        if used >= settings.max_llm_calls:
            return {"stop_reason": "call_budget"}
        result = await generate_guidance(state, llm)
        return {**result, "llm_calls_used": used + int(result.get("llm_called", False))}

    async def guard_node(state: ModeratorState) -> dict:
        used = state.get("llm_calls_used", 0)
        judge = settings.output_guard_llm_judge and used < settings.max_llm_calls
        class CountingLLM:
            calls = 0
            async def complete_json(self, system: str, user: str) -> dict:
                self.calls += 1
                return await llm.complete_json(system, user)
        counted = CountingLLM()
        result = await output_guard(state, counted, judge)
        source = state.get("grounded_source")
        if source and "guidance" not in result and state.get("guidance"):
            # Gợi ý AI qua được kiểm duyệt và dựa trên tài liệu: thêm nguồn để người học mở đúng slide.
            result = {**result, "guidance": f"{state['guidance']}\n(Xem {source_label(source)})"}
        return {**result, "llm_calls_used": used + counted.calls}

    def verify_node(state: ModeratorState) -> dict:
        _to_output(state)
        if state["action"] == ModerationAction.GUIDE and not state.get("guidance"):
            raise ValueError("GUIDE requires verified guidance")
        return {"verified": True, "stop_reason": state.get("stop_reason", "verified")}

    builder = StateGraph(ModeratorState)
    builder.add_node("preflight_rules", preflight_node)
    builder.add_node("classify_intent", classify_node)
    builder.add_node("assess_risk", assess_risk)
    builder.add_node("choose_action", choose_node)
    builder.add_node("retrieve_context", retrieve_node)
    builder.add_node("generate_guidance", guidance_node)
    builder.add_node("output_guard", guard_node)
    builder.add_node("verify_contract", verify_node)
    builder.add_edge(START, "preflight_rules")
    builder.add_conditional_edges("preflight_rules",
        lambda state: "assess_risk" if "intent" in state else "classify_intent",
        ["assess_risk", "classify_intent"])
    builder.add_edge("classify_intent", "assess_risk")
    builder.add_edge("assess_risk", "choose_action")
    builder.add_conditional_edges("choose_action", route_after_action, ["retrieve_context", "output_guard"])
    builder.add_edge("retrieve_context", "generate_guidance")
    builder.add_edge("generate_guidance", "output_guard")
    builder.add_edge("output_guard", "verify_contract")
    builder.add_edge("verify_contract", END)
    return builder.compile()


def _snippet(source: RetrievedSource) -> RetrievedSource:
    """Bản output của source: text cắt còn tối đa SNIPPET_MAX_CHARS ký tự."""
    if source.text is None or len(source.text) <= SNIPPET_MAX_CHARS:
        return source
    return source.model_copy(update={"text": source.text[: SNIPPET_MAX_CHARS - 1].rstrip() + "…"})


def _to_output(state: ModeratorState) -> ModeratorOutput:
    return ModeratorOutput(
        action=state["action"],
        risk_score=state["risk_score"],
        reason=sanitize_reason(state["reason"]),
        guidance=state.get("guidance"),
        needs_human_review=state["needs_human_review"],
        retrieved_sources=[_snippet(source) for source in state.get("retrieved_sources", [])],
        audit={"trace_id": str(state["input"].message_id), "prompt_version": PROMPT_VERSION,
               "llm_calls_used": state.get("llm_calls_used", 0), "verified": state.get("verified", False),
               "intent": str(state.get("intent", "")), "prefiltered": bool(state.get("prefiltered", False)),
               "ai_budget_exhausted": bool(state.get("ai_budget_exhausted", False)),
               "stop_reason": state.get("stop_reason", "verification"),
               "node_latency_ms": state.get("node_latency_ms", {})},
    )


def _system_error_output(exc: Exception) -> ModeratorOutput:
    return ModeratorOutput(
        action=ModerationAction.ESCALATE,
        risk_score=1.0,
        reason=sanitize_reason(
            f"Lỗi hệ thống khi kiểm duyệt ({type(exc).__name__}); chuyển Admin xem xét."
        ),
        needs_human_review=True,
    )


def _failed_state(payload: ModeratorInput, exc: Exception) -> ModeratorState:
    """State tối thiểu khi graph lỗi, để vẫn ghi được audit event."""
    return {"input": payload, "errors": [f"system: {type(exc).__name__}"]}


async def run_moderator_with_state(graph: Any, payload: ModeratorInput) -> tuple[ModeratorOutput, ModeratorState]:
    """Chạy graph, trả (output, state cuối). Mọi lỗi thành ESCALATE nên luôn có ModeratorOutput hợp lệ."""
    try:
        state = await asyncio.wait_for(graph.ainvoke({"input": payload, "errors": [], "llm_calls_used": 0}),
            timeout=get_moderator_settings().moderation_timeout_seconds)
        if not state.get("verified"):
            raise ValueError("Unverified moderator output")
        return _to_output(state), state
    except Exception as exc:  # noqa: BLE001 - fail-safe: lỗi hệ thống -> HITL
        return _system_error_output(exc), _failed_state(payload, exc)


async def run_moderator(graph: Any, payload: ModeratorInput) -> ModeratorOutput:
    """Chạy graph; mọi lỗi được chuyển thành ESCALATE nên luôn trả ModeratorOutput hợp lệ."""
    output, _state = await run_moderator_with_state(graph, payload)
    return output


def _build_llm(settings: ModeratorSettings) -> LLMClient:
    if settings.llm_provider == "fake":
        return neutral_fake_llm()
    api_key = settings.effective_llm_api_key
    if not api_key:
        raise ValueError("Configured LLM provider requires an API key")
    return OpenAICompatibleLLM(
        OpenAILLMConfig(
            base_url=settings.llm_base_url,
            api_key=SecretStr(api_key),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            json_mode=settings.llm_json_mode,
            max_retries=0,
        ),
        usage_hook=_record_usage,
    )


def _record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Ghi chi phí kiểm duyệt vào sổ chi phí AI chung (trần VISION_DAILY_BUDGET_USD)."""
    from ...loop.ai_budget import record

    record("moderation", model, prompt_tokens, completion_tokens)


def _shared_budget_left() -> float:
    from ...loop.ai_budget import budget_left

    return budget_left()


def _build_retriever(settings: ModeratorSettings) -> Retriever:
    if settings.retriever_provider == "fake":
        return FakeRetriever()
    if settings.retriever_provider == "local":
        from .local_retriever import LocalRetriever

        return LocalRetriever(Path(settings.rag_corpus_dir), min_score=settings.rag_local_min_score)
    from .embedding import get_e5_embedder
    from .qdrant_retriever import QdrantRetriever, QdrantRetrieverConfig, get_client

    return QdrantRetriever(
        get_client(settings.qdrant_url),
        get_e5_embedder(settings.embedding_model),
        QdrantRetrieverConfig(collection=settings.qdrant_collection, min_score=settings.rag_min_score),
    )


@lru_cache
def _default_retriever() -> Retriever:
    return _build_retriever(get_moderator_settings())


@lru_cache
def _default_graph() -> Any:
    settings = get_moderator_settings()
    budget = None if settings.llm_provider == "fake" else _shared_budget_left
    return build_moderator_graph(_build_llm(settings), _default_retriever(), settings, budget_left=budget)


async def warmup_moderator() -> bool:
    """Dựng graph và nạp model khi corpus đã tồn tại; helper tùy chọn, không được gọi bởi app.main.

    Trả True nếu sẵn sàng; lỗi chỉ được log (moderate vẫn fail-safe về ESCALATE).
    """
    try:
        graph = _default_graph()
        warm = getattr(_default_retriever(), "warmup", None)
        if warm is not None:
            await asyncio.to_thread(warm)
    except Exception as exc:  # noqa: BLE001 - warmup không được làm sập app
        logger.warning("warmup_moderator thất bại (%s: %s)", type(exc).__name__, exc)
        return False
    return graph is not None


async def moderate_default_with_state(payload: ModeratorInput) -> tuple[ModeratorOutput, ModeratorState]:
    """Chạy graph mặc định theo settings, trả (output, state); lỗi dựng graph cũng thành ESCALATE."""
    try:
        graph = _default_graph()
    except Exception as exc:  # noqa: BLE001 - fail-safe
        return _system_error_output(exc), _failed_state(payload, exc)
    return await run_moderator_with_state(graph, payload)


async def moderate_default(payload: ModeratorInput) -> ModeratorOutput:
    """Chạy graph mặc định theo settings; lỗi dựng graph cũng thành ESCALATE."""
    output, _state = await moderate_default_with_state(payload)
    return output
