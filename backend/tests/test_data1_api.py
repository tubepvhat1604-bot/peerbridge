from uuid import uuid4

import pytest
from app.config import get_settings
from app.db import database
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data1.db"))
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    monkeypatch.setenv("JWT_SECRET", "data1-test-secret")
    get_settings.cache_clear()
    # Keep this module's registration traffic out of the legacy tests' shared auth bucket.
    with TestClient(app, client=(f"data1-{uuid4().hex}", 50000)) as test_client:
        yield test_client
    get_settings.cache_clear()


def register(client):
    response = client.post("/api/v1/auth/register", json={
        "email": f"data1-{uuid4().hex}@example.edu", "password": "password123",
        "display_name": "Data 1 learner", "age": 22, "city": "Hà Nội", "intent": "conversation",
    })
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def payload():
    return {
        "learning_goal": "Learn SQL and support a partner with Python", "deadline": "2026-11-01",
        "committed_weekly_hours": 5, "conscientiousness": 0.8, "procrastination": 0.4,
        "communication_style": "gentle reminders",
        "topics": [
            {"text": "JOIN", "domain": "sql", "role": "need", "self_level": "unknown"},
            {"text": "Python dict", "domain": "python", "role": "offer", "self_level": "strong"},
            {"text": "IELTS writing", "role": "need", "self_level": "learning"},
        ],
        "availability": [{"day_of_week": 1, "start_time": "19:00", "end_time": "20:00"}],
    }


def submit_and_confirm(client, headers):
    draft = client.post("/api/v1/profile", json=payload(), headers=headers)
    assert draft.status_code == 200
    draft = draft.json()
    confirmation = {"revision": draft["revision"], "selections": [
        {"topic_index": item["topic_index"], "concept_id": item["concept_id"]} for item in draft["mappings"]
    ]}
    response = client.post("/api/v1/profile/confirm", json=confirmation, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_confirmation_persistence_and_teammate_contract(client):
    headers, user_id = register(client)
    draft = client.post("/api/v1/profile", json=payload(), headers=headers).json()
    assert draft["status"] == "draft" and draft["user_concepts"] == []
    assert draft["onboarding"]["availability"][0]["timezone"] == "Asia/Ho_Chi_Minh"
    assert client.get("/api/v1/profile/confirmed", headers=headers).status_code == 409
    confirmation = {"revision": draft["revision"], "selections": [
        {"topic_index": 0, "concept_id": "sql.join"},
        {"topic_index": 1, "concept_id": "py.dictionaries"},
        {"topic_index": 2, "concept_id": None},
    ], "additional_concepts": [{"concept_id": "py.functions", "role": "need", "self_level": "learning"}]}
    response = client.post("/api/v1/profile/confirm", json=confirmation, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_version"] == "data1.v1" and body["user_id"] == user_id
    assert body["confirmed_at"] and body["status"] == "confirmed"
    assert [(item["concept_id"], item["theta"]) for item in body["user_concepts"]] == [
        ("py.dictionaries", 1), ("py.functions", 0), ("sql.join", -1),
    ]
    assert body["unmapped"][0]["topic"]["text"] == "IELTS writing"
    assert client.get("/api/v1/profile/confirmed", headers=headers).json() == body
    assert client.post("/api/v1/profile/confirm", json=confirmation, headers=headers).status_code == 409


def test_correction_of_unmapped_topic_and_level_is_persisted(client):
    headers, _ = register(client)
    data = payload()
    data["topics"] = [{"text": "Lab 123", "domain": "sql", "self_level": "unknown"}]
    draft = client.post("/api/v1/profile", json=data, headers=headers).json()
    assert draft["mappings"][0]["concept_id"] is None
    response = client.post("/api/v1/profile/confirm", headers=headers, json={
        "revision": draft["revision"], "selections": [
            {"topic_index": 0, "concept_id": "sql.join", "self_level": "learning"},
        ],
    })
    assert response.status_code == 200
    assert response.json()["unmapped"] == []
    assert response.json()["user_concepts"][0]["theta"] == 0
    assert response.json()["mappings"][0]["topic"]["text"] == "Lab 123"


def test_conflicting_levels_for_same_concept_cannot_create_inconsistent_strengths(client):
    headers, _ = register(client)
    draft = client.post("/api/v1/profile", json=payload(), headers=headers).json()
    response = client.post("/api/v1/profile/confirm", headers=headers, json={
        "revision": draft["revision"], "selections": [
            {"topic_index": item["topic_index"], "concept_id": item["concept_id"]} for item in draft["mappings"]
        ], "additional_concepts": [{"concept_id": "sql.join", "role": "offer", "self_level": "strong"}],
    })
    assert response.status_code == 422
    assert client.get("/api/v1/profile", headers=headers).json()["status"] == "draft"


@pytest.mark.parametrize("selections", [
    [], [{"topic_index": 0, "concept_id": "sql.join"}] * 3,
    [{"topic_index": 0, "concept_id": "sql.made_up"}, {"topic_index": 1, "concept_id": None},
     {"topic_index": 2, "concept_id": None}],
    [{"topic_index": 0, "concept_id": "py.basic"}, {"topic_index": 1, "concept_id": None},
     {"topic_index": 2, "concept_id": None}],
])
def test_invalid_confirmation_is_atomic(client, selections):
    headers, user_id = register(client)
    draft = client.post("/api/v1/profile", json=payload(), headers=headers).json()
    response = client.post("/api/v1/profile/confirm", headers=headers,
                           json={"revision": draft["revision"], "selections": selections})
    assert response.status_code == 422
    assert client.get("/api/v1/profile", headers=headers).json() == draft
    with database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_concepts WHERE user_id=?", (user_id,)).fetchone()[0] == 0


def test_revision_guard_and_reconfirmation_preserve_attempted_theta(client):
    headers, user_id = register(client)
    first = submit_and_confirm(client, headers)
    with database() as connection:
        connection.execute("UPDATE user_concepts SET theta=0.4, n_attempts=3 WHERE user_id=? AND concept_id='sql.join'",
                           (user_id,))
    second = client.post("/api/v1/profile", json=payload(), headers=headers).json()
    assert second["revision"] == first["revision"] + 1
    assert client.get("/api/v1/profile/confirmed", headers=headers).status_code == 409
    assert client.post("/api/v1/profile/confirm", headers=headers, json={
        "revision": first["revision"], "selections": [],
    }).status_code == 409
    result = client.post("/api/v1/profile/confirm", headers=headers, json={
        "revision": second["revision"], "selections": [
            {"topic_index": item["topic_index"], "concept_id": item["concept_id"]} for item in second["mappings"]
        ],
    }).json()
    join = next(item for item in result["user_concepts"] if item["concept_id"] == "sql.join")
    assert join["theta"] == 0.4 and join["n_attempts"] == 3


def test_authentication_student_scope_and_ownership(client):
    headers, user_id = register(client)
    other, _ = register(client)
    assert client.get("/api/v1/concepts").status_code == 401
    assert client.post("/api/v1/profile", json=payload()).status_code == 401
    submit_and_confirm(client, headers)
    assert client.get("/api/v1/profile", headers=other).status_code == 404
    assert client.post("/api/v1/profile", headers=headers, json={**payload(), "user_id": 99}).status_code == 422
    with database() as connection:
        connection.execute("UPDATE users SET role='INSTRUCTOR' WHERE id=?", (user_id,))
    assert client.get("/api/v1/profile", headers=headers).status_code == 403


def test_catalog_api_has_stable_vision_ids_and_domain_scoped_candidates(client):
    headers, _ = register(client)
    catalog = client.get("/api/v1/concepts?domain=sql", headers=headers).json()
    assert len(catalog["concepts"]) == 30
    concept = client.get("/api/v1/concepts/sql.join", headers=headers).json()
    assert concept["id"] == "sql.join" and concept["prerequisites"] == ["sql.select_basic"]
    assert client.get("/api/v1/concepts/sql.fake", headers=headers).status_code == 404
    result = client.post("/api/v1/concepts/candidates", headers=headers, json={"topic": "JOIN", "domain": "sql"}).json()
    assert result["backend"] == "local_lexical"
    assert result["candidates"][0]["concept_id"] == "sql.join"
    assert client.get("/api/v1/concepts?domain=ielts", headers=headers).status_code == 422


def test_pair_profile_access_uses_existing_accepted_pair_and_requires_confirmation(client):
    a, a_id = register(client)
    b, b_id = register(client)
    outsider, _ = register(client)
    request = client.post("/api/v1/connections", headers=a, json={"recipient_id": b_id}).json()
    accepted = client.post(f"/api/v1/connections/{request['id']}/accept", headers=b).json()
    path = f"/api/v1/pairs/{accepted['peer_match_id']}/concept-profiles"
    assert client.get(path, headers=outsider).status_code == 403
    submit_and_confirm(client, a)
    client.post("/api/v1/profile", json=payload(), headers=b)
    assert client.get(path, headers=a).status_code == 409
    submit_and_confirm(client, b)
    response = client.get(path, headers=a)
    assert response.status_code == 200
    assert {response.json()["user_a"]["user_id"], response.json()["user_b"]["user_id"]} == {a_id, b_id}


def test_legacy_profile_and_matching_are_unchanged_by_new_onboarding(client):
    a, _ = register(client)
    b, _ = register(client)
    common = {"profile": {"display_name": "Legacy", "subjects": ["SQL"], "learning_goals": ["SQL"]},
              "needs_help_with": [{"topic": "JOIN"}], "can_help_with": [{"topic": "JOIN"}],
              "availability": [{"day_of_week": 1, "start_time": "19:00", "end_time": "20:00"}]}
    for headers in (a, b):
        assert client.put("/api/v1/profiles/me", json=common, headers=headers).status_code == 200
    profile_before = client.get("/api/v1/profiles/me", headers=a).json()
    matches_before = client.post("/api/v1/matches/search", headers=a).json()["candidates"]
    submit_and_confirm(client, a)
    assert client.get("/api/v1/profiles/me", headers=a).json() == profile_before
    matches_after = client.post("/api/v1/matches/search", headers=a).json()["candidates"]
    assert [(item["candidate_id"], item["total_score"], item["component_scores"]) for item in matches_after] == [
        (item["candidate_id"], item["total_score"], item["component_scores"]) for item in matches_before
    ]
