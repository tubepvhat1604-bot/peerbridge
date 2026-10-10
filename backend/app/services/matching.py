import json
from typing import Any

INTENT_LABELS = {
    "serious": "cùng tìm mối quan hệ nghiêm túc",
    "friends": "cùng muốn tìm bạn mới",
    "conversation": "cùng ưu tiên trò chuyện sâu",
    "activity": "cùng muốn tìm người tham gia hoạt động",
}


def _set(value: str) -> set[str]:
    try:
        return {str(item).lower() for item in json.loads(value)}
    except (json.JSONDecodeError, TypeError):
        return set()


def score_profiles(viewer: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, list[str]]:
    score = 30
    reasons: list[str] = []

    if viewer["intent"] == candidate["intent"]:
        score += 25
        reasons.append(INTENT_LABELS.get(viewer["intent"], "cùng mục tiêu kết nối"))

    viewer_interests, candidate_interests = _set(viewer["interests"]), _set(candidate["interests"])
    shared_interests = sorted(viewer_interests & candidate_interests)
    score += min(25, len(shared_interests) * 7)
    if shared_interests:
        reasons.append("chung sở thích " + ", ".join(shared_interests[:3]))

    shared_times = sorted(_set(viewer["available_times"]) & _set(candidate["available_times"]))
    score += min(15, len(shared_times) * 6)
    if shared_times:
        reasons.append("lịch rảnh giao nhau: " + ", ".join(shared_times[:2]))

    if viewer["city"].casefold() == candidate["city"].casefold():
        score += 5
        reasons.append("cùng ở " + candidate["city"])

    score += max(0, 5 - abs(viewer["age"] - candidate["age"]))
    if not reasons:
        reasons.append("hồ sơ mới phù hợp để khám phá")
    return min(score, 99), reasons

