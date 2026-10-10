import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import Base
from app.db import SCHEMA
from app.onboarding.schema import initialize_onboarding
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_runtime_schema_seeds_catalog_idempotently_and_preserves_legacy_data():
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'test@example.edu','hash','2026-10-06')")
    initialize_onboarding(connection)
    initialize_onboarding(connection)
    assert connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 75  # 30 SQL + 30 Python + 15 bài AICB
    assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert "embedding" in {row[1] for row in connection.execute("PRAGMA table_info(concepts)")}
    connection.close()


def test_alembic_upgrade_supports_fresh_database_and_existing_runtime_tables(monkeypatch, tmp_path):
    for runtime_first in (False, True):
        path = tmp_path / f"migration-{runtime_first}.db"
        if runtime_first:
            connection = sqlite3.connect(path)
            connection.executescript(SCHEMA)
            connection.execute("INSERT INTO users(email,password_hash,created_at) VALUES('kept@example.edu','hash','2026-10-06')")
            initialize_onboarding(connection)
            connection.commit()
            connection.close()
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
        get_settings.cache_clear()
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        assert {"concepts", "onboarding_profiles", "user_concepts"}.issubset(inspect(engine).get_table_names())
        assert inspect(engine).get_pk_constraint("user_concepts")["constrained_columns"] == ["user_id", "concept_id", "role"]
        with engine.connect() as conn:
            if runtime_first:
                assert conn.exec_driver_sql("SELECT COUNT(*) FROM users WHERE email='kept@example.edu'").scalar() == 1
        engine.dispose()
    get_settings.cache_clear()


def test_orm_metadata_includes_data1_tables_and_foreign_keys():
    from app import models  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert {"concepts", "onboarding_profiles", "user_concepts"}.issubset(inspector.get_table_names())
    assert {row["referred_table"] for row in inspector.get_foreign_keys("user_concepts")} == {"users", "concepts"}
    engine.dispose()
