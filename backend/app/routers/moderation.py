from fastapi import APIRouter, Depends, HTTPException

from ..cache import cache
from ..db import database, utc_now
from ..schemas import BlockRequest, ReportRequest
from ..security import current_user

router = APIRouter(tags=["safety"])


def _require_target(connection, target_id: int, user_id: int) -> None:
    if target_id == user_id:
        raise HTTPException(status_code=400, detail="Không thể thực hiện với chính mình")
    target = connection.execute("SELECT id FROM users WHERE id=?", (target_id,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")


@router.post("/blocks", status_code=201)
def block_user(payload: BlockRequest, user: dict = Depends(current_user)) -> dict:
    with database() as connection:
        _require_target(connection, payload.user_id, user["id"])
        connection.execute(
            "INSERT OR IGNORE INTO blocks(blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (user["id"], payload.user_id, utc_now()),
        )
        connection.execute(
            "DELETE FROM swipes WHERE (actor_id=? AND target_id=?) OR (actor_id=? AND target_id=?)",
            (user["id"], payload.user_id, payload.user_id, user["id"]),
        )
        connection.execute(
            "DELETE FROM matches WHERE (user_a_id=? AND user_b_id=?) OR (user_a_id=? AND user_b_id=?)",
            (user["id"], payload.user_id, payload.user_id, user["id"]),
        )
    cache.delete_prefix(f"discover:{user['id']}:")
    cache.delete_prefix(f"discover:{payload.user_id}:")
    return {"blocked_user_id": payload.user_id, "blocked": True}


@router.delete("/blocks/{blocked_user_id}")
def unblock_user(blocked_user_id: int, user: dict = Depends(current_user)) -> dict:
    with database() as connection:
        cursor = connection.execute(
            "DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (user["id"], blocked_user_id)
        )
    cache.delete_prefix(f"discover:{user['id']}:")
    return {"blocked_user_id": blocked_user_id, "blocked": False, "removed": cursor.rowcount > 0}


@router.get("/blocks")
def list_blocks(user: dict = Depends(current_user)) -> dict:
    with database() as connection:
        rows = connection.execute(
            """SELECT b.blocked_id AS user_id, p.display_name AS name, b.created_at
               FROM blocks b JOIN profiles p ON p.user_id=b.blocked_id
               WHERE b.blocker_id=? ORDER BY b.created_at DESC""",
            (user["id"],),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


@router.post("/reports", status_code=201)
def report_user(payload: ReportRequest, user: dict = Depends(current_user)) -> dict:
    with database() as connection:
        _require_target(connection, payload.user_id, user["id"])
        cursor = connection.execute(
            """INSERT INTO reports(reporter_id, reported_id, reason, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], payload.user_id, payload.reason, payload.details, utc_now()),
        )
    return {"report_id": cursor.lastrowid, "status": "pending"}
