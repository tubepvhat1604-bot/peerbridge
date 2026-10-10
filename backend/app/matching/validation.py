"""Validate public claims against confirmed source profiles for evaluation/integration guards."""

from ..onboarding.contracts import LearnerProfile
from .config import DEFAULT_CONFIG, MatchingConfig
from .contracts import MatchResult
from .engine import result_for


def explanation_is_grounded(result: MatchResult, a: LearnerProfile, b: LearnerProfile,
                            config: MatchingConfig = DEFAULT_CONFIG) -> bool:
    if a.status != "confirmed" or b.status != "confirmed":
        return False
    expected = result_for(a, b, config, reference_week=result.facts.reference_week)
    # The authored renderer is the only accepted prose source. A candidate/slot/commitment/concept mutation fails closed.
    return (result.candidate_user_id == b.user_id and result.facts == expected.facts
            and result.explanation == expected.explanation and result.match_level == expected.match_level
            and result.component_scores == expected.component_scores
            and result.reciprocal_score == expected.reciprocal_score and result.total_score == expected.total_score)
