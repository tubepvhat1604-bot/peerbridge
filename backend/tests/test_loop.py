"""Vòng AI: check-in → Data 1 đo tiến độ → coach đọc số đo → thông báo trong app."""

from app.db import database
from checkin_helpers import LAN, MINH, PAIR, STRANGER, auth, client, post_photo, vision_env

__all__ = ["client", "vision_env"]  # fixture dùng chung


def metric_rows(pair_id=PAIR):
    with database() as db:
        return db.execute("SELECT pacing_a, pacing_b, pair_score FROM pair_metrics_daily WHERE pair_id=?", (pair_id,)).fetchall()


def test_checkin_triggers_measurement(client):
    assert metric_rows() == []
    cid, _ = post_photo(client, MINH, note="làm bài join")
    rows = metric_rows()
    assert len(rows) == 1
    assert rows[0]["pacing_a"] > 0  # Minh (user_a) đã xong một việc đến hạn


def test_home_shows_pair_progress(client):
    post_photo(client, MINH, note="làm bài join")
    h = client.get("/api/v1/home", headers=auth(MINH)).json()
    p = h["progress"]
    assert p["available"] and p["me"]["completed_minutes"] == 45 and p["partner"]["completed_minutes"] == 0
    assert p["pair_score"] == 0 and p["needs_attention"] is True  # Lan chưa làm gì, cặp cần chú ý


def test_metrics_adapter_builds_coach_snapshot(client):
    from app.loop.coach_bridge import Data1MetricsAdapter

    post_photo(client, MINH, note="làm bài join")
    snap = Data1MetricsAdapter().load(PAIR)
    assert snap is not None and set(snap.plan_versions) == {MINH, LAN}
    assert snap.pacing[LAN] == 0 and snap.due_count[LAN] == 1
    assert snap.last_checkin[MINH] is not None and snap.last_checkin[LAN] is None
    assert snap.lagging_user_id == LAN


def test_connection_only_pair_becomes_data1_pair_on_activity(client):
    from app.loop.pairing import ensure_for_user

    with database() as db:
        db.execute("DELETE FROM pair_memberships")
        db.execute("DELETE FROM pairs")
    assert ensure_for_user(MINH) == PAIR
    with database() as db:
        assert db.execute("SELECT status, source FROM pairs WHERE id=?", (PAIR,)).fetchone()["status"] == "active"
        assert db.execute("SELECT COUNT(*) FROM pair_memberships WHERE pair_id=?", (PAIR,)).fetchone()[0] == 2
    assert ensure_for_user(STRANGER) is None  # chưa kết nối ai


def test_coach_notification_goes_to_bell(client):
    from app.loop.coach_bridge import InAppNotification

    assert InAppNotification().send(LAN, "Bạn đã vắng check-in hai ngày.", "missing-intervention") == "SENT"
    items = client.get("/api/v1/notifications", headers=auth(LAN)).json()["items"]
    assert items[0]["kind"] == "plan" and items[0]["title"].startswith("Coach")



def _daytime_zone() -> str:
    """Múi giờ đang ban ngày lúc chạy test, để coach không rơi vào giờ nghỉ 22:00–07:00 (test chạy được mọi lúc)."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    for zone in ("Asia/Ho_Chi_Minh", "Europe/London", "America/New_York", "Pacific/Auckland", "Asia/Tokyo",
                 "America/Los_Angeles", "Asia/Dubai", "Pacific/Honolulu", "Asia/Kolkata", "America/Sao_Paulo"):
        if 9 <= dt.datetime.now(ZoneInfo(zone)).hour <= 18:
            return zone
    return "Asia/Ho_Chi_Minh"


def test_full_loop_coach_intervenes_for_lagging_partner(client):
    """Kế hoạch thật của Data 2 (danh mục chuẩn Data 1) → Minh check-in, Lan không → coach can thiệp cho Lan."""
    import asyncio
    import datetime as dt
    from pathlib import Path

    from app.agents.plan_coach.contract import Availability, GenerateRequest, Member
    from app.agents.plan_coach.llm import PlanSettings
    from app.loop.coach_bridge import Data1MetricsAdapter, InAppNotification
    from app.loop.trigger import recompute
    from app.services.coach import CoachService
    from app.services.plans import PlanService

    catalog = Path(__file__).resolve().parents[1] / "data" / "concepts" / "plan_catalog.json"
    with database() as db:  # bỏ plan mẫu, tạo plan thật bằng PlanService
        for t in ("pb_plan_items", "pb_plans"):
            db.execute(f"DELETE FROM {t}")
    zone = _daytime_zone()
    windows = [Availability(id=f"w{d}", day_of_week=d, start_time="07:00", end_time="21:00") for d in range(7)]
    members = [
        Member(user_id=MINH, goal="Học SQL", concept_ids=["sql.join"], known_concept_ids=["sql.select_basic"],
               committed_minutes_per_week=600, availability=windows, timezone=zone),
        Member(user_id=LAN, goal="Học Python", concept_ids=["py.lists"], known_concept_ids=["py.basic", "py.variables"],
               committed_minutes_per_week=600, availability=windows, timezone=zone, can_help_concept_ids=[]),
    ]
    start = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
    settings = PlanSettings(_env_file=None, llm_provider="template", catalog_path=str(catalog), metrics_path=None)
    planner = PlanService(settings, clock=lambda: start)
    with database() as db:
        user = {k: db.execute("SELECT id, role, is_seed FROM users WHERE id=?", (k,)).fetchone() for k in (MINH, LAN)}
    asyncio.run(planner.generate(GenerateRequest(pair_id=PAIR, members=members, horizon_days=7), dict(user[MINH]), "k1"))

    # Minh làm và check-in một việc đã tới giờ; Lan không làm gì.
    cid, _ = post_photo(client, MINH, note="#low học bài")
    opts = client.get(f"/api/v1/checkins/{cid}", headers=auth(MINH)).json()["options"]
    assert opts, "phải có việc đã tới giờ để chọn"
    assert client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH),
                       json={"plan_item_id": opts[0]["plan_item_id"]}).json()["status"] == "done"
    assert recompute(PAIR)
    snap = Data1MetricsAdapter().load(PAIR)
    assert snap.pacing[LAN] == 0 and snap.pacing[MINH] > 0

    # Check-in của Minh đã tự chạy vòng AI: coach đã can thiệp cho Lan (đang chậm) và báo qua chuông.
    bell = client.get("/api/v1/notifications", headers=auth(LAN)).json()["items"]
    coach_notes = [i for i in bell if i["title"].startswith("Coach")]
    assert coach_notes, bell
    home = client.get("/api/v1/home", headers=auth(LAN)).json()
    assert home["coach"]["action"] in ("replan", "reminder", "offer_support") and home["coach"]["text"]
    assert home["progress"]["available"] and home["progress"]["i_am_lagging"]
    # Không nhắc hai lần một ngày.
    coach = CoachService(plans=PlanService(settings), metrics=Data1MetricsAdapter(), notification=InAppNotification())
    again = asyncio.run(coach.evaluate(PAIR, dict(user[LAN])))
    assert again["action"] == "no_action" and again["reason"] == "DAILY_LIMIT"


def test_fresh_plan_is_not_counted_as_behind(client):
    """Vừa lập plan xong: các việc chưa tới giờ kết thúc không bị tính là chậm, coach không nhắc ngay."""
    import asyncio
    import datetime as dt
    from pathlib import Path

    from app.agents.plan_coach.contract import Availability, GenerateRequest, Member
    from app.agents.plan_coach.llm import PlanSettings
    from app.loop.coach_bridge import Data1MetricsAdapter
    from app.loop.measurement import plan_workload
    from app.loop.trigger import recompute
    from app.services.plans import PlanService

    catalog = Path(__file__).resolve().parents[1] / "data" / "concepts" / "plan_catalog.json"
    with database() as db:
        for t in ("pb_plan_items", "pb_plans"):
            db.execute(f"DELETE FROM {t}")
    windows = [Availability(id=f"w{d}", day_of_week=d, start_time="00:00", end_time="23:59") for d in range(7)]
    members = [Member(user_id=u, goal="Học SQL", concept_ids=["sql.join"], known_concept_ids=["sql.select_basic"],
                      committed_minutes_per_week=600, availability=windows) for u in (MINH, LAN)]
    settings = PlanSettings(_env_file=None, llm_provider="template", catalog_path=str(catalog), metrics_path=None)
    with database() as db:
        user = dict(db.execute("SELECT id, role, is_seed FROM users WHERE id=?", (MINH,)).fetchone())
    asyncio.run(PlanService(settings).generate(GenerateRequest(pair_id=PAIR, members=members), user, "fresh"))

    now = dt.datetime.now(dt.UTC)
    items, _ = plan_workload(PAIR, (MINH, LAN), now)
    assert items == [] or all(i.completed_at for i in items)
    assert recompute(PAIR)
    snap = Data1MetricsAdapter().load(PAIR)
    assert snap.pacing == {MINH: None, LAN: None}
    home = client.get("/api/v1/home", headers=auth(LAN)).json()
    assert home["progress"]["available"] and not home["progress"]["needs_attention"]
