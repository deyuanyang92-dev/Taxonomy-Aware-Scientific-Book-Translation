"""A8/A9：分类单元对的区分审计（TaxonWorks Matrix Validation 思路，自行实现）。

对每一对分类单元，按性状矩阵给出三档，只描述"矩阵里有没有区分证据"，不下分类学结论：
- separated：至少 1 个性状 comp=1（状态集不相交）。evidence 列出这些性状。
  只有 1 个时 weak=True（弱边界，单性状支撑）。
- evidence_gap：没有分开的性状，但有性状因任一方未知/不适用而不可比较 → 可能是数据缺口。
- matrix_silent：没有分开的性状，且所有性状都可比较且状态集相交 → 矩阵未给出区分
  （可能是性状选得不够，也可能确实同种；矩阵本身无法判定）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from .matrix import INAPPLICABLE, UNKNOWN, Matrix
from .metrics import comp


@dataclass
class PairResult:
    a: int
    b: int
    tier: str  # separated | evidence_gap | matrix_silent
    separating: list[int] = field(default_factory=list)
    gaps: list[int] = field(default_factory=list)  # 因未知/不适用无法比较的性状
    weak: bool = False


def audit_pairs(m: Matrix, chars: list[int] | None = None) -> list[PairResult]:
    cs = list(range(len(m.characters))) if chars is None else chars
    out = []
    for i, j in combinations(range(len(m.taxa)), 2):
        sep, gaps = [], []
        for c in cs:
            x, y = m.value(i, c), m.value(j, c)
            if x in (UNKNOWN, INAPPLICABLE) or y in (UNKNOWN, INAPPLICABLE):
                gaps.append(c)
            elif comp(m, i, j, c) == 1:
                sep.append(c)
        if sep:
            out.append(PairResult(i, j, "separated", sep, gaps, weak=len(sep) == 1))
        elif gaps:
            out.append(PairResult(i, j, "evidence_gap", sep, gaps))
        else:
            out.append(PairResult(i, j, "matrix_silent", sep, gaps))
    return out
