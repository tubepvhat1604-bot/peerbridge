"""Reproducible offline Plan evaluation using the application's scheduler/validator."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
sys.path.insert(0, str(WORKSPACE / "backend"))

# Script entry point needs the backend source path before app imports.
from app.agents.plan_coach.artifacts import claim_run, new_run_path, write_json, write_text  # noqa: E402
from app.agents.plan_coach.contract import PlannerInput, PlannerOutput  # noqa: E402
from app.agents.plan_coach.eval import dataset, run_eval, write_run  # noqa: E402
from app.agents.plan_coach.scheduler import validate_plan  # noqa: E402


def load_dataset(path):
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("Dataset must be a non-empty list of pair cases")
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate pair-case IDs")
    for r in records:
        if r["split"] not in ("development", "holdout") or r.get("synthetic") is not True:
            raise ValueError("This offline runner requires explicit synthetic development/holdout records")
        PlannerInput.model_validate(r["input"])
    return records


def summarize(records, results_dir):
    """Validate saved accepted outputs again before reporting aggregate hard passes."""
    reports = []
    for mode in ("template", "fake"):
        for split in ("development", "holdout"):
            report = json.loads((results_dir / f"{mode}-{split}" / "results.json").read_text(encoding="utf-8"))
            selected = [r for r in records if r["split"] == split]
            expected_hash = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
            if report["mode"] != mode or report["dataset_sha256"] != expected_hash:
                raise ValueError("Saved results do not match mode/frozen dataset")
            if len(report["results"]) != len(selected) or {r["id"] for r in report["results"]} != {
                r["id"] for r in selected
            }:
                raise ValueError("Saved results are missing/duplicating pair cases")
            inputs = {r["id"]: r["input"] for r in selected}
            for result in report["results"]:
                if result["accepted"]:
                    validate_plan(
                        PlannerInput.model_validate(inputs[result["id"]]),
                        PlannerOutput.model_validate(result["output"]),
                    )
            reports.append(report)
    if len({r["prompt_sha256"] for r in reports}) != 1:
        raise ValueError("Development and holdout must use the same frozen prompt")
    modes = {}
    for mode in ("template", "fake"):
        runs = [r for r in reports if r["mode"] == mode]
        outcomes = [o for r in runs for o in r["results"]]
        accepted = [o for o in outcomes if o["accepted"]]
        plans = [p for o in accepted for p in o["output"]["plans"]]
        partial = sum(p["partial"] for p in plans)
        generated = sum(r["generated_pair_cases"] for r in runs)
        errors = sum(r["initial_generation_errors"] for r in runs)
        modes[mode] = {
            "pair_cases": len(outcomes),
            "accepted_pairs": len(accepted),
            "rejected_pairs": len(outcomes) - len(accepted),
            "rejection_rate": (len(outcomes) - len(accepted)) / len(outcomes),
            "accepted_personal_plans": len(plans),
            "hard_pass_personal_plans": len(plans),
            "partial_personal_plans": partial,
            "partial_personal_plan_rate": partial / len(plans) if plans else None,
            "partial_pair_cases": sum(o["partial"] for o in accepted),
            "generated_pairs": generated,
            "initial_generation_errors": errors,
            "initial_generation_error_rate": errors / generated if generated else None,
            "repaired_successfully": sum(r["repaired_successfully"] for r in runs),
        }
    return {
        "synthetic": True,
        "unique_personas": 2 * len(records),
        "development_personas": 2 * sum(r["split"] == "development" for r in records),
        "holdout_personas": 2 * sum(r["split"] == "holdout" for r in records),
        "first_run_at": min(r["ran_at"] for r in reports),
        "last_run_at": max(r["ran_at"] for r in reports),
        "prompt_version": reports[0]["prompt_version"],
        "prompt_sha256": reports[0]["prompt_sha256"],
        "accepted_outputs_revalidated": True,
        "by_mode": modes,
        "human_rating_count": 0,
        "llm_judge_count": 0,
        "human_rubric_average": None,
        "llm_judge_average": None,
        "quality_target_verified": False,
        "interpretation": "Synthetic template/fake only. Fake errors are injected, not a live LLM error rate. No human scores or causal claims.",
    }


def write_summary(output, summary):
    claim_run(output)
    write_json(output / "summary.json", summary)
    rubric_link = Path(os.path.relpath(WORKSPACE / "docs/plan-eval-rubric.md", output)).as_posix()
    readme_link = Path(os.path.relpath(HERE / "README.md", output)).as_posix()
    testing_link = Path(os.path.relpath(WORKSPACE / "docs/plan-coach-testing.md", output)).as_posix()
    lines = [
        "# Eval Plan — kết quả chạy thực tế trên persona synthetic",
        "",
        f"{summary['unique_personas']} persona; development {summary['development_personas']}, holdout {summary['holdout_personas']}. Cùng dataset chạy ở hai mode, không cộng thành hai nhóm người khác nhau.",
        "",
        f"Prompt `{summary['prompt_version']}`, SHA-256 `{summary['prompt_sha256']}`. Lượt chạy {summary['first_run_at']} → {summary['last_run_at']}.",
        "",
        "| Mode | Cặp nhận/tổng | Personal plan hard-pass | Personal plan partial | Lỗi sinh đầu/ca sinh | Repair thành công |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode, r in summary["by_mode"].items():
        lines.append(
            f"| {mode} | {r['accepted_pairs']}/{r['pair_cases']} | {r['hard_pass_personal_plans']} | {r['partial_personal_plans']}/{r['accepted_personal_plans']} | {r['initial_generation_errors']}/{r['generated_pairs']} | {r['repaired_successfully']} |"
        )
    lines += [
        "",
        "Các output được chấp nhận đã được runner summary kiểm tra lại bằng validator của app. Xem từng lỗi/trace/split trong results/<mode>-<split>/results.json. Dataset thiếu prerequisite bị từ chối trước generator; không tính là lỗi sinh model.",
        "",
        "FakeLLM cố ý trả tasks rỗng ở lần đầu để kiểm tra repair. Đây không phải tỷ lệ lỗi của LLM thật. Plan partial chỉ đáp ứng một phần goal.",
        "",
        f"Chưa chạy AI/judge thật hoặc chấm tay: cả hai count=0, trung bình=null, mục tiêu ≥4/5 chưa xác nhận. CSV trống của mỗi run dành cho người chấm; hướng dẫn [rubric]({rubric_link}). Không dùng kết quả holdout để sửa prompt trong lượt bàn giao này.",
        "",
        f"[Hướng dẫn chạy]({readme_link}) · [Kiểm thử và thao tác app]({testing_link})",
    ]
    write_text(output / "report.md", "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=HERE / "dataset.json")
    parser.add_argument("--write-dataset", action="store_true", help="Export the app's synthetic persona fixtures")
    parser.add_argument("--mode", choices=("template", "fake"), default="template")
    parser.add_argument("--split", choices=("development", "holdout"), default="development")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument(
        "--results-dir", type=Path, help="Parent containing four mode/split runs; required for --summarize"
    )
    args = parser.parse_args()
    try:
        if args.write_dataset:
            args.dataset.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.dataset, dataset())
            print(f"Exported synthetic dataset: {args.dataset}")
            return
        records = load_dataset(args.dataset)
        if args.summarize:
            if args.results_dir is None:
                raise ValueError("--summarize requires an explicit --results-dir")
            summary = summarize(records, args.results_dir)
            output = args.output or new_run_path(HERE / "summaries", "summary")
            write_summary(output, summary)
            print(f"Artifacts: {output}")
            print(json.dumps(summary, ensure_ascii=False))
            return
        selected = [r for r in records if r["split"] == args.split]
        if not selected:
            raise ValueError("Selected split is empty")
        report = asyncio.run(run_eval(args.mode, selected))
        output = args.output or (
            args.results_dir / f"{args.mode}-{args.split}"
            if args.results_dir
            else new_run_path(HERE / "runs", f"{args.mode}-{args.split}")
        )
        write_run(output, selected, report)
        print(f"Artifacts: {output}")
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Evaluation failed: {error}\n")


if __name__ == "__main__":
    main()
