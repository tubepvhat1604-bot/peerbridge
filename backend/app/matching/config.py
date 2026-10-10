from dataclasses import dataclass
from datetime import timedelta
from math import isfinite


@dataclass(frozen=True)
class MatchingConfig:
    complementarity_weight: float = 0.35
    concept_overlap_weight: float = 0.25
    availability_weight: float = 0.20
    commitment_weight: float = 0.20
    minimum_common_slots: int = 2
    maximum_deadline_days: int = 28
    maximum_hours_ratio: float = 2.0
    strength_theta: float = 0.5
    candidate_limit: int = 5
    minimum_match_score: float = 0.5
    wait_duration: timedelta = timedelta(hours=24)
    # MVP policy, not an invitation-expiry requirement stated in CONTEXT.
    invitation_lifetime: timedelta = timedelta(days=7)
    rerank_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        weights = (self.complementarity_weight, self.concept_overlap_weight,
                   self.availability_weight, self.commitment_weight)
        if any(not isfinite(w) or not 0 <= w <= 1 for w in weights) or abs(sum(weights) - 1) > 1e-12:
            raise ValueError("Matching weights must be finite, nonnegative and sum to one")
        if not 1 <= self.candidate_limit <= 5 or self.minimum_common_slots < 1:
            raise ValueError("Invalid slot or candidate limit")
        if self.maximum_deadline_days < 0 or not isfinite(self.maximum_hours_ratio) or self.maximum_hours_ratio < 1:
            raise ValueError("Invalid compatibility thresholds")
        if not isfinite(self.minimum_match_score) or not 0 <= self.minimum_match_score <= 1:
            raise ValueError("Invalid pairing threshold")
        if not isfinite(self.strength_theta):
            raise ValueError("Invalid theta threshold")
        if not isfinite(self.rerank_timeout_seconds) or self.rerank_timeout_seconds <= 0:
            raise ValueError("Invalid reranking timeout")
        if self.wait_duration.total_seconds() <= 0 or self.invitation_lifetime.total_seconds() <= 0:
            raise ValueError("Durations must be positive")


DEFAULT_CONFIG = MatchingConfig()
