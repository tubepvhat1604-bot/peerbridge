"""Dựng báo cáo Markdown từ metric và kết quả."""

from pydantic import BaseModel

from ....enums import ModerationAction
from .metrics import ACTIONS, CaseResult, Metrics

MESSAGE_PREVIEW = 70


class ReportMeta(BaseModel):
    """Thông tin chạy; không chứa key hay nội dung .env."""

    date: str
    mode: str
    split: str
    llm: str
    retriever: str
    dataset: str = "dataset.jsonl"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _preview(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "/")
    return flat if len(flat) <= MESSAGE_PREVIEW else flat[: MESSAGE_PREVIEW - 1] + "…"


def _case_table(results: list[CaseResult], ids: list[str]) -> list[str]:
    if not ids:
        return ["_Không có._", ""]
    by_id = {r.id: r for r in results}
    lines = ["| id | category | kỳ vọng | thực tế | tin nhắn |", "|---|---|---|---|---|"]
    for case_id in ids:
        r = by_id[case_id]
        expected = "/".join([r.expected_action.value, *[a.value for a in r.acceptable_actions]])
        lines.append(f"| {r.id} | {r.category} | {expected} | {r.actual_action.value} | {_preview(r.message)} |")
    return [*lines, ""]


def _confusion_table(metrics: Metrics) -> list[str]:
    lines = ["| kỳ vọng \\ thực tế | " + " | ".join(ACTIONS) + " |", "|---|" + "---|" * len(ACTIONS)]
    for expected in ACTIONS:
        row = metrics.confusion[expected]
        lines.append(f"| **{expected}** | " + " | ".join(str(row[a]) for a in ACTIONS) + " |")
    return [*lines, ""]


def render_report(meta: ReportMeta, metrics: Metrics, results: list[CaseResult]) -> str:
    """Báo cáo Markdown cho một lần chạy."""
    lines = [
        f"# Báo cáo eval Socratic Moderator — {meta.mode} / {meta.split}",
        "",
        f"- Ngày: {meta.date}",
        f"- Dataset: {meta.dataset}",
        f"- LLM: {meta.llm}",
        f"- Retriever: {meta.retriever}",
        f"- Số tin nhắn: {metrics.n}",
        "",
        "## Tóm tắt",
        "",
        "| Chỉ số | Giá trị |",
        "|---|---|",
        f"| Accuracy theo action (expected hoặc acceptable) | {_pct(metrics.accuracy)} |",
        f"| Accuracy theo intent | {_pct(metrics.intent_accuracy)} |",
        f"| Lỗi nghiêm trọng (cần ESCALATE/BLOCK mà bị ALLOW/GUIDE) | {len(metrics.severe_errors)} |",
        f"| Báo nhầm (không cần ESCALATE/BLOCK mà bị ESCALATE/BLOCK) | {len(metrics.false_alarms)} |",
        f"| Tin có vi phạm output_guard | {metrics.guard_violation_cases} |",
        f"| Lỗi LLM/retriever | {metrics.dependency_errors} |",
        f"| Latency p50 / p95 | {metrics.latency_p50_ms:.0f} ms / {metrics.latency_p95_ms:.0f} ms |",
        "",
        "## Precision / recall",
        "",
        "| Action | TP | FP | FN | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for action in (ModerationAction.ESCALATE, ModerationAction.BLOCK):
        s = metrics.class_stats[action.value]
        lines.append(f"| {action.value} | {s.tp} | {s.fp} | {s.fn} | {_pct(s.precision)} | {_pct(s.recall)} |")
    lines += ["", "## Accuracy theo category", "", "| Category | n | Accuracy |", "|---|---|---|"]
    lines += [f"| {c} | {n} | {_pct(acc)} |" for c, (n, acc) in metrics.per_category.items()]
    lines += ["", "## Confusion matrix", "", *_confusion_table(metrics)]
    lines += ["## Lỗi nghiêm trọng", "", *_case_table(results, metrics.severe_errors)]
    lines += ["## Báo nhầm", "", *_case_table(results, metrics.false_alarms)]
    lines += [f"## Tất cả câu sai ({len(metrics.wrong)})", "", *_case_table(results, metrics.wrong)]
    return "\n".join(lines)


def render_comparison(rules: Metrics, live: Metrics) -> str:
    """Bảng so sánh rules và live."""
    rows = [
        ("Accuracy", _pct(rules.accuracy), _pct(live.accuracy)),
        ("Accuracy intent", _pct(rules.intent_accuracy), _pct(live.intent_accuracy)),
        ("Lỗi nghiêm trọng", str(len(rules.severe_errors)), str(len(live.severe_errors))),
        ("Báo nhầm", str(len(rules.false_alarms)), str(len(live.false_alarms))),
        ("Latency p50 (ms)", f"{rules.latency_p50_ms:.0f}", f"{live.latency_p50_ms:.0f}"),
        ("Latency p95 (ms)", f"{rules.latency_p95_ms:.0f}", f"{live.latency_p95_ms:.0f}"),
    ]
    lines = ["## So sánh rules và live", "", "| Chỉ số | rules | live |", "|---|---|---|"]
    return "\n".join([*lines, *[f"| {name} | {a} | {b} |" for name, a, b in rows], ""])
