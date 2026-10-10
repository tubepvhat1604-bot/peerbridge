import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.config import get_settings
from app.database import Base
from app.db import SCHEMA as LEGACY_SCHEMA
from app.matching.schema import SCHEMA, initialize_matching
from app.onboarding.schema import initialize_onboarding
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = {"pairs", "pair_memberships", "pair_invitations", "pair_match_queue"}


def test_runtime_and_orm_matching_schema_align_and_startup_is_idempotent():
    from app import models  # noqa: F401

    conn = sqlite3.connect(":memory:")
    conn.executescript(LEGACY_SCHEMA)
    initialize_matching(conn)
    initialize_matching(conn)
    runtime_columns = {table: {r[1] for r in conn.execute(f"PRAGMA table_info({table})")} for table in TABLES}
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    for table in TABLES:
        assert runtime_columns[table] == {r["name"] for r in inspector.get_columns(table)}
    assert "peer_matches" in {r["referred_table"] for r in inspector.get_foreign_keys("pairs")}
    assert inspector.get_pk_constraint("pair_memberships")["constrained_columns"] == ["user_id"]
    assert "pair_metrics" not in SCHEMA and "pacing" not in SCHEMA
    conn.close()
    engine.dispose()


def test_fresh_migration_and_existing_phase1_upgrade_preserve_data(monkeypatch, tmp_path):
    for scenario in ("fresh", "phase1", "runtime"):
        path = tmp_path / f"{scenario}.db"
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
        get_settings.cache_clear()
        if scenario != "fresh":
            conn = sqlite3.connect(path)
            conn.executescript(LEGACY_SCHEMA)
            initialize_onboarding(conn)
            conn.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'kept@example.edu','hash','2026-10-06')")
            conn.execute("INSERT INTO onboarding_profiles(user_id,payload,mappings,revision,status,updated_at) VALUES(1,'{}','[]',1,'draft','2026-10-06')")
            if scenario == "runtime":
                initialize_matching(conn)
            conn.commit()
            conn.close()
            command.stamp(config, "20261006_0007")
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        assert TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == ScriptDirectory.from_config(config).get_current_head()
            if scenario != "fresh":
                assert connection.exec_driver_sql("SELECT email FROM users WHERE id=1").scalar() == "kept@example.edu"
                assert connection.exec_driver_sql("SELECT revision FROM onboarding_profiles WHERE user_id=1").scalar() == 1
        engine.dispose()
    get_settings.cache_clear()
