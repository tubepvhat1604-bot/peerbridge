"""Synthetic metadata-only external trace probe; no LLM or notification calls."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import claim_run, new_run_path, write_json
from .llm import PROMPT_VERSION, PlanSettings
from .tracing import emit_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    output = args.output_dir or new_run_path(root / "docs/evidence/ai-data-2", "trace-smoke")
    claim_run(output)
    settings = PlanSettings(trace_verify=True)
    result = emit_trace(
        settings,
        "planner_smoke",
        {
            "prompt_version": PROMPT_VERSION,
            "model": "synthetic-metadata-probe",
            "mode": "fake",
            "repairs": 0,
            "request_count": 0,
            "latency_ms": 0,
            "usage": None,
        },
    )
    report = {
        "ran_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "llm_requests": 0,
        "real_notification_sends": 0,
        "pilot": False,
        "trace": result,
        "trace_service_request_limit": 3,
    }
    write_json(output / "results.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
