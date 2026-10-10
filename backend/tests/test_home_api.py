"""Trang Tổng quan và thông báo: số liệu thật, các bước bắt đầu, chuông thông báo."""

from app.db import database
from checkin_helpers import LAN, MINH, STRANGER, auth, client, new_id, post_photo, vision_env

__all__ = ["client", "vision_env"]  # fixture dùng chung


def test_home_requires_auth(client):
    assert client.get("/api/v1/home").status_code == 401


def test_home_for_user_without_pair(client):
    h = client.get("/api/v1/home", headers=auth(STRANGER)).json()
    assert h["pair"] is None and h["display_name"] == "Khách"
    steps = {s["key"]: s["done"] for s in h["steps"]}
    assert steps == {"profile": False, "connect": False, "plan": False, "checkin": False}
    assert h["plan"]["has_plan"] is False and h["checkin"]["streak"] == 0


def test_home_reflects_plan_and_checkin(client):
    before = client.get("/api/v1/home", headers=auth(MINH)).json()
    assert before["pair"]["partner_name"] == "Lan"
    assert before["plan"]["has_plan"] and before["plan"]["next"]
    assert {s["key"]: s["done"] for s in before["steps"]}["checkin"] is False
    post_photo(client, MINH, note="làm bài join")
    after = client.get("/api/v1/home", headers=auth(MINH)).json()
    assert after["checkin"]["checked_in_today"] and after["checkin"]["total_done"] == 1
    assert {s["key"]: s["done"] for s in after["steps"]}["checkin"] is True
    lan = client.get("/api/v1/home", headers=auth(LAN)).json()
    assert lan["checkin"]["partner_checked_in_today"] and lan["checkin"]["partner_latest"]
    assert lan["unread"] >= 1 and lan["activity"][0]["kind"] == "checkin"


def test_notifications_flow(client):
    cid, _ = post_photo(client, MINH, note="join")
    client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(LAN), json={"emoji": "🔥"})
    client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(LAN), json={"comment": "Giỏi quá"})
    n = client.get("/api/v1/notifications", headers=auth(MINH)).json()
    kinds = [i["kind"] for i in n["items"]]
    assert "reaction" in kinds and "comment" in kinds and n["unread"] == 2
    assert client.post("/api/v1/notifications/read", headers=auth(MINH), json={}).json()["unread"] == 0
    # không đọc được thông báo của người khác
    assert all(i["kind"] != "reaction" for i in client.get("/api/v1/notifications", headers=auth(STRANGER)).json()["items"])


def test_connection_request_and_accept_notify(client):
    with database() as db:
        db.execute("DELETE FROM notifications")
    r = client.post("/api/v1/connections", headers=auth(STRANGER), json={"recipient_id": MINH})
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/notifications", headers=auth(MINH)).json()["items"][0]["kind"] == "connection_request"
    client.post(f"/api/v1/connections/{r.json()['id']}/accept", headers=auth(MINH))
    items = client.get("/api/v1/notifications", headers=auth(STRANGER)).json()["items"]
    assert items[0]["kind"] == "connection_accepted"


def test_nudge_creates_notification(client, monkeypatch):
    from app.checkin import service

    monkeypatch.setattr(service, "in_quiet_hours", lambda *a, **k: False)
    client.post("/api/v1/pairs/1/nudge", headers=auth(LAN))
    assert client.get("/api/v1/notifications", headers=auth(MINH)).json()["items"][0]["kind"] == "nudge"
    assert new_id()  # giữ import dùng chung
