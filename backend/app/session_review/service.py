"""Chấm/tóm tắt phiên, số đo "phiên không lộ đáp án" và số liệu cho dashboard Admin."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import SecretStr

from ..db import database, utc_now
from .judge import SessionReview, ai_review, dumps, rules_review
from .transcript import delivered_messages, load_session

LLMFactory = Callable[[], Any]
SAMPLE_EMAIL = "%@mau.peerbridge"  # bạn học mẫu của chế độ demo, không tính vào số liệu


def review_llm() -> Any | None:
    """LLM cho tóm tắt/chấm phiên: dùng chung cấu hình moderator, ghi chi phí vào sổ AI với tên session_review."""
    from ..agents.moderator.openai_llm import OpenAICompatibleLLM, OpenAILLMConfig
    from ..agents.moderator.settings import get_moderator_settings
    from ..loop.ai_budget import record

    settings = get_moderator_settings()
    key = settings.effective_llm_api_key
    if settings.llm_provider == "fake" or not key:
        return None
    return OpenAICompatibleLLM(
        OpenAILLMConfig(base_url=settings.llm_base_url, api_key=SecretStr(key), model=settings.llm_model,
                        timeout_seconds=settings.llm_timeout_seconds, json_mode=settings.llm_json_mode, max_retries=0),
        usage_hook=lambda model, prompt, completion: record("session_review", model, prompt, completion),
    )


def _budget_left() -> float:
    from ..loop.ai_budget import budget_left

    return budget_left()


def _row_to_review(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": int(row["session_id"]), "mode": row["mode"], "summary": row["summary"],
        "key_points": json.loads(row["key_points"]), "open_questions": json.loads(row["open_questions"]),
        "next_steps": json.loads(row["next_steps"]), "socratic_score": row["socratic_score"],
        "answer_leaked": bool(row["answer_leaked"]), "leak_message_ids": json.loads(row["leak_message_ids"]),
        "judge_notes": row["judge_notes"], "message_count": int(row["message_count"]),
        "last_message_id": int(row["last_message_id"]), "updated_at": row["updated_at"],
    }


def get_review(connection: sqlite3.Connection, session_id: int) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM session_reviews WHERE session_id = ?", (session_id,)).fetchone()
    return _row_to_review(row) if row else None


def student_view(review: dict[str, Any] | None) -> dict[str, Any] | None:
    """Phần sinh viên được xem: chỉ tóm tắt và gợi ý, không có điểm chấm."""
    if review is None:
        return None
    keys = ("session_id", "mode", "summary", "key_points", "open_questions", "next_steps", "message_count", "updated_at")
    return {key: review[key] for key in keys}


async def review_session(session_id: int, requested_by: int | None, *, force: bool = False,
                         llm_factory: LLMFactory = review_llm,
                         budget_left: Callable[[], float] = _budget_left) -> dict[str, Any] | None:
    """Tóm tắt + chấm phiên. Không có tin mới từ lần chấm trước thì trả kết quả cũ (không gọi AI lại)."""
    with database() as connection:
        session = load_session(connection, session_id)
        if session is None:
            return None
        existing = get_review(connection, session_id)
    messages = delivered_messages(session)
    last_id = messages[-1]["id"] if messages else 0
    if existing and existing["last_message_id"] == last_id and (not force or existing["mode"] == "ai"):
        return existing
    llm = llm_factory() if messages else None
    error = None
    if llm is not None and budget_left() > 0:
        review, error = await ai_review(llm, session["topic"], messages)
    else:
        review = rules_review(session["topic"], messages)
    with database() as connection:
        _store(connection, session_id, review, len(messages), last_id, requested_by)
        stored = get_review(connection, session_id)
    if stored is not None and error:
        stored["ai_error"] = error
    return stored


def _store(connection: sqlite3.Connection, session_id: int, review: SessionReview, count: int, last_id: int,
           requested_by: int | None) -> None:
    now = utc_now()
    connection.execute(
        """INSERT INTO session_reviews(session_id, mode, summary, key_points, open_questions, next_steps,
               socratic_score, answer_leaked, leak_message_ids, judge_notes, message_count, last_message_id,
               requested_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET mode=excluded.mode, summary=excluded.summary,
               key_points=excluded.key_points, open_questions=excluded.open_questions, next_steps=excluded.next_steps,
               socratic_score=excluded.socratic_score, answer_leaked=excluded.answer_leaked,
               leak_message_ids=excluded.leak_message_ids, judge_notes=excluded.judge_notes,
               message_count=excluded.message_count, last_message_id=excluded.last_message_id,
               requested_by=excluded.requested_by, updated_at=excluded.updated_at""",
        (session_id, review.mode, review.summary, dumps(review.key_points), dumps(review.open_questions),
         dumps(review.next_steps), review.socratic_score, int(review.answer_leaked), dumps(review.leak_message_ids),
         review.judge_notes, count, last_id, requested_by, now, now),
    )


# ---- Số liệu cho Admin ----


def _slipped_through(session: dict[str, Any]) -> bool:
    """Admin đổi một tin đã phát (ALLOW/GUIDE) thành chặn/cảnh báo = có tin lộ đáp án lọt qua AI."""
    return any(m["agent_action"] in {"ALLOW", "GUIDE"} and m["final_action"] in {"WARN", "BLOCK", "ESCALATE"}
               for m in session["messages"])


def session_verdict(connection: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    """Kết luận của một phiên: dùng kết quả đã lưu, chưa chấm thì chấm nhanh bằng luật (không gọi AI)."""
    stored = get_review(connection, int(session["id"]))
    delivered = delivered_messages(session)
    if stored is None:
        quick = rules_review(session["topic"], delivered)
        stored = {"mode": "rules", "socratic_score": quick.socratic_score, "answer_leaked": quick.answer_leaked,
                  "stored": False}
    else:
        stored = {**stored, "stored": True}
    leaked = bool(stored["answer_leaked"]) or _slipped_through(session)
    return {"mode": stored["mode"], "stored": stored["stored"], "socratic_score": stored["socratic_score"],
            "answer_leaked": leaked, "has_chat": bool(delivered)}


def session_rows(connection: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    ids = [int(row["id"]) for row in connection.execute(
        "SELECT id FROM study_sessions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    rows = []
    for session_id in ids:
        session = load_session(connection, session_id)
        if session is None:
            continue
        messages = session["messages"]
        verdict = session_verdict(connection, session)
        rows.append({
            "id": session_id, "peer_match_id": session["peer_match_id"], "topic": session["topic"],
            "learner": {"id": session["learner_id"], "name": session["learner_name"]},
            "helper": {"id": session["helper_id"], "name": session["helper_name"]},
            "scheduled_start": session["scheduled_start"], "created_at": session["created_at"],
            "message_count": len(messages),
            "held_count": sum(1 for m in messages if m["final_action"] and not m["delivered"]),
            "guide_count": sum(1 for m in messages if m["final_action"] == "GUIDE"),
            "pending_review": sum(1 for m in messages if m["needs_review"]),
            "last_activity": messages[-1]["created_at"] if messages else session["created_at"],
            "verdict": verdict,
        })
    return rows


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def overview(connection: sqlite3.Connection) -> dict[str, Any]:
    sessions = session_rows(connection, limit=1000)
    with_chat = [s for s in sessions if s["verdict"]["has_chat"]]
    leaked = [s for s in with_chat if s["verdict"]["answer_leaked"]]
    scores = [s["verdict"]["socratic_score"] for s in with_chat if s["verdict"]["socratic_score"] is not None]
    events = connection.execute("SELECT agent_action, context FROM moderation_events").fetchall()
    actions = Counter(row["agent_action"] for row in events)
    prefiltered = ai_classified = 0
    for row in events:
        try:
            audit = json.loads(row["context"] or "{}").get("audit") or {}
        except (TypeError, ValueError):
            audit = {}
        prefiltered += bool(audit.get("prefiltered"))
        ai_classified += int(audit.get("llm_calls_used") or 0) > 0
    week_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    pending = connection.execute(
        """SELECT COUNT(*) FROM moderation_events me
           LEFT JOIN instructor_reviews ir ON ir.moderation_event_id = me.id
           WHERE me.needs_human_review = 1 AND ir.id IS NULL""").fetchone()[0]
    return {
        "students": connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='STUDENT' AND is_seed=0 AND email NOT LIKE ?",
            (SAMPLE_EMAIL,)).fetchone()[0],
        "pairs": connection.execute("SELECT COUNT(*) FROM peer_matches").fetchone()[0],
        "sessions_total": len(sessions),
        "sessions_with_chat": len(with_chat),
        "sessions_7d": sum(1 for s in sessions if (s["created_at"] or "") >= week_ago),
        "messages_total": sum(s["message_count"] for s in sessions),
        "messages_held": sum(s["held_count"] for s in sessions),
        "guides_total": sum(s["guide_count"] for s in sessions),
        "actions": {action: actions.get(action, 0) for action in ("ALLOW", "GUIDE", "WARN", "BLOCK", "ESCALATE")},
        "pending_reviews": int(pending),
        "leak_free": {"sessions": len(with_chat), "leaked": len(leaked),
                      "rate": _rate(len(with_chat) - len(leaked), len(with_chat)),
                      "judged_by_ai": sum(1 for s in with_chat if s["verdict"]["mode"] == "ai")},
        "socratic_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "ai": _ai_usage(prefiltered, ai_classified),
        "network": _network(sessions),
    }


def _ai_usage(prefiltered: int, ai_classified: int) -> dict[str, Any]:
    from ..loop.ai_budget import budget_left, cost_since

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        costs = cost_since(day_start)
        left = budget_left()
    except Exception:  # noqa: BLE001 - số liệu chi phí là phụ
        costs, left = {}, None
    return {"messages_prefiltered": prefiltered, "messages_ai_classified": ai_classified,
            "saved_rate": _rate(prefiltered, prefiltered + ai_classified),
            "moderation_cost_today_usd": round(costs.get("moderation", 0.0), 4),
            "review_cost_today_usd": round(costs.get("session_review", 0.0), 4),
            "budget_left_usd": round(left, 4) if left is not None else None}


def _network(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: dict[int, dict[str, Any]] = {}
    for s in sessions:
        pair = pairs.setdefault(s["peer_match_id"], {
            "peer_match_id": s["peer_match_id"], "members": [s["learner"], s["helper"]], "sessions": 0,
            "messages": 0, "held": 0, "leaked_sessions": 0, "socratic_scores": [], "last_activity": ""})
        pair["sessions"] += 1
        pair["messages"] += s["message_count"]
        pair["held"] += s["held_count"]
        pair["leaked_sessions"] += int(s["verdict"]["answer_leaked"])
        if s["verdict"]["socratic_score"] is not None:
            pair["socratic_scores"].append(s["verdict"]["socratic_score"])
        pair["last_activity"] = max(pair["last_activity"], s["last_activity"] or "")
    result = []
    for pair in pairs.values():
        scores = pair.pop("socratic_scores")
        pair["socratic_avg"] = round(sum(scores) / len(scores), 2) if scores else None
        result.append(pair)
    return sorted(result, key=lambda p: p["last_activity"], reverse=True)[:100]
