"""SQLite bootstrap for the app's actual db.py runtime; mirrored by Alembic."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS pb_plans (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pair_id INTEGER NOT NULL REFERENCES peer_matches(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 version INTEGER NOT NULL CHECK(version > 0),
 status TEXT NOT NULL CHECK(status IN ('DRAFT','ACTIVE','SUPERSEDED','REJECTED')),
 payload TEXT NOT NULL, context TEXT NOT NULL,
 base_plan_id INTEGER REFERENCES pb_plans(id),
 progress_hash TEXT, cutoff TEXT, reason TEXT,
 created_at TEXT NOT NULL, accepted_at TEXT,
 UNIQUE(pair_id,user_id,version)
);
CREATE UNIQUE INDEX IF NOT EXISTS pb_one_active_plan ON pb_plans(pair_id,user_id) WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS pb_plan_items (
 id TEXT PRIMARY KEY,
 pair_id INTEGER NOT NULL REFERENCES peer_matches(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 concept_id TEXT NOT NULL,
 completed_at TEXT, completed_payload TEXT
);
CREATE TABLE IF NOT EXISTS pb_plan_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pair_id INTEGER NOT NULL REFERENCES peer_matches(id), actor_id INTEGER NOT NULL REFERENCES users(id),
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL, owner_token TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','DONE','FAILED')),
 result TEXT, created_at TEXT NOT NULL,
 UNIQUE(pair_id,actor_id,request_key)
);
CREATE TABLE IF NOT EXISTS pb_completion_events (
 event_id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES pb_plan_items(id),
 event_hash TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pb_interventions (
 id TEXT PRIMARY KEY, pair_id INTEGER NOT NULL REFERENCES peer_matches(id),
 user_id INTEGER NOT NULL REFERENCES users(id), local_date TEXT NOT NULL,
 action TEXT NOT NULL, variant TEXT NOT NULL, decision TEXT NOT NULL,
 delivery_status TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(user_id,local_date)
);
CREATE TABLE IF NOT EXISTS pb_delivery_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 intervention_id TEXT NOT NULL REFERENCES pb_interventions(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pb_variants (
 pair_id INTEGER PRIMARY KEY REFERENCES peer_matches(id), variant TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pb_traces (
 id TEXT PRIMARY KEY, pair_id INTEGER NOT NULL REFERENCES peer_matches(id),
 kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
);
"""
