import asyncio
import csv
import json

import pytest
from app.agents.plan_coach.eval import dataset, run_eval, write_run
from app.agents.plan_coach.rubric import DIMENSIONS, aggregate, prepare


@pytest.fixture
def rating_table(tmp_path):
    selected = [dataset()[1]]  # Development, including a partial plan.
    run = tmp_path / "run"
    write_run(run, selected, asyncio.run(run_eval("template", selected)))
    output = tmp_path / "ratings"
    prepare(run, output)
    path = output / "ratings.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return run, path, rows


def fill(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_blank_real_rating_table_stays_null_and_marks_missing(rating_table):
    run, path, _ = rating_table
    before = path.read_bytes()
    report = aggregate(run, [path])
    assert report["by_source"]["human"]["rating_count"] == 0
    assert report["by_source"]["human"]["overall_mean"] is None
    assert report["by_source"]["human"]["missing_samples"] == 2
    assert not report["quality_target_verified"] and report["partial_samples"] == 1
    assert "chưa xác nhận" in report["quality_status"] and path.read_bytes() == before
    guide = (path.parent / "rating-guide.md").read_text(encoding="utf-8")
    assert "Giờ rảnh địa phương:" in guide and "Tiên quyết catalog:" in guide and "80%" in guide


def test_submitted_human_and_judge_scores_are_separate_and_never_infer_full_goal(rating_table):
    run, path, rows = rating_table
    rows[0].update(rater="synthetic-unit-test-rater", **{d: "4" for d in DIMENSIONS})
    rows[1].update(
        rater="synthetic-unit-test-judge",
        source="llm_judge",
        model="FakeJudge",
        prompt_version="judge-test",
        **{d: "5" for d in DIMENSIONS},
    )
    fill(path, rows)
    report = aggregate(run, [path])
    assert report["by_source"]["human"]["overall_mean"] == 4
    assert report["by_source"]["llm_judge"]["overall_mean"] == 5
    assert report["by_source"]["human"]["missing_samples"] == 1
    assert not report["full_goal_completion_inferred"] and not report["quality_target_verified"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "999"),
        ("split", "holdout"),
        ("pair_case", "invented"),
        ("goal_fit", "0"),
        ("goal_fit", "6"),
        ("goal_fit", "4.0"),
        ("goal_fit", "=5"),
        ("rater", ""),
        ("source", "unverified"),
        ("run_sha256", "other-run"),
        ("specificity", ""),
    ],
)
def test_invalid_ids_scores_sources_or_incomplete_rating_are_rejected(rating_table, field, value):
    run, path, rows = rating_table
    rows[0].update(rater="synthetic-unit-test-rater", **{d: "4" for d in DIMENSIONS})
    rows[0][field] = value
    fill(path, rows)
    with pytest.raises(ValueError):
        aggregate(run, [path])


def test_duplicates_are_rejected_instead_of_counted_twice(rating_table):
    run, path, rows = rating_table
    rows[0].update(rater="synthetic-unit-test-rater", **{d: "4" for d in DIMENSIONS})
    fill(path, [rows[0], rows[0]])
    with pytest.raises(ValueError, match="DUPLICATE_RATING"):
        aggregate(run, [path])
    with pytest.raises(ValueError, match="DUPLICATE_RATING"):
        aggregate(run, [path, path])


def test_llm_judge_requires_model_and_prompt_provenance(rating_table):
    run, path, rows = rating_table
    rows[0].update(rater="synthetic-unit-test-judge", source="llm_judge", **{d: "4" for d in DIMENSIONS})
    fill(path, rows)
    with pytest.raises(ValueError, match="JUDGE_PROVENANCE"):
        aggregate(run, [path])


def test_prepare_never_overwrites_existing_rated_file(rating_table):
    run, path, rows = rating_table
    rows[0].update(rater="synthetic-unit-test-rater", goal_fit="3")
    fill(path, rows)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(run, path.parent)
    assert path.read_bytes() == before


def test_corrupt_accepted_plan_cannot_be_used_to_claim_rubric_quality(rating_table):
    run, path, _ = rating_table
    result_path = run / "results.json"
    report = json.loads(result_path.read_text(encoding="utf-8"))
    scheduled = next(p for p in report["results"][0]["output"]["plans"] if p["items"])
    scheduled["items"][0]["scheduled_end"] = "2030-01-07T00:00:00+00:00"
    result_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        aggregate(run, [path])
