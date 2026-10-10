import json
import re
import sqlite3

from .catalog import load_catalog
from .contracts import CATALOG_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK(domain IN ('sql', 'python', 'ai')),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    prerequisites TEXT NOT NULL,
    aliases TEXT NOT NULL,
    embedding TEXT,
    catalog_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS onboarding_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    payload TEXT NOT NULL,
    mappings TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('draft', 'confirmed')),
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS user_concepts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    role TEXT NOT NULL CHECK(role IN ('need', 'offer')),
    self_level TEXT NOT NULL CHECK(self_level IN ('unknown', 'learning', 'strong')),
    theta REAL NOT NULL,
    n_attempts INTEGER NOT NULL DEFAULT 0 CHECK(n_attempts >= 0),
    PRIMARY KEY(user_id, concept_id, role)
);
CREATE INDEX IF NOT EXISTS idx_user_concepts_concept ON user_concepts(concept_id, role);
"""


_OLD_DOMAIN_CHECK = re.compile(r"CHECK\s*\(\s*domain IN \('sql', 'python'\)\s*\)")


def allow_ai_domain(connection: sqlite3.Connection) -> None:
    """Database cũ chỉ cho domain sql/python: nới CHECK để nhận thêm domain "ai" (khóa AICB).

    Chỉ nới ràng buộc, dữ liệu cũ vẫn hợp lệ, nên sửa thẳng câu CREATE theo cách SQLite hướng dẫn
    ("Making Other Kinds Of Table Schema Changes") thay vì dựng lại bảng đang được user_concepts tham chiếu.
    """
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='concepts'").fetchone()
    if row is None or not _OLD_DOMAIN_CHECK.search(row[0]):
        return
    new_sql = _OLD_DOMAIN_CHECK.sub("CHECK(domain IN ('sql', 'python', 'ai'))", row[0])
    version = connection.execute("PRAGMA schema_version").fetchone()[0]
    connection.execute("PRAGMA writable_schema=ON")
    try:
        connection.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name='concepts'", (new_sql,))
        connection.execute(f"PRAGMA schema_version={version + 1}")
    finally:
        connection.execute("PRAGMA writable_schema=OFF")


def initialize_onboarding(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    allow_ai_domain(connection)
    connection.executemany(
        """INSERT INTO concepts(id, domain, name, description, prerequisites, aliases, catalog_version)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET domain=excluded.domain, name=excluded.name,
             description=excluded.description, prerequisites=excluded.prerequisites,
             aliases=excluded.aliases, catalog_version=excluded.catalog_version""",
        [(item.id, item.domain, item.name, item.description,
          json.dumps(item.prerequisites), json.dumps(item.aliases, ensure_ascii=False), CATALOG_VERSION)
         for item in load_catalog()],
    )
