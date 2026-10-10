"""Vai trò Admin, tóm tắt/chấm phiên học, số đo "phiên không lộ đáp án" và cảnh báo realtime."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-review-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from app.agents.moderator.llm import FakeLLM
from app.config import get_settings
from app.db import database, init_db, utc_now
from app.enums import ModerationAction
from app.main import app
from app.schemas import ModerationResult
from app.security import create_token
from app.services.moderation_agent import MockModerationAgent, get_moderation_agent
from app.session_review import service
from app.session_review.judge import rules_review
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean() -> None:
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    init_db()
    yield
    app.dependency_overrides.clear()


def headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id)}"}


def create_user(name: str, role: str = "STUDENT") -> int:
    now = utc_now()
    with database() as connection:
        user_id = int(connection.execute(
            "INSERT INTO users(email, role, password_hash, created_at) VALUES (?, ?, 'x', ?)",
            (f"{name.lower()}-{uuid4().hex}@example.edu", role, now)).lastrowid)
        connection.execute(
            """INSERT INTO profiles(user_id, display_name, age, city, intent, interests, available_times, updated_at)
               VALUES (?, ?, 22, 'Ha Noi', 'conversation', '[]', '[]', ?)""", (user_id, name, now))
    return user_id


def create_session(learner: int, helper: int, topic: str = "SQL JOIN") -> int:
    now = utc_now()
    a, b = sorted((learner, helper))
    with database() as connection:
        request = connection.execute(
            "INSERT INTO connection_requests(requester_id, recipient_id, status, created_at, responded_at)"
            " VALUES (?, ?, 'MATCHED', ?, ?)", (learner, helper, now, now)).lastrowid
        match = connection.execute(
            "INSERT INTO peer_matches(connection_request_id, user_a_id, user_b_id, created_at) VALUES (?, ?, ?, ?)",
            (request, a, b, now)).lastrowid
        return int(connection.execute(
            """INSERT INTO study_sessions(peer_match_id, learner_id, helper_id, topic, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""", (match, learner, helper, topic, now, now)).lastrowid)


def add_message(session_id: int, sender: int, content: str, action: str = "ALLOW", guidance: str | None = None,
                audit: dict[str, Any] | None = None) -> tuple[int, int]:
    now = utc_now()
    with database() as connection:
        message_id = int(connection.execute(
            "INSERT INTO chat_messages(session_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, sender, content, now)).lastrowid)
        event_id = int(connection.execute(
            """INSERT INTO moderation_events(session_id, message_id, sender_id, agent_action, risk_score, reason,
                   guidance, needs_human_review, context, created_at) VALUES (?, ?, ?, ?, 0.1, 'test', ?, ?, ?, ?)""",
            (session_id, message_id, sender, action, guidance, int(action == "ESCALATE"),
             json.dumps({"audit": audit or {}}), now)).lastrowid)
    return message_id, event_id


def socratic_session() -> tuple[int, int, int]:
    learner, helper = create_user("Lan"), create_user("Minh")
    session_id = create_session(learner, helper)
    add_message(session_id, learner, "Mình chưa hiểu LEFT JOIN, giúp mình với")
    add_message(session_id, helper, "Nếu khách chưa mua hàng thì cậu có muốn họ hiện ra không?")
    add_message(session_id, learner, "Cho mình xin đáp án bài 3", "GUIDE", "Bạn đã thử viết truy vấn nào chưa?")
    add_message(session_id, helper, "Đáp án bài 3 là SELECT * FROM a LEFT JOIN b", "BLOCK")
    add_message(session_id, learner, "ok mai học tiếp nhé", audit={"prefiltered": True, "llm_calls_used": 0})
    return learner, helper, session_id


def test_whoami_and_admin_email_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    student, admin = create_user("Sv"), create_user("Ad", "INSTRUCTOR")
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/me", headers=headers(student)).json()["role"] == "STUDENT"
        assert client.get("/api/v1/admin/me", headers=headers(admin)).json() == {
            "user_id": admin, "role": "ADMIN", "is_admin": True}
        email = f"boss-{uuid4().hex}@example.edu"
        monkeypatch.setenv("ADMIN_EMAILS", f"other@example.edu, {email.upper()}")
        token = client.post("/api/v1/auth/register", json={
            "email": email, "password": "matkhau123", "display_name": "Boss", "age": 30, "city": "HN",
            "intent": "conversation"}).json()["access_token"]
        me = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["is_admin"] is True


def test_student_gets_summary_without_scores_and_outsider_is_blocked() -> None:
    learner, _helper, session_id = socratic_session()
    outsider = create_user("Nguoila")
    with TestClient(app) as client:
        response = client.post(f"/api/v1/sessions/{session_id}/review", headers=headers(learner))
        assert response.status_code == 200
        review = response.json()["review"]
        assert review["mode"] == "rules" and review["summary"]
        assert "socratic_score" not in review and "answer_leaked" not in review
        assert review["message_count"] == 4  # tin bị chặn không được tính
        assert client.post(f"/api/v1/sessions/{session_id}/review", headers=headers(outsider)).status_code == 403
        assert client.get(f"/api/v1/sessions/{session_id}/review", headers=headers(learner)).json()["review"]


def test_ai_review_is_cached_until_new_messages_and_ignores_unknown_leak_ids() -> None:
    learner, _helper, session_id = socratic_session()
    llm = FakeLLM(rule=lambda _s, _u: {
        "summary": "Hai bạn ôn LEFT JOIN qua câu hỏi gợi mở.", "key_points": ["LEFT JOIN"],
        "open_questions": [], "next_steps": ["Tự viết một truy vấn LEFT JOIN nhỏ"], "socratic_score": 0.9,
        "answer_leaked": False, "leak_message_ids": [99999], "judge_notes": "Dẫn dắt tốt"})

    first = asyncio.run(service.review_session(session_id, learner, llm_factory=lambda: llm, budget_left=lambda: 1.0))
    again = asyncio.run(service.review_session(session_id, learner, llm_factory=lambda: llm, budget_left=lambda: 1.0))

    assert first["mode"] == "ai" and first["socratic_score"] == 0.9 and first["leak_message_ids"] == []
    assert again["updated_at"] == first["updated_at"] and len(llm.calls) == 1
    add_message(session_id, learner, "Mình thử viết rồi, đúng không?")
    asyncio.run(service.review_session(session_id, learner, llm_factory=lambda: llm, budget_left=lambda: 1.0))
    assert len(llm.calls) == 2


def test_ai_review_falls_back_to_rules_on_unsafe_output_or_no_budget() -> None:
    learner, _helper, session_id = socratic_session()
    unsafe = FakeLLM(rule=lambda _s, _u: {
        "summary": "Đáp án: ```SELECT * FROM a LEFT JOIN b```", "socratic_score": 0.5, "answer_leaked": False})
    review = asyncio.run(service.review_session(session_id, learner, llm_factory=lambda: unsafe,
                                                budget_left=lambda: 1.0))
    assert review["mode"] == "rules" and review["ai_error"] == "unsafe_output"

    learner2, _h, session2 = socratic_session()
    broke = FakeLLM(responses=[])
    review2 = asyncio.run(service.review_session(session2, learner2, llm_factory=lambda: broke,
                                                 budget_left=lambda: 0.0))
    assert review2["mode"] == "rules" and broke.calls == []


def test_rules_review_detects_shared_exam_and_scores_questions() -> None:
    messages = [
        {"id": 1, "sender_role": "learner", "content": "Bài này làm sao?", "final_action": "ALLOW"},
        {"id": 2, "sender_role": "helper", "content": "Cậu thử nghĩ xem điều kiện dừng là gì?", "final_action": "ALLOW"},
        {"id": 3, "sender_role": "helper", "content": "Mình gửi mọi người đề thi với đáp án", "final_action": "ALLOW"},
    ]
    review = rules_review("Python", messages)
    assert review.answer_leaked is True and review.leak_message_ids == [3]
    assert review.socratic_score == 0.5


def test_admin_dashboard_sessions_and_leak_rate() -> None:
    learner, helper, session_id = socratic_session()
    admin = create_user("Admin", "INSTRUCTOR")
    leaked_learner, leaked_helper = create_user("A"), create_user("B")
    leaked_session = create_session(leaked_learner, leaked_helper, "Python")
    add_message(leaked_session, leaked_learner, "Bài 2 làm sao vậy")
    _msg, slipped_event = add_message(leaked_session, leaked_helper, "Cứ nộp code này: for i in range(3): print(i)")
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/overview", headers=headers(learner)).status_code == 403
        # Admin phát hiện một tin đã lọt qua AI và chặn lại -> phiên đó tính là lộ đáp án.
        reviewed = client.post(f"/instructor/moderation/{slipped_event}/review", headers=headers(admin),
                               json={"action": "OVERRIDE", "override_action": "BLOCK", "notes": "Lộ code"})
        assert reviewed.status_code == 201
        overview = client.get("/api/v1/admin/overview", headers=headers(admin)).json()
        sessions = client.get("/api/v1/admin/sessions", headers=headers(admin)).json()["items"]
        detail = client.get(f"/api/v1/admin/sessions/{session_id}", headers=headers(admin)).json()
        judged = client.post(f"/api/v1/admin/sessions/{session_id}/review", headers=headers(admin)).json()

    by_id = {item["id"]: item for item in sessions}
    assert by_id[leaked_session]["verdict"]["answer_leaked"] is True
    assert by_id[session_id]["verdict"]["answer_leaked"] is False
    assert by_id[session_id]["held_count"] == 1 and by_id[session_id]["guide_count"] == 1
    assert overview["leak_free"]["sessions"] >= 2 and overview["leak_free"]["leaked"] >= 1
    assert 0 <= overview["leak_free"]["rate"] < 1
    assert overview["ai"]["messages_prefiltered"] >= 1
    assert any(pair["peer_match_id"] == by_id[session_id]["peer_match_id"] for pair in overview["network"])
    held = [m for m in detail["session"]["messages"] if not m["delivered"]]
    assert [m["final_action"] for m in held] == ["BLOCK"]
    assert judged["review"]["socratic_score"] is not None and "judge_notes" in judged["review"]


class BlockingAgent(MockModerationAgent):
    def __init__(self) -> None:
        super().__init__(ModerationResult(action=ModerationAction.BLOCK, risk_score=0.9, reason="xúc phạm",
                                          needs_human_review=False))


def test_block_alerts_admins_and_intervention_reaches_room() -> None:
    learner, helper = create_user("Lan"), create_user("Minh")
    admin = create_user("Admin", "INSTRUCTOR")
    session_id = create_session(learner, helper)
    app.dependency_overrides[get_moderation_agent] = BlockingAgent
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}?token={create_token(learner)}") as room:
            room.receive_json()
            room.send_json({"type": "CHAT_MESSAGE", "content": "Đồ ngu"})
            result = room.receive_json()
            room.receive_json()  # WARNING
            event_id = result["moderation_event_id"]
            response = client.post(f"/instructor/moderation/{event_id}/review", headers=headers(admin),
                                   json={"action": "INTERVENE", "notes": "Hai bạn giữ lời lẽ tôn trọng nhé."})
            assert response.status_code == 201
            note = room.receive_json()
        bell = client.get("/api/v1/notifications?limit=20", headers=headers(admin)).json()

    assert note["type"] == "ADMIN_NOTE" and "tôn trọng" in note["note"]
    items = bell["items"] if isinstance(bell, dict) else bell
    assert any(f"Phiên #{session_id}" in item["title"] for item in items)
