from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..schemas import AvailabilityInput

CONTRACT_VERSION = "data1.v1"
CATALOG_VERSION = "2026-10-06.1"
Domain = Literal["sql", "python", "ai"]
ConceptRole = Literal["need", "offer"]
SelfLevel = Literal["unknown", "learning", "strong"]
INITIAL_THETA: dict[str, float] = {"unknown": -1.0, "learning": 0.0, "strong": 1.0}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Concept(StrictModel):
    id: str = Field(pattern=r"^(sql|py|ai)\.[a-z][a-z0-9_]*$")
    domain: Domain
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    prerequisites: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_identity(self) -> "Concept":
        prefix = {"sql": "sql.", "python": "py.", "ai": "ai."}[self.domain]
        if not self.id.startswith(prefix):
            raise ValueError("Concept ID prefix must agree with domain")
        if self.id in self.prerequisites:
            raise ValueError("A concept cannot require itself")
        if len(set(self.prerequisites)) != len(self.prerequisites):
            raise ValueError("Duplicate prerequisites")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("Aliases must not be blank")
        return self


class StudySlot(AvailabilityInput):
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Use a valid IANA timezone") from error
        return value


class TopicInput(StrictModel):
    text: str = Field(min_length=1, max_length=300)
    domain: Domain | None = None
    role: ConceptRole = "need"
    self_level: SelfLevel = "learning"

    @field_validator("self_level", mode="before")
    @classmethod
    def normalize_level(cls, value: str) -> str:
        aliases = {"chưa biết": "unknown", "đang học": "learning", "vững": "strong"}
        return aliases.get(str(value).strip().casefold(), str(value).strip().casefold())


class OnboardingInput(StrictModel):
    learning_goal: str = Field(min_length=1, max_length=1000)
    deadline: date | None = None
    topics: list[TopicInput] = Field(default_factory=list, max_length=60)
    availability: list[StudySlot] = Field(default_factory=list, max_length=30)
    committed_weekly_hours: float = Field(gt=0, le=168)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)
    conscientiousness: float | None = Field(default=None, ge=0, le=1)
    procrastination: float | None = Field(default=None, ge=0, le=1)
    communication_style: str = Field(default="", max_length=120)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return StudySlot.validate_timezone(value)


class Candidate(StrictModel):
    concept_id: str
    domain: Domain
    name: str
    description: str
    score: float = Field(ge=0, le=1)


class CandidateRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=300)
    domain: Domain
    top_k: int = Field(default=5, ge=1, le=5)


class MappingDecision(StrictModel):
    concept_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)


class TopicMapping(StrictModel):
    topic_index: int = Field(ge=0)
    topic: TopicInput
    resolved_domain: Domain | None
    concept_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str
    candidates: list[Candidate] = Field(default_factory=list, max_length=5)
    backend: str


class UserConceptInput(StrictModel):
    concept_id: str
    role: ConceptRole
    self_level: SelfLevel


class UserConcept(UserConceptInput):
    user_id: int = Field(gt=0)
    theta: float
    n_attempts: int = Field(ge=0)


class Selection(StrictModel):
    topic_index: int = Field(ge=0)
    concept_id: str | None
    self_level: SelfLevel | None = None


class ConfirmRequest(StrictModel):
    revision: int = Field(ge=1)
    selections: list[Selection] = Field(max_length=60)
    additional_concepts: list[UserConceptInput] = Field(default_factory=list, max_length=60)


class LearnerProfile(StrictModel):
    contract_version: str = CONTRACT_VERSION
    catalog_version: str = CATALOG_VERSION
    user_id: int = Field(gt=0)
    revision: int = Field(ge=1)
    status: Literal["draft", "confirmed"]
    onboarding: OnboardingInput
    mappings: list[TopicMapping]
    unmapped: list[TopicMapping]
    user_concepts: list[UserConcept] = Field(default_factory=list)
    confirmed_at: datetime | None = None


class CatalogResponse(StrictModel):
    contract_version: str = CONTRACT_VERSION
    catalog_version: str = CATALOG_VERSION
    concepts: list[Concept]


class CandidateResponse(StrictModel):
    contract_version: str = CONTRACT_VERSION
    catalog_version: str = CATALOG_VERSION
    backend: str
    candidates: list[Candidate]


class PairProfiles(StrictModel):
    contract_version: str = CONTRACT_VERSION
    pair_id: int
    user_a: LearnerProfile
    user_b: LearnerProfile
