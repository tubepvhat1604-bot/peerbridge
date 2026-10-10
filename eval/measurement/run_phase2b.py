"""Offline internal measurement regression. Run: python eval/measurement/run_phase2b.py"""

import json
import sys
from datetime import UTC, date, datetime, timedelta
from math import isclose
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.metrics.contracts import (  # noqa: E402
    FinalizedCheckin,
    MeasurementInput,
    PairContext,
    PlanWorkload,
    RiskObservation,
)
from app.metrics.engine import compute_metrics  # noqa: E402
from app.metrics.time import study_date  # noqa: E402

DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
START = NOW - timedelta(days=30)


def build_input(case):
    items, checkins = [], []
    for index, user_id in enumerate((1, 2)):
        due, credit = case["due"][index], case["credit"][index]
        if due:
            items.append(PlanWorkload(id=f"due-{user_id}", user_id=user_id, pair_id=1, concept_id="sql.join",
                                      estimated_minutes=due, due_date=DAY - timedelta(days=3) if case.get("overdue") else DAY))
        if credit:
            # Separate early work gives explicit completed/due workload without assuming task-count ratios.
            items.append(PlanWorkload(id=f"credit-{user_id}", user_id=user_id, pair_id=1, concept_id="sql.join",
                                      estimated_minutes=credit, due_date=DAY + timedelta(days=1)))
            checkins.append(FinalizedCheckin(id=f"credit-c-{user_id}", user_id=user_id, pair_id=1,
                                            plan_item_id=f"credit-{user_id}", status="done", created_at=NOW, finalized_at=NOW))
            if case.get("duplicates"):
                checkins.extend([checkins[-1], checkins[-1].model_copy(update={"id": f"duplicate-{user_id}"})])
        if case.get("future_unfinished"):
            items.append(PlanWorkload(id=f"future-{user_id}", user_id=user_id, pair_id=1, concept_id="py.functions",
                                      estimated_minutes=60, due_date=DAY + timedelta(days=1)))
        times = [NOW + timedelta(days=offset) for offset in case.get("presence_days", [])]
        if "presence_at" in case:
            times.append(datetime.fromisoformat(case["presence_at"]))
        for n, timestamp in enumerate(times):
            checkins.append(FinalizedCheckin(id=f"presence-{user_id}-{n}", user_id=user_id, pair_id=1,
                                            status="done", created_at=timestamp, finalized_at=timestamp))
    observations = [RiskObservation(user_id=1, observed_at=NOW, latest_reminder_responded=False,
                                   theta_stagnant=True)] if case.get("risk_observations") else []
    return MeasurementInput(pair=PairContext(pair_id=1, user_a=1, user_b=2, started_at=START),
                            source_revision=case["id"], plans_ready=True, history_complete=True,
                            plan_items=items, checkins=checkins, risk_observations=observations)


def evaluate():
    dataset = json.loads(Path(__file__).with_name("scenarios.json").read_text(encoding="utf-8"))
    outcomes = []
    for case in dataset["scenarios"]:
        metric = compute_metrics(build_input(case), DAY, NOW)
        checks = {
            "pacing_a": isclose(metric.pacing_a, case["expected_pacing"][0], abs_tol=1e-12),
            "pacing_b": isclose(metric.pacing_b, case["expected_pacing"][1], abs_tol=1e-12),
            "pair_score": isclose(metric.pair_score, case["expected_score"], abs_tol=1e-12),
            "gap": isclose(metric.gap, case["expected_gap"], abs_tol=1e-12),
            "invariants": metric.pair_score == min(metric.pacing_a, metric.pacing_b) and metric.gap == abs(metric.pacing_a - metric.pacing_b),
            "risk_range": 0 <= metric.risk_a.score <= metric.risk_a.upper_bound <= 1 and 0 <= metric.risk_b.score <= 1,
        }
        for expected, actual in [("expected_streak", metric.streak), ("expected_absent", metric.absent_members),
                                 ("expected_gap_attention", metric.gap_exceeds_threshold)]:
            if expected in case:
                checks[expected] = actual == case[expected]
        if "expected_risk_a" in case:
            checks["risk_a"] = isclose(metric.risk_a.score, case["expected_risk_a"], abs_tol=1e-12)
        if "expected_presence_date" in case:
            checks["presence_date"] = study_date(datetime.fromisoformat(case["presence_at"])).isoformat() == case["expected_presence_date"]
        outcomes.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                         "pacing_a": metric.pacing_a, "pacing_b": metric.pacing_b, "pair_score": metric.pair_score,
                         "gap": metric.gap, "risk_a": metric.risk_a.score, "streak": metric.streak})
    return {"evaluation": "internal measurement regression/evaluation", "authorship": dataset["authorship"],
            "cases": len(outcomes), "passed": sum(item["passed"] for item in outcomes), "outcomes": outcomes}


if __name__ == "__main__":
    report = evaluate()
    Path(__file__).with_name("results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "outcomes"}, indent=2))
    raise SystemExit(0 if report["passed"] == report["cases"] else 1)
