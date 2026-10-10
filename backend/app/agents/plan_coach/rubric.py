"""Read real submitted ratings; never generate human/judge scores."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .artifacts import claim_run, write_json, write_text
from .contract import PlannerInput, PlannerOutput
from .scheduler import validate_plan

DIMENSIONS = ("goal_fit", "feasibility", "specificity", "schedule_accuracy", "if_then_accuracy")


def roster(run_dir):
    path = run_dir / "results.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = json.loads(path.read_text(encoding="utf-8"))
    cases = json.loads((run_dir / "dataset.json").read_text(encoding="utf-8"))
    inputs = {r["id"]: r for r in cases}
    if hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest() != report["dataset_sha256"]:
        raise ValueError("RUN_DATASET_MISMATCH")
    expected = {}
    for result in report["results"]:
        record = inputs[result["id"]]
        if result["split"] != record["split"]:
            raise ValueError("RUN_SPLIT_MISMATCH")
        if not result["accepted"]:
            continue
        ctx = PlannerInput.model_validate(record["input"])
        output = PlannerOutput.model_validate(result["output"])
        validate_plan(ctx, output)
        for plan in output.plans:
            key = (result["id"], plan.user_id, result["split"])
            if key in expected:
                raise ValueError("DUPLICATE_RUN_SAMPLE")
            expected[key] = {
                "plan": plan,
                "member": next(m for m in ctx.members if m.user_id == plan.user_id),
                "context": ctx,
            }
    return digest, report, expected


def prepare(run_dir, output):
    digest, report, expected = roster(run_dir)
    claim_run(output)
    with (output / "ratings.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "pair_case",
                "user_id",
                "split",
                "rater",
                "source",
                "run_sha256",
                *DIMENSIONS,
                "notes",
                "model",
                "prompt_version",
            ]
        )
        for key in expected:
            writer.writerow([*key, "", "human", digest, *([""] * len(DIMENSIONS)), "", "", ""])
    lines = [
        "# Bảng chấm Plan — chưa có điểm",
        "",
        "Điền rater và cả năm điểm nguyên 1–5 trong ratings.csv. source=human cho người chấm; không chuyển điểm judge thành human. Không sửa ID, split hoặc run_sha256. Giữ CSV gốc; dùng output mới khi tổng hợp. Plan partial chỉ đáp ứng một phần mục tiêu; hard-pass không chứng minh chất lượng ≥4/5.",
        "",
        "1: không đạt; 3: còn thiếu đáng kể; 5: đáp ứng đầy đủ. goal_fit: mục tiêu/concept và phần chưa đạt; feasibility: giờ rảnh/ngân sách; specificity: hành động/đầu ra; schedule_accuracy: lịch/tiên quyết; if_then_accuracy: Nếu–thì khớp ngày giờ/nơi/việc.",
        "",
    ]
    for key, value in expected.items():
        plan, member = value["plan"], value["member"]
        ctx = value["context"]
        weekdays = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
        windows = (
            "; ".join(f"{weekdays[w.day_of_week]} {w.start_time}–{w.end_time}" for w in member.availability)
            or "không có"
        )
        prerequisites = "; ".join(f"{c.id} ← {', '.join(c.prerequisites) or 'không'}" for c in ctx.concepts)
        lines += [
            f"## {key[0]} · user_id={key[1]} · {key[2]}",
            "",
            f"Mục tiêu: {member.goal}",
            f"Cam kết: {member.committed_minutes_per_week} phút/tuần; timezone: {member.timezone}; partial={plan.partial}; để sau={len(plan.deferred_items)}.",
            f"Giờ rảnh địa phương: {windows}. Ngân sách xếp lịch tự học: 80% cam kết mỗi tuần.",
            f"Mốc lập lịch: {ctx.planning_start}; horizon={ctx.horizon_days} ngày; deadline={member.deadline or 'không đặt'}.",
            f"Concept mục tiêu: {', '.join(member.concept_ids)}; đã biết do người dùng khai báo: {', '.join(member.known_concept_ids) or 'không'}. Tiên quyết catalog: {prerequisites}.",
            f"Lịch bận bổ sung: {[(b.start.isoformat(), b.end.isoformat()) for b in ctx.busy_intervals.get(member.user_id, [])]}; nơi: {member.location}.",
            "",
            "| Concept/việc | Đầu ra | Phút | Lịch/trạng thái | Nếu–thì/lý do để sau |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in plan.items + plan.deferred_items:
            values = [
                item.concept_id + ": " + item.action,
                item.expected_output,
                str(item.est_minutes),
                f"{item.status} · {item.scheduled_start} → {item.scheduled_end}",
                item.if_then_text or item.defer_reason or "",
            ]
            lines.append("| " + " | ".join(v.replace("|", "\\|").replace("\n", " ") for v in values) + " |")
        lines.append("")
    write_text(output / "rating-guide.md", "\n".join(lines) + "\n")
    return {
        "mode": report["mode"],
        "expected_samples": len(expected),
        "human_rating_count": 0,
        "human_average": None,
        "quality_status": "chưa xác nhận ≥4/5",
    }


def aggregate(run_dir, files, legacy_source=None):
    digest, report, expected = roster(run_dir)
    seen, rows, sources, seen_files = set(), [], [], set()
    for path in files:
        path = Path(path)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if file_hash in seen_files:
            raise ValueError("DUPLICATE_RATING_FILE")
        seen_files.add(file_hash)
        sources.append({"file": path.name, "sha256": file_hash})
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            names = reader.fieldnames or []
            required = {"pair_case", "user_id", "split", "rater", *DIMENSIONS, "notes"}
            if not required.issubset(names) or len(set(names)) != len(names):
                raise ValueError("RUBRIC_HEADERS")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("RUBRIC_ROW_COLUMNS")
                try:
                    key = (row["pair_case"], int(row["user_id"]), row["split"])
                except ValueError:
                    raise ValueError("RUBRIC_ID") from None
                if key not in expected:
                    raise ValueError("UNKNOWN_RUBRIC_SAMPLE")
                source = row.get("source") or legacy_source
                if source not in ("human", "llm_judge"):
                    raise ValueError("RUBRIC_SOURCE_REQUIRED")
                if row.get("run_sha256") and row["run_sha256"] != digest:
                    raise ValueError("RUBRIC_RUN_MISMATCH")
                rater = row["rater"].strip()
                identity = (source, key, rater)
                if identity in seen:
                    raise ValueError("DUPLICATE_RATING")
                seen.add(identity)
                values = [row[d].strip() for d in DIMENSIONS]
                if not any(values):
                    continue
                if not rater or len(rater) > 120 or not all(v in ("1", "2", "3", "4", "5") for v in values):
                    raise ValueError("RUBRIC_RATER_OR_SCORE")
                if source == "llm_judge" and not (
                    row.get("model", "").strip() and row.get("prompt_version", "").strip()
                ):
                    raise ValueError("JUDGE_PROVENANCE_REQUIRED")
                rows.append(
                    {
                        "source": source,
                        "key": key,
                        "rater": rater,
                        "scores": dict(zip(DIMENSIONS, map(int, values))),
                        "run_bound": row.get("run_sha256") == digest,
                    }
                )
    by_source = {}
    for source in ("human", "llm_judge"):
        group = [r for r in rows if r["source"] == source]
        per_sample = defaultdict(list)
        for row in group:
            per_sample[row["key"]].append(row)
        means = {
            d: sum(sum(r["scores"][d] for r in ratings) / len(ratings) for ratings in per_sample.values())
            / len(per_sample)
            if per_sample
            else None
            for d in DIMENSIONS
        }
        by_source[source] = {
            "rating_count": len(group),
            "point_count": 5 * len(group),
            "sample_count": len(per_sample),
            "missing_samples": len(expected) - len(per_sample),
            "rater_count": len({r["rater"] for r in group}),
            "per_dimension_means": means,
            "overall_mean": sum(means.values()) / 5 if per_sample else None,
            "unbound_legacy_rating_count": sum(not r["run_bound"] for r in group),
        }
    human = by_source["human"]
    verified = (
        bool(expected)
        and human["missing_samples"] == 0
        and human["unbound_legacy_rating_count"] == 0
        and all(v is not None and v >= 4 for v in human["per_dimension_means"].values())
    )
    return {
        "mode": report["mode"],
        "run_sha256": digest,
        "expected_samples": len(expected),
        "partial_samples": sum(v["plan"].partial for v in expected.values()),
        "deferred_item_count": sum(len(v["plan"].deferred_items) for v in expected.values()),
        "by_source": by_source,
        "sources": sources,
        "source_attestation": "CSV source/rater is declared by the submitter; no external verification of human identity.",
        "averaging": "Average raters within each sample, then average samples; human and judge remain separate.",
        "quality_target_verified": verified,
        "quality_status": "human rubric ≥4/5 trên đủ mẫu đã chấm" if verified else "chưa xác nhận ≥4/5",
        "full_goal_completion_inferred": False,
    }


def save_summary(output, summary):
    claim_run(output)
    write_json(output / "summary.json", summary)
    lines = [
        "# Rubric — điểm đã nộp",
        "",
        summary["quality_status"],
        "",
        "| Nguồn | Rating | Mẫu đã chấm | Còn thiếu | Trung bình |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source, result in summary["by_source"].items():
        lines.append(
            f"| {source} | {result['rating_count']} | {result['sample_count']} | {result['missing_samples']} | {result['overall_mean']} |"
        )
    lines += [
        "",
        f"Partial={summary['partial_samples']}; deferred items={summary['deferred_item_count']}. Không suy ra đạt toàn bộ mục tiêu từ hard-pass hoặc rubric. CSV chỉ đọc, nguồn/rater do người nộp khai báo.",
    ]
    write_text(output / "report.md", "\n".join(lines) + "\n")
