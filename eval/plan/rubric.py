"""Prepare a fresh human rating table or summarize submitted CSV files read-only."""

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "backend"))
from app.agents.plan_coach.artifacts import new_run_path  # noqa: E402
from app.agents.plan_coach.rubric import aggregate, prepare, save_summary  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--ratings", nargs="+", type=Path)
    parser.add_argument("--legacy-source", choices=("human", "llm_judge"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or new_run_path(WORKSPACE / "eval/plan/ratings", "prepare" if args.prepare else "summary")
    try:
        if args.prepare:
            if args.ratings:
                raise ValueError("PREPARE_OR_AGGREGATE_ONLY")
            summary = prepare(args.run_dir, output)
        else:
            if not args.ratings:
                raise ValueError("RATINGS_REQUIRED")
            summary = aggregate(args.run_dir, args.ratings, args.legacy_source)
            save_summary(output, summary)
        print(json.dumps(summary, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            2,
            "Rubric rejected: invalid IDs/scores/source/provenance/duplicate or existing output. No file overwritten.\n",
        )


if __name__ == "__main__":
    main()
