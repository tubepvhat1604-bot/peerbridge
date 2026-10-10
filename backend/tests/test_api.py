import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ["DATABASE_PATH"] = str(Path(tempfile.gettempdir()) / f"dongdieu-test-{uuid4().hex}.db")
os.environ["UPLOAD_DIRECTORY"] = str(Path(tempfile.gettempdir()) / f"dongdieu-uploads-{uuid4().hex}")
os.environ["JWT_SECRET"] = "test-secret"

from app.config import get_settings
from app.main import app
from fastapi.testclient import TestClient


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/register", json={
        "email": "tester@example.com", "password": "password123", "display_name": "Tester",
        "age": 26, "city": "Hà Nội", "intent": "serious",
    })
    if response.status_code == 409:
        response = client.post("/api/v1/auth/login", json={"email": "tester@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_complete_flow():
    get_settings.cache_clear()
    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"] == "/docs"
        assert client.get("/health").status_code == 200
        headers = auth_headers(client)
        updated = client.put("/api/v1/profiles/me", headers=headers, json={
            "display_name": "Tester", "age": 26, "city": "Hà Nội", "occupation": "Developer",
            "bio": "Thích đọc sách", "intent": "serious", "interests": ["đọc sách", "cà phê"],
            "available_times": ["tối thứ 7", "chủ nhật"],
        })
        assert updated.status_code == 200
        suggestions = client.get("/api/v1/discover", headers=headers).json()["items"]
        assert suggestions and suggestions[0]["score"] >= suggestions[-1]["score"]
        interested = {"Lan", "Nhung", "Kiên", "Hoàng", "Đức Minh", "Trang", "Bích Ngọc", "Mai Phương", "Quỳnh Như", "Minh Trí",
                      "Quang Huy", "Thủy Tiên", "Ngọc Mai", "Hà Phương", "Gia Hân", "Minh Quân", "Văn Long", "Ngọc Hân"}
        target = next(item for item in suggestions if item["name"] in interested)
        swipe = client.post("/api/v1/interactions", headers=headers, json={
            "target_user_id": target["user_id"], "action": "like",
        })
        assert swipe.json()["is_match"] is True
        match_id = swipe.json()["match_id"]
        message = client.post(f"/api/v1/matches/{match_id}/messages", headers=headers, json={"content": "Xin chào!"})
        assert message.status_code == 201
        token = headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/api/v1/ws?token={token}") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            realtime_message = client.post(
                f"/api/v1/matches/{match_id}/messages", headers=headers, json={"content": "Tin nhắn realtime"}
            )
            assert realtime_message.status_code == 201
            event = websocket.receive_json()
            assert event["type"] == "message"
            assert event["match_id"] == match_id
        unsafe_message = client.post(
            f"/api/v1/matches/{match_id}/messages",
            headers=headers,
            json={"content": "Gọi cho mình theo số 0912345678"},
        )
        assert unsafe_message.status_code == 422
        agent = client.post("/api/v1/agent/chat", headers=headers, json={"message": "Gợi ý cách bắt chuyện"})
        assert agent.status_code == 200
        assert agent.json()["intent"] == "conversation"
        assert agent.json()["tool_result"]["matched_people"]

        profile_agent = client.post(
            "/api/v1/agent/chat",
            headers=headers,
            json={"message": "Hồ sơ của tôi còn thiếu gì?", "session_id": "profile-check"},
        )
        assert profile_agent.status_code == 200
        assert profile_agent.json()["intent"] == "profile"
        assert profile_agent.json()["tool_result"]["completeness"] == 100

        safety_agent = client.post(
            "/api/v1/agent/chat",
            headers=headers,
            json={"message": "Tôi muốn báo cáo tài khoản lừa đảo", "session_id": "safety-check"},
        )
        assert safety_agent.status_code == 200
        assert safety_agent.json()["intent"] == "safety"

        history = client.get("/api/v1/agent/history?session_id=profile-check", headers=headers)
        assert [item["role"] for item in history.json()["items"]] == ["user", "assistant"]

        status = client.get("/api/v1/agent/status")
        assert status.json()["engine"] == "LangGraph"

        avatar = client.post(
            "/api/v1/profiles/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\nexample", "image/png")},
        )
        assert avatar.status_code == 201
        assert avatar.json()["avatar_url"].startswith("/uploads/avatar-")

        report = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"user_id": target["user_id"], "reason": "other", "details": "Test report"},
        )
        assert report.status_code == 201
        assert report.json()["status"] == "pending"

        blocked = client.post("/api/v1/blocks", headers=headers, json={"user_id": target["user_id"]})
        assert blocked.status_code == 201
        assert client.get("/api/v1/blocks", headers=headers).json()["count"] == 1
        assert all(
            item["user_id"] != target["user_id"]
            for item in client.get("/api/v1/discover?refresh=true", headers=headers).json()["items"]
        )
