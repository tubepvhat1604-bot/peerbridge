import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-study-room-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from app.config import get_settings
from app.db import database, utc_now
from app.enums import ModerationAction
from app.main import app
from app.schemas import ModerationResult
from app.security import create_token
from app.services.moderation_agent import get_moderation_agent
from app.services.study_room import study_room_connections
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class RecordingModerationAgent:
    def __init__(self, action: ModerationAction = ModerationAction.ALLOW, guidance: str | None = None) -> None:
        self.action = action
        self.guidance = guidance
        self.calls: list[dict[str, Any]] = []

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: dict[str, Any],
    ) -> ModerationResult:
        self.calls.append({"session_id": session_id, "message": message, "context": context})
        return ModerationResult(
            action=self.action,
            risk_score=0.25 if self.action != ModerationAction.ALLOW else 0.0,
            reason="recorded moderation",
            guidance=self.guidance,
            needs_human_review=False,
        )


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def create_student(display_name: str) -> int:
    now = utc_now()
    with database() as connection:
        cursor = connection.execute(
            """INSERT INTO users(email, role, password_hash, created_at)
               VALUES (?, 'STUDENT', ?, ?)""",
            (f"{display_name.lower()}-{uuid4().hex}@example.edu", "not-used", now),
        )
        user_id = int(cursor.lastrowid)
        connection.execute(
            """INSERT INTO profiles(user_id, display_name, age, city, intent, interests, available_times, updated_at)
               VALUES (?, ?, 22, 'Ha Noi', 'conversation', '[]', '[]', ?)""",
            (user_id, display_name, now),
        )
    return user_id


def create_study_session(learner_id: int, helper_id: int) -> int:
    now = utc_now()
    user_a_id, user_b_id = sorted((learner_id, helper_id))
    with database() as connection:
        request = connection.execute(
            """INSERT INTO connection_requests(requester_id, recipient_id, status, created_at, responded_at)
               VALUES (?, ?, 'MATCHED', ?, ?)""",
            (learner_id, helper_id, now, now),
        )
        peer_match = connection.execute(
            """INSERT INTO peer_matches(connection_request_id, user_a_id, user_b_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (int(request.lastrowid), user_a_id, user_b_id, now),
        )
        session = connection.execute(
            """INSERT INTO study_sessions(
                peer_match_id, learner_id, helper_id, topic, scheduled_start, scheduled_end, created_at, updated_at
            ) VALUES (?, ?, ?, 'Limits', NULL, NULL, ?, ?)""",
            (int(peer_match.lastrowid), learner_id, helper_id, now, now),
        )
        return int(session.lastrowid)


def test_study_room_websocket_accepts_valid_session_member() -> None:
    with TestClient(app) as client:
        learner_id = create_student("WsLearner")
        helper_id = create_student("WsHelper")
        session_id = create_study_session(learner_id, helper_id)

        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner_id)}") as websocket:
            event = websocket.receive_json()

    assert event == {
            "type": "SESSION_STATUS",
            "session_id": session_id,
            "user_id": learner_id,
        "status": "JOINED",
        "tutor": {"active": False, "topic": "", "turn_count": 0, "max_turns": 6},
        }


def test_study_room_websocket_rejects_unauthorized_session() -> None:
    with TestClient(app) as client:
        learner_id = create_student("PrivateLearner")
        helper_id = create_student("PrivateHelper")
        outsider_id = create_student("Outsider")
        session_id = create_study_session(learner_id, helper_id)

        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(outsider_id)}"):
                pass

    assert error.value.code == 4403


def test_study_room_websocket_persists_chat_message_before_moderation() -> None:
    agent = RecordingModerationAgent()
    app.dependency_overrides[get_moderation_agent] = lambda: agent

    with TestClient(app) as client:
        learner_id = create_student("PersistLearner")
        helper_id = create_student("PersistHelper")
        session_id = create_study_session(learner_id, helper_id)

        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner_id)}") as websocket:
            assert websocket.receive_json()["status"] == "JOINED"
            websocket.send_json({"type": "CHAT_MESSAGE", "content": "  Start with the definition.  "})
            chat_event = websocket.receive_json()
            moderation_event = websocket.receive_json()

    assert chat_event["type"] == "CHAT_MESSAGE"
    assert chat_event["message"]["content"] == "Start with the definition."
    assert moderation_event["type"] == "MODERATION_RESULT"
    with database() as connection:
        row = connection.execute(
            "SELECT id, session_id, sender_id, content FROM chat_messages WHERE id = ?",
            (chat_event["message"]["id"],),
        ).fetchone()
    assert dict(row) == {
        "id": chat_event["message"]["id"],
        "session_id": session_id,
        "sender_id": learner_id,
        "content": "Start with the definition.",
    }
    assert agent.calls[0]["context"]["message_id"] == chat_event["message"]["id"]


def test_study_room_websocket_calls_mock_moderation_agent_and_broadcasts_guidance() -> None:
    agent = RecordingModerationAgent(
        action=ModerationAction.GUIDE,
        guidance="Ask a Socratic follow-up.",
    )
    app.dependency_overrides[get_moderation_agent] = lambda: agent

    with TestClient(app) as client:
        learner_id = create_student("MockLearner")
        helper_id = create_student("MockHelper")
        session_id = create_study_session(learner_id, helper_id)
        with database() as connection:
            expected_peer_match_id = connection.execute(
                "SELECT peer_match_id FROM study_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()["peer_match_id"]

        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(helper_id)}") as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "CHAT_MESSAGE", "content": "Give me the final answer."})
            chat_event = websocket.receive_json()
            moderation_event = websocket.receive_json()
            guidance_event = websocket.receive_json()

    assert agent.calls == [
        {
            "session_id": str(session_id),
            "message": "Give me the final answer.",
            "context": {
                "message_id": chat_event["message"]["id"],
                "sender_id": helper_id,
                "session_id": session_id,
                "peer_match_id": expected_peer_match_id,
                "topic": "Limits",
                "course_id": "__no_authorized_course__",
                "conversation_history": [],
            },
        }
    ]
    assert agent.calls[0]["context"]["peer_match_id"] > 0
    assert moderation_event["type"] == "MODERATION_RESULT"
    assert moderation_event["result"]["action"] == "GUIDE"
    assert guidance_event == {
        "type": "GUIDANCE",
        "session_id": session_id,
        "message_id": chat_event["message"]["id"],
        "moderation_event_id": moderation_event["moderation_event_id"],
        "guidance": "Ask a Socratic follow-up.",
    }


def test_websocket_persists_multiturn_tutor_state_and_keeps_allow_silent() -> None:
    from app.agents.moderator.graph import build_moderator_graph, run_moderator
    from app.agents.moderator.llm import neutral_fake_llm
    from app.agents.moderator.retriever import FakeRetriever
    from app.agents.moderator.settings import ModeratorSettings
    from app.services.moderation_agent import LangGraphModerationAgent

    graph = build_moderator_graph(neutral_fake_llm(), FakeRetriever(), ModeratorSettings(_env_file=None))
    app.dependency_overrides[get_moderation_agent] = lambda: LangGraphModerationAgent(
        moderate=lambda payload: run_moderator(graph, payload))
    with TestClient(app) as client:
        learner, helper = create_student("TutorLearner"), create_student("TutorHelper")
        session = create_study_session(learner, helper)
        with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(learner)}") as ws:
            assert ws.receive_json()["tutor"]["active"] is False
            ws.send_json({"type": "CHAT_MESSAGE", "content": "Cho mình đáp án bài SQL JOIN này với."})
            assert ws.receive_json()["type"] == "CHAT_MESSAGE"
            first = ws.receive_json()
            assert first["result"]["action"] == "GUIDE"
            assert first["tutor"]["active"] is True
            assert first["tutor"]["turn_count"] == 1
            assert ws.receive_json()["type"] == "GUIDANCE"

            ws.send_json({"type": "CHAT_MESSAGE", "content": "Tôi đang không biết câu lệnh."})
            assert ws.receive_json()["type"] == "CHAT_MESSAGE"
            second = ws.receive_json()
            assert second["result"]["action"] == "GUIDE"
            assert second["tutor"]["turn_count"] == 2
            assert ws.receive_json()["type"] == "GUIDANCE"

            ws.send_json({"type": "CHAT_MESSAGE", "content": "Dừng trợ giảng"})
            assert ws.receive_json()["type"] == "CHAT_MESSAGE"
            stopped = ws.receive_json()
            assert stopped["result"]["action"] == "ALLOW"
            assert stopped["tutor"]["active"] is False

        with database() as connection:
            assert connection.execute("SELECT COUNT(*) FROM moderation_events WHERE session_id = ?", (session,)).fetchone()[0] == 3
            assert connection.execute("SELECT turn_count, active FROM socratic_sessions WHERE session_id = ? AND sender_id = ?",
                                      (session, learner)).fetchone()[:] == (2, 0)


def test_tutor_state_closes_at_configured_max_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.study_room as room_module
    from app.agents.moderator.settings import ModeratorSettings
    from app.services.study_room import StudyRoomService, StudyRoomSession, StudyRoomUser

    monkeypatch.setattr(room_module, "get_moderator_settings",
                        lambda: ModeratorSettings(_env_file=None, max_socratic_turns=2))
    with TestClient(app):
        learner, helper = create_student("MaxLearner"), create_student("MaxHelper")
        session_id = create_study_session(learner, helper)
        session = StudyRoomSession(id=session_id, peer_match_id=1, learner_id=learner, helper_id=helper, topic="SQL")
        user = StudyRoomUser(id=learner, email="learner@example.edu", role="STUDENT")
        result = ModerationResult(action=ModerationAction.GUIDE, risk_score=0.1,
                                  reason="guide", guidance="Bạn sẽ bắt đầu từ đâu?")
        first = StudyRoomService._update_tutor_state(session, user, {"content": "Xin đáp án"}, result)
        second = StudyRoomService._update_tutor_state(session, user, {"content": "Tôi chưa biết"}, result)

    assert first == {"active": True, "topic": "SQL", "turn_count": 1, "max_turns": 2}
    assert second == {"active": False, "topic": "", "turn_count": 0, "max_turns": 2}
    with database() as connection:
        assert connection.execute("SELECT turn_count, active FROM socratic_sessions WHERE session_id = ? AND sender_id = ?",
                                  (session_id, learner)).fetchone()[:] == (2, 0)


def test_study_room_websocket_returns_structured_error_for_invalid_payload() -> None:
    with TestClient(app) as client:
        learner_id = create_student("InvalidPayloadLearner")
        helper_id = create_student("InvalidPayloadHelper")
        session_id = create_study_session(learner_id, helper_id)

        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner_id)}") as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "CHAT_MESSAGE", "content": "   "})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "ERROR",
        "code": "INVALID_PAYLOAD",
        "message": "Study room messages must be CHAT_MESSAGE events with non-empty content.",
    }


def test_study_room_websocket_disconnect_cleans_manager_and_broadcasts_left_status() -> None:
    with TestClient(app) as client:
        learner_id = create_student("DisconnectLearner")
        helper_id = create_student("DisconnectHelper")
        session_id = create_study_session(learner_id, helper_id)

        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner_id)}") as learner_ws:
            assert learner_ws.receive_json()["status"] == "JOINED"
            with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(helper_id)}") as helper_ws:
                helper_joined = helper_ws.receive_json()
                learner_saw_helper = learner_ws.receive_json()
                assert helper_joined["status"] == "JOINED"
                assert learner_saw_helper["user_id"] == helper_id
                assert study_room_connections.active_count(session_id) == 2

            left_event = learner_ws.receive_json()
            assert left_event == {
                "type": "SESSION_STATUS",
                "session_id": session_id,
                "user_id": helper_id,
                "status": "LEFT",
            }
            assert study_room_connections.active_count(session_id) == 1

        assert study_room_connections.active_count(session_id) == 0


@pytest.mark.parametrize("action", [ModerationAction.WARN, ModerationAction.BLOCK, ModerationAction.ESCALATE])
def test_held_message_never_reaches_peer_or_rest_history(action) -> None:
    agent = RecordingModerationAgent(action=action)
    app.dependency_overrides[get_moderation_agent] = lambda: agent
    with TestClient(app) as client:
        learner, helper = create_student("GateLearner"), create_student("GateHelper")
        session = create_study_session(learner, helper)
        with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(learner)}") as sender:
            sender.receive_json()
            with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(helper)}") as peer:
                peer.receive_json()
                sender.receive_json()
                sender.send_json({"type": "CHAT_MESSAGE", "content": "private held content"})
                assert sender.receive_json()["result"]["action"] == action.value
                assert sender.receive_json()["type"] == "WARNING"
                headers = {"Authorization": f"Bearer {create_token(helper)}"}
                assert client.get(f"/api/v1/sessions/{session}", headers=headers).json()["chat_messages"] == []
                # A safe sentinel makes queue ordering observable without a blocking negative receive.
                agent.action = ModerationAction.ALLOW
                sender.send_json({"type": "CHAT_MESSAGE", "content": "safe sentinel"})
                assert peer.receive_json()["message"]["content"] == "safe sentinel"
                assert peer.receive_json()["result"]["action"] == "ALLOW"
                sender.receive_json()
                sender.receive_json()


def test_moderator_exception_is_persisted_as_pending_review() -> None:
    class BrokenAgent:
        async def moderate(self, **kwargs):
            raise RuntimeError("secret implementation details")
    app.dependency_overrides[get_moderation_agent] = lambda: BrokenAgent()
    with TestClient(app) as client:
        learner, helper = create_student("FailureLearner"), create_student("FailureHelper")
        session = create_study_session(learner, helper)
        with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(learner)}") as ws:
            ws.receive_json()
            ws.send_json({"type": "CHAT_MESSAGE", "content": "held after failure"})
            result = ws.receive_json()
            assert result["result"]["action"] == "ESCALATE"
            assert result["result"]["needs_human_review"]
            assert "secret" not in str(result)
            assert ws.receive_json()["type"] == "WARNING"
        with database() as connection:
            assert connection.execute("SELECT needs_human_review FROM moderation_events WHERE message_id = ?",
                (result["message_id"],)).fetchone()[0] == 1


def test_pending_block_does_not_leak_while_other_member_can_chat() -> None:
    import asyncio
    import threading

    entered, release = threading.Event(), threading.Event()

    class DelayedBlockAgent(RecordingModerationAgent):
        async def moderate(self, session_id, message, context):
            if message == "pending private content":
                entered.set()
                if not await asyncio.to_thread(release.wait, 5):
                    raise TimeoutError("Test did not release moderation")
                return ModerationResult(action=ModerationAction.BLOCK, risk_score=0.9, reason="blocked")
            return await super().moderate(session_id, message, context)

    app.dependency_overrides[get_moderation_agent] = lambda: DelayedBlockAgent()
    with TestClient(app) as client:
        learner, helper = create_student("PendingLearner"), create_student("PendingHelper")
        session = create_study_session(learner, helper)
        with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(learner)}") as sender:
            sender.receive_json()
            with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(helper)}") as peer:
                peer.receive_json()
                sender.receive_json()
                try:
                    sender.send_json({"type": "CHAT_MESSAGE", "content": "pending private content"})
                    assert entered.wait(3), "Moderator must be actively waiting"
                    headers = {"Authorization": f"Bearer {create_token(helper)}"}
                    assert client.get(f"/api/v1/sessions/{session}", headers=headers).json()["chat_messages"] == []
                    peer.send_json({"type": "CHAT_MESSAGE", "content": "safe during moderation"})
                    assert peer.receive_json()["message"]["content"] == "safe during moderation"
                    assert peer.receive_json()["result"]["action"] == "ALLOW"
                    assert sender.receive_json()["message"]["content"] == "safe during moderation"
                    sender.receive_json()
                finally:
                    release.set()
                assert sender.receive_json()["result"]["action"] == "BLOCK"
                assert sender.receive_json()["type"] == "WARNING"
                sender.send_json({"type": "CHAT_MESSAGE", "content": "safe after block"})
                assert peer.receive_json()["message"]["content"] == "safe after block"
                assert peer.receive_json()["result"]["action"] == "ALLOW"
                sender.receive_json()
                sender.receive_json()
                history = client.get(f"/api/v1/sessions/{session}", headers=headers).json()["chat_messages"]
                assert [item["content"] for item in history] == ["safe during moderation", "safe after block"]


def test_raw_contact_is_not_retained_but_moderator_sees_original() -> None:
    agent = RecordingModerationAgent(action=ModerationAction.BLOCK)
    app.dependency_overrides[get_moderation_agent] = lambda: agent
    with TestClient(app) as client:
        learner, helper = create_student("PrivacyLearner"), create_student("PrivacyHelper")
        session = create_study_session(learner, helper)
        with client.websocket_connect(f"/ws/sessions/{session}?token={create_token(learner)}") as ws:
            ws.receive_json()
            ws.send_json({"type": "CHAT_MESSAGE", "content": "Contact private@example.com"})
            result = ws.receive_json()
            ws.receive_json()
        with database() as connection:
            stored = connection.execute("SELECT content FROM chat_messages WHERE id = ?", (result["message_id"],)).fetchone()[0]
        assert stored == "Contact [REDACTED]"
        assert agent.calls[0]["message"] == "Contact private@example.com"


def test_database_quota_applies_across_service_instances(monkeypatch) -> None:
    import app.services.study_room as module
    from app.agents.moderator.settings import ModeratorSettings
    from app.services.study_room import StudyRoomRateLimitError, StudyRoomService
    monkeypatch.setattr(module, "get_moderator_settings", lambda: ModeratorSettings(_env_file=None, moderation_messages_per_minute=1))
    with TestClient(app):
        user_id = create_student("QuotaUser")
        StudyRoomService._reserve_moderation(user_id)
        with pytest.raises(StudyRoomRateLimitError):
            StudyRoomService._reserve_moderation(user_id)
