"""Coach v2 chooses from code-authorized actions; no write tools or RAM interrupts.

Plan confirmation is the durable pb_plans DRAFT workflow outside this graph.
"""

import asyncio
import json
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .coach import TEMPLATES, decide_v1
from .llm import CompatibleLLM, FakeLLM
from .nudge import PROMPT_VERSION, SYSTEM_PROMPT, ActionResponse, validate_message
from .tracing import private_graph_context, safe_usage


class CoachState(TypedDict, total=False):
    allowed: list[str]
    reason: str
    concept_id: str | None
    action: str
    raw: dict
    mode: str
    nodes: list[str]
    error: str
    text: str
    latency_ms: float


class CoachSelector:
    def __init__(self, llm, timeout=20):
        self.llm, self.timeout = llm, timeout
        graph = StateGraph(CoachState)
        for name, node in [
            ("load_context", self.load),
            ("eligibility", self.eligibility),
            ("decide", self.decide),
            ("validate_action", self.validate),
            ("prepare_action", self.prepare),
            ("save_log", self.save),
        ]:
            graph.add_node(name, node)
        graph.add_edge(START, "load_context")
        for left, right in zip(
            ["load_context", "eligibility", "decide", "validate_action", "prepare_action"],
            ["eligibility", "decide", "validate_action", "prepare_action", "save_log"],
        ):
            graph.add_edge(left, right)
        graph.add_edge("save_log", END)
        self.graph = graph.compile()

    def load(self, state):
        return {"nodes": ["load_context"], "mode": "v2"}

    def eligibility(self, state):
        allowed = [a for a in dict.fromkeys(state["allowed"]) if a in TEMPLATES or a == "no_action"]
        if state["reason"] != "ELIGIBLE" or not allowed:
            allowed = ["no_action"]
        elif "no_action" not in allowed:
            allowed.append("no_action")
        return {"allowed": allowed, "nodes": state["nodes"] + ["eligibility"]}

    async def decide(self, state):
        if state["allowed"] == ["no_action"]:
            return {"raw": {"action": "no_action", "message": ""}, "nodes": state["nodes"] + ["decide"]}
        try:
            raw = await asyncio.wait_for(
                self.llm.complete_json(
                    SYSTEM_PROMPT,
                    json.dumps(
                        {"allowed": state["allowed"], "reason": state["reason"], "concept_id": state.get("concept_id")}
                    ),
                ),
                self.timeout,
            )
            return {"raw": raw, "nodes": state["nodes"] + ["decide"]}
        except Exception as error:
            return {"error": type(error).__name__, "nodes": state["nodes"] + ["decide"]}

    def validate(self, state):
        try:
            if state.get("error"):
                raise ValueError("provider_failure")
            result = ActionResponse.model_validate(state.get("raw"))
            if result.action not in state["allowed"]:
                raise ValueError("unauthorized_action")
            text = validate_message(result.action, result.message, state.get("concept_id"))
            update = {"action": result.action, "text": text}
        except ValueError:
            update = {
                "action": decide_v1(state["allowed"]),
                "mode": "v1_fallback",
                "error": state.get("error", "INVALID_ACTION"),
                "text": TEMPLATES.get(decide_v1(state["allowed"]), "").format(concept_id=state.get("concept_id") or ""),
            }
        return {**update, "nodes": state["nodes"] + ["validate_action"]}

    def prepare(self, state):
        text = state.get("text", "")
        return {"text": text, "nodes": state["nodes"] + ["prepare_action"]}

    def save(self, state):
        return {"nodes": state["nodes"] + ["save_log"]}

    async def select(self, actions, reason, concept=None):
        start = time.perf_counter()
        with private_graph_context():
            result = await self.graph.ainvoke({"allowed": actions, "reason": reason, "concept_id": concept})
        # Never persist raw provider output or free-form reasons.
        return {
            "mode": result["mode"],
            "action": result["action"],
            "text": result["text"],
            "message_source": "ai"
            if result["mode"] == "v2" and result["action"] != "no_action"
            else "template"
            if result["action"] != "no_action"
            else "none",
            "nodes": result["nodes"],
            "error": result.get("error"),
            "model": self.llm.model,
            "provider_mode": self.llm.mode,
            "prompt_version": PROMPT_VERSION,
            "latency_ms": round((time.perf_counter() - start) * 1000, 3),
            "usage": safe_usage(self.llm.usage),
            "cost": self.llm.cost,
        }


def make_selector(settings):
    if settings.llm_provider == "openai_compatible":
        return CoachSelector(CompatibleLLM(settings), settings.llm_timeout_seconds)
    # Fake AI selection is labelled explicitly; template provider stays on Coach v1.
    if settings.llm_provider == "fake":
        return CoachSelector(FakeLLM([{"action": "no_action", "message": ""}]), settings.llm_timeout_seconds)
    return None
