from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import ConnectionStatus, ModerationAction, ReviewAction, Role
from .matching.models import PairInvitationRecord, PairMembershipRecord, PairQueueRecord, PairRecord  # noqa: F401
from .metrics.models import PairMetricRecord  # noqa: F401
from .onboarding.models import ConceptRecord, OnboardingRecord, UserConceptRecord  # noqa: F401


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, validate_strings=True, create_constraint=True, name="role"),
        nullable=False,
        default=Role.STUDENT,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_seed: Mapped[bool] = mapped_column(default=False, nullable=False)
    simulated_interest: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    profile: Mapped[Profile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    match_requests: Mapped[list[MatchRequest]] = relationship(
        back_populates="requester",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    connection_requests_sent: Mapped[list[ConnectionRequest]] = relationship(
        back_populates="requester",
        cascade="all, delete-orphan",
        foreign_keys="ConnectionRequest.requester_id",
        passive_deletes=True,
    )
    connection_requests_received: Mapped[list[ConnectionRequest]] = relationship(
        back_populates="recipient",
        cascade="all, delete-orphan",
        foreign_keys="ConnectionRequest.recipient_id",
        passive_deletes=True,
    )
    peer_matches_as_user_a: Mapped[list[PeerMatch]] = relationship(
        back_populates="user_a",
        foreign_keys="PeerMatch.user_a_id",
    )
    peer_matches_as_user_b: Mapped[list[PeerMatch]] = relationship(
        back_populates="user_b",
        foreign_keys="PeerMatch.user_b_id",
    )
    moderation_events_sent: Mapped[list[ModerationEvent]] = relationship(
        back_populates="sender",
        foreign_keys="ModerationEvent.sender_id",
    )
    instructor_reviews: Mapped[list[InstructorReview]] = relationship(
        back_populates="instructor",
        foreign_keys="InstructorReview.instructor_id",
    )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (CheckConstraint("age BETWEEN 18 AND 100", name="ck_profiles_age_range"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    age: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    occupation: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="", nullable=False)
    school: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    major: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    learning_goals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    intent: Mapped[str] = mapped_column(String(32), default="conversation", nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    available_times: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    avatar_style: Mapped[str] = mapped_column(String(32), default="one", nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")
    help_needs: Mapped[list[HelpNeed]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    help_offers: Mapped[list[HelpOffer]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    availability: Mapped[list[Availability]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class HelpNeed(Base):
    __tablename__ = "help_needs"
    __table_args__ = (CheckConstraint("length(trim(topic)) BETWEEN 1 AND 120", name="ck_help_needs_topic_length"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_level: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    target_outcome: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="help_needs")


class HelpOffer(Base):
    __tablename__ = "help_offers"
    __table_args__ = (
        CheckConstraint("length(trim(topic)) BETWEEN 1 AND 120", name="ck_help_offers_topic_length"),
        CheckConstraint("max_sessions_per_week BETWEEN 1 AND 20", name="ck_help_offers_weekly_sessions"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proficiency_level: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    max_sessions_per_week: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="help_offers")


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_availability_day_of_week"),
        CheckConstraint("start_time < end_time", name="ck_availability_time_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_user_id: Mapped[int] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="availability")


class MatchRequest(Base):
    __tablename__ = "match_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    requester: Mapped[User] = relationship(back_populates="match_requests")
    candidates: Mapped[list[MatchCandidate]] = relationship(
        back_populates="match_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MatchCandidate.rank",
    )


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (
        CheckConstraint("total_score >= 0 AND total_score <= 100", name="ck_match_candidates_total_score"),
        CheckConstraint("rank > 0", name="ck_match_candidates_rank"),
        UniqueConstraint("request_id", "candidate_id", name="uq_match_candidates_request_candidate"),
        UniqueConstraint("request_id", "rank", name="uq_match_candidates_request_rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("match_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    component_scores: Mapped[dict[str, float]] = mapped_column(JSON, default=dict, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    match_request: Mapped[MatchRequest] = relationship(back_populates="candidates")
    candidate: Mapped[User] = relationship(foreign_keys=[candidate_id])


class ConnectionRequest(Base):
    __tablename__ = "connection_requests"
    __table_args__ = (
        CheckConstraint("requester_id != recipient_id", name="ck_connection_requests_distinct_users"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, native_enum=False, validate_strings=True, create_constraint=True, name="connection_status"),
        nullable=False,
        default=ConnectionStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requester: Mapped[User] = relationship(
        back_populates="connection_requests_sent",
        foreign_keys=[requester_id],
    )
    recipient: Mapped[User] = relationship(
        back_populates="connection_requests_received",
        foreign_keys=[recipient_id],
    )
    peer_match: Mapped[PeerMatch | None] = relationship(
        back_populates="connection_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class PeerMatch(Base):
    __tablename__ = "peer_matches"
    __table_args__ = (
        CheckConstraint("user_a_id < user_b_id", name="ck_peer_matches_ordered_users"),
        UniqueConstraint("connection_request_id", name="uq_peer_matches_connection_request"),
        UniqueConstraint("user_a_id", "user_b_id", name="uq_peer_matches_user_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_request_id: Mapped[int] = mapped_column(
        ForeignKey("connection_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_a_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_b_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    connection_request: Mapped[ConnectionRequest] = relationship(back_populates="peer_match")
    user_a: Mapped[User] = relationship(back_populates="peer_matches_as_user_a", foreign_keys=[user_a_id])
    user_b: Mapped[User] = relationship(back_populates="peer_matches_as_user_b", foreign_keys=[user_b_id])
    study_sessions: Mapped[list[StudySession]] = relationship(
        back_populates="peer_match",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class StudySession(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint("learner_id != helper_id", name="ck_study_sessions_distinct_participants"),
        CheckConstraint(
            "scheduled_start IS NULL OR scheduled_end IS NULL OR scheduled_end > scheduled_start",
            name="ck_study_sessions_schedule_order",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    peer_match_id: Mapped[int] = mapped_column(ForeignKey("peer_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    helper_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    peer_match: Mapped[PeerMatch] = relationship(back_populates="study_sessions")
    learner: Mapped[User] = relationship(foreign_keys=[learner_id])
    helper: Mapped[User] = relationship(foreign_keys=[helper_id])
    chat_messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.id",
    )
    moderation_events: Mapped[list[ModerationEvent]] = relationship(
        back_populates="session",
        order_by="ModerationEvent.id",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("length(trim(content)) BETWEEN 1 AND 2000", name="ck_chat_messages_content_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped[StudySession] = relationship(back_populates="chat_messages")
    sender: Mapped[User] = relationship(foreign_keys=[sender_id])
    moderation_events: Mapped[list[ModerationEvent]] = relationship(
        back_populates="message",
        order_by="ModerationEvent.id",
    )


class ModerationEvent(Base):
    __tablename__ = "moderation_events"
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="ck_moderation_events_risk_score"),
        CheckConstraint("length(trim(reason)) BETWEEN 1 AND 1000", name="ck_moderation_events_reason_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id"), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), nullable=False, index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    agent_action: Mapped[ModerationAction] = mapped_column(
        Enum(ModerationAction, native_enum=False, validate_strings=True, create_constraint=True, name="moderation_action"),
        nullable=False,
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[str | None] = mapped_column(Text)
    needs_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped[StudySession] = relationship(back_populates="moderation_events")
    message: Mapped[ChatMessage] = relationship(back_populates="moderation_events")
    sender: Mapped[User] = relationship(back_populates="moderation_events_sent", foreign_keys=[sender_id])
    instructor_review: Mapped[InstructorReview | None] = relationship(
        back_populates="moderation_event",
        uselist=False,
    )


class InstructorReview(Base):
    __tablename__ = "instructor_reviews"
    __table_args__ = (UniqueConstraint("moderation_event_id", name="uq_instructor_reviews_moderation_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moderation_event_id: Mapped[int] = mapped_column(ForeignKey("moderation_events.id"), nullable=False, index=True)
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    review_action: Mapped[ReviewAction] = mapped_column(
        Enum(ReviewAction, native_enum=False, validate_strings=True, create_constraint=True, name="review_action"),
        nullable=False,
    )
    override_action: Mapped[ModerationAction | None] = mapped_column(
        Enum(
            ModerationAction,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="review_override_action",
        )
    )
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    moderation_event: Mapped[ModerationEvent] = relationship(back_populates="instructor_review")
    instructor: Mapped[User] = relationship(back_populates="instructor_reviews", foreign_keys=[instructor_id])


class SessionInstructor(Base):
    __tablename__ = "session_instructors"
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True)
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class CourseMembership(Base):
    __tablename__ = "course_memberships"
    course_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class SessionCourse(Base):
    __tablename__ = "session_courses"
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(120), nullable=False)


class ModerationQuota(Base):
    __tablename__ = "moderation_quota"
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    window_start: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
