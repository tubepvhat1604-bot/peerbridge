"""Offline, reproducible matching regression evaluation. No database or provider calls."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.matching.engine import rank_candidates  # noqa: E402
from app.matching.validation import explanation_is_grounded  # noqa: E402
from app.onboarding.contracts import LearnerProfile, OnboardingInput, UserConcept  # noqa: E402

DATASET = Path(__file__).with_name("personas.json")


def load_personas(path: Path = DATASET) -> tuple[list[LearnerProfile], dict[int, set[int]]]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    profiles, labels = [], {}
    for persona in dataset["personas"]:
        group = dataset["groups"][persona["group"]]
        need, offer = group["concept_a"], group["concept_b"]
        if persona["orientation"] == "b":
            need, offer = offer, need
        user_id = persona["user_id"]
        if user_id in labels:
            raise ValueError("Duplicate persona ID")
        labels[user_id] = set(persona["relevant_partner_ids"])
        profiles.append(LearnerProfile(
            user_id=user_id, revision=1, status="confirmed", confirmed_at=datetime(2026, 10, 6, tzinfo=UTC),
            mappings=[], unmapped=[], onboarding=OnboardingInput(
                learning_goal=f"Practice {need} for an internship", committed_weekly_hours=persona["hours"],
                deadline=persona["deadline"], availability=[{
                    "day_of_week": day, "start_time": "19:00", "end_time": "20:00"} for day in group["days"]]),
            user_concepts=[UserConcept(user_id=user_id, concept_id=need, role="need", self_level="learning",
                                       theta=0, n_attempts=0),
                           UserConcept(user_id=user_id, concept_id=offer, role="offer", self_level="strong",
                                       theta=1, n_attempts=0)]))
    for user_id, partners in labels.items():
        if user_id in partners or not partners <= set(labels):
            raise ValueError("Invalid relevance label")
    return profiles, labels


def precision_at_k(predictions: list[int], relevant: set[int], k: int = 3) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(predictions[:k]) & relevant) / k


def evaluate() -> tuple[dict, list[dict]]:
    profiles, labels = load_personas()
    by_id = {p.user_id: p for p in profiles}
    precisions, reviews, factual_checks, failures = [], [], 0, 0
    for profile in profiles:
        ranked, _ = rank_candidates(profile, profiles)
        precisions.append(precision_at_k([r.candidate_user_id for r in ranked], labels[profile.user_id]))
        for rank, result in enumerate(ranked[:3]):
            partner = by_id[result.candidate_user_id]
            factual_checks += 1
            if not explanation_is_grounded(result, profile, partner):
                failures += 1
            # Twenty distinct source learners across all five groups, including both orientations.
            if rank == 0 and (profile.user_id - 1) % 6 < 4:
                def source(p: LearnerProfile) -> dict:
                    return {"user_id": p.user_id, "user_concepts": [c.model_dump() for c in p.user_concepts],
                            "availability": [s.model_dump(mode="json") for s in p.onboarding.availability],
                            "weekly_hours": p.onboarding.committed_weekly_hours,
                            "deadline": p.onboarding.deadline.isoformat() if p.onboarding.deadline else None}
                reviews.append({"review_id": len(reviews) + 1, "human_review": "PENDING",
                                "source_a": source(profile), "source_b": source(partner),
                                "result": result.model_dump(mode="json")})
    return {"dataset": "agent-authored synthetic regression fixtures", "personas": len(profiles),
            "precision_at_3": sum(precisions) / len(precisions), "target": .70,
            "automated_explanation_checks": factual_checks, "factuality_failures": failures,
            "manual_explanation_reviews": "PENDING (20 samples available)",
            "backend": "deterministic; no LLM or external calls"}, reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-artifact", type=Path, help="Write the 20 synthetic explanation samples for human review")
    args = parser.parse_args()
    report, reviews = evaluate()
    if args.review_artifact:
        args.review_artifact.write_text(json.dumps({"human_review_status": "PENDING", "samples": reviews},
                                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["precision_at_3"] >= report["target"] and not report["factuality_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
