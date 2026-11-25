"""性状可用性判断：哪些性状适合做检索表分支依据。

两类证据，缺一不可，结论写明依据（不凭感觉）：
1. 数据证据（从矩阵算）：覆盖率、种内多态率、可比对中的分开比例、不可替代性（只有它能分开的对数）、与其他性状的冗余。
2. 文献/用户证据（外部表 evidence.csv：pattern,verdict,basis）：pattern 为性状名正则，verdict 取 core/ok/caution/avoid，
   basis 写出处（文献页码、用户规则、日期）。没有命中时用下面 GENERIC 的通则（依据写在规则里）。

输出 Judgement：reliability（0-10，喂给 build.cost，默认 5）与 verdict（core/ok/caution/weak/avoid）。
avoid 的性状不进检索表（可用 use_chars 过滤）；caution/weak 由 build 的成本自然降权。
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from .matrix import INAPPLICABLE, UNKNOWN, Matrix

# 通则（无外部证据时使用）：(性状名正则, verdict, 依据)
GENERIC: list[tuple[str, str, str]] = [
    (r"(?i)comment|remark|note|text|description", "avoid", "G1 自由文本不可比较"),
    (r"(?i)colou?r|pigment|stain|pattern_colour", "avoid", "G2 颜色/染色随保存与固定液变化"),
    (r"(?i)^(body|total|overall)[ _]?(length|width|size)|_mm$|weight", "caution", "G3 体长/体宽随个体大小与收缩变化（异速生长）"),
]
VERDICT_BASE = {"core": 7.0, "ok": 5.0, "caution": 3.0, "avoid": 0.0}


@dataclass
class Judgement:
    char: int
    name: str
    coverage: float  # 已知分类单元比例
    poly: float  # 已知值中多态（种内多状态）比例
    sep_comparable: float  # 可比对中状态集不相交的比例
    sep_pairs: int  # 能分开的分类单元对数
    unique_pairs: int  # 只有它能分开的对数（不可替代）
    redundant_with: str  # 分开集合与其高度重合（Jaccard>=0.9）的性状名；无则空
    prior: str  # 外部证据 verdict（无则 generic 或 ''）
    basis: str
    reliability: float
    verdict: str
    reasons: list[str] = field(default_factory=list)


def load_evidence(path: Path | None) -> list[tuple[str, str, str]]:
    if path is None or not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return [(r["pattern"], r["verdict"].strip(), r.get("basis", "")) for r in csv.DictReader(f)
                if r.get("pattern") and r.get("verdict", "").strip() in VERDICT_BASE]


def _known(v: object) -> bool:
    return v not in (UNKNOWN, INAPPLICABLE) and not isinstance(v, str)


def judge(m: Matrix, evidence: list[tuple[str, str, str]] | None = None) -> list[Judgement]:
    ev = (evidence or []) + GENERIC
    n, nc = len(m.taxa), len(m.characters)
    sepset: list[set[tuple[int, int]]] = []
    comparable: list[int] = []
    for c in range(nc):
        s: set[tuple[int, int]] = set()
        cmp_n = 0
        for i, j in combinations(range(n), 2):
            x, y = m.value(i, c), m.value(j, c)
            if _known(x) and _known(y):
                cmp_n += 1
                if not (x & y):  # type: ignore[operator]
                    s.add((i, j))
        sepset.append(s)
        comparable.append(cmp_n)
    cover_all: dict[tuple[int, int], int] = {}
    for s in sepset:
        for p in s:
            cover_all[p] = cover_all.get(p, 0) + 1
    out: list[Judgement] = []
    for c in range(nc):
        vals = [m.value(t, c) for t in range(n)]
        kn = [v for v in vals if _known(v)]
        cov = len(kn) / n if n else 0.0
        poly = sum(1 for v in kn if len(v) > 1) / len(kn) if kn else 0.0  # type: ignore[arg-type]
        sepc = len(sepset[c]) / comparable[c] if comparable[c] else 0.0
        uniq = sum(1 for p in sepset[c] if cover_all[p] == 1)
        red = ""
        for d in range(nc):
            if d != c and sepset[c] and sepset[d]:
                jac = len(sepset[c] & sepset[d]) / len(sepset[c] | sepset[d])
                if jac >= 0.9 and (len(sepset[d]) > len(sepset[c]) or (len(sepset[d]) == len(sepset[c]) and d < c)):
                    red = m.characters[d].name
                    break
        name = m.characters[c].name
        prior, basis = "", ""
        for pat, vd, why in ev:
            if re.search(pat, name):
                prior, basis = vd, why
                break
        reasons: list[str] = []
        r = VERDICT_BASE.get(prior, 5.0)
        if prior:
            reasons.append(f"证据:{prior}（{basis}）")
        if cov < 0.5:
            r -= (0.5 - cov) * 6
            reasons.append(f"覆盖率低 {cov:.0%}")
        if poly > 0.15:
            r -= poly * 5
            reasons.append(f"种内多态 {poly:.0%}")
        if kn and sepc < 0.15:
            r -= 1.5
            reasons.append(f"区分力弱（可比对中仅 {sepc:.0%} 分开）")
        if uniq:
            r += min(2.0, 0.5 * uniq)
            reasons.append(f"不可替代：独自分开 {uniq} 对")
        if red:
            r -= 1.5
            reasons.append(f"与『{red}』冗余")
        if not kn or not sepset[c]:
            r = min(r, 1.0)
            reasons.append("无可用区分信息")
        r = max(0.0, min(10.0, r))
        if prior == "avoid":
            vdict = "avoid"
        elif r >= 6.5:
            vdict = "core"
        elif r >= 4.5:
            vdict = "ok"
        elif r >= 2.5:
            vdict = "caution"
        else:
            vdict = "weak"
        out.append(Judgement(c, name, round(cov, 3), round(poly, 3), round(sepc, 3), len(sepset[c]), uniq, red,
                             prior, basis, round(r, 2), vdict, reasons))
    return out


def apply(m: Matrix, js: list[Judgement]) -> list[int]:
    """把 reliability 写回矩阵，返回可进检索表的性状下标（排除 avoid / 无区分信息）。"""
    use = []
    for j in js:
        m.characters[j.char].reliability = j.reliability
        if j.verdict != "avoid" and j.sep_pairs > 0:
            use.append(j.char)
    return use


def entropy(ps: list[float]) -> float:
    return -sum(p * math.log2(p) for p in ps if p > 0)


def report_md(js: list[Judgement]) -> str:
    rows = ["| 性状 | 判定 | 可靠度 | 覆盖 | 多态 | 区分力 | 独占对 | 理由 |", "|---|---|---|---|---|---|---|---|"]
    for j in sorted(js, key=lambda x: -x.reliability):
        rows.append(f"| {j.name} | {j.verdict} | {j.reliability} | {j.coverage:.0%} | {j.poly:.0%} | {j.sep_comparable:.0%} | "
                    f"{j.unique_pairs} | {'；'.join(j.reasons)} |")
    return "\n".join(rows)
