import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-hitl-{uuid4().hex}.db"))
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
from fastapi.testclient import TestClient


class EscalatingModerationAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: dict[str, Any],
    ) -> ModerationResult:
        self.calls.append({"session_id": session_id, "message": message, "context": context})
        return ModerationResult(
            action=ModerationAction.ESCALATE,
            risk_score=0.88,
            reason="Needs instructor review",
            guidance="Instructor should review this exchange.",
            needs_human_review=True,
        )


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id)}"}


def create_user(display_name: str, role: str = "STUDENT") -> int:
    now = utc_now()
    with database() as connection:
        cursor = connection.execute(
            """INSERT INTO users(email, role, password_hash, created_at)
               VALUES (?, ?, ?, ?)""",
            (f"{display_name.lower()}-{uuid4().hex}@example.edu", role, "not-used", now),
        )
        user_id = int(cursor.lastrowid)
        if role == "STUDENT":
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
            ) VALUES (?, ?, ?, 'Derivatives', NULL, NULL, ?, ?)""",
            (int(peer_match.lastrowid), learner_id, helper_id, now, now),
        )
    return int(session.lastrowid)


def create_escalated_event(client: TestClient, learner_id: int, helper_id: int) -> dict[str, Any]:
    session_id = create_study_session(learner_id, helper_id)
    with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner_id)}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "CHAT_MESSAGE", "content": "I need a human to resolve this."})
        moderation_event = websocket.receive_json()
        warning_event = websocket.receive_json()

    assert moderation_event["type"] == "MODERATION_RESULT"
    assert warning_event["type"] == "WARNING"
    return {
        "session_id": session_id,
        "message_id": moderation_event["message_id"],
        "moderation_event_id": moderation_event["moderation_event_id"],
    }


def test_instructor_moderation_requires_instructor_role() -> None:
    agent = EscalatingModerationAgent()
    app.dependency_overrides[get_moderation_agent] = lambda: agent

    with TestClient(app) as client:
        learner_id = create_user("AuthLearner")
        helper_id = create_user("AuthHelper")
        event = create_escalated_event(client, learner_id, helper_id)

        with database() as connection:
            instructors = connection.execute("SELECT id FROM users WHERE role = 'INSTRUCTOR'").fetchall()
            connection.executemany("INSERT INTO session_instructors(session_id, instructor_id) VALUES (?, ?)",
                [(event["session_id"], row["id"]) for row in instructors])

        student_list = client.get("/instructor/moderation", headers=auth_headers(learner_id))
        student_review = client.post(
            f"/instructor/moderation/{event['moderation_event_id']}/review",
            headers=auth_headers(helper_id),
            json={"action": "APPROVE"},
        )
        missing_token = client.get("/instructor/moderation")

    assert student_list.status_code == 403
    assert student_review.status_code == 403
    assert missing_token.status_code == 401


def test_instructor_can_list_escalated_event_and_create_review_audit_record() -> None:
    agent = EscalatingModerationAgent()
    app.dependency_overrides[get_moderation_agent] = lambda: agent

    with TestClient(app) as client:
        learner_id = create_user("ReviewLearner")
        helper_id = create_user("ReviewHelper")
        instructor_id = create_user("ReviewInstructor", role="INSTRUCTOR")
        event = create_escalated_event(client, learner_id, helper_id)
        with database() as connection:
            connection.execute("INSERT INTO session_instructors VALUES (?, ?)", (event["session_id"], instructor_id))

        listed = client.get("/instructor/moderation", headers=auth_headers(instructor_id))
        assert listed.status_code == 200
        items = listed.json()["items"]
        escalated = next(item for item in items if item["id"] == event["moderation_event_id"])
        assert escalated["agent_action"] == "ESCALATE"
        assert escalated["needs_human_review"] is True
        assert escalated["instructor_review"] is None
        assert escalated["context"] == {
            "message_id": event["message_id"],
            "peer_match_id": escalated["context"]["peer_match_id"],
            "sender_id": learner_id,
            "session_id": event["session_id"],
            "topic": "Derivatives",
            "course_id": "__no_authorized_course__",
            "retrieved_sources": [],
            "audit": {},
        }
        assert escalated["context"]["peer_match_id"] > 0

        reviewed = client.post(
            f"/instructor/moderation/{event['moderation_event_id']}/review",
            headers=auth_headers(instructor_id),
            json={"action": "INTERVENE", "notes": "Joining this study room now."},
        )
        duplicate_review = client.post(
            f"/instructor/moderation/{event['moderation_event_id']}/review",
            headers=auth_headers(instructor_id),
            json={"action": "APPROVE"},
        )

    assert reviewed.status_code == 201
    reviewed_body = reviewed.json()
    assert reviewed_body["agent_action"] == "ESCALATE"
    assert reviewed_body["instructor_review"]["action"] == "INTERVENE"
    assert reviewed_body["instructor_review"]["instructor_id"] == instructor_id
    assert reviewed_body["instructor_review"]["notes"] == "Joining this study room now."
    assert duplicate_review.status_code == 409
    with database() as connection:
        moderation_count = connection.execute(
            "SELECT COUNT(*) FROM moderation_events WHERE id = ?",
            (event["moderation_event_id"],),
        ).fetchone()[0]
        review_count = connection.execute(
            "SELECT COUNT(*) FROM instructor_reviews WHERE moderation_event_id = ?",
            (event["moderation_event_id"],),
        ).fetchone()[0]
    assert moderation_count == 1
    assert review_count == 1


def test_any_admin_can_review_and_retry_does_not_duplicate() -> None:
    app.dependency_overrides[get_moderation_agent] = lambda: EscalatingModerationAgent()
    with TestClient(app) as client:
        learner, helper = create_user("ReleaseLearner"), create_user("ReleaseHelper")
        assigned = create_user("AnyAdmin", "INSTRUCTOR")  # Admin không cần được phân công phiên
        event = create_escalated_event(client, learner, helper)
        url = f"/instructor/moderation/{event['moderation_event_id']}/review"
        listed = client.get("/instructor/moderation", headers=auth_headers(assigned)).json()["items"]
        assert event["moderation_event_id"] in [item["id"] for item in listed]
        assert client.post(url, headers=auth_headers(learner), json={"action": "APPROVE"}).status_code == 403
        with client.websocket_connect(f"/ws/sessions/{event['session_id']}?token={create_token(helper)}") as peer:
            peer.receive_json()
            assert client.post(url, headers=auth_headers(assigned), json={"action": "APPROVE"}).status_code == 201
            # APPROVE agrees with ESCALATE and cannot release the original.
            history = client.get(f"/api/v1/sessions/{event['session_id']}", headers=auth_headers(helper)).json()
            assert history["chat_messages"] == []
            assert client.post(url, headers=auth_headers(assigned), json={"action": "OVERRIDE", "override_action": "ALLOW"}).status_code == 409


def test_explicit_override_releases_once_to_ws_and_reconnect_history() -> None:
    app.dependency_overrides[get_moderation_agent] = lambda: EscalatingModerationAgent()
    with TestClient(app) as client:
        learner, helper = create_user("OverrideLearner"), create_user("OverrideHelper")
        instructor = create_user("OverrideTeacher", "INSTRUCTOR")
        event = create_escalated_event(client, learner, helper)
        with database() as connection:
            connection.execute("INSERT INTO session_instructors VALUES (?, ?)", (event["session_id"], instructor))
        with client.websocket_connect(f"/ws/sessions/{event['session_id']}?token={create_token(helper)}") as peer:
            peer.receive_json()
            url = f"/instructor/moderation/{event['moderation_event_id']}/review"
            payload = {"action": "OVERRIDE", "override_action": "ALLOW", "notes": "Reviewed and safe"}
            assert client.post(url, headers=auth_headers(instructor), json=payload).status_code == 201
            released = peer.receive_json()
            assert released["type"] == "CHAT_MESSAGE"
            assert released["message"]["id"] == event["message_id"]
            assert client.post(url, headers=auth_headers(instructor), json=payload).status_code == 409
        history = client.get(f"/api/v1/sessions/{event['session_id']}", headers=auth_headers(helper)).json()
        assert [item["id"] for item in history["chat_messages"]] == [event["message_id"]]
