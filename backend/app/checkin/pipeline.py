"""Pipeline check-in (chạy nền sau khi API đã trả về).

    load_context -> analyze -> decide -> persist

Dùng LangGraph nếu đã cài (để trace hiển thị theo node), nếu không thì chạy tuần tự cùng các node.
"""
from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from .actions import CheckinContext, PairAccessError, complete_checkin, load_context
from .config import get_settings
from .db import session_factory
from .decision import Decision, decide
from .llm import LLMError, get_llm
from .models import Checkin, CheckinStatus
from .schemas import LLMUsage, VisionResult
from .storage import get_storage
from .timeutil import now_utc
from .tracing import traced

log = logging.getLogger("checkin.pipeline")


class State(TypedDict, total=False):
    checkin_id: str
    ctx: CheckinContext
    image: bytes | None
    note: str | None
    result: VisionResult | None
    usage: LLMUsage | None
    error: str | None
    decision: Decision
    stop: bool


def _node_load(db: Session):
    def node(state: State) -> State:
        checkin = db.get(Checkin, state["checkin_id"])
        if checkin is None or checkin.status != CheckinStatus.PROCESSING:
            return {"stop": True}
        try:
            ctx = load_context(checkin)
        except PairAccessError as e:
            return {"stop": True, "error": str(e)}
        image = get_storage().read(checkin.image_path) if checkin.image_path else None
        return {"ctx": ctx, "image": image, "note": checkin.note, "stop": False}

    return node


@traced("checkin.vision_llm", run_type="llm")
def _call_llm(image, learner_name, concepts, note):
    return get_llm().analyze(
        image=image, media_type="image/jpeg", learner_name=learner_name, concepts=concepts, note=note
    )


def _node_analyze(state: State) -> State:
    if state.get("stop"):
        return {}
    ctx = state["ctx"]
    from .stats import budget_left_usd

    if budget_left_usd() <= 0:  # chặn chi phí: hết ngân sách hôm nay thì để người dùng tự chọn mục
        log.warning("Hết ngân sách AI hôm nay, bỏ qua bước gọi AI")
        return {"result": None, "usage": None, "error": "Hết ngân sách AI hôm nay"}
    attempts = get_settings().llm_max_retries + 1
    last_error = None
    for attempt in range(attempts):
        try:
            result, usage = _call_llm(state.get("image"), ctx.learner_name, ctx.concepts, state.get("note"))
            return {"result": result, "usage": usage, "error": None}
        except LLMError as e:
            last_error = str(e)
            log.warning("Vision lỗi (lần %s/%s): %s", attempt + 1, attempts, e)
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    return {"result": None, "usage": None, "error": last_error}


def _node_decide(state: State) -> State:
    if state.get("stop"):
        return {}
    s = get_settings()
    ctx = state["ctx"]
    return {
        "decision": decide(
            state.get("result"),
            ctx.open_items,
            ctx.concept_names,
            high=s.confidence_high,
            low=s.confidence_low,
            max_confirm=s.max_confirm_options,
            max_week=s.max_week_options,
        )
    }


def _node_persist(db: Session):
    def node(state: State) -> State:
        if state.get("stop"):
            return {}
        checkin = db.get(Checkin, state["checkin_id"])
        if checkin is None or checkin.status != CheckinStatus.PROCESSING:
            return {}
        result, usage, decision = state.get("result"), state.get("usage"), state["decision"]
        if result is not None:
            checkin.ai_result = result.model_dump()
            checkin.confidence = result.confidence
        if usage is not None:
            checkin.model = usage.model
            checkin.input_tokens = usage.input_tokens
            checkin.output_tokens = usage.output_tokens
            checkin.cost_usd = usage.cost_usd
        checkin.error = state.get("error")
        checkin.suggested_plan_item_id = decision.plan_item_id
        checkin.options = [o.model_dump() for o in decision.options]
        created = checkin.created_at
        if created is not None:
            if created.tzinfo is None:
                import datetime as dt

                created = created.replace(tzinfo=dt.UTC)
            checkin.processing_ms = int((now_utc() - created).total_seconds() * 1000)

        if decision.status == CheckinStatus.DONE:
            complete_checkin(db, checkin, decision.plan_item_id, state["ctx"])
        else:
            checkin.status = decision.status
            db.commit()
        return {}

    return node


def _run_graph(db: Session, checkin_id: str) -> None:
    nodes = [
        ("load_context", _node_load(db)),
        ("analyze", _node_analyze),
        ("decide", _node_decide),
        ("persist", _node_persist(db)),
    ]
    try:
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(State)
        for name, fn in nodes:
            g.add_node(name, fn)
        g.add_edge(START, "load_context")
        g.add_conditional_edges("load_context", lambda s: END if s.get("stop") else "analyze")
        g.add_edge("analyze", "decide")
        g.add_edge("decide", "persist")
        g.add_edge("persist", END)
        g.compile().invoke({"checkin_id": checkin_id}, {"run_name": "checkin_pipeline"})
    except ImportError:
        state: dict[str, Any] = {"checkin_id": checkin_id}
        for _, fn in nodes:
            state.update(fn(state) or {})
            if state.get("stop"):
                break


@traced("checkin.pipeline")
def run_pipeline(checkin_id: str) -> None:
    """Điểm vào cho BackgroundTasks. Không bao giờ ném lỗi ra ngoài: lỗi -> trạng thái failed."""
    db = session_factory()()
    try:
        _run_graph(db, checkin_id)
    except Exception as e:  # lưới an toàn cuối cùng
        log.exception("Pipeline lỗi cho check-in %s", checkin_id)
        db.rollback()
        checkin = db.get(Checkin, checkin_id)
        if checkin is not None and checkin.status == CheckinStatus.PROCESSING:
            checkin.status = CheckinStatus.FAILED
            checkin.error = f"{type(e).__name__}: {e}"[:500]
            try:
                ctx = load_context(checkin)
                checkin.options = [
                    {"plan_item_id": i.id, "label": i.label, "concept_name": ctx.concept_names.get(i.concept_id)}
                    for i in ctx.open_items[: get_settings().max_week_options]
                ]
            except Exception:
                checkin.options = []
            db.commit()
    finally:
        db.close()
