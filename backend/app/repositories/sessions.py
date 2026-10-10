import sqlite3
from datetime import datetime
from typing import Any

from ..schemas import StudySessionCreateRequest

PeerMatchRecord = dict[str, Any]
StudySessionRecord = dict[str, Any]
StudyRoomSessionRecord = dict[str, Any]
ChatMessageRecord = dict[str, Any]


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class StudySessionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_peer_match(self, peer_match_id: int) -> PeerMatchRecord | None:
        row = self.connection.execute(
            "SELECT id, user_a_id, user_b_id FROM peer_matches WHERE id = ?",
            (peer_match_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_study_sessions(self, user_id: int | None) -> list[StudySessionRecord]:
        query = """SELECT ss.id, ss.peer_match_id, ss.learner_id, ss.helper_id, ss.topic,
                          ss.scheduled_start, ss.scheduled_end, ss.created_at, ss.updated_at
                   FROM study_sessions ss
                   JOIN peer_matches pm ON pm.id = ss.peer_match_id"""
        parameters: tuple[int, ...] = ()
        if user_id is not None:
            query += " WHERE pm.user_a_id = ? OR pm.user_b_id = ?"
            parameters = (user_id, user_id)
        query += " ORDER BY ss.id DESC"
        return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]

    def create_study_session(
        self,
        payload: StudySessionCreateRequest,
        created_at: str,
    ) -> StudySessionRecord:
        cursor = self.connection.execute(
            """INSERT INTO study_sessions(
                peer_match_id, learner_id, helper_id, topic, scheduled_start, scheduled_end, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.peer_match_id,
                payload.learner_id,
                payload.helper_id,
                payload.topic,
                _datetime_value(payload.scheduled_start),
                _datetime_value(payload.scheduled_end),
                created_at,
                created_at,
            ),
        )
        record = self.get_study_session(int(cursor.lastrowid))
        if record is None:
            raise RuntimeError("Created study session could not be loaded")
        return record

    def get_study_session(self, session_id: int) -> StudySessionRecord | None:
        row = self.connection.execute(
            """SELECT ss.id, ss.peer_match_id, ss.learner_id, ss.helper_id, ss.topic,
                      ss.scheduled_start, ss.scheduled_end, ss.created_at, ss.updated_at,
                      pm.user_a_id, pm.user_b_id
               FROM study_sessions ss
               JOIN peer_matches pm ON pm.id = ss.peer_match_id
               WHERE ss.id = ?""",
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        messages = self.connection.execute(
            """SELECT id, session_id, sender_id, content, created_at
               FROM chat_messages cm
               WHERE session_id = ? AND EXISTS (
                   SELECT 1 FROM moderation_events me
                   LEFT JOIN instructor_reviews ir ON ir.moderation_event_id = me.id
                   WHERE me.message_id = cm.id AND
                       CASE WHEN ir.review_action = 'OVERRIDE' THEN ir.override_action
                            ELSE me.agent_action END IN ('ALLOW', 'GUIDE')
               )
               ORDER BY id""",
            (session_id,),
        ).fetchall()
        record = dict(row)
        record["chat_messages"] = [dict(message) for message in messages]
        record["icebreaker_eligible"] = not bool(self.connection.execute(
            "SELECT 1 FROM chat_messages cm JOIN study_sessions ss ON ss.id=cm.session_id WHERE ss.peer_match_id=? LIMIT 1", (record["peer_match_id"],)
        ).fetchone())
        return record

    def get_study_room_session(self, session_id: int) -> StudyRoomSessionRecord | None:
        row = self.connection.execute(
            """SELECT ss.id, ss.peer_match_id, ss.learner_id, ss.helper_id, ss.topic,
                      pm.user_a_id, pm.user_b_id
               FROM study_sessions ss
               JOIN peer_matches pm ON pm.id = ss.peer_match_id
               WHERE ss.id = ?""",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def instructor_has_session(self, instructor_id: int, session_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM session_instructors WHERE session_id = ? AND instructor_id = ?",
            (session_id, instructor_id),
        ).fetchone() is not None

    def create_chat_message(
        self,
        *,
        session_id: int,
        sender_id: int,
        content: str,
        created_at: str,
    ) -> ChatMessageRecord:
        cursor = self.connection.execute(
            """INSERT INTO chat_messages(session_id, sender_id, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, sender_id, content, created_at),
        )
        row = self.connection.execute(
            """SELECT id, session_id, sender_id, content, created_at
               FROM chat_messages
               WHERE id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Created chat message could not be loaded")
        return dict(row)
