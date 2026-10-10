import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id INTEGER PRIMARY KEY REFERENCES peer_matches(id) ON DELETE CASCADE,
    user_a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_level TEXT NOT NULL CHECK(match_level IN ('same_outcome','concept_overlap','complementary','shared_commitment')),
    match_reason TEXT NOT NULL,
    match_result TEXT NOT NULL,
    reranking TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('automatic','invitation')),
    started_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','ended')),
    ended_at TEXT,
    streak INTEGER NOT NULL DEFAULT 0 CHECK(streak >= 0),
    UNIQUE(user_a,user_b),
    CHECK(user_a < user_b)
);
CREATE TABLE IF NOT EXISTS pair_memberships (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    pair_id INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pair_memberships_pair ON pair_memberships(pair_id);
CREATE TABLE IF NOT EXISTS pair_invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('pending','used','revoked')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER REFERENCES users(id),
    pair_id INTEGER REFERENCES pairs(id),
    CHECK(target_user_id IS NULL OR target_user_id != owner_user_id)
);
CREATE TABLE IF NOT EXISTS pair_match_queue (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    waiting_since TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('waiting','paired','cancelled'))
);
"""


def initialize_matching(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
