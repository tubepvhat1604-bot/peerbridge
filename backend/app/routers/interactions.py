from fastapi import APIRouter, Depends, HTTPException

from ..cache import cache
from ..db import database, utc_now
from ..schemas import SwipeRequest
from ..security import current_user

router = APIRouter(tags=["interactions"])


@router.post("/interactions")
def swipe(payload: SwipeRequest, user: dict = Depends(current_user)) -> dict:
    if payload.target_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Không thể tương tác với chính mình")
    with database() as connection:
        target = connection.execute(
            "SELECT id, simulated_interest FROM users WHERE id = ?", (payload.target_user_id,)
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
        blocked = connection.execute(
            """SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?)
               OR (blocker_id=? AND blocked_id=?)""",
            (user["id"], payload.target_user_id, payload.target_user_id, user["id"]),
        ).fetchone()
        if blocked:
            raise HTTPException(status_code=403, detail="Không thể tương tác với tài khoản này")
        connection.execute(
            """INSERT INTO swipes(actor_id, target_id, action, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(actor_id, target_id) DO UPDATE SET action=excluded.action, created_at=excluded.created_at""",
            (user["id"], payload.target_user_id, payload.action, utc_now()),
        )
        is_match = False
        match_id = None
        if payload.action == "like":
            reverse = connection.execute(
                "SELECT 1 FROM swipes WHERE actor_id=? AND target_id=? AND action='like'",
                (payload.target_user_id, user["id"]),
            ).fetchone()
            if reverse or target["simulated_interest"]:
                a, b = sorted((user["id"], payload.target_user_id))
                connection.execute(
                    "INSERT OR IGNORE INTO matches(user_a_id, user_b_id, created_at) VALUES (?, ?, ?)",
                    (a, b, utc_now()),
                )
                match = connection.execute(
                    "SELECT id FROM matches WHERE user_a_id=? AND user_b_id=?", (a, b)
                ).fetchone()
                is_match, match_id = True, match["id"]
    cache.delete_prefix(f"discover:{user['id']}:")
    return {"action": payload.action, "is_match": is_match, "match_id": match_id}


@router.get("/matches")
def matches(user: dict = Depends(current_user)) -> dict:
    from ..services.realtime import realtime

    with database() as connection:
        rows = connection.execute(
            """SELECT m.id AS match_id, m.created_at, p.user_id, p.display_name AS name,
                      p.age, p.city, p.occupation, p.avatar_style, p.avatar_url,
                      (SELECT content FROM messages WHERE match_id=m.id ORDER BY id DESC LIMIT 1) AS last_message,
                      (SELECT COUNT(*) FROM messages WHERE match_id=m.id AND sender_id!=? AND read_at IS NULL) AS unread_count
               FROM matches m JOIN profiles p
                 ON p.user_id = CASE WHEN m.user_a_id=? THEN m.user_b_id ELSE m.user_a_id END
               WHERE (m.user_a_id=? OR m.user_b_id=?)
                 AND NOT EXISTS (
                   SELECT 1 FROM blocks b WHERE
                   (b.blocker_id=m.user_a_id AND b.blocked_id=m.user_b_id)
                   OR (b.blocker_id=m.user_b_id AND b.blocked_id=m.user_a_id)
                 )
               ORDER BY m.id DESC""",
            (user["id"], user["id"], user["id"], user["id"]),
        ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["online"] = realtime.is_online(item["user_id"])
    return {"items": items, "count": len(items)}
