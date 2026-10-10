from datetime import date

from ..onboarding.contracts import LearnerProfile
from .availability import DEFAULT_REFERENCE_WEEK
from .config import DEFAULT_CONFIG, MatchingConfig
from .contracts import MatchResult
from .explanations import explain
from .filters import RejectionReason, rejection_reasons
from .scoring import match_level, score_pair


def result_for(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG,
               reference_week: date = DEFAULT_REFERENCE_WEEK) -> MatchResult:
    total, components, facts = score_pair(a, b, config, reference_week)
    level = match_level(components.reciprocal_complementarity, components.concept_overlap, facts.same_stated_goal)
    return MatchResult(candidate_user_id=b.user_id, total_score=total,
                       reciprocal_score=components.reciprocal_complementarity, component_scores=components,
                       match_level=level, facts=facts, explanation=explain(facts, level))


def ranking_key(result: MatchResult) -> tuple[float, float, float, int]:
    return (-result.total_score, -result.reciprocal_score,
            -result.component_scores.availability_overlap, result.candidate_user_id)


def rank_candidates(a: LearnerProfile, candidates: list[LearnerProfile], config: MatchingConfig = DEFAULT_CONFIG,
                    reference_week: date = DEFAULT_REFERENCE_WEEK) -> tuple[list[MatchResult], dict[int, list[RejectionReason]]]:
    results, rejected = [], {}
    seen: set[int] = set()
    for b in candidates:
        if b.user_id in seen:
            raise ValueError("Duplicate candidate IDs")
        seen.add(b.user_id)
        reasons = rejection_reasons(a, b, config, reference_week)
        if reasons:
            rejected[b.user_id] = reasons
        else:
            results.append(result_for(a, b, config, reference_week))
    return sorted(results, key=ranking_key)[:config.candidate_limit], rejected
