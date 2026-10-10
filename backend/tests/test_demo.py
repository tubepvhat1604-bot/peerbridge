from app.db import database
from checkin_helpers import client, vision_env

__all__ = ["client", "vision_env"]  # fixture dùng chung


def test_demo_off_by_default(client):
    assert client.get("/api/v1/demo").json()["enabled"] is False
    assert client.post("/api/v1/demo/login/lan").status_code == 404


def test_demo_accounts_match_each_other_among_sample_learners(client, monkeypatch):
    from app.demo import seed_demo

    monkeypatch.setenv("DEMO_MODE", "true")
    assert seed_demo() == 39  # 36 bạn học mẫu + Lan + Minh + Admin
    assert seed_demo() == 0  # chạy lại không tạo trùng
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE email LIKE '%@mau.peerbridge'").fetchone()[0] == 36

    lan = client.post("/api/v1/demo/login/lan").json()
    minh = client.post("/api/v1/demo/login/minh").json()
    token = lan["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    result = client.post("/api/v1/matches/search", headers=headers).json()
    assert 5 <= len(result["candidates"]) <= 15
    assert result["candidates"][0]["candidate_id"] == minh["user_id"]
    # Lan gửi lời mời cho Minh, Minh chấp nhận được.
    req = client.post("/api/v1/connections", headers=headers, json={"recipient_id": minh["user_id"]}).json()
    accepted = client.post(f"/api/v1/connections/{req['id']}/accept",
                           headers={"Authorization": f"Bearer {minh['access_token']}"})
    assert accepted.status_code == 200 and accepted.json()["peer_match_id"]
    assert client.get("/api/v1/home", headers=headers).json()["pair"]["partner_id"] == minh["user_id"]


def test_demo_plan_uses_slide_topics_and_has_work_today(client, monkeypatch):
    """Lan và Minh rảnh mọi ngày: kế hoạch có việc ngay hôm nay, nên check-in hôm nay làm số tiến độ nhảy."""
    from app.demo import seed_demo

    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PLAN_LLM_PROVIDER", "template")
    monkeypatch.setenv("PLAN_CATALOG_PATH", "data/concepts/plan_catalog.json")
    seed_demo()
    lan, minh = (client.post(f"/api/v1/demo/login/{s}").json() for s in ("lan", "minh"))
    h = {"Authorization": f"Bearer {lan['access_token']}"}
    req = client.post("/api/v1/connections", headers=h, json={"recipient_id": minh["user_id"]}).json()
    pair_id = client.post(f"/api/v1/connections/{req['id']}/accept",
                          headers={"Authorization": f"Bearer {minh['access_token']}"}).json()["peer_match_id"]

    setup = client.get(f"/api/v1/plans/{pair_id}/setup", headers=h).json()
    suggested = {m["user_id"]: m["suggested_concept_ids"] for m in setup["members"]}
    assert suggested[lan["user_id"]] == ["ai.rag_pipeline", "ai.data_foundations"]
    assert suggested[minh["user_id"]] == ["ai.prompt_tool_calling", "ai.react_agent"]
    members = [{
        "user_id": m["user_id"], "goal": "; ".join(m["goals"]), "concept_ids": m["suggested_concept_ids"],
        "known_concept_ids": [], "can_help_concept_ids": [], "committed_minutes_per_week": 240,
        "availability": [{"id": str(w["id"]), "day_of_week": w["day_of_week"], "start_time": w["start_time"][:5],
                          "end_time": w["end_time"][:5]} for w in m["availability"]],
        "timezone": "Asia/Ho_Chi_Minh", "location": "Góc học tập", "deadline": None,
    } for m in setup["members"]]
    created = client.post("/api/v1/plans/generate", headers={**h, "Idempotency-Key": "demo-plan"},
                          json={"pair_id": pair_id, "members": members, "horizon_days": 7})
    assert created.status_code == 201, created.text

    plan = client.get("/api/v1/home", headers=h).json()["plan"]
    from app.checkin.timeutil import now_utc, to_local

    hour = to_local(now_utc()).hour
    if 7 <= hour < 22:  # còn đủ giờ rảnh hôm nay để xếp một việc
        assert plan["today_total"] == 1 and plan["today_done"] == 0
    assert plan["week_total"] >= 1
    assert all(n["concept_id"].startswith("ai.") for n in plan["next"])
