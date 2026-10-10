import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.agents.plan_coach.variants import assigned_variant, choose_variant


def test_seeded_assignment_reproducible_per_pair_and_has_both_groups():
    first = [choose_variant(i, "test-seed") for i in range(1, 40)]
    assert first == [choose_variant(i, "test-seed") for i in range(1, 40)]
    assert set(first) == {"ai", "template"}


def test_old_assignment_is_kept_when_seed_or_feature_flag_changes(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE pb_variants(pair_id INTEGER PRIMARY KEY,variant TEXT NOT NULL)")
    db.execute("INSERT INTO pb_variants VALUES (1,'template')")

    def forbidden(*args):
        raise AssertionError("Existing pairs must never be re-randomized")

    monkeypatch.setattr("app.agents.plan_coach.variants.choose_variant", forbidden)
    assert assigned_variant(db, 1, "new-seed") == "template"
    assert assigned_variant(db, 1, None) == "template"
    db.close()


def test_random_assignment_commits_once_under_concurrent_calls(tmp_path):
    path = tmp_path / "assignment.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE pb_variants(pair_id INTEGER PRIMARY KEY,variant TEXT NOT NULL)")
    barrier = Barrier(8)

    def assign(_):
        barrier.wait()
        with sqlite3.connect(path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            return assigned_variant(db, 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assignments = list(pool.map(assign, range(8)))
    assert len(set(assignments)) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pb_variants").fetchone()[0] == 1
