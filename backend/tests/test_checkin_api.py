"""Luồng check-in end-to-end qua HTTP: cặp học của Data 1, plan của Data 2, AI giả."""

import datetime as dt

from app.checkin.db import session_factory
from app.checkin.models import Checkin, CheckinStatus
from app.checkin.notify import sent_messages
from app.checkin.service import pair_streak
from checkin_helpers import (
    LAN,
    MINH,
    PAIR,
    STRANGER,
    auth,
    client,
    completed_items,
    new_id,
    png,
    post_photo,
    vision_env,
)

__all__ = ["client", "vision_env"]  # fixture dùng chung


def get(client, cid, uid):
    return client.get(f"/api/v1/checkins/{cid}", headers=auth(uid))


def test_requires_auth(client):
    assert client.get("/api/v1/pairs/me/feed").status_code == 401


def test_photo_checkin_done_marks_data2_plan_and_notifies_partner(client):
    cid, r = post_photo(client, MINH, note="làm bài join")
    assert r.status_code == 202 and r.json()["status"] == "processing"
    c = get(client, cid, MINH).json()
    assert c["status"] == "done"
    assert c["plan_item_label"] == "Làm 5 bài inner join trên sqlbolt"
    assert c["bridge"]  # Lan mạnh sql.join
    assert completed_items()["minh-join"] is not None  # Data 2 đã ghi nhận
    assert sent_messages()[-1][0] == LAN and "Phần này bạn mạnh" in sent_messages()[-1][1]
    with session_factory()() as db:
        assert db.get(Checkin, cid).plan_version == 1


def test_idempotent_resend(client):
    cid, _ = post_photo(client, MINH, note="join")
    _, r2 = post_photo(client, MINH, cid=cid)
    assert r2.status_code == 202 and r2.json()["status"] == "done"


def test_same_id_other_user_conflict(client):
    cid, _ = post_photo(client, MINH)
    _, r = post_photo(client, LAN, cid=cid)
    assert r.status_code == 409


def test_low_confidence_then_confirm(client):
    cid, _ = post_photo(client, MINH, note="#low group by")
    c = get(client, cid, MINH).json()
    assert c["status"] == "needs_confirm" and c["options"]
    offered = {o["plan_item_id"] for o in c["options"]}
    assert "minh-future" not in offered  # việc chưa tới giờ không được đề xuất
    r = client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH), json={"plan_item_id": "minh-join"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert completed_items()["minh-join"] is not None
    with session_factory()() as db:
        assert db.get(Checkin, cid).user_corrected is True


def test_confirm_future_item_is_rejected_by_data2(client):
    cid, _ = post_photo(client, MINH, note="#low join")
    r = client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH), json={"plan_item_id": "minh-future"})
    assert r.status_code == 400
    assert completed_items()["minh-future"] is None


def test_cannot_confirm_partners_item(client):
    cid, _ = post_photo(client, MINH, note="#low join")
    r = client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH), json={"plan_item_id": "lan-lists"})
    assert r.status_code == 400


def test_failed_then_studied_something_else(client):
    cid = new_id()
    client.post("/api/v1/checkins/text", headers=auth(MINH), json={"id": cid, "note": "#fail học gì đó"})
    c = get(client, cid, MINH).json()
    assert c["status"] == "failed" and c["options"]
    r = client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH), json={"plan_item_id": None})
    assert r.json()["status"] == "done" and r.json()["plan_item_label"] is None


def test_not_study_and_override(client):
    cid = new_id()
    client.post("/api/v1/checkins/text", headers=auth(MINH), json={"id": cid, "note": "#notstudy ăn trưa"})
    assert get(client, cid, MINH).json()["status"] == "not_study"
    r = client.post(f"/api/v1/checkins/{cid}/confirm", headers=auth(MINH), json={"plan_item_id": None})
    assert r.json()["status"] == "done"


def test_user_without_pair_is_forbidden(client):
    _, r = post_photo(client, STRANGER)
    assert r.status_code == 403


def test_partner_visibility_and_media(client):
    cid = new_id()
    client.post("/api/v1/checkins/text", headers=auth(MINH), json={"id": cid, "note": "#fail"})
    assert get(client, cid, LAN).status_code == 404  # chưa done: partner không thấy
    cid2, _ = post_photo(client, MINH, note="join")
    assert get(client, cid2, LAN).status_code == 200
    assert get(client, cid2, STRANGER).status_code in (403, 404)
    url = get(client, cid2, MINH).json()["image_url"]
    assert url.startswith("/api/v1/checkins/media/")
    assert client.get(url).status_code == 200  # link ký dùng thẳng trong <img>
    assert client.get(url.replace("sig=", "sig=0")).status_code == 404  # sửa chữ ký
    bare = url.split("?")[0]
    assert client.get(bare).status_code == 401
    assert client.get(bare, headers=auth(MINH)).status_code == 200
    assert client.get(bare, headers=auth(LAN)).status_code == 200
    assert client.get(bare, headers=auth(STRANGER)).status_code == 404


def test_expired_media_link_is_rejected(client, monkeypatch):
    from app.checkin import storage

    cid, _ = post_photo(client, MINH, note="join")
    monkeypatch.setattr(storage, "URL_TTL_SECONDS", -10)
    url = get(client, cid, MINH).json()["image_url"]
    assert client.get(url).status_code == 404


def test_reactions_toggle_and_rules(client):
    cid, _ = post_photo(client, MINH, note="join")
    assert client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(MINH), json={"emoji": "🔥"}).status_code == 400
    r = client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(LAN), json={"emoji": "🔥"})
    assert len(r.json()["reactions"]) == 1
    r = client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(LAN), json={"emoji": "🔥"})
    assert len(r.json()["reactions"]) == 0  # bấm lại = bỏ
    assert client.post(f"/api/v1/checkins/{cid}/reactions", headers=auth(LAN), json={"emoji": "💩"}).status_code == 422


def test_feed_progress_and_streak(client):
    post_photo(client, MINH, note="join")
    f = client.get("/api/v1/pairs/me/feed", headers=auth(MINH)).json()
    assert f["pair_id"] == PAIR
    assert f["me"]["display_name"] == "Minh" and f["partner"]["display_name"] == "Lan"
    assert f["me"]["checked_in_today"] and not f["partner"]["checked_in_today"]
    assert f["me"]["pacing"] is not None
    assert f["partner_latest"] is None and f["my_latest"]["status"] == "done"


def test_nudge_cooldown_and_wrong_pair(client, monkeypatch):
    from app.checkin import service

    monkeypatch.setattr(service, "in_quiet_hours", lambda *a, **k: False)
    r = client.post(f"/api/v1/pairs/{PAIR}/nudge", headers=auth(LAN))  # Minh chưa check-in hôm nay
    assert r.status_code == 200, r.text
    r2 = client.post(f"/api/v1/pairs/{PAIR}/nudge", headers=auth(LAN))
    assert r2.status_code == 409 and "nhắc lại" in r2.json()["detail"]
    assert client.post("/api/v1/pairs/999/nudge", headers=auth(MINH)).status_code == 403


def test_daily_cap(client, monkeypatch):
    monkeypatch.setenv("VISION_MAX_CHECKINS_PER_DAY", "2")
    from app.checkin import config

    config.get_settings.cache_clear()
    post_photo(client, MINH)
    post_photo(client, MINH)
    _, r = post_photo(client, MINH)
    assert r.status_code == 429


def test_bad_image_and_bad_id(client):
    r = client.post("/api/v1/checkins", headers=auth(MINH), data={"id": new_id()},
                    files={"image": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    r = client.post("/api/v1/checkins", headers=auth(MINH), data={"id": "not-a-uuid"},
                    files={"image": ("a.png", png(), "image/png")})
    assert r.status_code == 400


def test_streak_logic(client):
    today = dt.date(2026, 10, 15)
    with session_factory()() as db:
        def add(uid, day):
            db.add(Checkin(id=new_id(), user_id=uid, pair_id=PAIR, kind="text", status=CheckinStatus.DONE, study_day=day))

        for back in (1, 2, 3):
            add(MINH, today - dt.timedelta(days=back))
            add(LAN, today - dt.timedelta(days=back))
        add(MINH, today - dt.timedelta(days=5))  # ngày 4 trống -> đứt chuỗi
        add(LAN, today - dt.timedelta(days=5))
        db.commit()
        assert pair_streak(db, MINH, LAN, today) == 3
        add(MINH, today)
        db.commit()
        assert pair_streak(db, MINH, LAN, today) == 3  # hôm nay mới một người
        add(LAN, today)
        db.commit()
        assert pair_streak(db, MINH, LAN, today) == 4


def test_connection_without_data1_pair_can_check_in(client):
    """Hai bạn chỉ bấm "Kết nối" (peer_matches), chưa ghép cặp kiểu Data 1: vẫn check-in được."""
    from app.db import database

    with database() as db:
        db.execute("DELETE FROM pair_memberships")
        db.execute("UPDATE pairs SET status='ended'")
    cid = new_id()
    r = client.post("/api/v1/checkins/text", headers=auth(MINH), json={"id": cid, "note": "làm bài join"})
    assert r.status_code == 202
    assert get(client, cid, MINH).json()["status"] == "done"
    assert client.get("/api/v1/pairs/me/feed", headers=auth(LAN)).json()["partner"]["display_name"] == "Minh"


def test_stats_summary(client):
    post_photo(client, MINH, note="join")
    post_photo(client, MINH, note="#low group by")
    s = client.get("/api/v1/checkins/stats", headers=auth(LAN)).json()
    assert s["total_checkins"] == 2 and s["by_status"]["done"] == 1 and s["by_status"]["needs_confirm"] == 1
    assert s["ai_accept_rate"] == 100.0 and s["ask_again_rate"] == 50.0
    assert s["per_day"] and "cost_today_usd" in s


def test_daily_budget_stops_ai_calls(client, monkeypatch):
    monkeypatch.setenv("VISION_DAILY_BUDGET_USD", "0")
    from app.checkin import config

    config.get_settings.cache_clear()
    cid, _ = post_photo(client, MINH, note="join")
    c = get(client, cid, MINH).json()
    assert c["status"] == "failed" and c["options"]  # không gọi AI, người dùng tự chọn mục
