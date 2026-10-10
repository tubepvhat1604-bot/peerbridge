import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-test-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.config import get_settings
from app.main import app
from fastapi.testclient import TestClient


def auth_headers(client: TestClient) -> tuple[dict[str, str], int]:
    email = f"learner-{uuid4().hex}@example.edu"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "Learner",
            "age": 22,
            "city": "Hà Nội",
            "intent": "conversation",
        },
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


def peerbridge_payload() -> dict:
    return {
        "profile": {
            "display_name": " Linh ",
            "bio": "Working through algorithms and proofs.",
            "school": " Open University ",
            "major": " Computer Science ",
            "subjects": [" Python ", "python", "Data Structures"],
            "learning_goals": [" Build APIs ", "debug async code"],
        },
        "needs_help_with": [
            {
                "topic": " Calculus ",
                "description": "Limits and continuity",
                "current_level": "beginner",
                "target_outcome": "solve weekly problem sets",
            }
        ],
        "can_help_with": [
            {
                "topic": " Python ",
                "description": "API project structure",
                "proficiency_level": "advanced",
                "max_sessions_per_week": 4,
            }
        ],
        "availability": [
            {
                "day_of_week": 2,
                "start_time": "09:00",
                "end_time": "10:30",
                "timezone": "Asia/Bangkok",
            }
        ],
    }


def test_get_profile_returns_current_user_profile() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, user_id = auth_headers(client)

        response = client.get("/api/v1/profiles/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["profile"]["user_id"] == user_id
    assert data["profile"]["display_name"] == "Learner"
    assert data["needs_help_with"] == []
    assert data["can_help_with"] == []
    assert data["availability"] == []


def test_update_profile_saves_basic_profile() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, _ = auth_headers(client)
        response = client.put("/api/v1/profiles/me", headers=headers, json=peerbridge_payload())

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["display_name"] == "Linh"
    assert profile["school"] == "Open University"
    assert profile["major"] == "Computer Science"
    assert profile["subjects"] == ["Python", "Data Structures"]
    assert profile["learning_goals"] == ["Build APIs", "debug async code"]


def test_invalid_profile_input_returns_422() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, _ = auth_headers(client)
        payload = peerbridge_payload()
        payload["availability"][0]["end_time"] = "08:30"
        response = client.put("/api/v1/profiles/me", headers=headers, json=payload)

    assert response.status_code == 422


def test_help_need_saved() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, _ = auth_headers(client)
        assert client.put("/api/v1/profiles/me", headers=headers, json=peerbridge_payload()).status_code == 200
        response = client.get("/api/v1/profiles/me", headers=headers)

    needs = response.json()["needs_help_with"]
    assert needs[0]["topic"] == "Calculus"
    assert needs[0]["current_level"] == "beginner"
    assert needs[0]["target_outcome"] == "solve weekly problem sets"


def test_help_offer_saved() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, _ = auth_headers(client)
        assert client.put("/api/v1/profiles/me", headers=headers, json=peerbridge_payload()).status_code == 200
        response = client.get("/api/v1/profiles/me", headers=headers)

    offers = response.json()["can_help_with"]
    assert offers[0]["topic"] == "Python"
    assert offers[0]["proficiency_level"] == "advanced"
    assert offers[0]["max_sessions_per_week"] == 4


def test_availability_saved() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        headers, _ = auth_headers(client)
        assert client.put("/api/v1/profiles/me", headers=headers, json=peerbridge_payload()).status_code == 200
        response = client.get("/api/v1/profiles/me", headers=headers)

    availability = response.json()["availability"]
    assert availability[0]["day_of_week"] == 2
    assert availability[0]["start_time"] == "09:00:00"
    assert availability[0]["end_time"] == "10:30:00"
    assert availability[0]["timezone"] == "Asia/Bangkok"
