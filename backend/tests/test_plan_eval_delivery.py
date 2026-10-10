"""Handoff runners must preserve holdout integrity and real observation status."""

import asyncio
import importlib.util
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from app.agents.plan_coach.artifacts import claim_run, write_json
from app.agents.plan_coach.eval import dataset, run_eval

ROOT = Path(__file__).resolve().parents[2]


def runner(area):
    spec = importlib.util.spec_from_file_location(f"handoff_{area}", ROOT / "eval" / area / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nudge_fixture_reports_immature_response_as_pending_and_excludes_replay():
    nudge = runner("nudge")
    fixture = json.loads((ROOT / "eval/nudge/dataset.json").read_text(encoding="utf-8"))
    db = nudge.fixture_database(fixture)
    try:
        report = nudge.analyze(
            db, nudge.timestamp(fixture["as_of"]), source_kind="synthetic_boundary_fixture", simulation=True
        )
    finally:
        db.close()
    assert report["simulation"] and report["production_origin_verified"] is False
    assert report["sent_count"] == 4 and report["matured_count"] == 3 and report["pending_count"] == 1
    assert report["checkin_24h_count"] == 1 and report["observation_status"] == "PARTIALLY_MATURED"
    observations = {r["intervention_id"]: r for r in report["observations"]}
    assert observations["fixture-ai-immature"]["observed_checkin"] is True
    assert observations["fixture-ai-immature"]["status"] == "pending"
    assert observations["fixture-ai-replay"]["observed_checkin"] is False
    assert report["future_interventions_excluded"] == 1


def test_nudge_db_input_is_read_only_and_never_creates_missing_file(tmp_path):
    nudge = runner("nudge")
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        nudge.open_read_only(missing)
    assert not missing.exists()
    db_path = tmp_path / "snapshot.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE untouched(id INTEGER)")
    db = nudge.open_read_only(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO untouched VALUES (1)")
    finally:
        db.close()


@pytest.mark.parametrize("invalid", ["mixed_prompt", "invalid_accepted_output"])
def test_plan_summary_refuses_mixed_prompt_or_invalid_accepted_output(tmp_path, invalid):
    plan = runner("plan")
    cases = [dataset()[0], dataset()[7]]
    for mode in ("template", "fake"):
        for split in ("development", "holdout"):
            selected = [r for r in cases if r["split"] == split]
            report = asyncio.run(run_eval(mode, selected))
            plan.write_run(tmp_path / f"{mode}-{split}", selected, report)
    summary = plan.summarize(cases, tmp_path)
    assert summary["accepted_outputs_revalidated"] and summary["unique_personas"] == 4
    assert summary["human_rubric_average"] is None and summary["llm_judge_count"] == 0
    path = tmp_path / "template-holdout/results.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if invalid == "mixed_prompt":
        report["prompt_sha256"] = "different-prompt"
    else:
        report["results"][0]["output"]["plans"][0]["items"][0]["scheduled_end"] = "2030-01-07T00:01:00+00:00"
    # Deliberate corruption only inside this test's temporary run, not through the protected writer.
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        plan.summarize(cases, tmp_path)


@pytest.mark.parametrize("entry", ["plan", "backend_plan", "plan_summary", "nudge"])
def test_evidence_writers_preserve_rated_csv_and_previous_results(tmp_path, entry):
    output = tmp_path / "rated-run"
    output.mkdir()
    original = {
        "human-rubric.csv": b"rater,goal_fit,notes\nreviewer,4,keep my rating\n",
        "results.json": b'{"accepted":true,"source":"previous-run"}\n',
    }
    for name, content in original.items():
        (output / name).write_bytes(content)
    with pytest.raises(FileExistsError):
        if entry == "nudge":
            runner("nudge").write_report(output, {})
        elif entry == "plan_summary":
            runner("plan").write_summary(output, {})
        elif entry == "backend_plan":
            from app.agents.plan_coach.eval import write_run

            write_run(output, [], {})
        else:
            runner("plan").write_run(output, [], {})
    assert {p.name: p.read_bytes() for p in output.iterdir()} == original


def test_evidence_directory_claim_is_exclusive_under_concurrency(tmp_path):
    output = tmp_path / "same-run"
    barrier = Barrier(8)

    def attempt(index):
        barrier.wait()
        try:
            claim_run(output)
        except FileExistsError:
            return False
        write_json(output / "owner.json", {"owner": index})
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert sum(outcomes) == 1
    assert json.loads((output / "owner.json").read_text())["owner"] == outcomes.index(True)


def test_existing_empty_directory_and_individual_artifact_are_protected(tmp_path):
    output = tmp_path / "already-claimed"
    output.mkdir()
    with pytest.raises(FileExistsError):
        claim_run(output)
    path = output / "dataset.json"
    write_json(path, {"frozen": True})
    with pytest.raises(FileExistsError):
        write_json(path, {"frozen": False})
    assert json.loads(path.read_text()) == {"frozen": True}


def test_nudge_read_only_analysis_and_export_use_one_database_snapshot(tmp_path):
    nudge = runner("nudge")
    path = tmp_path / "concurrent.db"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE source(value INTEGER)")
        writer.execute("INSERT INTO source VALUES (1)")
    reader = nudge.open_read_only(path)
    try:
        assert reader.execute("SELECT value FROM source").fetchone()[0] == 1
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE source SET value=2")
        assert reader.execute("SELECT value FROM source").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("UPDATE source SET value=3")
    finally:
        reader.close()
    with sqlite3.connect(path) as reader:
        assert reader.execute("SELECT value FROM source").fetchone()[0] == 2


def test_nudge_first_successful_send_uses_actual_time_across_timezone_offsets():
    nudge = runner("nudge")
    fixture = {
        "synthetic": True,
        "interventions": [
            {
                "id": "offset-send",
                "pair_id": 1,
                "user_id": 101,
                "variant": "ai",
                "action": "reminder",
                "delivery_status": "SENT",
                "created_at": "2030-01-09T12:00:00+00:00",
                "attempts": [
                    {"status": "SENT", "created_at": "2030-01-09T20:00:00+07:00"},
                    {"status": "SENT", "created_at": "2030-01-09T14:00:00+00:00"},
                ],
            }
        ],
        "completions": [
            {"item_id": "first", "pair_id": 1, "user_id": 101, "completed_at": "2030-01-09T13:30:00+00:00"}
        ],
    }
    db = nudge.fixture_database(fixture)
    try:
        report = nudge.analyze(
            db, nudge.timestamp("2030-01-10T13:00:00+00:00"), source_kind="synthetic_boundary_fixture", simulation=True
        )
    finally:
        db.close()
    assert report["matured_count"] == 1 and report["pending_count"] == 0
    assert report["checkin_24h_count"] == 1
