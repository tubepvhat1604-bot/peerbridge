import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-connections-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.config import get_settings
from app.db import database, utc_now
from app.main import app
from app.security import create_token
from fastapi.testclient import TestClient


def user_auth(display_name: str, *, role: str = "STUDENT", school: str | None = None, major: str | None = None) -> tuple[dict[str, str], int]:
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
                """INSERT INTO profiles(
                    user_id, display_name, age, city, school, major, intent, interests, available_times, updated_at
                ) VALUES (?, ?, 22, 'Ha Noi', ?, ?, 'conversation', '[]', '[]', ?)""",
                (
                    user_id,
                    display_name,
                    school or f"{display_name} School",
                    major or f"{display_name} Major",
                    now,
                ),
            )
    return {"Authorization": f"Bearer {create_token(user_id)}"}, user_id


def student_auth(display_name: str, *, school: str | None = None, major: str | None = None) -> tuple[dict[str, str], int]:
    return user_auth(display_name, school=school, major=major)


def create_connection(client: TestClient, requester_headers: dict[str, str], recipient_id: int) -> dict:
    response = client.post(
        "/api/v1/connections",
        headers=requester_headers,
        json={"recipient_id": recipient_id},
    )
    assert response.status_code == 201
    return response.json()


def test_accept_flow_creates_one_peer_match_and_blocks_reaccept() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        requester_headers, requester_id = student_auth("Requester")
        recipient_headers, recipient_id = student_auth("Recipient")

        created = create_connection(client, requester_headers, recipient_id)
        assert created["requester_id"] == requester_id
        assert created["recipient_id"] == recipient_id
        assert created["status"] == "PENDING"
        assert created["peer_match_id"] is None

        accepted = client.post(f"/api/v1/connections/{created['id']}/accept", headers=recipient_headers)
        assert accepted.status_code == 200
        accepted_data = accepted.json()
        assert accepted_data["status"] == "MATCHED"
        assert accepted_data["peer_match_id"] > 0

        accepted_again = client.post(f"/api/v1/connections/{created['id']}/accept", headers=recipient_headers)
        rejected_after_match = client.post(f"/api/v1/connections/{created['id']}/reject", headers=recipient_headers)

    assert accepted_again.status_code == 409
    assert rejected_after_match.status_code == 409
    with database() as connection:
        peer_matches = connection.execute(
            "SELECT connection_request_id, user_a_id, user_b_id FROM peer_matches WHERE connection_request_id = ?",
            (created["id"],),
        ).fetchall()
        request = connection.execute(
            "SELECT status FROM connection_requests WHERE id = ?",
            (created["id"],),
        ).fetchone()

    assert request["status"] == "MATCHED"
    assert len(peer_matches) == 1
    assert {peer_matches[0]["user_a_id"], peer_matches[0]["user_b_id"]} == {requester_id, recipient_id}


def test_reject_flow_does_not_create_peer_match_and_blocks_later_accept() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        requester_headers, _ = student_auth("RejectRequester")
        recipient_headers, recipient_id = student_auth("RejectRecipient")
        created = create_connection(client, requester_headers, recipient_id)

        rejected = client.post(f"/api/v1/connections/{created['id']}/reject", headers=recipient_headers)
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "REJECTED"
        assert rejected.json()["peer_match_id"] is None

        accepted_after_reject = client.post(f"/api/v1/connections/{created['id']}/accept", headers=recipient_headers)

    assert accepted_after_reject.status_code == 409
    with database() as connection:
        peer_match_count = connection.execute(
            "SELECT COUNT(*) FROM peer_matches WHERE connection_request_id = ?",
            (created["id"],),
        ).fetchone()[0]
        request = connection.execute(
            "SELECT status FROM connection_requests WHERE id = ?",
            (created["id"],),
        ).fetchone()

    assert peer_match_count == 0
    assert request["status"] == "REJECTED"


def test_only_receiver_can_respond_and_self_request_is_rejected() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        requester_headers, requester_id = student_auth("Sender")
        recipient_headers, recipient_id = student_auth("Receiver")
        other_headers, _ = student_auth("Observer")

        self_request = client.post(
            "/api/v1/connections",
            headers=requester_headers,
            json={"recipient_id": requester_id},
        )
        assert self_request.status_code == 400

        created = create_connection(client, requester_headers, recipient_id)
        requester_accept = client.post(f"/api/v1/connections/{created['id']}/accept", headers=requester_headers)
        other_reject = client.post(f"/api/v1/connections/{created['id']}/reject", headers=other_headers)
        recipient_accept = client.post(f"/api/v1/connections/{created['id']}/accept", headers=recipient_headers)

    assert requester_accept.status_code == 403
    assert other_reject.status_code == 403
    assert recipient_accept.status_code == 200
    assert recipient_accept.json()["status"] == "MATCHED"


def test_list_connections_returns_scoped_public_invitations_and_connected_peers() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        alice_headers, alice_id = student_auth("Alice", school="Alpha University", major="Computer Science")
        bob_headers, bob_id = student_auth("Bob", school="Beta College", major="Math")
        cara_headers, cara_id = student_auth("Cara", school="Gamma Institute", major="Physics")
        dana_headers, dana_id = student_auth("Dana", school="Delta Academy", major="Design")
        outsider_headers, _ = student_auth("Outsider")

        sent_request = create_connection(client, alice_headers, bob_id)
        incoming_request = create_connection(client, cara_headers, alice_id)
        matched_request = create_connection(client, alice_headers, dana_id)
        accepted = client.post(f"/api/v1/connections/{matched_request['id']}/accept", headers=dana_headers)
        assert accepted.status_code == 200

        response = client.get("/api/v1/connections", headers=alice_headers)
        bob_response = client.get("/api/v1/connections", headers=bob_headers)
        outsider_response = client.get("/api/v1/connections", headers=outsider_headers)

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data["incoming"]] == [incoming_request["id"]]
    assert [item["id"] for item in data["sent"]] == [sent_request["id"]]
    assert [item["connection_request_id"] for item in data["connected"]] == [matched_request["id"]]
    assert data["incoming"][0]["peer"] == {
        "user_id": cara_id,
        "display_name": "Cara",
        "school": "Gamma Institute",
        "major": "Physics",
    }
    assert data["sent"][0]["peer"] == {
        "user_id": bob_id,
        "display_name": "Bob",
        "school": "Beta College",
        "major": "Math",
    }
    assert data["connected"][0]["peer"] == {
        "user_id": dana_id,
        "display_name": "Dana",
        "school": "Delta Academy",
        "major": "Design",
    }
    assert data["incoming"][0]["status"] == "PENDING"
    assert data["sent"][0]["status"] == "PENDING"
    assert data["connected"][0]["requester_id"] == alice_id
    assert data["connected"][0]["recipient_id"] == dana_id
    serialized = str(data)
    assert "@example.edu" not in serialized
    assert "email" not in serialized

    assert bob_response.status_code == 200
    assert [item["peer"]["user_id"] for item in bob_response.json()["incoming"]] == [alice_id]
    assert outsider_response.status_code == 200
    assert outsider_response.json() == {"incoming": [], "sent": [], "connected": []}


def test_list_connections_requires_authentication_and_student_role() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        instructor_headers, _ = user_auth("Instructor", role="INSTRUCTOR")
        missing_token = client.get("/api/v1/connections")
        forbidden = client.get("/api/v1/connections", headers=instructor_headers)

    assert missing_token.status_code == 401
    assert forbidden.status_code == 403
