"""Thử nhanh vision trên một thư mục ảnh (chưa cần nhãn) – việc của ngày 1.

    python eval/vision/try_vision.py path/to/folder            # dùng VISION_MODEL
    python eval/vision/try_vision.py path/to/folder --model gpt-5-mini
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.checkin.config import get_settings  # noqa: E402
from app.checkin.imaging import process_image  # noqa: E402
from app.checkin.llm import get_llm  # noqa: E402
from app.checkin.schemas import ConceptRef  # noqa: E402

EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows không in được emoji/tiếng Việt
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--model", default=None)
    ap.add_argument("--note", default=None)
    args = ap.parse_args()
    fx = json.loads((ROOT / "eval/vision/fixtures.json").read_text(encoding="utf-8"))
    concepts = [ConceptRef(**c) for c in fx["concepts"]]
    llm = get_llm()
    print(f"Provider: {get_settings().llm_provider} · model: {args.model or get_settings().vision_model}\n")
    total = 0.0
    for p in sorted(Path(args.folder).rglob("*")):
        if p.suffix.lower() not in EXT:
            continue
        t0 = time.perf_counter()
        try:
            img = process_image(p.read_bytes())
            r, u = llm.analyze(image=img.data, media_type=img.media_type, learner_name="Minh",
                               concepts=concepts, note=args.note, model=args.model)
        except Exception as e:
            print(f"✗ {p.name}: {e}")
            continue
        total += u.cost_usd
        mark = "📚" if r.is_study else "🚫"
        print(f"{mark} {p.name}  [{', '.join(r.concepts) or '—'}]  conf={r.confidence:.2f}  "
              f"{(time.perf_counter() - t0):.1f}s  ${u.cost_usd:.4f}\n    {r.description}")
    print(f"\nTổng chi phí ước tính: ${total:.4f}")


if __name__ == "__main__":
    main()
