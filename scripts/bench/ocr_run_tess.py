#!/usr/bin/env python3
"""按 manifest 跑 Tesseract，写 test-ocr/runs/<tag>/<key>.txt，并用 ocr_score 打分。
用法：python3 scripts/bench/ocr_run_tess.py <tag> --lang jpn --psm 3 --dpi 300 [--bin tesseract] [--tessdata DIR]
后处理与 ocr_run.py 相同（prep_ja）。页图缓存在 /dev/shm/ocr_tmp。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
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
ap.add_argument("--lang", default="jpn")
ap.add_argument("--psm", default="3")
ap.add_argument("--dpi", type=int, default=300)
ap.add_argument("--bin", default="tesseract")
ap.add_argument("--tessdata", default="")
ap.add_argument("--prep", default="", help="预处理，逗号分隔：otsu,adaptive,deskew,scale2,denoise")
ap.add_argument("--extra", default="", help="额外参数，空格分隔，如 '-c preserve_interword_spaces=1'")
a = ap.parse_args()
out = TO / "runs" / a.tag
out.mkdir(parents=True, exist_ok=True)
img_dir = Path("/dev/shm/ocr_tmp")
img_dir.mkdir(exist_ok=True)


def render(vol: int, page: int, dpi: int) -> Path:
    p = img_dir / f"{vol}_{page}_{dpi}.png"
    if not p.exists():
        import fitz
        d = fitz.open(str(PDF[vol]))
        d[page - 1].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).save(str(p))
    return p


def preprocess(src: Path, prep: str) -> Path:
    """按 prep 依次处理灰度页图，结果缓存为独立文件（不覆盖原页图）。"""
    if not prep:
        return src
    import cv2
    import numpy as np
    dst = src.with_name(src.stem + "_" + prep.replace(",", "-") + ".png")
    if dst.exists():
        return dst
    im = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
    for op in prep.split(","):
        if op == "denoise":
            im = cv2.fastNlMeansDenoising(im, None, 10)
        elif op == "scale2":
            im = cv2.resize(im, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        elif op == "otsu":
            im = cv2.threshold(im, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        elif op == "adaptive":
            im = cv2.adaptiveThreshold(im, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
        elif op == "deskew":
            inv = cv2.threshold(im, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            pts = cv2.findNonZero(inv)
            ang = cv2.minAreaRect(pts)[-1]
            ang = ang - 90 if ang > 45 else ang
            if 0.1 < abs(ang) < 10:
                h, w = im.shape
                M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
                im = cv2.warpAffine(im, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=int(np.median(im)))
        else:
            raise SystemExit(f"未知 prep: {op}")
    cv2.imwrite(str(dst), im)
    return dst


rows_m = list(csv.DictReader(open(TO / "manifest.csv", encoding="utf-8")))
cnt: dict[str, int] = {}
for m in rows_m:
    cnt[m["id"]] = cnt.get(m["id"], 0) + 1
res, times = {}, {}
for m in rows_m:
    key = m["id"] if cnt[m["id"]] == 1 else f'{m["id"]}__{m["set"]}'
    gold = Path(m["gold_path"] if m["gold_path"].startswith("/") else ROOT / m["gold_path"]).read_text(encoding="utf-8")
    img = preprocess(render(int(m["vol"]), int(m["page"]), a.dpi), a.prep)
    eff_dpi = a.dpi * (2 if "scale2" in a.prep.split(",") else 1)
    cmd = [a.bin, str(img), "stdout", "-l", a.lang, "--psm", a.psm, "--dpi", str(eff_dpi)]
    if a.tessdata:
        cmd += ["--tessdata-dir", a.tessdata]
    cmd += a.extra.split()
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    times[key] = time.time() - t0
    if r.returncode:
        print(key, "ERR", r.stderr[-200:])
    raw = r.stdout
    prep_ja.PRIMES = prep_ja.Primes()
    text = "\n".join(prep_ja.page_paras(raw))
    text, _ = prep_ja.split_glued(text)
    (out / f"{key}.raw.txt").write_text(raw, encoding="utf-8")
    (out / f"{key}.txt").write_text(text, encoding="utf-8")
    res[key] = {**ocr_score.score_page(gold, text), "type": m["type"], "set": m["set"]}
    print(key, f"{res[key]['cer_norm']:.3f}", f"{times[key]:.1f}s", flush=True)
(out / "time.json").write_text(json.dumps(times))
(out / "metrics.json").write_text(json.dumps({"cmd": cmd, "version": subprocess.run([a.bin, "--version"], capture_output=True, text=True).stdout.splitlines()[:2], "pages": res}, ensure_ascii=False, indent=1))
for s in ("G0", "G2"):
    v = [r["cer_norm"] for r in res.values() if r["set"] == s]
    print("MEAN", s, sum(v) / len(v), "n", len(v))
