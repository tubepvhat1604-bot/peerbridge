import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from app.agents.moderator.eval import rag_eval, run
from app.agents.moderator.eval.metrics import (
    CaseResult,
    class_stats,
    compute_metrics,
    confusion_matrix,
    percentile,
)
from app.agents.moderator.eval.report import ReportMeta, render_comparison, render_report
from app.agents.moderator.eval.schema import (
    DATASET_PATH,
    check_dataset,
    filter_split,
    load_dataset,
    load_rag_queries,
)
from app.enums import ModerationAction as A

REQUIRED_CATEGORIES = {
    "concept",
    "solution_request",
    "code_request",
    "code_debug",
    "answer_sharing",
    "exam_cheating",
    "insult",
    "contact_info",
    "social",
    "off_topic",
    "injection",
    "no_diacritics",
    "teencode",
    "english",
    "hard_negative",
}


# ---- Dataset ----


def test_dataset_is_valid_and_balanced() -> None:
    cases = load_dataset()

    assert 60 <= len(cases) <= 85
    assert check_dataset(cases) == []
    assert REQUIRED_CATEGORIES <= {c.category for c in cases}
    assert Counter(c.category for c in cases)["hard_negative"] >= 12
    dev_share = len(filter_split(cases, "dev")) / len(cases)
    assert 0.4 <= dev_share <= 0.6
    assert len({c.message for c in cases}) == len(cases)
    assert any(c.history for c in cases)


def test_dataset_lines_have_only_known_fields() -> None:
    known = {
        "id",
        "message",
        "history",
        "course_id",
        "expected_action",
        "acceptable_actions",
        "expected_intent",
        "category",
        "split",
        "note",
    }
    for line in DATASET_PATH.read_text(encoding="utf-8").splitlines():
        assert set(json.loads(line)) <= known


def test_check_dataset_reports_problems() -> None:
    cases = load_dataset()
    bad = [cases[0].model_copy(update={"acceptable_actions": [cases[0].expected_action]}), cases[0]]

    problems = check_dataset(bad)

    assert any("id trùng" in p for p in problems)
    assert any("acceptable_actions" in p for p in problems)
    assert any("chỉ có ở split" in p for p in problems)


# ---- Metrics ----


def _result(case_id: str, expected: A, actual: A, acceptable: list[A] | None = None, **kwargs) -> CaseResult:
    data = {
        "id": case_id,
        "category": "x",
        "split": "dev",
        "message": "m",
        "expected_action": expected,
        "acceptable_actions": acceptable or [],
        "expected_intent": "CONCEPT_QUESTION",
        "actual_action": actual,
        "actual_intent": "CONCEPT_QUESTION",
        "risk_score": 0.0,
    }
    data.update(kwargs)
    return CaseResult(**data)


def _small() -> list[CaseResult]:
    return [
        _result("1", A.ALLOW, A.ALLOW),
        _result("2", A.ALLOW, A.BLOCK),  # báo nhầm
        _result("3", A.ESCALATE, A.ALLOW),  # lỗi nghiêm trọng
        _result("4", A.ESCALATE, A.ESCALATE),
        _result("5", A.BLOCK, A.WARN, acceptable=[A.WARN]),  # đúng nhờ acceptable
        _result("6", A.GUIDE, A.ALLOW),  # sai nhưng không nghiêm trọng
        _result("7", A.WARN, A.ESCALATE, actual_intent="OFF_TOPIC"),  # báo nhầm
    ]


def test_correctness_severe_and_false_alarm_flags() -> None:
    by_id = {r.id: r for r in _small()}

    assert by_id["5"].correct and not by_id["2"].correct
    assert by_id["3"].severe_error and not by_id["6"].severe_error
    assert by_id["2"].false_alarm and by_id["7"].false_alarm and not by_id["3"].false_alarm
    assert not by_id["7"].intent_correct and by_id["1"].intent_correct


def test_compute_metrics_on_small_data() -> None:
    m = compute_metrics(_small())

    assert m.n == 7 and m.accuracy == pytest.approx(3 / 7)
    assert m.intent_accuracy == pytest.approx(6 / 7)
    assert m.severe_errors == ["3"] and m.false_alarms == ["2", "7"]
    assert m.wrong == ["2", "3", "6", "7"]
    # ESCALATE: TP=1 (#4), FP=1 (#7), FN=1 (#3)
    esc = m.class_stats["ESCALATE"]
    assert (esc.tp, esc.fp, esc.fn) == (1, 1, 1)
    assert esc.precision == pytest.approx(0.5) and esc.recall == pytest.approx(0.5)
    # BLOCK: dự đoán 1 lần (#2, sai), kỳ vọng chính 1 (#5) nhưng được chấp nhận WARN nên không phải FN
    blk = m.class_stats["BLOCK"]
    assert (blk.tp, blk.fp, blk.fn) == (0, 1, 0)
    assert blk.precision == 0.0 and blk.recall is None
    assert m.per_category == {"x": (7, pytest.approx(3 / 7))}


def test_confusion_matrix_uses_primary_expected_action() -> None:
    matrix = confusion_matrix(_small())

    assert matrix["ALLOW"]["ALLOW"] == 1 and matrix["ALLOW"]["BLOCK"] == 1
    assert matrix["BLOCK"]["WARN"] == 1  # hàng = kỳ vọng chính
    assert sum(sum(row.values()) for row in matrix.values()) == 7


def test_class_stats_with_no_predictions_has_none_precision() -> None:
    stats = class_stats([_result("1", A.ALLOW, A.ALLOW)], A.ESCALATE)

    assert stats.precision is None and stats.recall is None


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 100.0
    assert percentile(values, 0) == 10.0
    assert percentile([], 95) == 0.0
    assert percentile([7.0], 95) == 7.0


def test_guard_violations_and_dependency_errors_are_parsed_from_errors() -> None:
    r = _result(
        "1",
        A.GUIDE,
        A.GUIDE,
        errors=[
            "output_guard: answer_leak, code_leak",
            "generate_guidance: không có tài liệu khớp, dùng template",
            "generate_guidance: RuntimeError: boom",
            "classify_intent: ValidationError",
            "retrieve_context: ConnectionError",
            "output_guard: judge_error",
        ],
    )

    assert r.guard_violations == ["answer_leak", "code_leak", "judge_error"]
    assert r.dependency_errors == 4
    assert compute_metrics([r]).guard_violation_cases == 1


def test_report_renders_sections_and_comparison() -> None:
    results = _small()
    metrics = compute_metrics(results)

    report = render_report(
        ReportMeta(date="2026-10-01", mode="rules", split="all", llm="x", retriever="y"), metrics, results
    )
    comparison = render_comparison(metrics, metrics)

    for section in ("## Tóm tắt", "## Precision / recall", "## Confusion matrix", "## Lỗi nghiêm trọng", "## Báo nhầm"):
        assert section in report
    assert "| 3 |" in report and "| rules | live |" in comparison


# ---- Runner (mode rules, không gọi mạng) ----


def test_payload_is_deterministic_and_maps_history() -> None:
    case = next(c for c in load_dataset() if c.history)

    first, second = run.build_payload(case), run.build_payload(case)

    assert first == second
    assert len(first.conversation_history) == len(case.history)
    assert all(turn.sender_id != first.sender_id for turn in first.conversation_history if turn)  # peer


def test_rules_runner_covers_every_case_offline() -> None:
    cases = load_dataset()

    results = asyncio.run(run.run_cases(cases, run.make_rules_runner()))

    assert [r.id for r in results] == [c.id for c in cases]
    assert all(r.latency_ms >= 0 for r in results)
    by_id = {r.id: r for r in results}
    assert by_id["e01"].actual_action is A.ESCALATE  # rule exam_leak
    assert by_id["i01"].actual_action is A.BLOCK
    assert by_id["h02"].actual_action is A.ESCALATE  # báo nhầm đã biết của rule 'chép bài'
    assert compute_metrics(results).n == len(cases)


def test_main_rules_mode_writes_report_and_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run.main(["--mode", "rules", "--split", "test", "--out-dir", str(tmp_path)])

    reports = list(tmp_path.glob("report-*-rules-test.md"))
    results = list(tmp_path.glob("results-*-rules-test.jsonl"))
    assert len(reports) == len(results) == 1
    rows = [json.loads(line) for line in results[0].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(filter_split(load_dataset(), "test"))
    assert {"id", "expected_action", "actual_action", "latency_ms"} <= set(rows[0])
    out = capsys.readouterr().out
    assert "câu sai" in out and "accuracy action" in out
    written = reports[0].read_text(encoding="utf-8") + results[0].read_text(encoding="utf-8")
    assert "sk-" not in written and "API_KEY" not in written


def test_filter_split_values() -> None:
    cases = load_dataset()

    assert len(filter_split(cases, "all")) == len(cases)
    assert {c.split for c in filter_split(cases, "dev")} == {"dev"}
    assert len(filter_split(cases, "dev")) + len(filter_split(cases, "test")) == len(cases)


# ---- RAG eval ----


def test_rag_queries_schema_and_sources_exist() -> None:
    queries = load_rag_queries()
    relevant = [q for q in queries if q.expected_source]

    assert len(relevant) >= 15 and len(queries) - len(relevant) >= 5
    for q in relevant:
        assert (rag_eval.DEMO_COURSE_DIR / str(q.expected_source)).is_file()


def test_suggest_threshold_picks_middle_of_the_gap() -> None:
    assert rag_eval.suggest_threshold([0.85, 0.9, 0.95], [0.6, 0.7, 0.75]) == pytest.approx(0.8)
    assert rag_eval.suggest_threshold([], [0.5]) is None
    overlap = rag_eval.suggest_threshold([0.7, 0.9], [0.8, 0.6])
    assert overlap is not None and 0.6 < overlap < 0.9


def test_rag_eval_runs_offline_with_fake_embedder(tmp_path: Path) -> None:
    path = asyncio.run(rag_eval.main_async(fake=True, k=4, out_dir=tmp_path))

    text = path.read_text(encoding="utf-8")
    assert "hit@1" in text and "RAG_MIN_SCORE đề xuất" in text
    assert path.name.endswith("-fake.md")


def test_rag_summary_hit_rates_on_known_results() -> None:
    results = [
        rag_eval.RagResult(
            id="a", query="q", expected_source="s.md", top_sources=["s.md", "t.md"], top1_score=0.9, expected_score=0.9
        ),
        rag_eval.RagResult(
            id="b", query="q", expected_source="s.md", top_sources=["t.md", "s.md"], top1_score=0.9, expected_score=0.8
        ),
        rag_eval.RagResult(
            id="c", query="q", expected_source="s.md", top_sources=["t.md"], top1_score=0.7, expected_score=None
        ),
        rag_eval.RagResult(
            id="x", query="q", expected_source=None, top_sources=["t.md"], top1_score=0.6, expected_score=None
        ),
    ]

    summary = rag_eval.summarize(results, 2)

    assert summary.hit_at_1 == pytest.approx(1 / 3) and summary.hit_at_k == pytest.approx(2 / 3)
    assert summary.relevant_scores == [0.9, 0.8] and summary.irrelevant_scores == [0.6]
    assert summary.suggested_min_score == pytest.approx(0.7)


# ---- --dataset và split holdout (dataset giả dựng trong tmp_path, không đụng file holdout thật) ----


def _holdout_file(tmp_path: Path) -> Path:
    rows = [
        {
            "id": "ho1",
            "message": "Mình có đề thi cuối kỳ, gửi mọi người nhé",
            "course_id": "demo-course",
            "expected_action": "ESCALATE",
            "expected_intent": "ACADEMIC_DISHONESTY",
            "category": "exam_cheating",
            "split": "holdout",
        },
        {
            "id": "ho2",
            "message": "Chào cả nhóm",
            "course_id": "demo-course",
            "expected_action": "ALLOW",
            "expected_intent": "SOCIAL",
            "category": "social",
            "split": "holdout",
        },
        {**json.loads(DATASET_PATH.read_text(encoding="utf-8").splitlines()[0]), "id": "dv1"},
    ]
    path = tmp_path / "my_holdout.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def test_runner_accepts_custom_dataset_and_holdout_split(tmp_path: Path) -> None:
    dataset = _holdout_file(tmp_path)
    out = tmp_path / "out"

    run.main(["--mode", "rules", "--split", "holdout", "--dataset", str(dataset), "--out-dir", str(out)])

    rows = [
        json.loads(line) for line in next(out.glob("results-*-rules-holdout.jsonl")).read_text("utf-8").splitlines()
    ]
    assert [r["id"] for r in rows] == ["ho1", "ho2"]
    report = next(out.glob("report-*-rules-holdout.md")).read_text(encoding="utf-8")
    assert "my_holdout.jsonl" in report and str(tmp_path) not in report


def test_split_all_includes_holdout_cases_of_custom_dataset(tmp_path: Path) -> None:
    dataset = _holdout_file(tmp_path)

    run.main(["--mode", "rules", "--split", "all", "--dataset", str(dataset), "--out-dir", str(tmp_path / "o")])

    assert len(next((tmp_path / "o").glob("results-*-rules-all.jsonl")).read_text("utf-8").splitlines()) == 3


def test_holdout_split_on_builtin_dataset_fails_cleanly_without_reading_any_holdout_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builtin_holdout = DATASET_PATH.with_name("holdout.jsonl").resolve()
    assert builtin_holdout.is_file()
    read_paths: list[Path] = []
    original_read_text = type(DATASET_PATH).read_text

    def guarded_read_text(self: Path, *args, **kwargs) -> str:
        resolved = self.resolve()
        if resolved == builtin_holdout:
            raise AssertionError("built-in holdout.jsonl must not be read implicitly")
        read_paths.append(resolved)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(DATASET_PATH), "read_text", guarded_read_text)

    with pytest.raises(SystemExit) as excinfo:
        run.main(["--mode", "rules", "--split", "holdout", "--out-dir", str(tmp_path)])

    assert excinfo.value.code == 2
    assert not list(tmp_path.iterdir())
    assert DATASET_PATH.resolve() in read_paths
    assert builtin_holdout not in read_paths


def test_missing_dataset_file_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run.main(["--dataset", str(tmp_path / "nope.jsonl"), "--out-dir", str(tmp_path)])

    assert excinfo.value.code == 2
