"""Trang demo check-in: tạo cặp Minh–Lan có plan, cấp token đúng tài khoản demo, làm lại dữ liệu."""

from checkin_helpers import new_id, vision_env

__all__ = ["vision_env"]  # fixture dùng chung


def test_demo_seed_token_checkin_and_reset(vision_env):
    from app.checkin.demo import mount_demo
    from app.db import init_db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    init_db()
    demo = FastAPI()
    mount_demo(demo)
    from app.main import app

    with TestClient(demo) as c, TestClient(app) as api:
        assert c.get("/checkin-demo").status_code == 200
        users = c.get("/checkin-demo/users").json()
        assert [u["name"] for u in users] == ["Minh", "Lan"]
        assert c.post("/checkin-demo/token/999999").status_code == 404
        token = c.post(f"/checkin-demo/token/{users[0]['id']}").json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        cid = new_id()
        api.post("/api/v1/checkins/text", headers=h, json={"id": cid, "note": "làm bài inner join"})
        assert api.get(f"/api/v1/checkins/{cid}", headers=h).json()["status"] == "done"
        assert c.post("/checkin-demo/reset").status_code == 200
        assert api.get(f"/api/v1/checkins/{cid}", headers=h).status_code == 404
        feed = api.get("/api/v1/pairs/me/feed", headers=h).json()
        assert feed["me"]["done_items"] == 0
