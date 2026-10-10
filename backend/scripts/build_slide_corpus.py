"""Chuyển slide giảng viên (.pdf hoặc .txt đã tách chữ) thành corpus .md cho RAG.

Mỗi slide thành một khối `<!-- page:N -->` để AI trích nguồn "bài <tên file>, slide N".
Tên bài lấy từ tên file, nên đặt tên file theo nội dung bài (không dùng "Day 1").

Chạy: python scripts/build_slide_corpus.py <thư mục slide> data/courses/<course_id>
"""

import argparse
import re
from collections import Counter
from pathlib import Path

# Footer lặp lại trên mọi slide: bỏ để không lẫn vào nội dung.
_FOOTER_LINE = re.compile(r"Giảng viên|AICB\s*·\s*(?:Ngày|Evaluation)|^\(?ViUi\)?$|^\d+$|^Tuần \d+$|^Ngày$")
_SLIDE_COUNTER = re.compile(r"(\d+)\s*/\s*(\d+)\s*$")


def _clean(lines: list[str]) -> str:
    kept = []
    for line in lines:
        line = _SLIDE_COUNTER.sub("", line.strip()).strip() if _SLIDE_COUNTER.search(line) else line.strip()
        if line and not _FOOTER_LINE.search(line):
            kept.append(re.sub(r"\s{2,}", " ", line))
    return "\n".join(kept)


def pdf_slides(path: Path) -> list[tuple[int, str]]:
    """(số trang PDF, nội dung) cho mỗi trang có chữ; trang toàn hình bị bỏ qua."""
    from pypdf import PdfReader

    slides = []
    for number, page in enumerate(PdfReader(path).pages, 1):
        text = _clean((page.extract_text() or "").splitlines())
        if len(text.split()) >= 3:
            slides.append((number, text))
    return slides


def txt_slides(path: Path) -> list[tuple[int, str]]:
    """Tách theo bộ đếm "x / y" ở chân slide (y là tổng số slide, giống nhau trong cả file).

    Bản .txt hay mất bộ đếm ở nhiều slide, nên một khối có thể trải nhiều slide: khi đó ghi số slide
    đầu khối để người học lật từ đó. Gửi bản PDF sẽ cho số slide chính xác.
    """
    lines = path.read_text(encoding="utf-8").replace("\r", "").splitlines()
    totals = Counter(m.group(2) for line in lines if (m := _SLIDE_COUNTER.search(line)))
    total = totals.most_common(1)[0][0] if totals else None
    slides, current, number = [], [], 1
    for line in lines:
        current.append(line)
        match = _SLIDE_COUNTER.search(line)
        if total and match and match.group(2) == total:
            slides.append((min(number, int(match.group(1))), _clean(current)))
            current, number = [], int(match.group(1)) + 1
    if current:
        slides.append((number, _clean(current)))
    return [(n, text) for n, text in slides if len(text.split()) >= 3]


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for path in sorted(source_dir.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".txt"}:
            continue
        slides = pdf_slides(path) if suffix == ".pdf" else txt_slides(path)
        body = "\n\n".join(f"<!-- page:{n} -->\n{text}" for n, text in slides)
        (out_dir / f"{path.stem}.md").write_text(f"# {path.stem}\n\n{body}\n", encoding="utf-8")
        result[path.stem] = len(slides)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for title, count in build(args.source, args.output).items():
        print(f"{title}: {count} slide")


if __name__ == "__main__":
    main()
