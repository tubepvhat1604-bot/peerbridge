import importlib.util
from pathlib import Path

import pytest
from app.matching.engine import result_for
from app.matching.validation import explanation_is_grounded

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase2a_eval", ROOT / "eval/matching/run_phase2a.py")
assert spec and spec.loader
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_thirty_persona_labels_and_precision_at_three_metric():
    profiles, labels = evaluation.load_personas()
    assert len(profiles) == len(labels) == 30
    assert evaluation.precision_at_k([1, 2, 3], {2, 3}) == pytest.approx(2 / 3)
    assert evaluation.precision_at_k([1], {1}) == pytest.approx(1 / 3)
    assert evaluation.precision_at_k([1, 1, 1], {1}) == pytest.approx(1 / 3)
    report, samples = evaluation.evaluate()
    assert report["precision_at_3"] >= .7
    assert report["automated_explanation_checks"] == 90 and report["factuality_failures"] == 0
    assert len(samples) == 20 and all(s["human_review"] == "PENDING" for s in samples)


@pytest.mark.parametrize("mutation", ["concept", "slot", "hours", "deadline", "candidate", "prose", "score"])
def test_factuality_guard_rejects_unsupported_claims(mutation):
    profiles, _ = evaluation.load_personas()
    a, b = profiles[0], profiles[3]
    result = result_for(a, b)
    assert explanation_is_grounded(result, a, b)
    if mutation == "concept":
        result.facts.concepts_a_receives_from_b = ["sql.fake"]
    elif mutation == "slot":
        result.facts.common_slots = []
    elif mutation == "hours":
        result.facts.weekly_hours_b = 7
    elif mutation == "deadline":
        result.facts.deadline_difference_days = 1
    elif mutation == "candidate":
        result.candidate_user_id = 999
    elif mutation == "prose":
        result.explanation = "Their personality and history guarantee success. They are motivated."
    else:
        result.component_scores.coverage_b_by_a = 0
    assert not explanation_is_grounded(result, a, b)
