#!/usr/bin/env python3
"""中文动物志 OCR 测试：每本随机抽 N 页（固定种子），导出单页 PDF + PNG(200dpi) 和 zh_manifest.csv。
用法：python3 scripts/bench/zh_sample.py [--n 10] [--seed 20261121]
正文区间：跳过前 15 页与后 6% 页（封面、版权、目录、索引）。
"""
import argparse, csv, glob, random
from pathlib import Path
import fitz

TO = Path(__file__).resolve().parents[2] / "test-ocr"
BOOKS = {"z09": "中国动物志 环节动物门 多毛纲 Ⅰ*.pdf", "z33": "*第三十三卷*.pdf", "z54": "*第五十四卷*.pdf"}
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=10); ap.add_argument("--seed", type=int, default=20261121)
a = ap.parse_args()
out = TO / "zh_fauna" / "pages"; out.mkdir(parents=True, exist_ok=True)
rows = []
for bk, pat in BOOKS.items():
    f = sorted(glob.glob(str(TO / pat)))[0]
    d = fitz.open(f); n = len(d)
    pool = list(range(15, int(n * 0.94)))
    for p in sorted(random.Random(f"{a.seed}{bk}").sample(pool, a.n)):
        pid = f"{bk}_p{p+1:04d}"
        one = fitz.open(); one.insert_pdf(d, from_page=p, to_page=p); one.save(out / f"{pid}.pdf")
        d[p].get_pixmap(dpi=200).save(out / f"{pid}.png")
        rows.append(dict(id=pid, book=bk, pdf=Path(f).name, page1=p + 1, pdf_path=f))
w = csv.DictWriter(open(TO / "zh_fauna" / "zh_manifest.csv", "w", newline="", encoding="utf-8"), fieldnames=rows[0])
w.writeheader(); w.writerows(rows); print(len(rows), "pages")
