"""Read-only 24-hour Coach observation analysis; never sends or marks completion."""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
sys.path.insert(0, str(WORKSPACE / "backend"))

# Script entry point needs the backend source path before app imports.
from app.agents.plan_coach.artifacts import claim_run, write_json, write_text  # noqa: E402
from app.agents.plan_coach.reports import reminder_report  # noqa: E402


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Observation timestamps require an explicit timezone offset")
    return parsed


def fixture_database(record):
    if record.get("synthetic") is not True:
        raise ValueError("Fixture must be explicitly labelled synthetic")
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE pb_interventions(id TEXT PRIMARY KEY,pair_id INTEGER,user_id INTEGER,
            variant TEXT,action TEXT,delivery_status TEXT,created_at TEXT);
        CREATE TABLE pb_delivery_attempts(intervention_id TEXT,status TEXT,created_at TEXT);
        CREATE TABLE pb_plan_items(id TEXT PRIMARY KEY,pair_id INTEGER,user_id INTEGER,completed_at TEXT);
        CREATE TABLE pb_completion_events(event_id TEXT,item_id TEXT,confirmed_at TEXT);
    """)
    for r in record["interventions"]:
        timestamp(r["created_at"])
        db.execute(
            "INSERT INTO pb_interventions VALUES (?,?,?,?,?,?,?)",
            (r["id"], r["pair_id"], r["user_id"], r["variant"], r["action"], r["delivery_status"], r["created_at"]),
        )
        for attempt in r.get("attempts", []):
            timestamp(attempt["created_at"])
            db.execute(
                "INSERT INTO pb_delivery_attempts VALUES (?,?,?)", (r["id"], attempt["status"], attempt["created_at"])
            )
    for r in record["completions"]:
        timestamp(r["completed_at"])
        db.execute(
            "INSERT INTO pb_plan_items VALUES (?,?,?,?)", (r["item_id"], r["pair_id"], r["user_id"], r["completed_at"])
        )
    for r in record.get("completion_events", []):
        timestamp(r["confirmed_at"])
        db.execute("INSERT INTO pb_completion_events VALUES (?,?,?)", (r["event_id"], r["item_id"], r["confirmed_at"]))
    return db


def open_read_only(path):
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("Database must exist; this runner never creates a product DB")
    db = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    # Keep report and optional source export on one snapshot if the app writes concurrently.
    db.execute("BEGIN")
    return db


def analyze(db, as_of, *, source_kind, simulation):
    if as_of.utcoffset() is None:
        raise ValueError("as_of requires an explicit timezone offset")
    report = reminder_report(db, as_of)
    metadata = db.execute("SELECT delivery_status,created_at FROM pb_interventions").fetchall()
    visible = [r for r in metadata if timestamp(r["created_at"]) <= as_of]
    counts = Counter(r["delivery_status"] for r in visible)
    if not report["sent_count"]:
        status = "NO_SUCCESSFUL_DELIVERIES"
    elif not report["matured_count"]:
        status = "WAITING_24H"
    elif report["pending_count"]:
        status = "PARTIALLY_MATURED"
    else:
        status = "MATURED_DESCRIPTIVE_ONLY"
    report.update(
        {
            "ran_at": datetime.now(UTC).isoformat(),
            "source_kind": source_kind,
            "simulation": simulation,
            "production_origin_verified": False,
            "current_delivery_status_counts": dict(counts),
            "status_count_scope": "Current stored status of interventions created by as_of; not historical state reconstruction.",
            "future_interventions_excluded": len(metadata) - len(visible),
            "observation_status": status,
            "overall_checkin_24h_rate": report["checkin_24h_count"] / report["matured_count"]
            if report["matured_count"]
            else None,
            "causal_effect_estimated": False,
        }
    )
    return report


def write_report(output, report):
    claim_run(output)
    write_json(output / "results.json", report)
    lines = [
        "# Nudge — trạng thái quan sát 24 giờ",
        "",
        f"Nguồn: `{report['source_kind']}`; simulation={report['simulation']}; mốc quan sát `{report['as_of']}`. Nguồn production chưa được xác nhận.",
        "",
        f"Trạng thái: **{report['observation_status']}**. SENT đủ điều kiện: {report['sent_count']}; đã đủ 24h: {report['matured_count']}; đang pending: {report['pending_count']}; có completion đầu tiên trong 24h ở mẫu đủ thời gian: {report['checkin_24h_count']}.",
        "",
        "| Variant | SENT | Đủ 24h | Pending | Check-in trong 24h | Tỷ lệ trên mẫu đủ 24h |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for variant, r in report["by_variant"].items():
        rate = "null" if r["checkin_24h_rate"] is None else f"{r['checkin_24h_rate']:.1%}"
        lines.append(
            f"| {variant} | {r['sent_count']} | {r['matured_count']} | {r['pending_count']} | {r['checkin_24h_count']} | {rate} |"
        )
    lines += [
        "",
        "Trạng thái hiện được lưu của intervention đã tạo trước mốc: `"
        + json.dumps(report["current_delivery_status_counts"], ensure_ascii=False)
        + "`. Đây không phải tái dựng lịch sử status tại cutoff.",
        "",
        "Dưới 24h luôn pending kể cả đã phản hồi. Chỉ lần completed_at đầu tiên của cùng user/pair được tính; replay không tạo tiến độ mới. SIMULATED/FAILED/PENDING/RESERVED/NOT_CONFIGURED không vào cohort SENT. Mẫu số 0 có rate=null.",
        "",
        "Đây là quan sát mô tả; phân nhóm parity ID không phải random experiment. Không ước lượng hiệu quả nhân quả hoặc điền điểm/pilot giả. Fixture SENT là acknowledgement synthetic, không phải thông báo thật.",
    ]
    write_text(output / "report.md", "\n".join(lines) + "\n")


def export_demo_snapshot(db, as_of):
    """Portable inputs from an explicitly simulated DB; excludes text, secrets and chat."""
    interventions = []
    for row in db.execute("SELECT id,pair_id,user_id,variant,action,delivery_status,created_at FROM pb_interventions"):
        value = dict(row)
        value["attempts"] = [
            dict(a)
            for a in db.execute(
                "SELECT status,created_at FROM pb_delivery_attempts WHERE intervention_id=?", (row["id"],)
            )
        ]
        interventions.append(value)
    return {
        "synthetic": True,
        "description": "Exported from explicitly isolated simulated localhost demo, never production pilot evidence.",
        "as_of": as_of.isoformat(),
        "interventions": interventions,
        "completions": [
            dict(r)
            for r in db.execute(
                "SELECT id AS item_id,pair_id,user_id,completed_at FROM pb_plan_items WHERE completed_at IS NOT NULL"
            )
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", type=Path)
    source.add_argument("--database", type=Path)
    parser.add_argument("--as-of", help="Timezone-aware ISO datetime; required for DB input")
    parser.add_argument("--simulation", action="store_true", help="Label a DB from the isolated demo as simulated")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    db = None
    try:
        if args.dataset:
            fixture = json.loads(args.dataset.read_text(encoding="utf-8"))
            as_of = timestamp(args.as_of or fixture["as_of"])
            db = fixture_database(fixture)
            kind, simulation = "synthetic_boundary_fixture", True
        else:
            if not args.as_of:
                raise ValueError("--as-of is required; never infer an observation cutoff")
            as_of = timestamp(args.as_of)
            db = open_read_only(args.database)
            kind, simulation = "sqlite_read_only", args.simulation
        report = analyze(db, as_of, source_kind=kind, simulation=simulation)
        write_report(args.output, report)
        if args.database and args.simulation:
            write_json(args.output / "source-dataset.json", export_demo_snapshot(db, as_of))
        print(json.dumps({k: v for k, v in report.items() if k != "observations"}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"Observation analysis failed: {error}\n")
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    main()
