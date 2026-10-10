import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-sessions-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.config import get_settings
from app.db import database, utc_now
from app.main import app
from app.security import create_token
from fastapi.testclient import TestClient


def user_auth(display_name: str, role: str = "STUDENT") -> tuple[dict[str, str], int]:
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
    return {"Authorization": f"Bearer {create_token(user_id)}"}, user_id


def create_peer_match(requester_id: int, recipient_id: int) -> int:
    now = utc_now()
    user_a_id, user_b_id = sorted((requester_id, recipient_id))
    with database() as connection:
        cursor = connection.execute(
            """INSERT INTO connection_requests(requester_id, recipient_id, status, created_at, responded_at)
               VALUES (?, ?, 'MATCHED', ?, ?)""",
            (requester_id, recipient_id, now, now),
        )
        connection_request_id = int(cursor.lastrowid)
        peer_match = connection.execute(
            """INSERT INTO peer_matches(connection_request_id, user_a_id, user_b_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (connection_request_id, user_a_id, user_b_id, now),
        )
        return int(peer_match.lastrowid)


def session_payload(peer_match_id: int, learner_id: int, helper_id: int) -> dict:
    return {
        "peer_match_id": peer_match_id,
        "learner_id": learner_id,
        "helper_id": helper_id,
        "topic": "Calculus limits",
        "scheduled_start": "2026-10-02T09:00:00+07:00",
        "scheduled_end": "2026-10-02T10:00:00+07:00",
    }


def test_matched_student_creates_session_and_members_or_instructor_can_read() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        learner_headers, learner_id = user_auth("Learner")
        helper_headers, helper_id = user_auth("Helper")
        outsider_headers, _ = user_auth("Outsider")
        instructor_headers, instructor_id = user_auth("Instructor", role="INSTRUCTOR")
        peer_match_id = create_peer_match(learner_id, helper_id)

        created = client.post(
            "/api/v1/sessions",
            headers=learner_headers,
            json=session_payload(peer_match_id, learner_id, helper_id),
        )
        assert created.status_code == 201
        session = created.json()
        assert session["peer_match_id"] == peer_match_id
        assert session["learner_id"] == learner_id
        assert session["helper_id"] == helper_id
        assert session["topic"] == "Calculus limits"
        assert session["chat_messages"] == []

        with database() as connection:
            connection.execute("INSERT INTO session_instructors VALUES (?, ?)", (session["id"], instructor_id))
            connection.execute(
                """INSERT INTO chat_messages(session_id, sender_id, content, created_at)
                   VALUES (?, ?, ?, ?)""",
                (session["id"], learner_id, "Can we start with epsilon-delta?", utc_now()),
            )

        learner_read = client.get(f"/api/v1/sessions/{session['id']}", headers=learner_headers)
        helper_read = client.get(f"/api/v1/sessions/{session['id']}", headers=helper_headers)
        instructor_read = client.get(f"/api/v1/sessions/{session['id']}", headers=instructor_headers)
        outsider_read = client.get(f"/api/v1/sessions/{session['id']}", headers=outsider_headers)

    assert learner_read.status_code == 200
    assert helper_read.status_code == 200
    assert instructor_read.status_code == 200
    assert outsider_read.status_code == 403
    assert learner_read.json()["chat_messages"] == []  # unmoderated legacy rows stay private


def test_only_peer_match_members_can_create_session() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        learner_headers, learner_id = user_auth("Owner")
        _, helper_id = user_auth("OwnerHelper")
        outsider_headers, outsider_id = user_auth("CreateOutsider")
        peer_match_id = create_peer_match(learner_id, helper_id)

        outsider_create = client.post(
            "/api/v1/sessions",
            headers=outsider_headers,
            json=session_payload(peer_match_id, learner_id, helper_id),
        )
        mismatched_participants = client.post(
            "/api/v1/sessions",
            headers=learner_headers,
            json=session_payload(peer_match_id, learner_id, outsider_id),
        )
        missing_peer_match = client.post(
            "/api/v1/sessions",
            headers=learner_headers,
            json=session_payload(peer_match_id + 9999, learner_id, helper_id),
        )

    assert outsider_create.status_code == 403
    assert mismatched_participants.status_code == 403
    assert missing_peer_match.status_code == 404


def test_instructor_cannot_create_session() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        _, learner_id = user_auth("StudentA")
        _, helper_id = user_auth("StudentB")
        instructor_headers, _ = user_auth("Teacher", role="INSTRUCTOR")
        peer_match_id = create_peer_match(learner_id, helper_id)

        response = client.post(
            "/api/v1/sessions",
            headers=instructor_headers,
            json=session_payload(peer_match_id, learner_id, helper_id),
        )

    assert response.status_code == 403


def test_session_list_is_scoped_and_includes_both_participant_roles() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        learner_headers, learner_id = user_auth("ListLearner")
        helper_headers, helper_id = user_auth("ListHelper")
        outsider_headers, outsider_id = user_auth("ListOutsider")
        _, outsider_peer_id = user_auth("ListOutsiderPeer")
        empty_headers, _ = user_auth("ListEmpty")
        instructor_headers, _ = user_auth("ListInstructor", role="INSTRUCTOR")
        own_match_id = create_peer_match(learner_id, helper_id)
        other_match_id = create_peer_match(outsider_id, outsider_peer_id)

        first = client.post(
            "/api/v1/sessions", headers=learner_headers,
            json=session_payload(own_match_id, learner_id, helper_id),
        )
        second = client.post(
            "/api/v1/sessions", headers=helper_headers,
            json=session_payload(own_match_id, helper_id, learner_id),
        )
        other = client.post(
            "/api/v1/sessions", headers=outsider_headers,
            json=session_payload(other_match_id, outsider_id, outsider_peer_id),
        )
        assert first.status_code == second.status_code == other.status_code == 201
        expected_ids = [second.json()["id"], first.json()["id"]]

        for headers in (learner_headers, helper_headers):
            response = client.get("/api/v1/sessions", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["count"] == 2
            assert [item["id"] for item in body["items"]] == expected_ids
            for item in body["items"]:
                assert set(item) == {
                    "id", "peer_match_id", "learner_id", "helper_id", "topic",
                    "scheduled_start", "scheduled_end", "created_at", "updated_at",
                }

        outsider_list = client.get("/api/v1/sessions", headers=outsider_headers).json()
        assert [item["id"] for item in outsider_list["items"]] == [other.json()["id"]]
        empty = client.get("/api/v1/sessions", headers=empty_headers)
        assert empty.status_code == 200
        assert empty.json() == {"items": [], "count": 0}

        instructor = client.get("/api/v1/sessions", headers=instructor_headers)
        assert instructor.status_code == 200
        instructor_body = instructor.json()
        ids = [item["id"] for item in instructor_body["items"]]
        assert set(expected_ids) | {other.json()["id"]} <= set(ids)  # Admin giám sát mọi phiên
        assert ids == sorted(ids, reverse=True)
        assert instructor_body["count"] == len(ids)


def test_session_list_requires_authenticated_non_seed_user() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/api/v1/sessions").status_code == 401
        assert client.get(
            "/api/v1/sessions", headers={"Authorization": "Bearer invalid-token"},
        ).status_code == 401
        with database() as connection:
            seed_id = connection.execute("SELECT id FROM users WHERE is_seed = 1 LIMIT 1").fetchone()["id"]
        assert client.get(
            "/api/v1/sessions", headers={"Authorization": f"Bearer {create_token(seed_id)}"},
        ).status_code == 401
