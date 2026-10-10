import json
from typing import Any

from ..db import database
from ..services.matching import score_profiles


def _decode_profile(row) -> dict[str, Any]:
    profile = dict(row)
    profile["interests"] = json.loads(profile.get("interests") or "[]")
    profile["available_times"] = json.loads(profile.get("available_times") or "[]")
    return profile


def get_profile_context(user_id: int) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return _decode_profile(row) if row else {}


def inspect_profile(profile: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for field, label in (
        ("occupation", "nghề nghiệp"),
        ("bio", "giới thiệu"),
        ("interests", "sở thích"),
        ("available_times", "lịch rảnh"),
    ):
        if not profile.get(field):
            missing.append(label)
    completeness = round((4 - len(missing)) / 4 * 100)
    return {"completeness": completeness, "missing": missing, "intent": profile.get("intent")}


def find_recommendations(user_id: int, profile: dict[str, Any], limit: int = 3) -> dict[str, Any]:
    viewer = dict(profile)
    viewer["interests"] = json.dumps(viewer.get("interests", []), ensure_ascii=False)
    viewer["available_times"] = json.dumps(viewer.get("available_times", []), ensure_ascii=False)
    with database() as connection:
        match_count = connection.execute(
            "SELECT COUNT(*) FROM matches WHERE user_a_id=? OR user_b_id=?", (user_id, user_id)
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT p.* FROM profiles p WHERE p.user_id != ?
               AND p.user_id NOT IN (SELECT target_id FROM swipes WHERE actor_id=?)""",
            (user_id, user_id),
        ).fetchall()
    items = []
    for row in rows:
        candidate = dict(row)
        score, reasons = score_profiles(viewer, candidate)
        items.append({"name": candidate["display_name"], "score": score, "reasons": reasons})
    items.sort(key=lambda item: -item["score"])
    return {"match_count": match_count, "recommendations": items[:limit]}


def conversation_context(user_id: int) -> dict[str, Any]:
    with database() as connection:
        rows = connection.execute(
            """SELECT p.display_name AS name, p.bio, p.interests
               FROM matches m JOIN profiles p
                 ON p.user_id=CASE WHEN m.user_a_id=? THEN m.user_b_id ELSE m.user_a_id END
               WHERE m.user_a_id=? OR m.user_b_id=? ORDER BY m.id DESC LIMIT 3""",
            (user_id, user_id, user_id),
        ).fetchall()
    people = []
    for row in rows:
        person = dict(row)
        person["interests"] = json.loads(person["interests"] or "[]")
        people.append(person)
    return {"matched_people": people}


def safety_guidance() -> dict[str, Any]:
    return {
        "steps": [
            "Dừng chia sẻ thông tin cá nhân và tiền bạc",
            "Chụp lại bằng chứng liên quan",
            "Chặn và báo cáo tài khoản",
            "Liên hệ cơ quan chức năng nếu có nguy hiểm trực tiếp",
        ],
        "urgent_note": "Bản demo không có đội kiểm duyệt trực 24/7.",
    }

