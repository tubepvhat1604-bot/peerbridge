from datetime import datetime, time

import pytest
from app.enums import ConnectionStatus, ModerationAction, ReviewAction, Role
from app.schemas import (
    Availability,
    ChatMessage,
    ConnectionRequest,
    HelpNeed,
    HelpOffer,
    InstructorReviewRequest,
    MatchCandidate,
    MatchResult,
    ModerationResult,
    PeerMatch,
    Profile,
    StudySession,
    User,
)
from pydantic import ValidationError


def test_user_accepts_valid_role_and_normalizes_email() -> None:
    user = User(id=1, email=" Learner@Example.edu ", role="STUDENT")

    assert user.email == "learner@example.edu"
    assert user.role is Role.STUDENT


def test_user_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        User(email="learner@example.edu", role="ADMIN")


def test_profile_normalizes_list_fields() -> None:
    profile = Profile(
        user_id=1,
        display_name=" Linh ",
        subjects=[" Calculus ", "calculus", "Python"],
        learning_goals=[" Debug proofs ", ""],
    )

    assert profile.display_name == "Linh"
    assert profile.subjects == ["Calculus", "Python"]
    assert profile.learning_goals == ["Debug proofs"]


def test_help_need_requires_topic() -> None:
    with pytest.raises(ValidationError):
        HelpNeed(user_id=1, topic=" ")


def test_help_offer_bounds_weekly_sessions_and_requires_topic() -> None:
    offer = HelpOffer(user_id=1, topic=" Python ", max_sessions_per_week=2)

    assert offer.topic == "Python"

    with pytest.raises(ValidationError):
        HelpOffer(user_id=1, topic="Python", max_sessions_per_week=0)

    with pytest.raises(ValidationError):
        HelpOffer(user_id=1, topic=" ")


def test_availability_requires_end_after_start() -> None:
    with pytest.raises(ValidationError):
        Availability(user_id=1, day_of_week=2, start_time=time(10, 0), end_time=time(9, 0))


def test_connection_request_uses_status_enum_and_rejects_self_request() -> None:
    request = ConnectionRequest(requester_id=1, recipient_id=2, status="PENDING")

    assert request.status is ConnectionStatus.PENDING

    with pytest.raises(ValidationError):
        ConnectionRequest(requester_id=1, recipient_id=1)


def test_match_result_accepts_candidates_with_bounded_score() -> None:
    profile = Profile(user_id=2, display_name="Minh")
    candidate = MatchCandidate(user_id=2, profile=profile, score=91.5, reasons=[" Same topic ", "same topic"])
    result = MatchResult(request_id=1, candidates=[candidate])

    assert result.candidates[0].reasons == ["Same topic"]

    with pytest.raises(ValidationError):
        MatchCandidate(user_id=2, profile=profile, score=101)


def test_peer_match_rejects_self_match() -> None:
    match = PeerMatch(connection_request_id=1, user_a_id=1, user_b_id=2)

    assert match.user_a_id == 1

    with pytest.raises(ValidationError):
        PeerMatch(connection_request_id=1, user_a_id=1, user_b_id=1)


def test_study_session_validates_participants_and_schedule() -> None:
    starts_at = datetime.fromisoformat("2026-10-01T09:00:00")
    ends_at = datetime.fromisoformat("2026-10-01T10:00:00")
    session = StudySession(
        peer_match_id=1,
        learner_id=1,
        helper_id=2,
        topic=" Linear algebra ",
        scheduled_start=starts_at,
        scheduled_end=ends_at,
    )

    assert session.topic == "Linear algebra"

    with pytest.raises(ValidationError):
        StudySession(peer_match_id=1, learner_id=1, helper_id=1, topic="Linear algebra")

    with pytest.raises(ValidationError):
        StudySession(
            peer_match_id=1,
            learner_id=1,
            helper_id=2,
            topic="Linear algebra",
            scheduled_start=ends_at,
            scheduled_end=starts_at,
        )


def test_chat_message_strips_content_and_rejects_blank_content() -> None:
    message = ChatMessage(session_id=1, sender_id=2, content="  Try a smaller example.  ")

    assert message.content == "Try a smaller example."

    with pytest.raises(ValidationError):
        ChatMessage(session_id=1, sender_id=2, content="  ")


def test_moderation_result_validates_risk_and_escalation_review_flag() -> None:
    result = ModerationResult(
        action=ModerationAction.GUIDE,
        risk_score=0.35,
        reason="Potential direct answer",
        guidance="Ask a Socratic follow-up.",
    )

    assert result.action is ModerationAction.GUIDE
    assert result.needs_human_review is False

    with pytest.raises(ValidationError):
        ModerationResult(action=ModerationAction.ALLOW, risk_score=1.2, reason="Too high")

    with pytest.raises(ValidationError):
        ModerationResult(action=ModerationAction.ESCALATE, risk_score=0.9, reason="Needs instructor")


def test_instructor_review_request_validates_override_action() -> None:
    approve = InstructorReviewRequest(action=ReviewAction.APPROVE, notes=" Looks good ")
    override = InstructorReviewRequest(action=ReviewAction.OVERRIDE, override_action=ModerationAction.GUIDE)

    assert approve.notes == "Looks good"
    assert override.override_action is ModerationAction.GUIDE

    with pytest.raises(ValidationError):
        InstructorReviewRequest(action=ReviewAction.OVERRIDE)

    with pytest.raises(ValidationError):
        InstructorReviewRequest(action=ReviewAction.APPROVE, override_action=ModerationAction.ALLOW)
