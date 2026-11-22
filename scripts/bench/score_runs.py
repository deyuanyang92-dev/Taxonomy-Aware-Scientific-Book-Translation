#!/usr/bin/env python3
"""给 bench/api_runs/<name>/<lang>/<id>.md 打分：对 bench/gold_dl 的 cer_norm，按语种报均值与 bootstrap 95% CI。
用法：python3 scripts/bench/score_runs.py <name> [<name2> ...]   （多个名称时按共同页做配对比较）
"""
import random
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ocr_score import cer, norm

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    d = {}
    for p in (ROOT / "bench/api_runs" / name).glob("*/*.md"):
        g = ROOT / "bench/gold_dl" / p.parent.name / p.name
        if g.exists():
            d[(p.parent.name, p.stem)] = cer(norm(g.read_text(encoding="utf-8")), norm(p.read_text(encoding="utf-8")))
    return d


def ci(x, n=2000):
    r = random.Random(1)
    m = sorted(statistics.mean(r.choices(x, k=len(x))) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]


names = sys.argv[1:]
res = {n: load(n) for n in names}
for n in names:
    for lang in ("ru", "fr", "la"):
        x = [v for (l, _), v in res[n].items() if l == lang]
        if x:
            lo, hi = ci(x)
            print(f"{n:24s} {lang} n={len(x):3d} CER={statistics.mean(x):.4f} [{lo:.4f},{hi:.4f}] median={statistics.median(x):.4f}")
if len(names) == 2:
    a, b = res[names[0]], res[names[1]]
    for lang in ("ru", "fr", "la"):
        k = [x for x in a if x in b and x[0] == lang]
        if k:
            d = [a[x] - b[x] for x in k]
            lo, hi = ci(d)
            print(f"paired {names[0]}-{names[1]} {lang} n={len(k)} meanΔ={statistics.mean(d):+.4f} [{lo:+.4f},{hi:+.4f}] sd={statistics.pstdev(d):.4f}")
