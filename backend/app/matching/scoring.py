from datetime import date
from math import isfinite
from unicodedata import normalize

from ..onboarding.catalog import get_concept
from ..onboarding.contracts import LearnerProfile
from .availability import DEFAULT_REFERENCE_WEEK, common_slots
from .config import DEFAULT_CONFIG, MatchingConfig
from .contracts import Components, ExplanationFacts, MatchLevel


def harmonic_mean(a: float, b: float) -> float:
    if any(not isfinite(value) or not 0 <= value <= 1 for value in (a, b)):
        raise ValueError("Coverage must be finite and between zero and one")
    return 0.0 if a + b == 0 else 2 * a * b / (a + b)


def concept_sets(profile: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG) -> tuple[set[str], set[str], set[str]]:
    needs, strengths, learning = set(), set(), set()
    for item in profile.user_concepts:
        get_concept(item.concept_id)
        if item.user_id != profile.user_id or not isfinite(item.theta):
            raise ValueError("Invalid concept ownership or theta")
        if item.role == "need":
            needs.add(item.concept_id)
        if item.role == "offer" and item.theta >= config.strength_theta:
            strengths.add(item.concept_id)
        if item.self_level == "learning":
            learning.add(item.concept_id)
    return needs, strengths, learning


def commitment_similarity(a: LearnerProfile, b: LearnerProfile) -> float:
    left, right = a.onboarding, b.onboarding
    values = [min(left.committed_weekly_hours, right.committed_weekly_hours)
              / max(left.committed_weekly_hours, right.committed_weekly_hours)]
    # CONTEXT names these inputs but does not prescribe a subformula. Unknown traits are omitted, never imputed.
    for field in ("conscientiousness", "procrastination"):
        x, y = getattr(left, field), getattr(right, field)
        if x is not None and y is not None:
            values.append(1 - abs(x - y))
    return sum(values) / len(values)


def same_goal(a: LearnerProfile, b: LearnerProfile) -> bool:
    def text(value: str) -> str:
        return " ".join(normalize("NFKC", value).casefold().split())
    return text(a.onboarding.learning_goal) == text(b.onboarding.learning_goal)


def match_level(reciprocal: float, overlap: float, same_stated_goal: bool) -> MatchLevel:
    if reciprocal > 0:
        return "complementary"
    if same_stated_goal:
        return "same_outcome"
    return "concept_overlap" if overlap > 0 else "shared_commitment"


def score_pair(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG,
               reference_week: date = DEFAULT_REFERENCE_WEEK) -> tuple[float, Components, ExplanationFacts]:
    needs_a, strengths_a, learning_a = concept_sets(a, config)
    needs_b, strengths_b, learning_b = concept_sets(b, config)
    receives_a = needs_a & strengths_b
    receives_b = needs_b & strengths_a
    coverage_a_by_b = len(receives_a) / len(needs_a) if needs_a else 0.0
    coverage_b_by_a = len(receives_b) / len(needs_b) if needs_b else 0.0
    reciprocal_complementarity = harmonic_mean(coverage_a_by_b, coverage_b_by_a)
    union = learning_a | learning_b
    concept_overlap = len(learning_a & learning_b) / len(union) if union else 0.0
    shared, fewer_slots = common_slots(a.onboarding.availability, b.onboarding.availability, reference_week)
    availability_overlap = len(shared) / fewer_slots if fewer_slots else 0.0
    commitment = commitment_similarity(a, b)
    components = Components(coverage_a_by_b=coverage_a_by_b, coverage_b_by_a=coverage_b_by_a,
                            reciprocal_complementarity=reciprocal_complementarity, concept_overlap=concept_overlap,
                            availability_overlap=availability_overlap, commitment_similarity=commitment)
    total = (config.complementarity_weight * reciprocal_complementarity
             + config.concept_overlap_weight * concept_overlap
             + config.availability_weight * availability_overlap + config.commitment_weight * commitment)
    hours_a, hours_b = a.onboarding.committed_weekly_hours, b.onboarding.committed_weekly_hours
    deadline_a, deadline_b = a.onboarding.deadline, b.onboarding.deadline
    facts = ExplanationFacts(
        requester_user_id=a.user_id, candidate_user_id=b.user_id,
        requester_revision=a.revision, candidate_revision=b.revision,
        concepts_a_receives_from_b=sorted(receives_a), concepts_b_receives_from_a=sorted(receives_b),
        shared_learning_concepts=sorted(learning_a & learning_b), common_slots=shared, reference_week=reference_week,
        weekly_hours_a=hours_a, weekly_hours_b=hours_b, weekly_hours_ratio=max(hours_a, hours_b) / min(hours_a, hours_b),
        deadline_difference_days=abs((deadline_a - deadline_b).days) if deadline_a and deadline_b else None,
        same_stated_goal=same_goal(a, b))
    return total, components, facts
