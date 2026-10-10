"""Eval pipeline chấm phiên: đo độ đúng của "lộ đáp án" và "tuân thủ Socratic" trên bộ phiên mẫu có nhãn.

Chạy từ thư mục backend:
    python -m app.session_review.eval --mode rules          # không gọi AI (baseline)
    python -m app.session_review.eval --mode live           # LLM-as-Judge thật, cần OPENAI_API_KEY + LLM_PROVIDER=openai
Báo cáo Markdown ghi vào eval/session_review/ ở gốc repo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

from .judge import SessionReview, ai_review, rules_review

DATASET = Path(__file__).with_name("eval_dataset.jsonl")
REPORT_DIR = Path(__file__).resolve().parents[3] / "eval" / "session_review"
SOCRATIC_HIGH = 0.5


def load_dataset(path: Path = DATASET) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def to_messages(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": index + 1, "sender_role": role, "content": content, "final_action": "ALLOW", "guidance": None,
             "review_action": None} for index, (role, content) in enumerate(case["messages"])]


def socratic_label(score: float | None) -> str:
    if score is None:
        return "none"
    return "high" if score >= SOCRATIC_HIGH else "low"


def score(cases: list[dict[str, Any]], reviews: list[SessionReview]) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    socratic_ok = socratic_n = 0
    rows = []
    for case, review in zip(cases, reviews, strict=True):
        expected_leak = case["expected"]["answer_leaked"]
        tp += expected_leak and review.answer_leaked
        fp += (not expected_leak) and review.answer_leaked
        fn += expected_leak and not review.answer_leaked
        tn += (not expected_leak) and not review.answer_leaked
        expected_socratic = case["expected"]["socratic"]
        got = socratic_label(review.socratic_score)
        if expected_socratic != "none":
            socratic_n += 1
            socratic_ok += got == expected_socratic
        rows.append({"id": case["id"], "leak_expected": expected_leak, "leak_got": review.answer_leaked,
                     "socratic_expected": expected_socratic, "socratic_got": got, "score": review.socratic_score,
                     "mode": review.mode})
    total = len(cases)
    return {
        "n": total,
        "leak_accuracy": (tp + tn) / total if total else 0.0,
        "leak_precision": tp / (tp + fp) if tp + fp else 1.0,
        "leak_recall": tp / (tp + fn) if tp + fn else 1.0,
        "socratic_accuracy": socratic_ok / socratic_n if socratic_n else 0.0,
        "rows": rows,
    }


async def run(mode: str, cases: list[dict[str, Any]], llm: Any = None) -> list[SessionReview]:
    reviews = []
    for case in cases:
        messages = to_messages(case)
        if mode == "rules":
            reviews.append(rules_review(case["topic"], messages))
        else:
            review, _error = await ai_review(llm, case["topic"], messages)
            reviews.append(review)
    return reviews


def report(mode: str, result: dict[str, Any]) -> str:
    lines = [f"# Eval chấm phiên học: {mode}", "", f"- Ngày: {date.today().isoformat()}",
             f"- Bộ dữ liệu: backend/app/session_review/eval_dataset.jsonl ({result['n']} phiên)", "",
             "| Chỉ số | Giá trị |", "|---|---|",
             f"| Độ đúng phát hiện lộ đáp án | {result['leak_accuracy']:.0%} |",
             f"| Precision lộ đáp án | {result['leak_precision']:.0%} |",
             f"| Recall lộ đáp án | {result['leak_recall']:.0%} |",
             f"| Độ đúng nhãn Socratic (cao/thấp) | {result['socratic_accuracy']:.0%} |", "",
             "| Phiên | Lộ (kỳ vọng) | Lộ (chấm) | Socratic (kỳ vọng) | Socratic (chấm) | Điểm |",
             "|---|---|---|---|---|---|"]
    for row in result["rows"]:
        lines.append(f"| {row['id']} | {row['leak_expected']} | {row['leak_got']} | {row['socratic_expected']} | "
                     f"{row['socratic_got']} | {row['score']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rules", "live"), default="rules")
    args = parser.parse_args()
    llm = None
    if args.mode == "live":
        from .service import review_llm

        llm = review_llm()
        if llm is None:
            raise SystemExit("Chế độ live cần LLM_PROVIDER=openai và OPENAI_API_KEY")
    cases = load_dataset()
    result = score(cases, asyncio.run(run(args.mode, cases, llm)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"report-{date.today().isoformat()}-{args.mode}.md"
    out.write_text(report(args.mode, result), encoding="utf-8")
    print(f"Đã ghi {out}")


if __name__ == "__main__":
    main()
