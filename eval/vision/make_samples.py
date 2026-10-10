"""Sinh ~12 ảnh mẫu tổng hợp để chạy thử bộ eval ngay ngày 1.

Ảnh tổng hợp chỉ để kiểm tra đường ống chạy đúng. Bộ eval thật phải là ẢNH CHỤP THẬT
(màn hình, vở, sách) — xem README.md. Chạy:  python eval/vision/make_samples.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
OUT = HERE / "images" / "synthetic"


def font(size, mono=True):
    for name in (["DejaVuSansMono.ttf"] if mono else []) + ["DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def screen(lines, dark=True):
    img = Image.new("RGB", (1280, 800), (30, 30, 46) if dark else (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1280, 40], fill=(55, 55, 75) if dark else (225, 228, 235))
    f = font(30)
    for i, line in enumerate(lines):
        d.text((50, 90 + i * 52), line, fill=(205, 220, 255) if dark else (30, 30, 30), font=f)
    return img


def notebook(lines):
    img = Image.new("RGB", (900, 1200), (252, 251, 246))
    d = ImageDraw.Draw(img)
    for y in range(0, 1200, 32):
        d.line([(0, y), (900, y)], fill=(210, 222, 240))
    d.line([(100, 0), (100, 1200)], fill=(225, 115, 115), width=3)
    f = font(34, mono=False)
    for i, line in enumerate(lines):
        d.text((130, 120 + i * 96), line, fill=(70, 45, 150), font=f)
    return img.rotate(random.uniform(-4, 4), expand=True, fillcolor=(120, 110, 100))


SAMPLES = [
    ("sql_join_dark.png", "photo_screen", True, "sql.join", screen(["SELECT c.name, o.total", "FROM customers c", "LEFT JOIN orders o ON o.customer_id = c.id", "WHERE o.total IS NULL;"])),
    ("sql_groupby_light.png", "photo_screen", True, "sql.group_by", screen(["SELECT country, COUNT(*) AS n", "FROM users", "GROUP BY country", "HAVING COUNT(*) > 10;"], dark=False)),
    ("sql_select.png", "photo_screen", True, "sql.select_basic", screen(["SELECT name, price", "FROM products", "WHERE price > 100", "ORDER BY price DESC;"])),
    ("sql_window.png", "photo_screen", True, "sql.window_func", screen(["SELECT name, dept,", "  RANK() OVER (PARTITION BY dept", "              ORDER BY salary DESC) AS r", "FROM employees;"])),
    ("py_pandas.png", "photo_screen", True, "py.pandas_basic", screen(["import pandas as pd", "df = pd.read_csv('titanic.csv')", "df.groupby('Pclass')['Fare'].mean()", "df.merge(ages, on='id')"])),
    ("py_basic.png", "photo_screen", True, "py.basic", screen(["nums = [3, 8, 1, 9]", "total = 0", "for n in nums:", "    total += n", "print(total / len(nums))"])),
    ("note_stats_desc.jpg", "notebook", True, "stats.descriptive", notebook(["Thống kê mô tả", "mean = tổng / n", "median: giá trị giữa", "std = căn phương sai"])),
    ("note_ttest.jpg", "notebook", True, "stats.hypothesis_test", notebook(["Kiểm định t một mẫu", "H0: mu = 50   H1: mu != 50", "t = (x̄ - mu) / (s/√n)", "p < 0.05 -> bác bỏ H0"])),
    ("blurry_join.jpg", "hard", True, "sql.join", screen(["SELECT *", "FROM a INNER JOIN b", "ON a.id = b.a_id;"]).filter(ImageFilter.GaussianBlur(5))),
    ("blank_page.jpg", "not_study", False, "", Image.new("RGB", (900, 1200), (240, 240, 238))),
    ("lunch.jpg", "not_study", False, "", None),
    ("sky.jpg", "not_study", False, "", None),
]


def colorful(seed):
    random.seed(seed)
    img = Image.new("RGB", (1000, 800), (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y, r = random.randint(0, 1000), random.randint(0, 800), random.randint(20, 140)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(random.randint(0, 255) for _ in range(3)))
    return img.filter(ImageFilter.GaussianBlur(2))


def main():
    random.seed(7)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (name, cat, study, concept, img) in enumerate(SAMPLES):
        img = img or colorful(i)
        img.convert("RGB").save(OUT / name)
        rows.append({"file": f"synthetic/{name}", "category": cat, "is_study": str(study).lower(),
                     "expected_concepts": concept, "note": ""})
    with open(HERE / "labels.synthetic.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "category", "is_study", "expected_concepts", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"Đã tạo {len(rows)} ảnh trong {OUT} và labels.synthetic.csv")


if __name__ == "__main__":
    main()
