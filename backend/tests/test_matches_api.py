import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-matches-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.config import get_settings
from app.db import database, utc_now
from app.main import app
from app.services.matching_config import (
    FEATURE_AVAILABILITY_OVERLAP,
    FEATURE_PREFERENCE_COMPATIBILITY,
    FEATURE_SKILL_COMPLEMENTARITY,
    FEATURE_TOPIC_COMPATIBILITY,
)
from fastapi.testclient import TestClient


def register_user(client: TestClient, display_name: str) -> tuple[dict[str, str], int]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{display_name.lower()}-{uuid4().hex}@example.edu",
            "password": "password123",
            "display_name": display_name,
            "age": 22,
            "city": "Ha Noi",
            "intent": "conversation",
        },
    )
    assert response.status_code == 201
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, int(data["user_id"])


def peerbridge_payload(display_name: str, *, needs: list[str] | None = None, offers: list[str] | None = None) -> dict:
    return {
        "profile": {
            "display_name": display_name,
            "bio": "Peer learning profile",
            "school": "Open University",
            "major": "Computer Science",
            "subjects": [],
            "learning_goals": [],
        },
        "needs_help_with": [{"topic": topic} for topic in needs or []],
        "can_help_with": [{"topic": topic, "max_sessions_per_week": 3} for topic in offers or []],
        "availability": [],
    }


def update_peerbridge_profile(client: TestClient, headers: dict[str, str], payload: dict) -> None:
    response = client.put("/api/v1/profiles/me", headers=headers, json=payload)
    assert response.status_code == 200


def insert_candidate_profiles(topic: str, count: int) -> list[int]:
    user_ids: list[int] = []
    with database() as connection:
        for index in range(count):
            now = utc_now()
            cursor = connection.execute(
                """INSERT INTO users(email, role, password_hash, created_at)
                   VALUES (?, 'STUDENT', ?, ?)""",
                (f"candidate-{uuid4().hex}@example.edu", "not-used", now),
            )
            user_id = int(cursor.lastrowid)
            connection.execute(
                """INSERT INTO profiles(
                    user_id, display_name, age, city, school, major, intent, interests, available_times, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    f"Candidate {index}",
                    22,
                    "Ha Noi",
                    f"Candidate School {index}",
                    f"Candidate Major {index}",
                    "conversation",
                    "[]",
                    "[]",
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO help_offers(
                    profile_user_id, topic, description, proficiency_level, max_sessions_per_week, created_at, updated_at
                ) VALUES (?, ?, '', '', 3, ?, ?)""",
                (user_id, topic, now, now),
            )
            user_ids.append(user_id)
    return user_ids


def test_search_matches_persists_top_five_can_be_loaded_and_is_owner_scoped() -> None:
    get_settings.cache_clear()
    topic = f"matching topic {uuid4().hex}"
    with TestClient(app) as client:
        requester_headers, requester_id = register_user(client, "Requester")
        update_peerbridge_profile(client, requester_headers, peerbridge_payload("Requester", needs=[topic]))
        helper_ids = insert_candidate_profiles(topic, 6)

        response = client.post("/api/v1/matches/search", headers=requester_headers)
        assert response.status_code == 201
        data = response.json()

        reloaded = client.get(f"/api/v1/matches/{data['request_id']}", headers=requester_headers)
        assert reloaded.status_code == 200

        other_headers, _ = register_user(client, "Other")
        forbidden = client.get(f"/api/v1/matches/{data['request_id']}", headers=other_headers)
        assert forbidden.status_code == 404

        assert reloaded.json() == data
        assert data["request_id"] > 0
        assert [candidate["candidate_id"] for candidate in data["candidates"]][:5] == helper_ids[:5]
        assert [candidate["rank"] for candidate in data["candidates"]] == list(range(1, len(data["candidates"]) + 1))
        assert data["candidates"][0]["display_name"] == "Candidate 0"
        assert data["candidates"][0]["school"] == "Candidate School 0"
        assert data["candidates"][0]["major"] == "Candidate Major 0"
        for candidate in data["candidates"]:
            assert candidate["request_id"] == data["request_id"]
            assert 0 <= candidate["total_score"] <= 100
            assert "email" not in candidate
            assert set(candidate["component_scores"]) == {
                FEATURE_SKILL_COMPLEMENTARITY,
                FEATURE_TOPIC_COMPATIBILITY,
                FEATURE_AVAILABILITY_OVERLAP,
                FEATURE_PREFERENCE_COMPATIBILITY,
            }

    with database() as connection:
        request = connection.execute(
            "SELECT requester_id FROM match_requests WHERE id = ?",
            (data["request_id"],),
        ).fetchone()
        candidates = connection.execute(
            "SELECT candidate_id, component_scores, rank FROM match_candidates WHERE request_id = ? ORDER BY rank",
            (data["request_id"],),
        ).fetchall()

    assert request["requester_id"] == requester_id
    assert [candidate["candidate_id"] for candidate in candidates][:5] == helper_ids[:5]
    assert [candidate["rank"] for candidate in candidates] == list(range(1, len(candidates) + 1))
    assert FEATURE_SKILL_COMPLEMENTARITY in json.loads(candidates[0]["component_scores"])


def test_search_matches_requires_authentication() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post("/api/v1/matches/search")

    assert response.status_code == 401
