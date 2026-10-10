"""Đọc nội dung một phiên học kèm kết quả kiểm duyệt từng tin."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

DELIVERED = {"ALLOW", "GUIDE"}


def load_session(connection: sqlite3.Connection, session_id: int) -> dict[str, Any] | None:
    session = connection.execute(
        """SELECT ss.id, ss.peer_match_id, ss.learner_id, ss.helper_id, ss.topic, ss.scheduled_start,
                  ss.scheduled_end, ss.created_at,
                  lp.display_name AS learner_name, hp.display_name AS helper_name
           FROM study_sessions ss
           LEFT JOIN profiles lp ON lp.user_id = ss.learner_id
           LEFT JOIN profiles hp ON hp.user_id = ss.helper_id
           WHERE ss.id = ?""",
        (session_id,),
    ).fetchone()
    if session is None:
        return None
    rows = connection.execute(
        """SELECT cm.id, cm.sender_id, cm.content, cm.created_at,
                  me.id AS event_id, me.agent_action, me.risk_score, me.reason, me.guidance, me.needs_human_review,
                  me.context, ir.review_action, ir.override_action, ir.notes AS review_notes
           FROM chat_messages cm
           LEFT JOIN moderation_events me ON me.message_id = cm.id
           LEFT JOIN instructor_reviews ir ON ir.moderation_event_id = me.id
           WHERE cm.session_id = ?
           ORDER BY cm.id""",
        (session_id,),
    ).fetchall()
    messages = [_message(dict(row), session) for row in rows]
    return {**dict(session), "messages": messages}


def _message(row: dict[str, Any], session: sqlite3.Row) -> dict[str, Any]:
    final_action = row["override_action"] or row["agent_action"]
    try:
        audit = json.loads(row["context"] or "{}").get("audit") or {}
    except (TypeError, ValueError):
        audit = {}
    sender = int(row["sender_id"])
    return {
        "id": int(row["id"]),
        "sender_id": sender,
        "sender_role": "learner" if sender == int(session["learner_id"]) else "helper",
        "sender_name": session["learner_name"] if sender == int(session["learner_id"]) else session["helper_name"],
        "content": row["content"],
        "created_at": row["created_at"],
        "moderation_event_id": row["event_id"],
        "agent_action": row["agent_action"],
        "final_action": final_action,
        "delivered": final_action in DELIVERED,
        "risk_score": row["risk_score"],
        "reason": row["reason"],
        "guidance": row["guidance"],
        "intent": audit.get("intent") or None,
        "prefiltered": bool(audit.get("prefiltered")),
        "needs_review": bool(row["needs_human_review"]) and row["review_action"] is None,
        "review_action": row["review_action"],
        "review_notes": row["review_notes"],
    }


def delivered_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Tin thực sự tới được bạn kia (ALLOW/GUIDE, hoặc Admin cho phát lại)."""
    return [message for message in session["messages"] if message["delivered"]]
