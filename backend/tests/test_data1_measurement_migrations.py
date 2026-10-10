import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import Base
from app.metrics.schema import initialize_metrics
from sqlalchemy import create_engine, inspect
from test_data1_measurement_storage import initialize, seed_pair

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_measurement_runtime_metadata_constraints_align_and_init_is_idempotent():
    from app import models  # noqa: F401

    conn = sqlite3.connect(":memory:")
    initialize(conn)
    initialize_metrics(conn)
    runtime = {row[1] for row in conn.execute("PRAGMA table_info(pair_metrics_daily)")}
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert runtime == {column["name"] for column in inspector.get_columns("pair_metrics_daily")}
    assert inspector.get_pk_constraint("pair_metrics_daily")["constrained_columns"] == ["pair_id", "date"]
    assert inspector.get_foreign_keys("pair_metrics_daily")[0]["referred_table"] == "pairs"
    assert "idx_pair_metrics_date" in {index["name"] for index in inspector.get_indexes("pair_metrics_daily")}
    conn.close()
    engine.dispose()


@pytest.mark.parametrize("scenario", ["fresh", "phase2a", "runtime"])
def test_new_migration_fresh_and_existing_upgrade_preserve_teammate_and_pair_data(scenario, monkeypatch, tmp_path):
    path = tmp_path / f"{scenario}.db"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    try:
        if scenario != "fresh":
            if scenario == "phase2a":
                command.upgrade(config, "20261006_0008")
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
            else:
                conn = sqlite3.connect(path)
                initialize(conn)
            seed_pair(conn)
            conn.execute("CREATE TABLE teammate_data(id INTEGER PRIMARY KEY, note TEXT)")
            conn.execute("INSERT INTO teammate_data VALUES(1,'preserved')")
            conn.commit()
            conn.close()
            if scenario == "runtime":
                command.stamp(config, "20261006_0008")
        command.upgrade(config, "head")
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] >= "20261006_0009"
            assert len(conn.execute("PRAGMA table_info(pair_metrics_daily)").fetchall()) == 14
            if scenario != "fresh":
                assert conn.execute("SELECT note FROM teammate_data").fetchone()[0] == "preserved"
                assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 1
                assert conn.execute("SELECT count(*) FROM peer_matches").fetchone()[0] == 1
    finally:
        get_settings.cache_clear()
