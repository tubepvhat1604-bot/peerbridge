"""Fixture cho test check-in: DB tạm, một cặp học (Data 1), plan ACTIVE (Data 2), AI giả."""

import datetime as dt
import io
import uuid

import pytest
from app.agents.plan_coach.contract import ItemStatus, PersonalPlan, PlanItem
from app.db import database, init_db
from app.security import create_token
from PIL import Image, ImageDraw

MINH, LAN, STRANGER, PAIR = 101, 102, 103, 1
NOW = dt.datetime.now(dt.UTC)


def png(w=800, h=600, text="SELECT * FROM a LEFT JOIN b") -> bytes:
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 20), text, fill="black")
    for i in range(0, w, 7):
        d.line([(i, 100), (i, h - 100)], fill=(i % 255, 40, 90))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def new_id() -> str:
    return str(uuid.uuid4())


def auth(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _item(uid, concept, action, start, item_id):
    return PlanItem(
        id=item_id, user_id=uid, pair_id=PAIR, plan_version=1, status=ItemStatus.SCHEDULED, concept_id=concept,
        action=action, expected_output="Bài làm chạy đúng", est_minutes=45,
        scheduled_start=start, scheduled_end=start + dt.timedelta(minutes=45),
        if_then_text=f"Nếu 19:00 ở thư viện thì {action.lower()}",
    )


PLAN = {
    MINH: [
        ("sql.join", "Làm 5 bài INNER JOIN trên SQLBolt", -1, "minh-join"),
        ("sql.group_by", "Viết 3 truy vấn GROUP BY", -2, "minh-groupby"),
        ("py.basic", "Ôn biến và vòng lặp Python", 2, "minh-future"),
    ],
    LAN: [("py.lists", "Làm bài list comprehension", -1, "lan-lists")],
}


def seed():
    created = NOW.isoformat()
    with database() as db:
        for uid, name in ((MINH, "Minh"), (LAN, "Lan"), (STRANGER, "Khách")):
            db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES (?,?,?,?)",
                       (uid, f"vision{uid}@example.test", "unused", created))
            db.execute("INSERT INTO profiles(user_id,display_name,age,intent,learning_goals,updated_at) VALUES (?,?,22,'conversation','[]',?)",
                       (uid, name, created))
        db.execute("INSERT INTO connection_requests(id,requester_id,recipient_id,status,created_at) VALUES (?,?,?,'MATCHED',?)",
                   (PAIR, MINH, LAN, created))
        db.execute("INSERT INTO peer_matches(id,connection_request_id,user_a_id,user_b_id,created_at) VALUES (?,?,?,?,?)",
                   (PAIR, PAIR, MINH, LAN, created))
        db.execute("""INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status)
                      VALUES (?,?,?,'complementary','fixture','{}','{}','invitation',?,'active')""", (PAIR, MINH, LAN, created))
        db.executemany("INSERT INTO pair_memberships(user_id,pair_id) VALUES (?,?)", [(MINH, PAIR), (LAN, PAIR)])
        # Lan mạnh JOIN -> câu cầu nối khi Minh check-in JOIN.
        db.execute("INSERT INTO user_concepts(user_id,concept_id,role,self_level,theta) VALUES (?,?,'offer','strong',0.8)",
                   (LAN, "sql.join"))
        for uid, rows in PLAN.items():
            items = [_item(uid, c, a, NOW + dt.timedelta(days=d), i) for c, a, d, i in rows]
            plan = PersonalPlan(user_id=uid, pair_id=PAIR, plan_version=1, items=items)
            db.execute("INSERT INTO pb_plans(pair_id,user_id,version,status,payload,context,created_at) VALUES (?,?,1,'ACTIVE',?,'{}',?)",
                       (PAIR, uid, plan.model_dump_json(), created))
            db.executemany("INSERT INTO pb_plan_items(id,pair_id,user_id,concept_id) VALUES (?,?,?,?)",
                           [(i.id, PAIR, uid, i.concept_id) for i in items])


def completed_items() -> dict[str, str | None]:
    with database() as db:
        return {r["id"]: r["completed_at"] for r in db.execute("SELECT id, completed_at FROM pb_plan_items")}


@pytest.fixture
def vision_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "vision.db"))
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    monkeypatch.setenv("JWT_SECRET", "vision-tests-only")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "10000")
    monkeypatch.setenv("VISION_LLM_PROVIDER", "fake")
    monkeypatch.setenv("VISION_LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("VISION_STORAGE_DIR", str(tmp_path / "checkin_images"))
    from app.checkin import config, llm, notify, storage
    from app.config import get_settings

    for cached in (get_settings, config.get_settings, storage.get_storage, llm.get_llm):
        cached.cache_clear()
    notify.clear_sent()
    yield tmp_path
    for cached in (get_settings, config.get_settings, storage.get_storage, llm.get_llm):
        cached.cache_clear()


@pytest.fixture
def client(vision_env):
    from app.main import app
    from fastapi.testclient import TestClient

    init_db()
    seed()
    with TestClient(app) as c:
        yield c


def post_photo(client, uid, note=None, cid=None):
    cid = cid or new_id()
    data = {"id": cid}
    if note:
        data["note"] = note
    r = client.post("/api/v1/checkins", headers=auth(uid), data=data, files={"image": ("a.png", png(), "image/png")})
    return cid, r
