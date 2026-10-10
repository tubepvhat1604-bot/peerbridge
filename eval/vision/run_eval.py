"""Eval cho check-in vision (CONTEXT.md mục 8.5 và 9.4).

Chạy:
    # thử đường ống bằng ảnh tổng hợp + AI giả (không tốn tiền)
    python eval/vision/make_samples.py
    python eval/vision/run_eval.py --labels eval/vision/labels.synthetic.csv --provider fake

    # chạy thật, so sánh hai model
    python eval/vision/run_eval.py --labels eval/vision/labels.csv \
        --models gpt-4.1-mini,gpt-5-mini

Ảnh được chuẩn hóa y hệt production (process_image) rồi đi qua cùng prompt + logic quyết định.
Kết quả ghi vào eval/vision/results/<thời gian>/: report.md, summary.json, predictions_<model>.csv.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def parse_args():
    p = argparse.ArgumentParser(description="Eval check-in vision")
    p.add_argument("--labels", default=str(HERE / "labels.csv"))
    p.add_argument("--images", default=str(HERE / "images"))
    p.add_argument("--fixtures", default=str(HERE / "fixtures.json"))
    p.add_argument("--models", default="", help="Danh sách model, cách nhau bằng dấu phẩy. Trống = VISION_MODEL")
    p.add_argument("--provider", choices=["openai", "fake"], default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help="Chỉ chạy N ảnh đầu (thử nhanh)")
    p.add_argument("--out", default=str(HERE / "results"))
    return p.parse_args()


def load_labels(path: str, images_dir: Path, limit: int):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            file = (r.get("file") or "").strip()
            if not file:
                continue
            img = images_dir / file
            if not img.exists():
                print(f"  [bỏ qua] không thấy ảnh: {img}")
                continue
            rows.append({
                "file": file,
                "path": img,
                "category": (r.get("category") or "").strip() or "other",
                "is_study": (r.get("is_study") or "").strip().lower() in ("true", "1", "yes", "có"),
                "expected": [c.strip() for c in (r.get("expected_concepts") or "").split(";") if c.strip()],
                "note": (r.get("note") or "").strip() or None,
            })
    return rows[:limit] if limit else rows


def pct(x):
    return "–" if x is None else f"{x * 100:.1f}%"


def ratio(a, b):
    return None if not b else a / b


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def run_model(model, rows, llm, concepts, plan_items, names, workers):
    from app.checkin.decision import decide
    from app.checkin.imaging import process_image
    from app.checkin.config import get_settings
    from app.checkin.llm import LLMError

    s = get_settings()

    def one(row):
        out = {"file": row["file"], "category": row["category"], "label_is_study": row["is_study"],
               "expected": ";".join(row["expected"])}
        try:
            img = process_image(row["path"].read_bytes())
            t0 = time.perf_counter()
            result, usage = llm.analyze(image=img.data, media_type=img.media_type, learner_name="Minh",
                                        concepts=concepts, note=row["note"], model=model or None)
            latency = int((time.perf_counter() - t0) * 1000)
            d = decide(result, plan_items, names, high=s.confidence_high, low=s.confidence_low)
            top1 = result.concepts[0] if result.concepts else ""
            out.update({
                "pred_is_study": result.is_study, "pred_concepts": ";".join(result.concepts),
                "confidence": round(result.confidence, 3), "status": d.status,
                "top1_correct": bool(row["expected"]) and top1 in row["expected"],
                "any_correct": bool(set(result.concepts) & set(row["expected"])),
                "description": result.description, "latency_ms": latency,
                "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                "cost_usd": usage.cost_usd, "error": "",
            })
        except (LLMError, ValueError) as e:
            out.update({"status": "error", "error": str(e)[:200]})
        return out

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, rows))


def summarize(preds):
    ok = [p for p in preds if p.get("status") != "error"]
    study = [p for p in ok if p["label_is_study"]]
    study_lab = [p for p in study if p["expected"]]
    non = [p for p in ok if not p["label_is_study"]]
    done = [p for p in study_lab if p["status"] == "done"]
    lat = [p["latency_ms"] for p in ok]
    cost = [p["cost_usd"] for p in ok]

    by_cat = {}
    for p in study_lab:
        c = by_cat.setdefault(p["category"], [0, 0])
        c[0] += int(p["top1_correct"])
        c[1] += 1

    # Quét ngưỡng "tự ghi nhận": done khi chỉ 1 concept và confidence >= t (không cần gọi lại API).
    sweep = []
    for t in [x / 100 for x in range(50, 100, 5)]:
        auto = [p for p in study_lab if p["pred_concepts"] and ";" not in p["pred_concepts"] and p["confidence"] >= t]
        sweep.append({"threshold": t, "auto_done_rate": ratio(len(auto), len(study_lab)),
                      "auto_done_precision": ratio(sum(p["top1_correct"] for p in auto), len(auto))})

    return {
        "n_images": len(preds),
        "n_errors": len(preds) - len(ok),
        "study_detection_accuracy": ratio(sum(p["pred_is_study"] == p["label_is_study"] for p in ok), len(ok)),
        "concept_top1_accuracy": ratio(sum(p["top1_correct"] for p in study_lab), len(study_lab)),
        "concept_any_accuracy": ratio(sum(p["any_correct"] for p in study_lab), len(study_lab)),
        "auto_done_rate": ratio(len(done), len(study_lab)),
        "auto_done_precision": ratio(sum(p["top1_correct"] for p in done), len(done)),
        "wrong_auto_done_rate": ratio(sum(not p["top1_correct"] for p in done), len(study_lab)),
        "ask_again_rate": ratio(sum(p["status"] == "needs_confirm" for p in study), len(study)),
        "not_study_recall": ratio(sum(not p["pred_is_study"] for p in non), len(non)),
        "false_not_study_rate": ratio(sum(not p["pred_is_study"] for p in study), len(study)),
        "latency_p50_ms": percentile(lat, 0.5),
        "latency_p90_ms": percentile(lat, 0.9),
        "cost_per_image_usd": statistics.mean(cost) if cost else None,
        "cost_total_usd": sum(cost) if cost else 0.0,
        "top1_by_category": {k: ratio(a, b) for k, (a, b) in by_cat.items()},
        "threshold_sweep": sweep,
    }


TARGETS = [
    ("concept_top1_accuracy", "Đúng concept (top-1)", ">= 75%", lambda v: v is not None and v >= 0.75),
    ("ask_again_rate", "Tỷ lệ phải hỏi lại", "<= 30%", lambda v: v is not None and v <= 0.30),
    ("not_study_recall", "Bắt đúng ảnh không học", ">= 80%", lambda v: v is not None and v >= 0.80),
    ("latency_p90_ms", "Độ trễ p90", "< 15 giây", lambda v: v is not None and v < 15000),
]


def write_report(out_dir: Path, summaries: dict, args, n_rows: int):
    lines = [f"# Eval check-in vision – {dt.datetime.now():%d/%m/%Y %H:%M}", "",
             f"- Nhãn: `{args.labels}` ({n_rows} ảnh)", f"- Provider: `{os.environ.get('VISION_LLM_PROVIDER')}`", ""]
    models = list(summaries)
    lines += ["## So sánh model", "", "| Chỉ số | Mục tiêu | " + " | ".join(models) + " |",
              "| --- | --- | " + " | ".join("---" for _ in models) + " |"]
    for key, label, target, check in TARGETS:
        cells = []
        for m in models:
            v = summaries[m][key]
            shown = (f"{v / 1000:.1f} s" if v is not None else "–") if key == "latency_p90_ms" else pct(v)
            cells.append(f"{shown} {'✅' if check(v) else '❌'}")
        lines.append(f"| {label} | {target} | " + " | ".join(cells) + " |")
    extra = [("study_detection_accuracy", "Nhận đúng có/không phải ảnh học"), ("concept_any_accuracy", "Có concept đúng trong danh sách"),
             ("auto_done_rate", "Tự ghi nhận không cần hỏi"), ("auto_done_precision", "Độ chính xác khi tự ghi nhận"),
             ("wrong_auto_done_rate", "Tự ghi nhận SAI (lỗi nặng nhất)"), ("false_not_study_rate", "Ảnh học bị coi là không học")]
    for key, label in extra:
        lines.append(f"| {label} | | " + " | ".join(pct(summaries[m][key]) for m in models) + " |")
    lines.append("| Chi phí trung bình / ảnh | | " + " | ".join(
        f"${summaries[m]['cost_per_image_usd']:.4f}" if summaries[m]["cost_per_image_usd"] is not None else "–" for m in models) + " |")
    lines.append("| Lỗi gọi API | | " + " | ".join(str(summaries[m]["n_errors"]) for m in models) + " |")

    for m in models:
        s = summaries[m]
        lines += ["", f"## {m}", "", "**Đúng concept theo loại ảnh**", "", "| Loại | Top-1 |", "| --- | --- |"]
        lines += [f"| {k} | {pct(v)} |" for k, v in sorted(s["top1_by_category"].items())]
        lines += ["", "**Quét ngưỡng tự ghi nhận** (chọn ngưỡng cân bằng giữa ít hỏi lại và ít ghi nhận sai)", "",
                  "| Ngưỡng | Tự ghi nhận | Độ chính xác khi tự ghi nhận |", "| --- | --- | --- |"]
        lines += [f"| {r['threshold']:.2f} | {pct(r['auto_done_rate'])} | {pct(r['auto_done_precision'])} |" for r in s["threshold_sweep"]]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows không in được emoji/tiếng Việt
    args = parse_args()
    if args.provider:
        os.environ["VISION_LLM_PROVIDER"] = args.provider
    from app.checkin.config import get_settings
    from app.checkin.llm import OpenAIVision, FakeVision
    from app.checkin.schemas import ConceptRef, PlanItemRef

    get_settings.cache_clear()
    s = get_settings()
    fx = json.loads(Path(args.fixtures).read_text(encoding="utf-8"))
    concepts = [ConceptRef(**c) for c in fx["concepts"]]
    names = {c.id: c.name for c in concepts}
    base = dt.date.today()
    plan_items = [PlanItemRef(id=f"pi_{i}", concept_id=c.id, label=f"Học {c.name}", due_date=base + dt.timedelta(days=i))
                  for i, c in enumerate(concepts)]

    rows = load_labels(args.labels, Path(args.images), args.limit)
    if not rows:
        sys.exit("Không có ảnh nào để chạy. Kiểm tra --labels và --images.")
    llm = OpenAIVision() if s.llm_provider == "openai" else FakeVision()
    models = [m.strip() for m in args.models.split(",") if m.strip()] or [s.vision_model if s.llm_provider == "openai" else "fake"]

    out_dir = Path(args.out) / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for m in models:
        print(f"▶ {m}: {len(rows)} ảnh…")
        preds = run_model(m if s.llm_provider == "openai" else None, rows, llm, concepts, plan_items, names, args.workers)
        with open(out_dir / f"predictions_{m}.csv", "w", newline="", encoding="utf-8") as f:
            fields = sorted({k for p in preds for k in p})
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(preds)
        summaries[m] = summarize(preds)
        sm = summaries[m]
        print(f"  top-1 {pct(sm['concept_top1_accuracy'])} · hỏi lại {pct(sm['ask_again_rate'])} · "
              f"bắt ảnh không học {pct(sm['not_study_recall'])} · lỗi {sm['n_errors']}")
    (out_dir / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(out_dir, summaries, args, len(rows))
    print(f"✔ Báo cáo: {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
