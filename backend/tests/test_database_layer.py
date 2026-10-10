from datetime import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import Base, get_engine, get_session_factory
from app.enums import ModerationAction, ReviewAction, Role
from app.models import (
    Availability,
    ChatMessage,
    ConnectionRequest,
    HelpNeed,
    HelpOffer,
    InstructorReview,
    MatchCandidate,
    MatchRequest,
    ModerationEvent,
    PeerMatch,
    Profile,
    StudySession,
    User,
)
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_database_url_comes_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'peerbridge.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert get_settings().sqlalchemy_database_url == database_url


def test_database_url_falls_back_to_local_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_path = tmp_path / "local.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    assert get_settings().sqlalchemy_database_url == f"sqlite:///{database_path.as_posix()}"


def test_alembic_peerbridge_migration_is_present() -> None:
    migration = BACKEND_DIR / "alembic" / "versions" / "20260930_0001_peerbridge_profile_schema.py"
    match_migration = BACKEND_DIR / "alembic" / "versions" / "20261001_0002_match_requests.py"
    connection_migration = BACKEND_DIR / "alembic" / "versions" / "20261001_0003_mutual_consent.py"
    session_migration = BACKEND_DIR / "alembic" / "versions" / "20261001_0004_study_sessions.py"
    moderation_migration = BACKEND_DIR / "alembic" / "versions" / "20261001_0005_human_in_loop_moderation.py"

    assert migration.exists()
    migration_text = migration.read_text(encoding="utf-8")
    assert "help_needs" in migration_text
    assert "help_offers" in migration_text
    assert "availability" in migration_text
    assert match_migration.exists()
    match_migration_text = match_migration.read_text(encoding="utf-8")
    assert "match_requests" in match_migration_text
    assert "match_candidates" in match_migration_text
    assert connection_migration.exists()
    connection_migration_text = connection_migration.read_text(encoding="utf-8")
    assert "connection_requests" in connection_migration_text
    assert "peer_matches" in connection_migration_text
    assert session_migration.exists()
    session_migration_text = session_migration.read_text(encoding="utf-8")
    assert "study_sessions" in session_migration_text
    assert "chat_messages" in session_migration_text
    assert moderation_migration.exists()
    moderation_migration_text = moderation_migration.read_text(encoding="utf-8")
    assert "moderation_events" in moderation_migration_text
    assert "instructor_reviews" in moderation_migration_text


def test_sqlalchemy_engine_and_session_factory_use_database_url(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'session.db').as_posix()}"

    engine = get_engine(database_url)
    session_factory = get_session_factory(database_url)

    assert engine.url.drivername == "sqlite"
    assert str(engine.url.database).endswith("session.db")
    with session_factory() as session:
        assert isinstance(session, Session)


def test_alembic_upgrade_head_creates_moderation_tables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'alembic.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    engine = create_engine(database_url)
    inspector = sa_inspect(engine)

    assert "moderation_events" in inspector.get_table_names()
    assert "instructor_reviews" in inspector.get_table_names()


def test_peerbridge_models_create_expected_tables_and_foreign_keys() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = sa_inspect(engine)

    assert {
        "users",
        "profiles",
        "help_needs",
        "help_offers",
        "availability",
        "match_requests",
        "match_candidates",
        "connection_requests",
        "peer_matches",
        "study_sessions",
        "chat_messages",
        "moderation_events",
        "instructor_reviews",
    }.issubset(inspector.get_table_names())
    assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("profiles")["constrained_columns"] == ["user_id"]

    profile_fks = inspector.get_foreign_keys("profiles")
    need_fks = inspector.get_foreign_keys("help_needs")
    offer_fks = inspector.get_foreign_keys("help_offers")
    availability_fks = inspector.get_foreign_keys("availability")
    request_fks = inspector.get_foreign_keys("match_requests")
    candidate_fks = inspector.get_foreign_keys("match_candidates")
    connection_fks = inspector.get_foreign_keys("connection_requests")
    peer_match_fks = inspector.get_foreign_keys("peer_matches")
    study_session_fks = inspector.get_foreign_keys("study_sessions")
    chat_message_fks = inspector.get_foreign_keys("chat_messages")
    moderation_event_fks = inspector.get_foreign_keys("moderation_events")
    instructor_review_fks = inspector.get_foreign_keys("instructor_reviews")

    assert profile_fks[0]["referred_table"] == "users"
    assert profile_fks[0]["constrained_columns"] == ["user_id"]
    assert need_fks[0]["referred_table"] == "profiles"
    assert offer_fks[0]["referred_table"] == "profiles"
    assert availability_fks[0]["referred_table"] == "profiles"
    assert request_fks[0]["referred_table"] == "users"
    assert {foreign_key["referred_table"] for foreign_key in candidate_fks} == {"match_requests", "users"}
    assert {foreign_key["referred_table"] for foreign_key in connection_fks} == {"users"}
    assert {foreign_key["referred_table"] for foreign_key in peer_match_fks} == {"connection_requests", "users"}
    assert {foreign_key["referred_table"] for foreign_key in study_session_fks} == {"peer_matches", "users"}
    assert {foreign_key["referred_table"] for foreign_key in chat_message_fks} == {"study_sessions", "users"}
    assert {foreign_key["referred_table"] for foreign_key in moderation_event_fks} == {
        "chat_messages",
        "study_sessions",
        "users",
    }
    assert {foreign_key["referred_table"] for foreign_key in instructor_review_fks} == {"moderation_events", "users"}


def test_peerbridge_model_relationships() -> None:
    user_relationships = sa_inspect(User).relationships
    profile_relationships = sa_inspect(Profile).relationships
    request_relationships = sa_inspect(MatchRequest).relationships
    candidate_relationships = sa_inspect(MatchCandidate).relationships
    connection_relationships = sa_inspect(ConnectionRequest).relationships
    peer_match_relationships = sa_inspect(PeerMatch).relationships
    study_session_relationships = sa_inspect(StudySession).relationships
    chat_message_relationships = sa_inspect(ChatMessage).relationships
    moderation_event_relationships = sa_inspect(ModerationEvent).relationships
    instructor_review_relationships = sa_inspect(InstructorReview).relationships

    assert user_relationships["profile"].mapper.class_ is Profile
    assert user_relationships["profile"].uselist is False
    assert user_relationships["match_requests"].mapper.class_ is MatchRequest
    assert user_relationships["match_requests"].uselist is True
    assert user_relationships["connection_requests_sent"].mapper.class_ is ConnectionRequest
    assert user_relationships["connection_requests_received"].mapper.class_ is ConnectionRequest
    assert user_relationships["peer_matches_as_user_a"].mapper.class_ is PeerMatch
    assert user_relationships["peer_matches_as_user_b"].mapper.class_ is PeerMatch
    assert user_relationships["moderation_events_sent"].mapper.class_ is ModerationEvent
    assert user_relationships["instructor_reviews"].mapper.class_ is InstructorReview
    assert profile_relationships["user"].mapper.class_ is User
    assert profile_relationships["help_needs"].mapper.class_ is HelpNeed
    assert profile_relationships["help_offers"].mapper.class_ is HelpOffer
    assert profile_relationships["availability"].mapper.class_ is Availability
    assert request_relationships["requester"].mapper.class_ is User
    assert request_relationships["candidates"].mapper.class_ is MatchCandidate
    assert request_relationships["candidates"].uselist is True
    assert candidate_relationships["match_request"].mapper.class_ is MatchRequest
    assert connection_relationships["requester"].mapper.class_ is User
    assert connection_relationships["recipient"].mapper.class_ is User
    assert connection_relationships["peer_match"].mapper.class_ is PeerMatch
    assert connection_relationships["peer_match"].uselist is False
    assert peer_match_relationships["connection_request"].mapper.class_ is ConnectionRequest
    assert peer_match_relationships["study_sessions"].mapper.class_ is StudySession
    assert peer_match_relationships["study_sessions"].uselist is True
    assert study_session_relationships["peer_match"].mapper.class_ is PeerMatch
    assert study_session_relationships["chat_messages"].mapper.class_ is ChatMessage
    assert study_session_relationships["chat_messages"].uselist is True
    assert study_session_relationships["moderation_events"].mapper.class_ is ModerationEvent
    assert chat_message_relationships["session"].mapper.class_ is StudySession
    assert chat_message_relationships["moderation_events"].mapper.class_ is ModerationEvent
    assert moderation_event_relationships["session"].mapper.class_ is StudySession
    assert moderation_event_relationships["message"].mapper.class_ is ChatMessage
    assert moderation_event_relationships["sender"].mapper.class_ is User
    assert moderation_event_relationships["instructor_review"].mapper.class_ is InstructorReview
    assert moderation_event_relationships["instructor_review"].uselist is False
    assert instructor_review_relationships["moderation_event"].mapper.class_ is ModerationEvent
    assert instructor_review_relationships["instructor"].mapper.class_ is User


def test_peerbridge_models_persist_profile_graph() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        candidate_user = User(
            email="helper@example.edu",
            role=Role.STUDENT,
            password_hash="hash",
            profile=Profile(display_name="Helper", help_offers=[HelpOffer(topic="Calculus")]),
        )
        instructor = User(
            email="teacher@example.edu",
            role=Role.INSTRUCTOR,
            password_hash="hash",
        )
        user = User(
            email="learner@example.edu",
            role=Role.STUDENT,
            password_hash="hash",
            profile=Profile(
                display_name="Learner",
                school="Open University",
                major="Computer Science",
                help_needs=[HelpNeed(topic="Calculus")],
                help_offers=[HelpOffer(topic="Python", max_sessions_per_week=2)],
                availability=[
                    Availability(day_of_week=2, start_time=time(9, 0), end_time=time(10, 30)),
                ],
            ),
        )
        session.add_all([user, candidate_user, instructor])
        session.flush()

        user_a_id, user_b_id = sorted((user.id, candidate_user.id))
        peer_match = PeerMatch(user_a_id=user_a_id, user_b_id=user_b_id)
        user.match_requests.append(
            MatchRequest(
                candidates=[
                    MatchCandidate(
                        candidate=candidate_user,
                        total_score=92.5,
                        component_scores={"skill_complementarity": 1.0},
                        rank=1,
                    )
                ]
            )
        )
        user.connection_requests_sent.append(
            ConnectionRequest(
                recipient=candidate_user,
                peer_match=peer_match,
            )
        )
        chat_message = ChatMessage(sender_id=user.id, content="Let's study limits.")
        moderation_event = ModerationEvent(
            sender_id=user.id,
            agent_action=ModerationAction.ESCALATE,
            risk_score=0.9,
            reason="Needs instructor review",
            needs_human_review=True,
            context={"topic": "Calculus"},
            instructor_review=InstructorReview(
                instructor_id=instructor.id,
                review_action=ReviewAction.INTERVENE,
                notes="Joining the room.",
            ),
        )
        chat_message.moderation_events.append(moderation_event)
        peer_match.study_sessions.append(
            StudySession(
                learner_id=user.id,
                helper_id=candidate_user.id,
                topic="Calculus",
                chat_messages=[chat_message],
                moderation_events=[moderation_event],
            )
        )
        session.commit()

        saved = session.query(User).filter_by(email="learner@example.edu").one()
        assert saved.profile is not None
        assert saved.profile.help_needs[0].topic == "Calculus"
        assert saved.profile.help_offers[0].topic == "Python"
        assert saved.profile.availability[0].day_of_week == 2
        assert saved.match_requests[0].candidates[0].candidate.email == "helper@example.edu"
        assert saved.match_requests[0].candidates[0].component_scores == {"skill_complementarity": 1.0}
        assert saved.connection_requests_sent[0].recipient.email == "helper@example.edu"
        assert saved.connection_requests_sent[0].peer_match is not None
        assert saved.connection_requests_sent[0].peer_match.study_sessions[0].topic == "Calculus"
        assert saved.connection_requests_sent[0].peer_match.study_sessions[0].chat_messages[0].content == "Let's study limits."
        saved_event = saved.connection_requests_sent[0].peer_match.study_sessions[0].moderation_events[0]
        assert saved_event.agent_action is ModerationAction.ESCALATE
        assert saved_event.instructor_review is not None
        assert saved_event.instructor_review.review_action is ReviewAction.INTERVENE
