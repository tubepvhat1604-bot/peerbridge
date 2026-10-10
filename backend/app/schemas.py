import unicodedata
from datetime import datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ConnectionStatus, ModerationAction, ReviewAction, Role

Intent = Literal["serious", "friends", "conversation", "activity"]


def _validate_email(value: str) -> str:
    value = value.strip().lower()
    local, separator, domain = value.partition("@")
    if not separator or not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Email không hợp lệ")
    return value


def _normalize_items(values: list[str]) -> list[str]:
    cleaned = [unicodedata.normalize("NFC", value.strip()) for value in values if value.strip()]
    seen = set()
    return [v for v in cleaned if not (v.casefold() in seen or seen.add(v.casefold()))]


def _strip_required(value: str, field_name: str) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value


class User(BaseModel):
    id: int | None = Field(default=None, gt=0)
    email: str = Field(min_length=5, max_length=254)
    role: Role = Role.STUDENT
    is_active: bool = True
    created_at: datetime | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _validate_email(value)


class ProfileFields(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str = Field(default="", max_length=800)
    school: str = Field(default="", max_length=120)
    major: str = Field(default="", max_length=120)
    subjects: list[str] = Field(default_factory=list, max_length=20)
    learning_goals: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return _strip_required(value, "display_name")

    @field_validator("bio", "school", "major")
    @classmethod
    def strip_optional_text(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())

    @field_validator("subjects", "learning_goals")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_items(values)


class Profile(ProfileFields):
    user_id: int = Field(gt=0)


class ProfileInput(ProfileFields):
    model_config = ConfigDict(extra="forbid")


class HelpNeedFields(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    current_level: str = Field(default="", max_length=80)
    target_outcome: str = Field(default="", max_length=200)

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return _strip_required(value, "topic")

    @field_validator("description", "current_level", "target_outcome")
    @classmethod
    def strip_optional_text(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())


class HelpNeed(HelpNeedFields):
    id: int | None = Field(default=None, gt=0)
    user_id: int = Field(gt=0)


class HelpNeedInput(HelpNeedFields):
    model_config = ConfigDict(extra="forbid")


class HelpOfferFields(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    proficiency_level: str = Field(default="", max_length=80)
    max_sessions_per_week: int = Field(default=3, ge=1, le=20)

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return _strip_required(value, "topic")

    @field_validator("description", "proficiency_level")
    @classmethod
    def strip_optional_text(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())


class HelpOffer(HelpOfferFields):
    id: int | None = Field(default=None, gt=0)
    user_id: int = Field(gt=0)


class HelpOfferInput(HelpOfferFields):
    model_config = ConfigDict(extra="forbid")


class AvailabilityFields(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    timezone: str = Field(default="Asia/Bangkok", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def strip_timezone(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())

    @model_validator(mode="after")
    def validate_time_range(self) -> "AvailabilityFields":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class Availability(AvailabilityFields):
    id: int | None = Field(default=None, gt=0)
    user_id: int = Field(gt=0)


class AvailabilityInput(AvailabilityFields):
    model_config = ConfigDict(extra="forbid")


class ProfileMeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileInput
    needs_help_with: list[HelpNeedInput] = Field(default_factory=list, max_length=20)
    can_help_with: list[HelpOfferInput] = Field(default_factory=list, max_length=20)
    availability: list[AvailabilityInput] = Field(default_factory=list, max_length=30)


class ProfileMeResponse(BaseModel):
    profile: Profile
    needs_help_with: list[HelpNeed] = Field(default_factory=list)
    can_help_with: list[HelpOffer] = Field(default_factory=list)
    availability: list[Availability] = Field(default_factory=list)


class MatchCandidate(BaseModel):
    user_id: int = Field(gt=0)
    profile: Profile
    score: float = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("reasons")
    @classmethod
    def normalize_reasons(cls, values: list[str]) -> list[str]:
        return _normalize_items(values)


class MatchResult(BaseModel):
    request_id: int | None = Field(default=None, gt=0)
    candidates: list[MatchCandidate] = Field(default_factory=list, max_length=50)


class MatchSearchCandidate(BaseModel):
    request_id: int = Field(gt=0)
    candidate_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=80)
    school: str = Field(default="", max_length=120)
    major: str = Field(default="", max_length=120)
    total_score: float = Field(ge=0, le=100)
    component_scores: dict[str, float] = Field(default_factory=dict)
    rank: int = Field(ge=1)
    learning_goals: list[str] = Field(default_factory=list)
    bio: str = ""
    needs: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    availability: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class MatchSearchResponse(BaseModel):
    matching_mode: str = "local"
    request_id: int = Field(gt=0)
    candidates: list[MatchSearchCandidate] = Field(default_factory=list, max_length=15)


class ConnectionRequest(BaseModel):
    id: int | None = Field(default=None, gt=0)
    requester_id: int = Field(gt=0)
    recipient_id: int = Field(gt=0)
    status: ConnectionStatus = ConnectionStatus.PENDING
    created_at: datetime | None = None
    responded_at: datetime | None = None

    @model_validator(mode="after")
    def validate_participants(self) -> "ConnectionRequest":
        if self.requester_id == self.recipient_id:
            raise ValueError("requester_id and recipient_id must be different")
        return self


class ConnectionCreateRequest(BaseModel):
    recipient_id: int = Field(gt=0)


class ConnectionResponse(ConnectionRequest):
    peer_match_id: int | None = Field(default=None, gt=0)


class ConnectionPeerProfile(BaseModel):
    user_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=80)
    school: str = Field(default="", max_length=120)
    major: str = Field(default="", max_length=120)


class ConnectionRequestSummary(BaseModel):
    id: int = Field(gt=0)
    requester_id: int = Field(gt=0)
    recipient_id: int = Field(gt=0)
    status: ConnectionStatus
    created_at: datetime
    responded_at: datetime | None = None
    peer: ConnectionPeerProfile


class ConnectedPeerSummary(BaseModel):
    peer_match_id: int = Field(gt=0)
    connection_request_id: int = Field(gt=0)
    requester_id: int = Field(gt=0)
    recipient_id: int = Field(gt=0)
    connected_at: datetime
    peer: ConnectionPeerProfile


class ConnectionsResponse(BaseModel):
    incoming: list[ConnectionRequestSummary] = Field(default_factory=list)
    sent: list[ConnectionRequestSummary] = Field(default_factory=list)
    connected: list[ConnectedPeerSummary] = Field(default_factory=list)


class PeerMatch(BaseModel):
    id: int | None = Field(default=None, gt=0)
    connection_request_id: int = Field(gt=0)
    user_a_id: int = Field(gt=0)
    user_b_id: int = Field(gt=0)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def validate_participants(self) -> "PeerMatch":
        if self.user_a_id == self.user_b_id:
            raise ValueError("user_a_id and user_b_id must be different")
        return self


class StudySession(BaseModel):
    id: int | None = Field(default=None, gt=0)
    peer_match_id: int = Field(gt=0)
    learner_id: int = Field(gt=0)
    helper_id: int = Field(gt=0)
    topic: str = Field(min_length=1, max_length=120)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return _strip_required(value, "topic")

    @model_validator(mode="after")
    def validate_session(self) -> "StudySession":
        if self.learner_id == self.helper_id:
            raise ValueError("learner_id and helper_id must be different")
        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class StudySessionListResponse(BaseModel):
    items: list[StudySession] = Field(default_factory=list)
    count: int = Field(ge=0)


class StudySessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_match_id: int = Field(gt=0)
    learner_id: int = Field(gt=0)
    helper_id: int = Field(gt=0)
    topic: str = Field(min_length=1, max_length=120)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return _strip_required(value, "topic")

    @model_validator(mode="after")
    def validate_session(self) -> "StudySessionCreateRequest":
        if self.learner_id == self.helper_id:
            raise ValueError("learner_id and helper_id must be different")
        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class ChatMessage(BaseModel):
    id: int | None = Field(default=None, gt=0)
    session_id: int = Field(gt=0)
    sender_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=2000)
    created_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return unicodedata.normalize("NFC", value.strip())


class StudySessionResponse(StudySession):
    icebreaker_eligible: bool = True
    chat_messages: list[ChatMessage] = Field(default_factory=list)


class StudyRoomClientMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["CHAT_MESSAGE"]
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return unicodedata.normalize("NFC", value.strip())


class ModerationResult(BaseModel):
    action: ModerationAction
    risk_score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    guidance: str | None = Field(default=None, max_length=1000)
    needs_human_review: bool = False
    retrieved_sources: list[dict[str, Any]] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return _strip_required(value, "reason")

    @field_validator("guidance")
    @classmethod
    def strip_guidance(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return unicodedata.normalize("NFC", value.strip())

    @model_validator(mode="after")
    def validate_review_flag(self) -> "ModerationResult":
        if self.action == ModerationAction.ESCALATE and not self.needs_human_review:
            raise ValueError("ESCALATE moderation results must need human review")
        return self


class InstructorReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    override_action: ModerationAction | None = None
    notes: str = Field(default="", max_length=1000)

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())

    @model_validator(mode="after")
    def validate_override_action(self) -> "InstructorReviewRequest":
        if self.action == ReviewAction.OVERRIDE and self.override_action is None:
            raise ValueError("OVERRIDE reviews require override_action")
        if self.action != ReviewAction.OVERRIDE and self.override_action is not None:
            raise ValueError("override_action is only valid for OVERRIDE reviews")
        return self


class InstructorReviewRecord(BaseModel):
    id: int = Field(gt=0)
    moderation_event_id: int = Field(gt=0)
    instructor_id: int = Field(gt=0)
    action: ReviewAction
    override_action: ModerationAction | None = None
    notes: str = ""
    created_at: datetime


class ModerationEventRecord(BaseModel):
    id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    message_id: int = Field(gt=0)
    sender_id: int = Field(gt=0)
    agent_action: ModerationAction
    risk_score: float = Field(ge=0, le=1)
    reason: str
    guidance: str | None = None
    needs_human_review: bool = False
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    instructor_review: InstructorReviewRecord | None = None
    message_content: str | None = None


class ModerationEventListResponse(BaseModel):
    items: list[ModerationEventRecord] = Field(default_factory=list)
    count: int = Field(ge=0)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)
    age: int = Field(ge=18, le=100)
    city: str = Field(default="Hà Nội", max_length=80)
    intent: Intent = "conversation"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _validate_email(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    age: int = Field(ge=18, le=100)
    city: str = Field(default="", max_length=80)
    occupation: str = Field(default="", max_length=100)
    bio: str = Field(default="", max_length=500)
    intent: Intent
    interests: list[str] = Field(default_factory=list, max_length=12)
    available_times: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("interests", "available_times")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return _normalize_items(values)


class SwipeRequest(BaseModel):
    target_user_id: int
    action: Literal["like", "pass"]


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tin nhắn không được để trống")
        return unicodedata.normalize("NFC", value.strip())


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default="default", min_length=1, max_length=80)


class BlockRequest(BaseModel):
    user_id: int = Field(gt=0)


class ReportRequest(BaseModel):
    user_id: int = Field(gt=0)
    reason: Literal["spam", "harassment", "scam", "inappropriate", "other"]
    details: str = Field(default="", max_length=1000)

    @field_validator("details")
    @classmethod
    def strip_details(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value.strip())
