from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import time
from typing import Any

from .matching_config import (
    DEFAULT_TOP_K,
    FEATURE_AVAILABILITY_OVERLAP,
    FEATURE_PREFERENCE_COMPATIBILITY,
    FEATURE_SKILL_COMPLEMENTARITY,
    FEATURE_TOPIC_COMPATIBILITY,
    MATCHING_WEIGHTS,
    MINUTES_PER_HOUR,
    SCORE_DECIMAL_PLACES,
    TOTAL_SCORE_MULTIPLIER,
)

ProfileBundle = Mapping[str, Any]
ComponentScores = dict[str, float]
MatchCandidateResult = dict[str, Any]
AvailabilityInterval = tuple[int, str, int, int]


def find_top_matches(
    requester: ProfileBundle,
    candidates: Iterable[ProfileBundle],
    top_k: int = DEFAULT_TOP_K,
) -> list[MatchCandidateResult]:
    if top_k <= 0:
        return []

    scored_candidates = [
        _score_candidate(requester, candidate)
        for candidate in load_candidates(candidates)
        if passes_hard_filters(requester, candidate)
    ]
    ranked_candidates = sorted(
        scored_candidates,
        key=lambda item: (
            -item["total_score"],
            -item["component_scores"][FEATURE_SKILL_COMPLEMENTARITY],
            -item["component_scores"][FEATURE_AVAILABILITY_OVERLAP],
            item["candidate_id"],
        ),
    )

    return [
        {
            **candidate,
            "rank": rank,
        }
        for rank, candidate in enumerate(ranked_candidates[:top_k], start=1)
    ]


def load_candidates(candidates: Iterable[ProfileBundle]) -> list[ProfileBundle]:
    return sorted(candidates, key=_user_id)


def passes_hard_filters(requester: ProfileBundle, candidate: ProfileBundle) -> bool:
    if _user_id(requester) == _user_id(candidate):
        return False
    return bool(_matching_skill_topics(requester, candidate) or (_topic_set(requester, "needs_help_with") & _topic_set(candidate, "needs_help_with")) or goal_similarity(requester, candidate) >= 0.2)


def calculate_component_scores(requester: ProfileBundle, candidate: ProfileBundle) -> ComponentScores:
    return {
        FEATURE_SKILL_COMPLEMENTARITY: calculate_skill_complementarity(requester, candidate),
        FEATURE_TOPIC_COMPATIBILITY: calculate_topic_compatibility(requester, candidate),
        FEATURE_AVAILABILITY_OVERLAP: calculate_availability_overlap(requester, candidate),
        FEATURE_PREFERENCE_COMPATIBILITY: calculate_preference_compatibility(requester, candidate),
    }


def calculate_skill_complementarity(requester: ProfileBundle, candidate: ProfileBundle) -> float:
    requester_need_topics = _topic_set(requester, "needs_help_with")
    if not requester_need_topics:
        return 0.0
    direct = len(_matching_skill_topics(requester, candidate)) / len(requester_need_topics)
    shared = len(requester_need_topics & _topic_set(candidate, "needs_help_with")) / len(requester_need_topics)
    return _round_score(max(direct, shared * 0.55))


def calculate_topic_compatibility(requester: ProfileBundle, candidate: ProfileBundle) -> float:
    mine = _topic_set(requester, "needs_help_with")
    theirs = _topic_set(candidate, "needs_help_with")
    union = mine | theirs
    shared = len(mine & theirs) / len(union) if union else 0
    return _round_score(max(shared, goal_similarity(requester, candidate)))


def calculate_availability_overlap(requester: ProfileBundle, candidate: ProfileBundle) -> float:
    requester_intervals = _merge_intervals(_availability_intervals(requester))
    candidate_intervals = _merge_intervals(_availability_intervals(candidate))
    requester_minutes = _total_minutes(requester_intervals)
    candidate_minutes = _total_minutes(candidate_intervals)
    if not requester_minutes or not candidate_minutes:
        return 0.0

    overlap_minutes = _overlap_minutes(requester_intervals, candidate_intervals)
    return _round_score(overlap_minutes / min(requester_minutes, candidate_minutes))


def calculate_preference_compatibility(requester: ProfileBundle, candidate: ProfileBundle) -> float:
    my_offers = _topic_set(requester, "can_help_with")
    their_needs = _topic_set(candidate, "needs_help_with")
    mutual = len(my_offers & their_needs) / len(their_needs) if their_needs else 0
    return _round_score(0.6 * goal_similarity(requester, candidate) + 0.4 * mutual)


def goal_similarity(requester: ProfileBundle, candidate: ProfileBundle) -> float:
    def terms(bundle):
        text = " ".join(_profile(bundle).get("learning_goals", []))
        words = set(re.findall(r"[a-z]+", _normalize_text(text)))
        return words - {"hoc", "trong", "tuan", "thang", "va", "de", "voi", "cua", "minh", "cho", "mot", "duoc", "ngay", "hoan", "thanh"}
    left, right = terms(requester), terms(candidate)
    return len(left & right) / len(left | right) if left or right else 0.0


def _score_candidate(requester: ProfileBundle, candidate: ProfileBundle) -> MatchCandidateResult:
    component_scores = calculate_component_scores(requester, candidate)
    weighted_score = sum(component_scores[feature] * weight for feature, weight in MATCHING_WEIGHTS.items())
    return {
        "candidate_id": _user_id(candidate),
        "total_score": _round_score(weighted_score * TOTAL_SCORE_MULTIPLIER),
        "component_scores": component_scores,
    }


def _user_id(bundle: ProfileBundle) -> int:
    profile = bundle.get("profile")
    if isinstance(profile, Mapping) and "user_id" in profile:
        return int(profile["user_id"])
    return int(bundle["user_id"])


def _items(bundle: ProfileBundle, key: str) -> list[Mapping[str, Any]]:
    values = bundle.get(key, [])
    if not isinstance(values, list | tuple):
        return []
    return [item for item in values if isinstance(item, Mapping)]


def _topic_set(bundle: ProfileBundle, key: str) -> set[str]:
    return {
        normalized
        for item in _items(bundle, key)
        if (normalized := _canonical_topic(item.get("topic", "")))
    }


def _matching_skill_topics(requester: ProfileBundle, candidate: ProfileBundle) -> set[str]:
    return _topic_set(requester, "needs_help_with") & _topic_set(candidate, "can_help_with")


def _profile(bundle: ProfileBundle) -> Mapping[str, Any]:
    profile = bundle.get("profile", {})
    return profile if isinstance(profile, Mapping) else {}


def _preference_terms(bundle: ProfileBundle) -> set[str]:
    profile = _profile(bundle)
    terms: set[str] = set()
    for field_name in ("subjects", "learning_goals", "interests"):
        values = profile.get(field_name, bundle.get(field_name, []))
        if not isinstance(values, list | tuple):
            continue
        terms.update(normalized for value in values if (normalized := _normalize_text(value)))
    return terms


def _availability_intervals(bundle: ProfileBundle) -> list[AvailabilityInterval]:
    intervals: list[AvailabilityInterval] = []
    for item in _items(bundle, "availability"):
        start_time = _parse_time(item.get("start_time"))
        end_time = _parse_time(item.get("end_time"))
        if start_time is None or end_time is None or end_time <= start_time:
            continue
        intervals.append(
            (
                int(item.get("day_of_week", 0)),
                str(item.get("timezone", "UTC")),
                _minutes_since_midnight(start_time),
                _minutes_since_midnight(end_time),
            )
        )
    return intervals


def _merge_intervals(intervals: list[AvailabilityInterval]) -> list[AvailabilityInterval]:
    merged: list[AvailabilityInterval] = []
    for day_of_week, timezone, start_minute, end_minute in sorted(intervals):
        if not merged:
            merged.append((day_of_week, timezone, start_minute, end_minute))
            continue

        last_day, last_timezone, last_start, last_end = merged[-1]
        if day_of_week == last_day and timezone == last_timezone and start_minute <= last_end:
            merged[-1] = (last_day, last_timezone, last_start, max(last_end, end_minute))
        else:
            merged.append((day_of_week, timezone, start_minute, end_minute))
    return merged


def _total_minutes(intervals: list[AvailabilityInterval]) -> int:
    return sum(end_minute - start_minute for _, _, start_minute, end_minute in intervals)


def _overlap_minutes(left: list[AvailabilityInterval], right: list[AvailabilityInterval]) -> int:
    total = 0
    right_by_key: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for day_of_week, timezone, start_minute, end_minute in right:
        right_by_key.setdefault((day_of_week, timezone), []).append((start_minute, end_minute))

    for day_of_week, timezone, left_start, left_end in left:
        for right_start, right_end in right_by_key.get((day_of_week, timezone), []):
            total += max(0, min(left_end, right_end) - max(left_start, right_start))
    return total


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None


def _minutes_since_midnight(value: time) -> int:
    return value.hour * MINUTES_PER_HOUR + value.minute


def _normalize_text(value: Any) -> str:
    normalized = "".join(c for c in unicodedata.normalize("NFKD", str(value)).casefold() if not unicodedata.combining(c)).replace("đ", "d").strip()
    return re.sub(r"\s+", " ", normalized)


def _round_score(value: float) -> float:
    return round(value, SCORE_DECIMAL_PLACES)


def _canonical_topic(value: Any) -> str:
    text = _normalize_text(value)
    aliases = {"english": ("tieng anh", "english", "ielts", "toeic"), "python": ("python",), "sql": ("sql", "co so du lieu"), "design": ("figma", "ui/ux", "thiet ke"), "marketing": ("marketing", "content"), "japanese": ("tieng nhat", "japanese", "jlpt")}
    for topic, names in aliases.items():
        if any(name in text for name in names):
            return topic
    return text
