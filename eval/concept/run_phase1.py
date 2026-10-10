"""Offline fixture evaluation. Does not read credentials, download models or write reports."""

import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.onboarding.contracts import TopicInput  # noqa: E402
from app.onboarding.normalization import ConceptNormalizer  # noqa: E402


async def evaluate() -> dict:
    cases = [json.loads(line) for line in (Path(__file__).parent / "phase1_cases.jsonl").read_text(
        encoding="utf-8",
    ).splitlines() if line]
    normalizer = ConceptNormalizer()
    results = []
    latencies = []
    for index, case in enumerate(cases):
        started = perf_counter()
        mapping = await normalizer.normalize(TopicInput(text=case["topic"], domain=case["domain"]), index)
        latencies.append(1000 * (perf_counter() - started))
        results.append({"topic": case["topic"], "expected": case["expected"], "actual": mapping.concept_id,
                        "correct": mapping.concept_id == case["expected"]})
    correct = sum(item["correct"] for item in results)
    positives = [item for item in results if item["expected"] is not None]
    negatives = [item for item in results if item["expected"] is None]
    return {
        "backend": "local_lexical+local_rules", "cases": len(cases), "correct": correct,
        "accuracy": correct / len(cases),
        "mapped_accuracy": sum(item["correct"] for item in positives) / len(positives),
        "null_accuracy": sum(item["correct"] for item in negatives) / len(negatives),
        "max_latency_ms": round(max(latencies), 3),
        "limitations": "Agent-authored regression fixtures; no independent human or live embedding/LLM evaluation.",
        "failures": [item for item in results if not item["correct"]],
    }


if __name__ == "__main__":
    report = asyncio.run(evaluate())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["accuracy"] >= 0.8 and not report["failures"] else 1)
