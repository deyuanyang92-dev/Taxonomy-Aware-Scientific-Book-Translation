#!/usr/bin/env python3
"""多引擎融合上界/投票实验（零成本，只读已有输出）。
用法：python3 scripts/bench/fusion_exp.py <lang> <引擎A> <引擎B> <引擎C> ...
引擎名：bench/matrix/<名>/<id>.txt 或 bench/api_runs/<名>/<lang>/<id>.md。第一个引擎为基底。
输出：各引擎 CER、逐页择优上界(oracle)、2:1 字符级投票融合的 CER，及配对 Δ 的 bootstrap 95% CI（对基底）。
"""
from __future__ import annotations

import difflib
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ocr_score import cer, norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def read(name: str, lang: str, pid: str) -> str | None:
    for p in (ROOT / "bench/matrix" / name / f"{pid}.txt", ROOT / "bench/api_runs" / name / lang / f"{pid}.md"):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def vote3(base: str, others: list[str]) -> str:
    """基底文本；某段基底与全部其余引擎不同、而其余引擎彼此一致时，采用其余引擎的版本（>=2 票对 1 票的覆盖）。"""
    if len(others) < 2:
        return base
    ops = []
    for o in others:
        sm = difflib.SequenceMatcher(None, base, o, autojunk=False)
        ops.append({(i1, i2): o[j1:j2] for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"})
    out, pos = [], 0
    keys = sorted(set().union(*[set(d) for d in ops]))
    for k in keys:
        if k[0] < pos:
            continue
        cands = [d[k] for d in ops if k in d]
        if len(cands) == len(others) and len(set(cands)) == 1:
            out.append(base[pos:k[0]])
            out.append(cands[0])
            pos = k[1]
    out.append(base[pos:])
    return "".join(out)


def ci(x: list[float], n: int = 2000) -> tuple[float, float]:
    r = random.Random(1)
    m = sorted(statistics.mean(r.choices(x, k=len(x))) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]


def main(argv: list[str]) -> int:
    lang, engines = argv[0], argv[1:]
    ids = sorted(p.stem for p in (ROOT / "bench/gold_dl" / lang).glob("*.md"))
    rows: list[tuple[list[float], float, float]] = []
    for pid in ids:
        texts = [read(e, lang, pid) for e in engines]
        if any(t is None for t in texts):
            continue
        g = norm((ROOT / "bench/gold_dl" / lang / f"{pid}.md").read_text(encoding="utf-8"))
        if not g:
            continue
        ns = [norm(t) for t in texts]  # type: ignore[arg-type]
        c = [cer(g, t) for t in ns]
        fused = cer(g, vote3(ns[0], ns[1:]))
        rows.append((c, min(c), fused))
    n = len(rows)
    print(f"{lang} n={n} 引擎={engines}")
    for i, e in enumerate(engines):
        print(f"  {e:28s} CER={statistics.mean(r[0][i] for r in rows):.4f}")
    base = [r[0][0] for r in rows]
    for label, v in (("oracle逐页择优(上界)", [r[1] for r in rows]), ("2:1字符投票融合", [r[2] for r in rows])):
        d = [a - b for a, b in zip(base, v)]
        lo, hi = ci(d)
        print(f"  {label:20s} CER={statistics.mean(v):.4f}  较基底改善 {statistics.mean(d):+.4f} [{lo:+.4f},{hi:+.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
