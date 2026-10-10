from datetime import date
from enum import StrEnum

from ..onboarding.contracts import LearnerProfile
from .availability import DEFAULT_REFERENCE_WEEK, common_slots
from .config import DEFAULT_CONFIG, MatchingConfig


class RejectionReason(StrEnum):
    SELF = "self"
    UNCONFIRMED = "unconfirmed_profile"
    SLOTS = "insufficient_common_slots"
    DEADLINE = "incompatible_deadlines"
    HOURS = "incompatible_weekly_hours"


def deadlines_compatible(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG) -> bool:
    left, right = a.onboarding.deadline, b.onboarding.deadline
    return left is None or right is None or abs((left - right).days) <= config.maximum_deadline_days


def hours_compatible(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG) -> bool:
    hours = (a.onboarding.committed_weekly_hours, b.onboarding.committed_weekly_hours)
    return max(hours) / min(hours) <= config.maximum_hours_ratio


def slots_compatible(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG,
                     reference_week: date = DEFAULT_REFERENCE_WEEK) -> bool:
    shared, _ = common_slots(a.onboarding.availability, b.onboarding.availability, reference_week)
    return len(shared) >= config.minimum_common_slots


def rejection_reasons(a: LearnerProfile, b: LearnerProfile, config: MatchingConfig = DEFAULT_CONFIG,
                      reference_week: date = DEFAULT_REFERENCE_WEEK) -> list[RejectionReason]:
    reasons = []
    if a.user_id == b.user_id:
        reasons.append(RejectionReason.SELF)
    if any(p.status != "confirmed" or p.confirmed_at is None for p in (a, b)):
        reasons.append(RejectionReason.UNCONFIRMED)
    if not slots_compatible(a, b, config, reference_week):
        reasons.append(RejectionReason.SLOTS)
    if not deadlines_compatible(a, b, config):
        reasons.append(RejectionReason.DEADLINE)
    if not hours_compatible(a, b, config):
        reasons.append(RejectionReason.HOURS)
    return reasons
