"""Trang demo check-in, CHỈ bật khi APP_ENV=development.

Mở http://localhost:8000/checkin-demo: có sẵn hai bạn Minh và Lan đã ghép cặp, mỗi bạn có plan ACTIVE.
Thanh trên cùng đổi qua lại Minh/Lan (server cấp token cho đúng hai tài khoản demo này).
Nút "Làm lại dữ liệu demo" tạo plan mới và xóa check-in cũ của cặp demo.
"""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..agents.plan_coach.contract import ItemStatus, PersonalPlan, PlanItem
from ..db import database
from ..security import create_token
from .db import session_factory
from .models import Checkin

HERE = Path(__file__).parent / "demo_static"
DEMO_USERS = (("demo-minh@peerbridge.local", "Minh"), ("demo-lan@peerbridge.local", "Lan"))
# (concept, việc cần làm, lùi bao nhiêu giờ so với bây giờ; số âm = việc ở tương lai)
DEMO_PLAN = {
    "Minh": [
        ("sql.join", "Làm 5 bài INNER JOIN trên SQLBolt", 2),
        ("sql.left_join", "Viết 3 truy vấn LEFT JOIN có dòng NULL", 26),
        ("sql.group_by", "Viết 3 truy vấn GROUP BY tính tổng doanh thu", 50),
        ("sql.window_func", "Thử ROW_NUMBER() trên bảng orders", -24),
    ],
    "Lan": [
        ("py.lists", "Làm 10 bài list trên HackerRank", 3),
        ("py.for_loop", "Viết vòng lặp tính điểm trung bình lớp", 27),
        ("py.dictionaries", "Đếm số lần xuất hiện từ bằng dict", -24),
    ],
}
# Điểm mạnh để hiện câu cầu nối: Lan giỏi JOIN, Minh giỏi list.
DEMO_STRENGTHS = {"Lan": ["sql.join", "sql.left_join"], "Minh": ["py.lists"]}

router = APIRouter(include_in_schema=False)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _ensure_users(db) -> dict[str, int]:
    ids = {}
    for email, name in DEMO_USERS:
        row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            cur = db.execute(
                "INSERT INTO users(email,password_hash,created_at) VALUES (?,?,?)",
                (email, "demo-account-no-login", _now().isoformat()),
            )
            uid = cur.lastrowid
            db.execute(
                "INSERT INTO profiles(user_id,display_name,age,intent,learning_goals,updated_at) "
                "VALUES (?,?,21,'conversation','[\"SQL\",\"Python\"]',?)",
                (uid, name, _now().isoformat()),
            )
        else:
            uid = row["id"]
        ids[name] = uid
    return ids


def _ensure_pair(db, ids: dict[str, int]) -> int:
    a, b = sorted(ids.values())
    row = db.execute("SELECT id FROM peer_matches WHERE user_a_id=? AND user_b_id=?", (a, b)).fetchone()
    now = _now().isoformat()
    if row is None:
        req = db.execute(
            "INSERT INTO connection_requests(requester_id,recipient_id,status,created_at,responded_at) VALUES (?,?,'MATCHED',?,?)",
            (a, b, now, now),
        ).lastrowid
        pair_id = db.execute(
            "INSERT INTO peer_matches(connection_request_id,user_a_id,user_b_id,created_at) VALUES (?,?,?,?)",
            (req, a, b, now),
        ).lastrowid
    else:
        pair_id = row["id"]
    if db.execute("SELECT 1 FROM pairs WHERE id=?", (pair_id,)).fetchone() is None:
        db.execute(
            "INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status) "
            "VALUES (?,?,?,'complementary','Cặp demo','{}','{}','invitation',?,'active')",
            (pair_id, a, b, now),
        )
    for uid in (a, b):
        db.execute("INSERT OR REPLACE INTO pair_memberships(user_id,pair_id) VALUES (?,?)", (uid, pair_id))
    for name, concepts in DEMO_STRENGTHS.items():
        for concept in concepts:
            db.execute(
                "INSERT OR REPLACE INTO user_concepts(user_id,concept_id,role,self_level,theta) VALUES (?,?,'offer','strong',0.8)",
                (ids[name], concept),
            )
    return pair_id


def _new_plans(db, ids: dict[str, int], pair_id: int) -> None:
    now = _now()
    for name, rows in DEMO_PLAN.items():
        uid = ids[name]
        version = db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM pb_plans WHERE pair_id=? AND user_id=?", (pair_id, uid)
        ).fetchone()[0]
        items = []
        for concept, action, hours_ago in rows:
            start = now - dt.timedelta(hours=hours_ago)
            items.append(PlanItem(
                id=str(uuid.uuid4()), user_id=uid, pair_id=pair_id, plan_version=version, status=ItemStatus.SCHEDULED,
                concept_id=concept, action=action, expected_output="Bài làm chạy đúng", est_minutes=45,
                scheduled_start=start, scheduled_end=start + dt.timedelta(minutes=45),
                if_then_text=f"Nếu tới giờ học thì {action[:1].lower() + action[1:]}",
            ))
        plan = PersonalPlan(user_id=uid, pair_id=pair_id, plan_version=version, items=items)
        db.execute("UPDATE pb_plans SET status='SUPERSEDED' WHERE pair_id=? AND user_id=? AND status='ACTIVE'", (pair_id, uid))
        db.execute(
            "INSERT INTO pb_plans(pair_id,user_id,version,status,payload,context,created_at,accepted_at) "
            "VALUES (?,?,?,'ACTIVE',?,'{}',?,?)",
            (pair_id, uid, version, plan.model_dump_json(), now.isoformat(), now.isoformat()),
        )
        db.executemany(
            "INSERT INTO pb_plan_items(id,pair_id,user_id,concept_id) VALUES (?,?,?,?)",
            [(i.id, pair_id, uid, i.concept_id) for i in items],
        )


def seed_demo(reset: bool = False) -> dict[str, int]:
    with database() as db:
        ids = _ensure_users(db)
        pair_id = _ensure_pair(db, ids)
        has_plan = db.execute(
            "SELECT 1 FROM pb_plans WHERE pair_id=? AND status='ACTIVE'", (pair_id,)
        ).fetchone()
        if reset or not has_plan:
            _new_plans(db, ids, pair_id)
    if reset:
        with session_factory()() as s:
            for c in s.query(Checkin).filter(Checkin.pair_id == pair_id):
                s.delete(c)
            s.commit()
    return ids


@router.get("/checkin-demo")
def page():
    return FileResponse(HERE / "index.html")


@router.get("/checkin-demo/users")
def users():
    ids = seed_demo()
    return [{"id": uid, "name": name} for name, uid in ids.items()]


@router.post("/checkin-demo/token/{user_id}")
def token(user_id: int):
    if user_id not in seed_demo().values():
        raise HTTPException(404, "Chỉ cấp token cho tài khoản demo")
    return {"token": create_token(user_id)}


@router.post("/checkin-demo/reset")
def reset():
    seed_demo(reset=True)
    return {"message": "Đã làm lại dữ liệu demo"}


def mount_demo(app: FastAPI) -> None:
    app.include_router(router)
    app.mount("/checkin-demo/static", StaticFiles(directory=HERE), name="checkin-demo-static")
