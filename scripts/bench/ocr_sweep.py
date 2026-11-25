"""PP-OCRv5 参数扫描：金标准 2 页，一次一个参数，结果追加到 docs/ocr_eval/LEDGER.tsv。

用法（在 /root/ocr_eval/venv_gpu 里，仓库根运行）：
  python scripts/bench/ocr_sweep.py '{"text_det_thresh":0.2}' [--dpi 200] [--note 说明]
参数 JSON 经 DOCSTORE_PPOCR_PARAMS 传给 worker；空对象 {} = 基线复核。动手前先查 LEDGER.tsv。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path("/mnt/p/翻译-译作/日本-imajima/bench")
PDF = {"Imajima2001": BENCH.parent / "Imajima 2001（环形动物 多毛类 II）无标本信息.pdf",
       "Imajima2009": BENCH.parent / "Imajima 2009（环动形物 多毛类 I）无标本信息.pdf"}
GOLD = [("Imajima2001", 61), ("Imajima2009", 66)]

ap = argparse.ArgumentParser()
ap.add_argument("params")
ap.add_argument("--dpi", type=int, default=200)
ap.add_argument("--note", default="")
a = ap.parse_args()
json.loads(a.params)
os.environ["DOCSTORE_PPOCR_PARAMS"] = "" if a.params == "{}" else a.params
sys.path[:0] = [str(ROOT), str(BENCH), "/mnt/p/翻译-译作/日本-imajima/scripts"]
from cer import cer  # noqa: E402
from docstore.engines.ppocr import ppocr_rows, rows_to_text  # noqa: E402
import prep_ja  # noqa: E402  与 bench/eval.py 同一后处理，数字才可与台账比

res = []
for key, pg in GOLD:
    gold = (BENCH / "gold" / f"{key}_p{pg:04d}.txt").read_text(encoding="utf-8")
    rows, w = ppocr_rows(str(PDF[key]), pg, a.dpi)
    prep_ja.PRIMES = prep_ja.Primes()
    text = "\n".join(prep_ja.page_paras(rows_to_text(rows, w)[0]))
    text, _ = prep_ja.split_glued(text)
    r = cer(gold, text)
    res.append(r[0] if isinstance(r, tuple) else r)
out = "/".join(f"{x * 100:.2f}%" for x in res)
print(a.params, a.dpi, out)
with open(ROOT / "docs/ocr_eval/LEDGER.tsv", "a", encoding="utf-8") as f:
    f.write(f"{datetime.date.today()}\tPP-OCRv5 server {a.dpi}dpi {a.params}\tImajima gold 2001p61/2009p66\tCER\t{out}\t0\t"
            f"scripts/bench/ocr_sweep.py {a.note}\n")
