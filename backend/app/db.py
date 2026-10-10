import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import get_settings

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL DEFAULT 'STUDENT' CHECK(role IN ('STUDENT', 'INSTRUCTOR')),
    password_hash TEXT NOT NULL,
    is_seed INTEGER NOT NULL DEFAULT 0,
    simulated_interest INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK(age >= 18 AND age <= 100),
    city TEXT NOT NULL DEFAULT '',
    occupation TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    school TEXT NOT NULL DEFAULT '',
    major TEXT NOT NULL DEFAULT '',
    subjects TEXT NOT NULL DEFAULT '[]',
    learning_goals TEXT NOT NULL DEFAULT '[]',
    intent TEXT NOT NULL,
    interests TEXT NOT NULL DEFAULT '[]',
    available_times TEXT NOT NULL DEFAULT '[]',
    avatar_style TEXT NOT NULL DEFAULT 'one',
    avatar_url TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS swipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK(action IN ('like', 'pass')),
    created_at TEXT NOT NULL,
    UNIQUE(actor_id, target_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(user_a_id, user_b_id),
    CHECK(user_a_id < user_b_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 1000),
    read_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_score REAL NOT NULL CHECK(total_score >= 0 AND total_score <= 100),
    component_scores TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK(rank > 0),
    created_at TEXT NOT NULL,
    UNIQUE(request_id, candidate_id),
    UNIQUE(request_id, rank)
);

CREATE TABLE IF NOT EXISTS connection_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'MATCHED', 'REJECTED', 'EXPIRED')),
    created_at TEXT NOT NULL,
    responded_at TEXT,
    CHECK(requester_id != recipient_id)
);

CREATE TABLE IF NOT EXISTS peer_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_request_id INTEGER NOT NULL UNIQUE REFERENCES connection_requests(id) ON DELETE CASCADE,
    user_a_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(user_a_id, user_b_id),
    CHECK(user_a_id < user_b_id)
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_match_id INTEGER NOT NULL REFERENCES peer_matches(id) ON DELETE CASCADE,
    learner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    helper_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL CHECK(length(trim(topic)) BETWEEN 1 AND 120),
    scheduled_start TEXT,
    scheduled_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(learner_id != helper_id),
    CHECK(scheduled_start IS NULL OR scheduled_end IS NULL OR scheduled_end > scheduled_start)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 2000),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moderation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES study_sessions(id),
    message_id INTEGER NOT NULL REFERENCES chat_messages(id),
    sender_id INTEGER NOT NULL REFERENCES users(id),
    agent_action TEXT NOT NULL CHECK(agent_action IN ('ALLOW', 'GUIDE', 'WARN', 'BLOCK', 'ESCALATE')),
    risk_score REAL NOT NULL CHECK(risk_score >= 0 AND risk_score <= 1),
    reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
    guidance TEXT,
    needs_human_review INTEGER NOT NULL DEFAULT 0,
    context TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS socratic_sessions (
    session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    active INTEGER NOT NULL DEFAULT 1,
    original_question TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    turn_count INTEGER NOT NULL DEFAULT 1,
    last_guidance TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id, sender_id)
);

CREATE TABLE IF NOT EXISTS instructor_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moderation_event_id INTEGER NOT NULL UNIQUE REFERENCES moderation_events(id),
    instructor_id INTEGER NOT NULL REFERENCES users(id),
    review_action TEXT NOT NULL CHECK(review_action IN ('APPROVE', 'OVERRIDE', 'INTERVENE')),
    override_action TEXT CHECK(override_action IS NULL OR override_action IN ('ALLOW', 'GUIDE', 'WARN', 'BLOCK', 'ESCALATE')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_instructors (
    session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    instructor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(session_id, instructor_id)
);

CREATE TABLE IF NOT EXISTS course_memberships (
    course_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(course_id, user_id)
);

CREATE TABLE IF NOT EXISTS session_courses (
    session_id INTEGER PRIMARY KEY REFERENCES study_sessions(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moderation_quota (
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    window_start TEXT NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY(sender_id, window_start)
);

CREATE TABLE IF NOT EXISTS blocks (
    blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(blocker_id, blocked_id),
    CHECK(blocker_id != blocked_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    CHECK(reporter_id != reported_id)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS help_needs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_user_id INTEGER NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
    topic TEXT NOT NULL CHECK(length(trim(topic)) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '',
    current_level TEXT NOT NULL DEFAULT '',
    target_outcome TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS help_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_user_id INTEGER NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
    topic TEXT NOT NULL CHECK(length(trim(topic)) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '',
    proficiency_level TEXT NOT NULL DEFAULT '',
    max_sessions_per_week INTEGER NOT NULL DEFAULT 3 CHECK(max_sessions_per_week BETWEEN 1 AND 20),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_user_id INTEGER NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(start_time < end_time)
);

CREATE INDEX IF NOT EXISTS idx_swipes_actor ON swipes(actor_id);
CREATE INDEX IF NOT EXISTS idx_messages_match ON messages(match_id, id);
CREATE INDEX IF NOT EXISTS idx_match_requests_requester ON match_requests(requester_id, id);
CREATE INDEX IF NOT EXISTS idx_match_candidates_request ON match_candidates(request_id, rank);
CREATE INDEX IF NOT EXISTS idx_match_candidates_candidate ON match_candidates(candidate_id);
CREATE INDEX IF NOT EXISTS idx_connection_requests_requester ON connection_requests(requester_id, id);
CREATE INDEX IF NOT EXISTS idx_connection_requests_recipient ON connection_requests(recipient_id, id);
CREATE INDEX IF NOT EXISTS idx_connection_requests_pair_status ON connection_requests(requester_id, recipient_id, status);
CREATE INDEX IF NOT EXISTS idx_peer_matches_user_a ON peer_matches(user_a_id);
CREATE INDEX IF NOT EXISTS idx_peer_matches_user_b ON peer_matches(user_b_id);
CREATE INDEX IF NOT EXISTS idx_study_sessions_peer_match ON study_sessions(peer_match_id, id);
CREATE INDEX IF NOT EXISTS idx_study_sessions_learner ON study_sessions(learner_id, id);
CREATE INDEX IF NOT EXISTS idx_study_sessions_helper ON study_sessions(helper_id, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_sender ON chat_messages(sender_id, id);
CREATE INDEX IF NOT EXISTS idx_moderation_events_session ON moderation_events(session_id, id);
CREATE INDEX IF NOT EXISTS idx_moderation_events_message ON moderation_events(message_id, id);
CREATE INDEX IF NOT EXISTS idx_moderation_events_review ON moderation_events(needs_human_review, id);
CREATE INDEX IF NOT EXISTS idx_instructor_reviews_event ON instructor_reviews(moderation_event_id);
CREATE INDEX IF NOT EXISTS idx_instructor_reviews_instructor ON instructor_reviews(instructor_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_session ON agent_messages(user_id, session_id, id);
CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id);
CREATE INDEX IF NOT EXISTS idx_help_needs_profile ON help_needs(profile_user_id, id);
CREATE INDEX IF NOT EXISTS idx_help_offers_profile ON help_offers(profile_user_id, id);
CREATE INDEX IF NOT EXISTS idx_availability_profile ON availability(profile_user_id, day_of_week, start_time);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or get_settings().database_file
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def database() -> Generator[sqlite3.Connection, None, None]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with database() as connection:
        connection.executescript(SCHEMA)
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "role" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'STUDENT'")
        profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(profiles)")}
        if "school" not in profile_columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN school TEXT NOT NULL DEFAULT ''")
        if "major" not in profile_columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN major TEXT NOT NULL DEFAULT ''")
        if "subjects" not in profile_columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN subjects TEXT NOT NULL DEFAULT '[]'")
        if "learning_goals" not in profile_columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN learning_goals TEXT NOT NULL DEFAULT '[]'")
        if "avatar_url" not in profile_columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
        message_columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
        if "read_at" not in message_columns:
            connection.execute("ALTER TABLE messages ADD COLUMN read_at TEXT")
        from .onboarding.schema import initialize_onboarding

        initialize_onboarding(connection)
        from .matching.schema import initialize_matching

        initialize_matching(connection)
        from .metrics.schema import initialize_metrics

        initialize_metrics(connection)
        from .agents.plan_coach.storage import SCHEMA as PLAN_SCHEMA

        connection.executescript(PLAN_SCHEMA)
        from .home.notifications import initialize as initialize_notifications
        from .loop.ai_budget import initialize as initialize_ai_usage

        initialize_notifications(connection)
        initialize_ai_usage(connection)
        from .session_review.schema import initialize as initialize_session_reviews

        initialize_session_reviews(connection)
    from .checkin.db import initialize_checkin_tables

    initialize_checkin_tables()
