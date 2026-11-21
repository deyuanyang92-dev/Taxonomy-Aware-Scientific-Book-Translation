#!/usr/bin/env python3
"""按 manifest 批量跑外部 OCR CLI（整目录一次调用，避免每页重载模型），写 test-ocr/runs/<tag>/，用 ocr_score 打分。
用法：python3 scripts/bench/ocr_run_ext.py <tag> --adapter yomitoku [--dpi 200] [--args '--lite']
适配器：yomitoku（/root/ocr_eval/venv_yt）、ndlocr（NDLOCR-Lite src/ocr.py，系统 python3，CPU）。参数用 --args=--lite 形式。s/页 = 整批墙钟 / 页数（含模型加载，写入 time.json 的 _batch_total）。
后处理与其他 runner 相同（prep_ja）。
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TO = ROOT / "test-ocr"
IMJ = Path("/mnt/p/翻译-译作/日本-imajima")
PDF = {2001: IMJ / "Imajima 2001（环形动物 多毛类 II）无标本信息.pdf",
       2007: IMJ / "Imajima 2007（环形动物 多毛类 III）无标本信息.pdf",
       2009: IMJ / "Imajima 2009（环动形物 多毛类 I）无标本信息.pdf"}
sys.path[:0] = [str(ROOT / "scripts/bench"), str(IMJ / "scripts")]
import ocr_score  # noqa: E402
import prep_ja  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--adapter", required=True, choices=["yomitoku", "ndlocr", "paddlevl"])
ap.add_argument("--dpi", type=int, default=200)
ap.add_argument("--args", default="")
a = ap.parse_args()
out = TO / "runs" / a.tag
img_dir = out / "img"
img_dir.mkdir(parents=True, exist_ok=True)
rows_m = list(csv.DictReader(open(TO / "manifest.csv", encoding="utf-8")))
cnt: dict[str, int] = {}
for m in rows_m:
    cnt[m["id"]] = cnt.get(m["id"], 0) + 1
keys = []
import fitz  # noqa: E402
for m in rows_m:
    key = m["id"] if cnt[m["id"]] == 1 else f'{m["id"]}__{m["set"]}'
    keys.append(key)
    p = img_dir / f"{key}.png"
    if not p.exists():
        fitz.open(str(PDF[int(m["vol"])]))[int(m["page"]) - 1].get_pixmap(dpi=a.dpi, colorspace=fitz.csRGB).save(str(p))

t0 = time.time()
if a.adapter == "yomitoku":
    cmd = ["/root/ocr_eval/venv_yt/bin/yomitoku", str(img_dir), "-f", "json", "-o", str(out / "raw"), "-d", "cuda", *shlex.split(a.args)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (out / "run.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    ver = subprocess.run(["/root/ocr_eval/venv_yt/bin/pip", "show", "yomitoku"], capture_output=True, text=True).stdout.splitlines()[:2]
elif a.adapter == "ndlocr":
    nd = "/root/ocr_eval/ext/ndlocr-lite/src"
    cmd = ["/root/ocr_eval/venv_ndl/bin/python", f"{nd}/ocr.py", "--sourcedir", str(img_dir), "--output", str(out / "raw"), *shlex.split(a.args)]
    (out / "raw").mkdir(exist_ok=True)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=nd)
    (out / "run.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    ver = ["NDLOCR-Lite 1.4.0"]
elif a.adapter == "paddlevl":
    cmd = ["/root/ocr_eval/venv_gpu/bin/python", str(Path(__file__).with_name("_paddlevl_worker.py")), str(img_dir), str(out / "raw")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (out / "run.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    ver = ["PaddleOCR-VL (paddleocr 3.7.0)"]
total = time.time() - t0
if r.returncode:
    sys.exit(f"ERR rc={r.returncode}: {(r.stderr or '')[-400:]}")


def read(key: str) -> str:
    if a.adapter in ("ndlocr", "paddlevl"):
        fs = list((out / "raw").glob(f"{key}.txt"))
        return fs[0].read_text(encoding="utf-8") if fs else ""
    fs = list((out / "raw").glob(f"*{key}_p1.json"))
    if not fs:
        return ""
    d = json.loads(fs[0].read_text(encoding="utf-8"))
    ps = sorted(d["paragraphs"], key=lambda x: x["order"])
    return "\n".join(p["contents"] for p in ps)


if not any((out / "raw").rglob("*")):
    sys.exit("ERR: 引擎无任何输出，见 run.log")
res = {}
for m, key in zip(rows_m, keys):
    gold = Path(m["gold_path"] if m["gold_path"].startswith("/") else ROOT / m["gold_path"]).read_text(encoding="utf-8")
    raw = read(key)
    prep_ja.PRIMES = prep_ja.Primes()
    text = "\n".join(prep_ja.page_paras(raw))
    text, _ = prep_ja.split_glued(text)
    (out / f"{key}.raw.txt").write_text(raw, encoding="utf-8")
    (out / f"{key}.txt").write_text(text, encoding="utf-8")
    res[key] = {**ocr_score.score_page(gold, text), "type": m["type"], "set": m["set"]}
    print(key, f"{res[key]['cer_norm']:.3f}", flush=True)
(out / "time.json").write_text(json.dumps({"_batch_total": total, "pages": len(keys), "s_per_page": total / len(keys)}))
(out / "metrics.json").write_text(json.dumps({"cmd": cmd, "version": ver, "pages": res}, ensure_ascii=False, indent=1))
for s in ("G0", "G2"):
    v = [x["cer_norm"] for x in res.values() if x["set"] == s]
    print("MEAN", s, sum(v) / len(v), "n", len(v), f"{total/len(keys):.1f}s/page")
