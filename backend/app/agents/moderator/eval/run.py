"""Runner eval cho moderator.

Chạy: python -m app.agents.moderator.eval.run --mode rules|live|both --split dev|test|all
  rules: FakeLLM trung tính + FakeRetriever, không gọi mạng.
  live:  settings thật (.env): LLM + retriever theo cấu hình.
Báo cáo và kết quả ghi vào <repo>/eval/moderator/.
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import BaseModel

from ..contract import ChatTurn, ModeratorInput, ModeratorOutput
from ..graph import build_moderator_graph, run_moderator_with_state, warmup_moderator
from ..hitl import ModerationEventRecord, build_event_record, moderate_message_with_event
from ..llm import neutral_fake_llm
from ..retriever import FakeRetriever
from ..settings import ModeratorSettings, get_moderator_settings
from .metrics import CaseResult, Metrics, compute_metrics, make_result
from .report import ReportMeta, render_comparison, render_report
from .schema import DATASET_PATH, EVAL_DIR, EvalCase, filter_split, load_dataset

REPO_ROOT = EVAL_DIR.parents[4]
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "moderator"
Runner = Callable[[ModeratorInput], Awaitable[tuple[ModeratorOutput, ModerationEventRecord]]]

_NAMESPACE = UUID("2f7d2a5e-8d3c-4a67-9f57-0d6f3b1c9a11")
_PEER_ID = uuid5(_NAMESPACE, "peer")
_ME_ID = uuid5(_NAMESPACE, "me")


def build_payload(case: EvalCase) -> ModeratorInput:
    """Dựng ModeratorInput ổn định (id sinh từ case.id) từ một case."""
    return ModeratorInput(
        session_id=uuid5(_NAMESPACE, f"session:{case.id}"),
        message_id=uuid5(_NAMESPACE, f"message:{case.id}"),
        sender_id=_ME_ID,
        message=case.message,
        course_id=case.course_id,
        conversation_history=[
            ChatTurn(sender_id=_ME_ID if item.who == "me" else _PEER_ID, content=item.content) for item in case.history
        ],
    )


def make_rules_runner() -> Runner:
    """Runner chỉ dùng rule: FakeLLM trung tính (confidence 0) + FakeRetriever rỗng."""
    graph = build_moderator_graph(neutral_fake_llm(), FakeRetriever(), ModeratorSettings(_env_file=None))

    async def run(payload: ModeratorInput) -> tuple[ModeratorOutput, ModerationEventRecord]:
        output, state = await run_moderator_with_state(graph, payload)
        return output, build_event_record(payload, output, state, "fake")

    return run


def make_live_runner() -> Runner:
    """Runner dùng settings thật, cùng đường chạy với service layer."""
    return moderate_message_with_event


async def run_cases(cases: list[EvalCase], runner: Runner) -> list[CaseResult]:
    """Chạy tuần tự (để đo latency từng tin) và gom CaseResult."""
    results: list[CaseResult] = []
    for case in cases:
        start = time.perf_counter()
        output, event = await runner(build_payload(case))
        latency_ms = (time.perf_counter() - start) * 1000
        actual = {
            "actual_action": output.action,
            "actual_intent": event.intent.value if event.intent else None,
            "risk_score": output.risk_score,
            "guidance": output.guidance,
            "reason": output.reason,
            "errors": event.errors,
        }
        results.append(make_result(case, actual, latency_ms))
    return results


class RunConfig(BaseModel):
    """Tham số một lần chạy eval."""

    modes: list[str]
    split: str
    out_dir: Path
    dataset: Path = DATASET_PATH


def _meta(mode: str, config: RunConfig) -> ReportMeta:
    if mode == "rules":
        llm, retriever = "FakeLLM trung tính (chỉ rule)", "FakeRetriever (rỗng)"
    else:
        settings = get_moderator_settings()
        llm = "fake (thiếu key hoặc LLM_PROVIDER=fake)" if settings.llm_provider == "fake" else settings.llm_model
        retriever = settings.retriever_provider
    return ReportMeta(
        date=date.today().isoformat(),
        mode=mode,
        split=config.split,
        llm=llm,
        retriever=retriever,
        dataset=config.dataset.name,
    )


def write_outputs(meta: ReportMeta, results: list[CaseResult], out_dir: Path, extra: str = "") -> tuple[Path, Path]:
    """Ghi report-<ngày>-<mode>-<split>.md và results-<ngày>-<mode>-<split>.jsonl; trả (report, results)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{meta.date}-{meta.mode}-{meta.split}"
    report_path, results_path = out_dir / f"report-{stem}.md", out_dir / f"results-{stem}.jsonl"
    report = render_report(meta, compute_metrics(results), results)
    report_path.write_text(report + ("\n" + extra if extra else "") + "\n", encoding="utf-8")
    results_path.write_text(
        "".join(r.model_dump_json() + "\n" for r in results),
        encoding="utf-8",
    )
    return report_path, results_path


def format_summary(mode: str, metrics: Metrics, results: list[CaseResult]) -> str:
    """Bảng tóm tắt và danh sách câu sai để in ra terminal."""
    esc, blk = metrics.class_stats["ESCALATE"], metrics.class_stats["BLOCK"]

    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    lines = [
        f"=== {mode}: {metrics.n} tin ===",
        f"accuracy action {metrics.accuracy:.1%} | intent {metrics.intent_accuracy:.1%}",
        f"lỗi nghiêm trọng {len(metrics.severe_errors)} | báo nhầm {len(metrics.false_alarms)} "
        f"| vi phạm guard {metrics.guard_violation_cases} | lỗi LLM/retriever {metrics.dependency_errors}",
        f"ESCALATE P={fmt(esc.precision)} R={fmt(esc.recall)} | BLOCK P={fmt(blk.precision)} R={fmt(blk.recall)}",
        f"latency p50 {metrics.latency_p50_ms:.0f}ms p95 {metrics.latency_p95_ms:.0f}ms",
        f"câu sai ({len(metrics.wrong)}):",
    ]
    by_id = {r.id: r for r in results}
    for case_id in metrics.wrong:
        r = by_id[case_id]
        expected = "/".join([r.expected_action.value, *[a.value for a in r.acceptable_actions]])
        flag = " [NGHIÊM TRỌNG]" if r.severe_error else " [báo nhầm]" if r.false_alarm else ""
        lines.append(f"  {r.id:4} {expected:>18} -> {r.actual_action.value:8}{flag} {' '.join(r.message.split())[:60]}")
    return "\n".join(lines)


async def run_mode(mode: str, cases: list[EvalCase]) -> list[CaseResult]:
    """Chạy một mode; live thì warmup trước để latency không gồm thời gian nạp model."""
    if mode == "rules":
        return await run_cases(cases, make_rules_runner())
    await warmup_moderator()
    return await run_cases(cases, make_live_runner())


async def main_async(config: RunConfig) -> None:
    """Chạy các mode, ghi file và in tóm tắt. Raise ValueError nếu split không có case nào."""
    cases = filter_split(load_dataset(config.dataset), config.split)
    if not cases:
        raise ValueError(f"Không có case nào với split={config.split!r} trong {config.dataset.name}")
    computed: dict[str, Metrics] = {}
    for mode in config.modes:
        results = await run_mode(mode, cases)
        metrics = computed[mode] = compute_metrics(results)
        extra = render_comparison(computed["rules"], metrics) if mode == "live" and "rules" in computed else ""
        report_path, results_path = write_outputs(_meta(mode, config), results, config.out_dir, extra)
        print(format_summary(mode, metrics, results))
        print(f"-> {report_path}\n-> {results_path}")


def main(argv: list[str] | None = None) -> None:
    """CLI."""
    parser = argparse.ArgumentParser(description="Eval Socratic Moderator")
    parser.add_argument("--mode", choices=["rules", "live", "both"], default="rules")
    parser.add_argument("--split", choices=["dev", "test", "holdout", "all"], default="all")
    parser.add_argument(
        "--dataset", type=Path, default=DATASET_PATH, help="đường dẫn dataset .jsonl (mặc định: dataset.jsonl)"
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    modes = ["rules", "live"] if args.mode == "both" else [args.mode]
    config = RunConfig(modes=modes, split=args.split, out_dir=args.out_dir, dataset=args.dataset)
    try:
        asyncio.run(main_async(config))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Lỗi: {exc}\n")


if __name__ == "__main__":
    main()
