from app.services.matching_config import (
    FEATURE_AVAILABILITY_OVERLAP,
    FEATURE_SKILL_COMPLEMENTARITY,
    FEATURE_TOPIC_COMPATIBILITY,
)
from app.services.matching_engine import (
    calculate_availability_overlap,
    calculate_skill_complementarity,
    find_top_matches,
)


def profile_bundle(
    user_id: int,
    *,
    needs: list[str] | None = None,
    offers: list[str] | None = None,
    availability: list[dict] | None = None,
    subjects: list[str] | None = None,
    learning_goals: list[str] | None = None,
) -> dict:
    return {
        "profile": {
            "user_id": user_id,
            "subjects": subjects or [],
            "learning_goals": learning_goals or [],
        },
        "needs_help_with": [{"topic": topic} for topic in needs or []],
        "can_help_with": [{"topic": topic} for topic in offers or []],
        "availability": availability or [],
    }


def window(day_of_week: int, start_time: str, end_time: str, timezone: str = "Asia/Bangkok") -> dict:
    return {
        "day_of_week": day_of_week,
        "start_time": start_time,
        "end_time": end_time,
        "timezone": timezone,
    }


def test_self_candidate_is_filtered_out() -> None:
    requester = profile_bundle(1, needs=["Python"])
    candidates = [
        profile_bundle(1, offers=["Python"]),
        profile_bundle(2, offers=["Python"]),
    ]

    results = find_top_matches(requester, candidates)

    assert [result["candidate_id"] for result in results] == [2]


def test_candidate_without_matching_skill_is_filtered_out() -> None:
    requester = profile_bundle(1, needs=["Python"])
    candidates = [profile_bundle(2, offers=["Calculus"])]

    assert find_top_matches(requester, candidates) == []


def test_skill_complementarity_is_requester_need_coverage() -> None:
    requester = profile_bundle(1, needs=["Python", "Calculus"])
    candidate = profile_bundle(2, offers=["python", "SQL"])

    assert calculate_skill_complementarity(requester, candidate) == 0.5


def test_availability_overlap_is_normalized_by_smaller_available_window() -> None:
    requester = profile_bundle(1, availability=[window(2, "09:00", "11:00")])
    candidate = profile_bundle(2, availability=[window(2, "10:00", "12:00")])

    assert calculate_availability_overlap(requester, candidate) == 0.5


def test_ranking_uses_weighted_score_and_deterministic_tie_breaking() -> None:
    requester = profile_bundle(
        1,
        needs=["Python", "Calculus"],
        availability=[window(2, "09:00", "11:00")],
        subjects=["Algorithms"],
    )
    candidates = [
        profile_bundle(4, offers=["Python"], availability=[window(2, "10:00", "11:00")]),
        profile_bundle(
            3,
            offers=["Python", "Calculus"],
            availability=[window(2, "09:00", "11:00")],
            subjects=["Algorithms"],
        ),
        profile_bundle(
            2,
            offers=["Python", "Calculus"],
            availability=[window(2, "09:00", "11:00")],
            subjects=["Algorithms"],
        ),
    ]

    results = find_top_matches(requester, candidates)

    assert [result["candidate_id"] for result in results] == [2, 3, 4]
    assert [result["rank"] for result in results] == [1, 2, 3]
    assert results[0]["total_score"] == results[1]["total_score"]
    assert results[1]["total_score"] > results[2]["total_score"]
    assert results[0]["component_scores"][FEATURE_SKILL_COMPLEMENTARITY] == 1.0
    # Bản UX/UI: điểm chủ đề = hai bạn cùng cần học một chủ đề hoặc mục tiêu giống nhau; ở đây bạn kia chỉ giúp.
    assert results[0]["component_scores"][FEATURE_TOPIC_COMPATIBILITY] == 0.0
    assert results[0]["component_scores"][FEATURE_AVAILABILITY_OVERLAP] == 1.0


def test_same_input_produces_same_result_independent_of_candidate_order() -> None:
    requester = profile_bundle(1, needs=["Python"], availability=[window(1, "09:00", "10:00")])
    candidates = [
        profile_bundle(3, offers=["Python"], availability=[window(1, "09:00", "10:00")]),
        profile_bundle(2, offers=["Python"], availability=[window(1, "09:00", "10:00")]),
    ]

    assert find_top_matches(requester, candidates) == find_top_matches(requester, list(reversed(candidates)))


def test_top_k_limits_ranked_results() -> None:
    requester = profile_bundle(1, needs=["Python"])
    candidates = [
        profile_bundle(2, offers=["Python"], subjects=["A"]),
        profile_bundle(3, offers=["Python"], subjects=["B"]),
        profile_bundle(4, offers=["Python"], subjects=["C"]),
    ]

    results = find_top_matches(requester, candidates, top_k=2)

    assert [result["candidate_id"] for result in results] == [2, 3]
    assert [result["rank"] for result in results] == [1, 2]
