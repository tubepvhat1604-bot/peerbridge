from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, WebSocket
from pydantic import ValidationError

from ..agents.moderator.settings import get_moderator_settings
from ..agents.moderator.socratic import exit_requested
from ..db import database, utc_now
from ..enums import ModerationAction
from ..repositories.moderation import ModerationRepository
from ..repositories.sessions import ChatMessageRecord, StudyRoomSessionRecord, StudySessionRepository
from ..schemas import ModerationResult, StudyRoomClientMessage
from ..security import decode_token
from .content_safety import EMAIL_PATTERN, PHONE_PATTERN
from .moderation_agent import ModerationAgentProtocol

CHAT_MESSAGE = "CHAT_MESSAGE"
MODERATION_RESULT = "MODERATION_RESULT"
GUIDANCE = "GUIDANCE"
WARNING = "WARNING"
SESSION_STATUS = "SESSION_STATUS"
ADMIN_NOTE = "ADMIN_NOTE"
ERROR = "ERROR"
# Hành động kiểm duyệt cần báo ngay cho Admin qua chuông thông báo.
ADMIN_ALERT_ACTIONS = {ModerationAction.BLOCK, ModerationAction.ESCALATE}


class StudyRoomAuthError(Exception):
    """Raised when a WebSocket user cannot be authenticated."""


class StudyRoomForbiddenError(Exception):
    """Raised when a WebSocket user cannot access the study session."""


class StudyRoomValidationError(Exception):
    """Raised when a study-room client event is malformed."""


class StudyRoomRateLimitError(Exception):
    """Database-backed per-user quota is exhausted."""


@dataclass(frozen=True)
class StudyRoomUser:
    id: int
    email: str
    role: str


@dataclass(frozen=True)
class StudyRoomSession:
    id: int
    peer_match_id: int
    learner_id: int
    helper_id: int
    topic: str


class StudyRoomConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)

    def disconnect(self, session_id: int, websocket: WebSocket) -> None:
        self._connections[session_id].discard(websocket)
        if not self._connections[session_id]:
            self._connections.pop(session_id, None)

    def active_count(self, session_id: int) -> int:
        return len(self._connections.get(session_id, ()))

    async def broadcast(self, session_id: int, event: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections.get(session_id, ())):
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(session_id, websocket)


class StudyRoomService:
    def __init__(self, moderation_agent: ModerationAgentProtocol) -> None:
        self.moderation_agent = moderation_agent

    def identify_user(self, token: str) -> StudyRoomUser:
        if not token:
            raise StudyRoomAuthError("Missing token")
        try:
            user_id = decode_token(token)
        except HTTPException as error:
            raise StudyRoomAuthError("Invalid token") from error

        with database() as connection:
            row = connection.execute(
                "SELECT id, email, role, is_seed FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None or row["is_seed"]:
            raise StudyRoomAuthError("User not found")
        return StudyRoomUser(id=int(row["id"]), email=str(row["email"]), role=str(row["role"]))

    def require_session_member(self, session_id: int, user_id: int) -> StudyRoomSession:
        with database() as connection:
            record = StudySessionRepository(connection).get_study_room_session(session_id)
        if record is None or user_id not in self._session_member_ids(record):
            raise StudyRoomForbiddenError("Study session access denied")
        return StudyRoomSession(
            id=int(record["id"]),
            peer_match_id=int(record["peer_match_id"]),
            learner_id=int(record["learner_id"]),
            helper_id=int(record["helper_id"]),
            topic=str(record["topic"]),
        )

    async def handle_client_event(
        self,
        session: StudyRoomSession,
        user: StudyRoomUser,
        payload: Any,
    ) -> list[dict[str, Any]]:
        self.require_session_member(session.id, user.id)
        client_message = self._validate_client_message(payload)
        self._reserve_moderation(user.id)
        message = self._persist_chat_message(session.id, user.id, client_message.content)
        moderation = await self._moderate_message(session, user, message)
        moderation_event = self._persist_moderation_event(session, user, message, moderation)
        if moderation.action in ADMIN_ALERT_ACTIONS:
            self._alert_admins(session, moderation)
        tutor = self._update_tutor_state(session, user, message, moderation)
        return [
            *([self.chat_message_event(session.id, message)] if moderation.action in {ModerationAction.ALLOW, ModerationAction.GUIDE} else []),
            *self.moderation_events(session.id, message, moderation, moderation_event_id=int(moderation_event["id"]), tutor=tutor),
        ]

    @staticmethod
    def _reserve_moderation(sender_id: int) -> None:
        window = datetime.fromisoformat(utc_now()).replace(second=0, microsecond=0).isoformat()
        limit = get_moderator_settings().moderation_messages_per_minute
        with database() as connection:
            cursor = connection.execute(
                """INSERT INTO moderation_quota VALUES (?, ?, 1)
                   ON CONFLICT(sender_id, window_start) DO UPDATE SET request_count = request_count + 1
                   WHERE request_count < ?""", (sender_id, window, limit))
            if cursor.rowcount != 1:
                raise StudyRoomRateLimitError("Moderation quota exhausted")

    @staticmethod
    def session_status_event(session_id: int, user_id: int, status: str, tutor: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "type": SESSION_STATUS,
            "session_id": session_id,
            "user_id": user_id,
            "status": status,
        }
        if tutor is not None:
            event["tutor"] = tutor
        return event

    @staticmethod
    def tutor_status(session_id: int, sender_id: int) -> dict[str, Any]:
        with database() as connection:
            row = connection.execute("SELECT active, topic, turn_count FROM socratic_sessions WHERE session_id = ? AND sender_id = ?",
                                     (session_id, sender_id)).fetchone()
        return {"active": bool(row["active"]) if row else False,
                "topic": str(row["topic"]) if row and row["active"] else "",
                "turn_count": int(row["turn_count"]) if row and row["active"] else 0,
                "max_turns": get_moderator_settings().max_socratic_turns}

    @staticmethod
    def admin_note_event(session_id: int, note: str, message_id: int | None = None) -> dict[str, Any]:
        return {"type": ADMIN_NOTE, "session_id": session_id, "message_id": message_id,
                "note": note[:1000], "created_at": utc_now()}

    @staticmethod
    def _alert_admins(session: StudyRoomSession, result: ModerationResult) -> None:
        """Cảnh báo realtime lệch liêm chính: ghi thông báo cho mọi Admin (chuông trong app)."""
        from ..admin_roles import admin_user_ids
        from ..home import notifications

        label = "đang chờ Admin xem xét" if result.action == ModerationAction.ESCALATE else "đã bị chặn"
        with database() as connection:
            for admin_id in admin_user_ids(connection):
                notifications.add(admin_id, "system", f"Phiên #{session.id}: tin nhắn {label}",
                                  f"{session.topic} · {result.reason}", page="moderation", connection=connection)

    @staticmethod
    def error_event(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
        event: dict[str, Any] = {"type": ERROR, "code": code, "message": message}
        if details is not None:
            event["details"] = details
        return event

    @staticmethod
    def chat_message_event(session_id: int, message: ChatMessageRecord) -> dict[str, Any]:
        return {
            "type": CHAT_MESSAGE,
            "session_id": session_id,
            "message": message,
        }

    @staticmethod
    def moderation_events(
        session_id: int,
        message: ChatMessageRecord,
        result: ModerationResult,
        *,
        moderation_event_id: int,
        tutor: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        message_id = int(message["id"])
        result_payload = result.model_dump(mode="json")
        events: list[dict[str, Any]] = [
            {
                "type": MODERATION_RESULT,
                "session_id": session_id,
                "message_id": message_id,
                "moderation_event_id": moderation_event_id,
                "result": result_payload,
                **({"tutor": tutor, "sender_id": int(message["sender_id"])} if tutor is not None else {}),
            }
        ]
        if result.action == ModerationAction.GUIDE and result.guidance:
            events.append(
                {
                    "type": GUIDANCE,
                    "session_id": session_id,
                    "message_id": message_id,
                    "moderation_event_id": moderation_event_id,
                    "guidance": result.guidance,
                }
            )
        if result.action in {ModerationAction.WARN, ModerationAction.BLOCK, ModerationAction.ESCALATE}:
            events.append(
                {
                    "type": WARNING,
                    "session_id": session_id,
                    "message_id": message_id,
                    "moderation_event_id": moderation_event_id,
                    "action": result.action.value,
                    "warning": ("Tin nhắn bị chặn vì nội dung không phù hợp với phòng học."
                                if result.action == ModerationAction.BLOCK else
                                "Tin nhắn đang chờ Admin xem xét."
                                if result.action == ModerationAction.ESCALATE else
                                result.guidance or "Vui lòng giữ nội dung phù hợp với buổi học."),
                }
            )
        return events

    @staticmethod
    def _session_member_ids(record: StudyRoomSessionRecord) -> set[int]:
        return {int(record["learner_id"]), int(record["helper_id"])}

    @staticmethod
    def _validate_client_message(payload: Any) -> StudyRoomClientMessage:
        try:
            return StudyRoomClientMessage.model_validate(payload)
        except ValidationError as error:
            raise StudyRoomValidationError("Invalid study-room event") from error

    @staticmethod
    def _persist_chat_message(session_id: int, sender_id: int, content: str) -> ChatMessageRecord:
        stored = PHONE_PATTERN.sub("[REDACTED]", EMAIL_PATTERN.sub("[REDACTED]", content))
        with database() as connection:
            record = StudySessionRepository(connection).create_chat_message(
                session_id=session_id,
                sender_id=sender_id,
                content=stored,
                created_at=utc_now(),
            )
        # Original content exists only in this invocation so hard PII rules still see it.
        return {**record, "content": content}

    async def _moderate_message(
        self,
        session: StudyRoomSession,
        user: StudyRoomUser,
        message: ChatMessageRecord,
    ) -> ModerationResult:
        context = self._moderation_context(session, user, message)
        with database() as connection:
            history = StudySessionRepository(connection).get_study_session(session.id)["chat_messages"]
            tutoring = connection.execute(
                "SELECT * FROM socratic_sessions WHERE session_id = ? AND sender_id = ? AND active = 1",
                (session.id, user.id),
            ).fetchone()
        context["conversation_history"] = [item for item in history if item["id"] < message["id"]][-6:]
        if tutoring:
            context["socratic_session"] = {
                "active": True, "session_id": str(session.id), "sender_id": str(user.id),
                "original_question": tutoring["original_question"], "topic": tutoring["topic"],
                "turn_count": tutoring["turn_count"], "last_guidance": tutoring["last_guidance"],
            }
        try:
            result = await asyncio.wait_for(self.moderation_agent.moderate(
                session_id=str(session.id),
                message=str(message["content"]),
                context=context,
            ), timeout=get_moderator_settings().moderation_timeout_seconds)
            if result.action == ModerationAction.ESCALATE:
                result = result.model_copy(update={"needs_human_review": True})
            return result
        except Exception:
            return ModerationResult(action=ModerationAction.ESCALATE, risk_score=1.0,
                reason="Không thể kiểm duyệt; tin đang chờ Admin xem xét.", needs_human_review=True)

    @staticmethod
    def _update_tutor_state(session: StudyRoomSession, user: StudyRoomUser,
                            message: ChatMessageRecord, result: ModerationResult) -> dict[str, Any]:
        now = utc_now()
        with database() as connection:
            row = connection.execute("SELECT active, turn_count FROM socratic_sessions WHERE session_id = ? AND sender_id = ?",
                                     (session.id, user.id)).fetchone()
            if row and row["active"]:
                if result.action == ModerationAction.GUIDE:
                    connection.execute("""UPDATE socratic_sessions SET turn_count = turn_count + 1,
                                       active = CASE WHEN turn_count + 1 >= ? THEN 0 ELSE 1 END,
                                       last_guidance = ?, updated_at = ?
                                       WHERE session_id = ? AND sender_id = ? AND active = 1""",
                                       (get_moderator_settings().max_socratic_turns, result.guidance,
                                        now, session.id, user.id))
                elif result.action == ModerationAction.ALLOW and exit_requested(str(message["content"])):
                    connection.execute("UPDATE socratic_sessions SET active = 0, updated_at = ? WHERE session_id = ? AND sender_id = ?",
                                       (now, session.id, user.id))
            elif result.action == ModerationAction.GUIDE:
                connection.execute("""INSERT INTO socratic_sessions(session_id, sender_id, active, original_question, topic,
                                   turn_count, last_guidance, started_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                                   ON CONFLICT(session_id, sender_id) DO UPDATE SET active = excluded.active, original_question = excluded.original_question,
                                   topic = excluded.topic, turn_count = 1, last_guidance = excluded.last_guidance,
                                   started_at = excluded.started_at, updated_at = excluded.updated_at""",
                                   (session.id, user.id, int(get_moderator_settings().max_socratic_turns > 1),
                                    str(message["content"]), session.topic, result.guidance, now, now))
        return StudyRoomService.tutor_status(session.id, user.id)

    @staticmethod
    def _moderation_context(
        session: StudyRoomSession,
        user: StudyRoomUser,
        message: ChatMessageRecord,
    ) -> dict[str, Any]:
        with database() as connection:
            course = connection.execute(
                """SELECT sc.course_id FROM session_courses sc
                   WHERE sc.session_id = ? AND EXISTS (
                     SELECT 1 FROM course_memberships cm WHERE cm.course_id = sc.course_id AND cm.user_id = ?
                   ) AND EXISTS (
                     SELECT 1 FROM course_memberships cm WHERE cm.course_id = sc.course_id AND cm.user_id = ?
                   )""", (session.id, session.learner_id, session.helper_id),
            ).fetchone()
        return {
            "message_id": int(message["id"]),
            "sender_id": user.id,
            "session_id": session.id,
            "peer_match_id": session.peer_match_id,
            "topic": session.topic,
            "course_id": course["course_id"] if course else "__no_authorized_course__",
        }

    def _persist_moderation_event(
        self,
        session: StudyRoomSession,
        user: StudyRoomUser,
        message: ChatMessageRecord,
        result: ModerationResult,
    ) -> dict[str, Any]:
        with database() as connection:
            return ModerationRepository(connection).create_moderation_event(
                session_id=session.id,
                message_id=int(message["id"]),
                sender_id=user.id,
                result=result,
                context={**self._moderation_context(session, user, message),
                         "retrieved_sources": result.retrieved_sources, "audit": result.audit},
                created_at=utc_now(),
            )


study_room_connections = StudyRoomConnectionManager()
