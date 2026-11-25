#!/usr/bin/env python3
"""汇总各引擎（Tesseract 矩阵、本地 PaddleOCR 矩阵、云 API 各版本）在同一批页上对 Datalab 金标的 CER。
只纳入 50/50 页都有结果的引擎；均值带 bootstrap 95% CI，另给中位数。输出 bench/summary_150.md。
用法：python3 scripts/bench/engine_summary.py
"""
import random
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ocr_score import cer, norm

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "bench/gold_dl"


def ci(x, n=2000):
    r = random.Random(1)
    m = sorted(statistics.mean(r.choices(x, k=len(x))) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]


def collect(lang):
    res = {}
    for d in (ROOT / "bench/matrix").iterdir():
        if d.is_dir() and d.name[0] in "TP":
            res["local:" + d.name] = {p.stem: p for p in d.glob(f"{lang}_*.txt")}
    for d in (ROOT / "bench/api_runs").iterdir():
        res["api:" + d.name] = {p.stem: p for p in (d / lang).glob("*.md")}
    out = {}
    for k, files in res.items():
        sc = {}
        for i, p in files.items():
            g = G / lang / (i + ".md")
            if g.exists():
                sc[i] = cer(norm(g.read_text(encoding="utf-8")), norm(p.read_text(encoding="utf-8")))
        if len(sc) >= 50:
            out[k] = sc
    return out


lines = ["# 150 页引擎汇总（对 Datalab 金标；金标不是人工真值；n=每语种 50 页）\n"]
for lang in ("ru", "fr", "la"):
    r = collect(lang)
    rank = sorted(r, key=lambda k: statistics.mean(r[k].values()))
    best = rank[0]
    lines += [f"## {lang}（最优均值：{best}）\n", "| 引擎/配置 | 均值 | 95% CI | 中位数 | 对最优 Δ [95% CI] |", "|---|---|---|---|---|"]
    for k in rank[:12]:
        x = list(r[k].values()); lo, hi = ci(x)
        d = [r[k][i] - r[best][i] for i in r[k] if i in r[best]]
        dl, dh = ci(d) if k != best else (0, 0)
        lines.append(f"| {k} | {statistics.mean(x):.4f} | [{lo:.4f}, {hi:.4f}] | {statistics.median(x):.4f} | {statistics.mean(d):+.4f} [{dl:+.4f}, {dh:+.4f}] |")
    lines.append("")
(ROOT / "bench/summary_150.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
