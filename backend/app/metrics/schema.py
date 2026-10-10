import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS pair_metrics_daily (
    pair_id INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    pacing_a REAL NOT NULL CHECK(pacing_a >= 0),
    pacing_b REAL NOT NULL CHECK(pacing_b >= 0),
    pair_score REAL NOT NULL CHECK(pair_score >= 0),
    gap REAL NOT NULL CHECK(gap >= 0),
    risk_a REAL CHECK(risk_a BETWEEN 0 AND 1),
    risk_b REAL CHECK(risk_b BETWEEN 0 AND 1),
    streak INTEGER NOT NULL CHECK(streak >= 0),
    metric_version TEXT NOT NULL,
    pair_started_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY(pair_id,date),
    CHECK(pair_score = min(pacing_a,pacing_b)),
    CHECK(gap = abs(pacing_a-pacing_b))
);
CREATE INDEX IF NOT EXISTS idx_pair_metrics_date ON pair_metrics_daily(date,pair_id);
"""


def initialize_metrics(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
