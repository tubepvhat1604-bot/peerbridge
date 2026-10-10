"""Offline evidence and blank human rubric, not synthetic pilot or model-quality scores."""

import argparse
import asyncio
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import claim_run, write_json
from .fixtures import synthetic_context
from .llm import PROMPT_VERSION, SYSTEM_PROMPT, FakeLLM, PlannerFailureError, TemplateLLM, divide_tasks
from .scheduler import PlanValidationError, schedule, template_tasks, validate_plan

DIMENSIONS = ["goal_fit", "feasibility", "specificity", "schedule_accuracy", "if_then_accuracy"]


def dataset():
    cases = [
        "normal",
        "little_time",
        "missing_prerequisite",
        "no_shared_time",
        "impossible_deadline",
        "late",
        "normal",
        "normal",
        "little_time",
        "no_shared_time",
    ]
    result = []
    for n, case in enumerate(cases):
        ctx = synthetic_context(case, n)
        split = "development" if n < 7 else "holdout"
        if n == 6:
            ctx.members[0].known_concept_ids += ["sql.select"]
        if n == 7:
            ctx.members[0].committed_minutes_per_week = 240
            ctx.members[1].committed_minutes_per_week = 90
        if n == 8:
            ctx.members[0].availability = []
        if n == 9:
            ctx.members[0].deadline = ctx.planning_start.replace(hour=20)
        result.append(
            {
                "id": f"pair-{n + 1:02}",
                "split": split,
                "case": case,
                "synthetic": True,
                "input": ctx.model_dump(mode="json"),
            }
        )
    return result


async def run_eval(mode, selected):
    from .contract import PlannerInput

    results = []
    for record in selected:
        ctx = PlannerInput.model_validate(record["input"])
        outcome = {
            "id": record["id"],
            "split": record["split"],
            "case": record["case"],
            "provider_mode": mode,
            "synthetic": True,
        }
        try:
            required = template_tasks(ctx)
            llm = (
                TemplateLLM(ctx)
                if mode == "template"
                else FakeLLM([{"tasks": []}, {"tasks": [t.model_dump(mode="json") for t in required]}])
            )
            tasks, trace = await divide_tasks(ctx, llm)
            output = schedule(ctx, tasks)
            validate_plan(ctx, output)
            outcome.update(
                {
                    "accepted": True,
                    "hard_constraints_passed": True,
                    "partial": any(p.partial for p in output.plans),
                    "trace": trace,
                    "output": output.model_dump(mode="json"),
                }
            )
        except PlanValidationError as error:
            outcome.update(
                {
                    "accepted": False,
                    "hard_constraints_passed": False,
                    "partial": False,
                    "errors": [i.model_dump(mode="json") for i in error.issues],
                }
            )
            if isinstance(error, PlannerFailureError):
                outcome["trace"] = error.trace
        results.append(outcome)
    generated = [r for r in results if "trace" in r]
    initially_invalid = [r for r in generated if r["trace"]["attempts"][0]["errors"]]
    accepted = [r for r in results if r["accepted"]]
    personal_plans = [p for r in accepted for p in r["output"]["plans"]]
    partial_pairs = sum(r["partial"] for r in accepted)
    partial_personal = sum(p["partial"] for p in personal_plans)
    error_codes = Counter(e["code"] for r in results for e in r.get("errors", []))
    return {
        "ran_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "synthetic": True,
        "splits": dict(Counter(r["split"] for r in selected)),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "dataset_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
        "pair_cases": len(results),
        "personas": 2 * len(results),
        "accepted": len(accepted),
        "rejected": len(results) - len(accepted),
        "hard_pass_among_accepted": sum(r["hard_constraints_passed"] for r in accepted),
        "initial_generation_errors": len(initially_invalid),
        "repaired_successfully": sum(r["accepted"] for r in initially_invalid),
        "partial_plans": partial_pairs,  # Legacy field counts pair cases, not individual plans.
        "partial_pair_cases": partial_pairs,
        "accepted_personal_plans": len(personal_plans),
        "partial_personal_plans": partial_personal,
        "generated_pair_cases": len(generated),
        "rejected_before_generation": len(results) - len(generated),
        "rejection_codes": dict(error_codes),
        "rates": {
            "rejection_pair_rate": (len(results) - len(accepted)) / len(results) if results else None,
            "initial_generation_error_rate": len(initially_invalid) / len(generated) if generated else None,
            "partial_pair_rate": partial_pairs / len(accepted) if accepted else None,
            "partial_personal_plan_rate": partial_personal / len(personal_plans) if personal_plans else None,
            "hard_pass_among_accepted_rate": (
                sum(r["hard_constraints_passed"] for r in accepted) / len(accepted) if accepted else None
            ),
        },
        "human_rating_count": 0,
        "llm_judge_count": 0,
        "human_rubric_average": None,
        "llm_judge_average": None,
        "quality_target": 4.0,
        "quality_target_verified": False,
        "results": results,
    }


def write_run(output, selected, report):
    claim_run(output)
    write_json(output / "dataset.json", selected)
    write_json(output / "results.json", report)
    with (output / "human-rubric.csv").open("x", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_case", "user_id", "split", "rater", *DIMENSIONS, "notes"])
        for r in report["results"]:
            for p in r.get("output", {}).get("plans", []):
                writer.writerow([r["id"], p["user_id"], r["split"], "", *([""] * len(DIMENSIONS)), ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["template", "fake"], default="template")
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    all_records = dataset()
    selected = [r for r in all_records if args.split == "all" or r["split"] == args.split]
    try:
        report = asyncio.run(run_eval(args.mode, selected))
        write_run(args.output, selected, report)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Evaluation failed: {error}\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
