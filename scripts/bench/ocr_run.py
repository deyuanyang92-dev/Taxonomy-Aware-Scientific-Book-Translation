#!/usr/bin/env python3
"""按 test-ocr/manifest.csv 跑一个 PP-OCR 配置，逐页写 test-ocr/runs/<tag>/<id>.txt（+ .raw.txt、time.json），并打分。

用法（在 /root/ocr_eval/venv_gpu 里，仓库根运行）：
  python scripts/bench/ocr_run.py <tag> --model PP-OCRv5_server --dpi 200 [--adaptive 0|1] [--params '{...}'] [--ids a,b]
.txt = rows_to_text + prep_ja（所有引擎共用同一后处理）；.raw.txt = 仅 rows_to_text。
缓存隔离到 runs/<tag>/cache，不复用旧缓存。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TO = ROOT / "test-ocr"
IMJ = Path("/mnt/p/翻译-译作/日本-imajima")
PDF = {2001: IMJ / "Imajima 2001（环形动物 多毛类 II）无标本信息.pdf",
       2007: IMJ / "Imajima 2007（环形动物 多毛类 III）无标本信息.pdf",
       2009: IMJ / "Imajima 2009（环动形物 多毛类 I）无标本信息.pdf"}

ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--model", default="PP-OCRv5_server")
ap.add_argument("--dpi", type=int, default=200)
ap.add_argument("--adaptive", default="0")
ap.add_argument("--params", default="{}")
ap.add_argument("--ids", default="")
a = ap.parse_args()
out = TO / "runs" / a.tag
out.mkdir(parents=True, exist_ok=True)
os.environ.update(DOCSTORE_PPOCR_MODEL=a.model, DOCSTORE_PPOCR_ADAPTIVE=a.adaptive,
                  DOCSTORE_PPOCR_CACHE=str(out / "cache"))
os.environ["DOCSTORE_PPOCR_PARAMS"] = "" if a.params == "{}" else a.params
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/bench"), str(IMJ / "scripts")]
from docstore.engines.ppocr import ppocr_rows, rows_to_text  # noqa: E402
import ocr_score  # noqa: E402
import prep_ja  # noqa: E402

rows_m = list(csv.DictReader(open(TO / "manifest.csv", encoding="utf-8")))
want = set(a.ids.split(",")) if a.ids else None
_cnt: dict[str, int] = {}
for _m in rows_m:
    _cnt[_m["id"]] = _cnt.get(_m["id"], 0) + 1
res, times = {}, {}
for m in rows_m:
    if want and m["id"] not in want:
        continue
    key = m["id"] if _cnt[m["id"]] == 1 else f'{m["id"]}__{m["set"]}'  # 同页多金标不互相覆盖
    gold = Path(m["gold_path"] if m["gold_path"].startswith("/") else ROOT / m["gold_path"]).read_text(encoding="utf-8")
    t0 = time.time()
    rows, w = ppocr_rows(str(PDF[int(m["vol"])]), int(m["page"]), a.dpi)
    times[key] = time.time() - t0
    raw = rows_to_text(rows, w)[0]
    prep_ja.PRIMES = prep_ja.Primes()
    text = "\n".join(prep_ja.page_paras(raw))
    text, _ = prep_ja.split_glued(text)
    (out / f"{key}.raw.txt").write_text(raw, encoding="utf-8")
    (out / f"{key}.txt").write_text(text, encoding="utf-8")
    res[key] = {**ocr_score.score_page(gold, text), "type": m["type"], "set": m["set"]}
    print(key, f"{res[key]['cer_norm']:.3f}", f"{times[key]:.1f}s", flush=True)
(out / "time.json").write_text(json.dumps(times))
(out / "metrics.json").write_text(json.dumps({"cmd": sys.argv, "env": {k: v for k, v in os.environ.items() if k.startswith("DOCSTORE_PPOCR")}, "pages": res}, ensure_ascii=False, indent=1))
cs = [r["cer_norm"] for r in res.values()]
print("MEAN cer_norm", sum(cs) / len(cs), "n", len(cs))
