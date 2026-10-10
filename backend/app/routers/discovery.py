import json

from fastapi import APIRouter, Depends, HTTPException, Query

from ..cache import cache
from ..db import database
from ..enums import Role
from ..security import current_user
from ..services.matching import score_profiles

router = APIRouter(tags=["discovery"])


@router.get("/discover")
def discover(
    limit: int = Query(default=12, ge=1, le=50),
    refresh: bool = False,
    user: dict = Depends(current_user),
) -> dict:
    if str(user.get("role")) != Role.STUDENT.value:
        raise HTTPException(status_code=403, detail="Only students can discover peers")
    key = f"discover:{user['id']}:{limit}"
    if not refresh and (cached := cache.get(key)) is not None:
        return cached
    with database() as connection:
        viewer_row = connection.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],)).fetchone()
        rows = connection.execute(
            """SELECT p.*, u.simulated_interest FROM profiles p
               JOIN users u ON u.id = p.user_id
               WHERE u.role = 'STUDENT' AND p.user_id != ? AND p.user_id NOT IN (
                   SELECT target_id FROM swipes WHERE actor_id = ?
               ) AND p.user_id NOT IN (
                   SELECT blocked_id FROM blocks WHERE blocker_id = ?
                   UNION SELECT blocker_id FROM blocks WHERE blocked_id = ?
               )""",
            (user["id"], user["id"], user["id"], user["id"]),
        ).fetchall()
    if viewer_row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    viewer = dict(viewer_row)
    suggestions = []
    for row in rows:
        candidate = dict(row)
        score, reasons = score_profiles(viewer, candidate)
        suggestions.append({
            "user_id": candidate["user_id"],
            "name": candidate["display_name"],
            "age": candidate["age"],
            "city": candidate["city"],
            "occupation": candidate["occupation"],
            "bio": candidate["bio"],
            "intent": candidate["intent"],
            "interests": json.loads(candidate["interests"]),
            "available_times": json.loads(candidate["available_times"]),
            "avatar_style": candidate["avatar_style"],
            "avatar_url": candidate["avatar_url"],
            "score": score,
            "reasons": reasons,
        })
    suggestions.sort(key=lambda item: (-item["score"], item["user_id"]))
    result = {"items": suggestions[:limit], "count": min(len(suggestions), limit)}
    cache.set(key, result)
    return result
