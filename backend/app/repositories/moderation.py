import json
import sqlite3
from typing import Any

from ..enums import ModerationAction, ReviewAction
from ..schemas import InstructorReviewRequest, ModerationResult

ModerationEventRecord = dict[str, Any]


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


class ModerationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def instructor_has_session(self, instructor_id: int, session_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM session_instructors WHERE session_id = ? AND instructor_id = ?",
            (session_id, instructor_id),
        ).fetchone() is not None

    def create_moderation_event(
        self,
        *,
        session_id: int,
        message_id: int,
        sender_id: int,
        result: ModerationResult,
        context: dict[str, Any],
        created_at: str,
    ) -> ModerationEventRecord:
        cursor = self.connection.execute(
            """INSERT INTO moderation_events(
                session_id, message_id, sender_id, agent_action, risk_score, reason,
                guidance, needs_human_review, context, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                message_id,
                sender_id,
                result.action.value,
                result.risk_score,
                result.reason,
                result.guidance,
                int(result.needs_human_review),
                _json_dump(context),
                created_at,
            ),
        )
        record = self.get_moderation_event(int(cursor.lastrowid))
        if record is None:
            raise RuntimeError("Created moderation event could not be loaded")
        return record

    def list_moderation_events(self, instructor_id: int | None = None) -> list[ModerationEventRecord]:
        rows = self.connection.execute(
            """SELECT me.id AS moderation_event_id
               FROM moderation_events me
               WHERE (? IS NULL OR EXISTS (
                   SELECT 1 FROM session_instructors si
                   WHERE si.session_id = me.session_id AND si.instructor_id = ?
               ))
               ORDER BY me.id DESC"""
            , (instructor_id, instructor_id)
        ).fetchall()
        return [record for row in rows if (record := self.get_moderation_event(int(row["moderation_event_id"]))) is not None]

    def get_moderation_event(self, moderation_event_id: int) -> ModerationEventRecord | None:
        row = self.connection.execute(
            """SELECT me.id, me.session_id, me.message_id, me.sender_id, me.agent_action,
                      me.risk_score, me.reason, me.guidance, me.needs_human_review,
                      me.context, me.created_at,
                      cm.content AS message_content,
                      ir.id AS review_id, ir.instructor_id, ir.review_action,
                      ir.override_action, ir.notes, ir.created_at AS review_created_at
               FROM moderation_events me
               JOIN chat_messages cm ON cm.id = me.message_id
               LEFT JOIN instructor_reviews ir ON ir.moderation_event_id = me.id
               WHERE me.id = ?""",
            (moderation_event_id,),
        ).fetchone()
        return self._record_from_row(row) if row else None

    def create_instructor_review(
        self,
        *,
        moderation_event_id: int,
        instructor_id: int,
        payload: InstructorReviewRequest,
        created_at: str,
    ) -> ModerationEventRecord:
        self.connection.execute(
            """INSERT INTO instructor_reviews(
                moderation_event_id, instructor_id, review_action, override_action, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                moderation_event_id,
                instructor_id,
                payload.action.value,
                payload.override_action.value if payload.override_action else None,
                payload.notes,
                created_at,
            ),
        )
        record = self.get_moderation_event(moderation_event_id)
        if record is None:
            raise RuntimeError("Reviewed moderation event could not be loaded")
        return record

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ModerationEventRecord:
        review = None
        if row["review_id"] is not None:
            review = {
                "id": int(row["review_id"]),
                "moderation_event_id": int(row["id"]),
                "instructor_id": int(row["instructor_id"]),
                "action": ReviewAction(row["review_action"]),
                "override_action": ModerationAction(row["override_action"]) if row["override_action"] else None,
                "notes": row["notes"],
                "created_at": row["review_created_at"],
            }
        return {
            "id": int(row["id"]),
            "session_id": int(row["session_id"]),
            "message_id": int(row["message_id"]),
            "sender_id": int(row["sender_id"]),
            "agent_action": ModerationAction(row["agent_action"]),
            "risk_score": float(row["risk_score"]),
            "reason": row["reason"],
            "guidance": row["guidance"],
            "needs_human_review": bool(row["needs_human_review"]),
            "context": _json_load(row["context"]),
            "created_at": row["created_at"],
            "instructor_review": review,
            "message_content": row["message_content"],
        }
