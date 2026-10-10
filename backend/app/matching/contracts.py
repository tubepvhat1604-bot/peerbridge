from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from ..onboarding.contracts import StrictModel

MATCH_CONTRACT_VERSION = "data1.match.v1"
MatchLevel = Literal["same_outcome", "concept_overlap", "complementary", "shared_commitment"]
UnitScore = Annotated[float, Field(ge=0, le=1)]


class CommonSlot(StrictModel):
    starts_at: datetime
    ends_at: datetime


class Components(StrictModel):
    coverage_a_by_b: UnitScore
    coverage_b_by_a: UnitScore
    reciprocal_complementarity: UnitScore
    concept_overlap: UnitScore
    availability_overlap: UnitScore
    commitment_similarity: UnitScore


class ExplanationFacts(StrictModel):
    requester_user_id: int = Field(gt=0)
    candidate_user_id: int = Field(gt=0)
    requester_revision: int = Field(ge=1)
    candidate_revision: int = Field(ge=1)
    concepts_a_receives_from_b: list[str]
    concepts_b_receives_from_a: list[str]
    shared_learning_concepts: list[str]
    common_slots: list[CommonSlot]
    reference_week: date
    weekly_hours_a: float = Field(gt=0, le=168)
    weekly_hours_b: float = Field(gt=0, le=168)
    weekly_hours_ratio: float = Field(ge=1)
    deadline_difference_days: int | None = Field(default=None, ge=0)
    same_stated_goal: bool


class MatchResult(StrictModel):
    contract_version: str = MATCH_CONTRACT_VERSION
    candidate_user_id: int = Field(gt=0)
    total_score: UnitScore
    reciprocal_score: UnitScore
    component_scores: Components
    match_level: MatchLevel
    facts: ExplanationFacts
    explanation: str
    rerank_rating: int | None = Field(default=None, ge=1, le=5)


class RerankingMetadata(StrictModel):
    backend: str = "deterministic"
    status: Literal["disabled", "applied", "invalid_output", "provider_error", "timeout"] = "disabled"


class Pair(StrictModel):
    contract_version: str = MATCH_CONTRACT_VERSION
    id: int = Field(gt=0)
    peer_match_id: int = Field(gt=0)
    user_a: int = Field(gt=0)
    user_b: int = Field(gt=0)
    match_level: MatchLevel
    match_reason: str
    match_result: MatchResult
    reranking: RerankingMetadata = Field(default_factory=RerankingMetadata)
    source: Literal["automatic", "invitation"]
    started_at: datetime
    status: Literal["active", "ended"]
    ended_at: datetime | None = None


class MatchResponse(StrictModel):
    contract_version: str = MATCH_CONTRACT_VERSION
    status: Literal["waiting", "paired", "invite_suggested"]
    candidates: list[MatchResult] = Field(default_factory=list, max_length=5)
    reranking: RerankingMetadata = Field(default_factory=RerankingMetadata)
    waiting_since: datetime | None = None
    fallback_available_at: datetime | None = None
    fallback_actions: list[Literal["invite_friend", "manual_concierge"]] = Field(default_factory=list)
    pair: Pair | None = None


class InviteRequest(StrictModel):
    target_user_id: int | None = Field(default=None, gt=0)


class Invitation(StrictModel):
    contract_version: str = MATCH_CONTRACT_VERSION
    invitation_id: int = Field(gt=0)
    owner_user_id: int = Field(gt=0)
    target_user_id: int | None = None
    code: str
    join_path: str
    expires_at: datetime
