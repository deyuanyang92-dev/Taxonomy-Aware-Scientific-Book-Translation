"""B4 判别力 PD 与 A1-A3 检索表形状指标。

PD：Kerner et al. 2025 (EJT 987) "Main mathematical functions"：
  comp_k(i,j)=1 当且仅当 d_k(i)∩d_k(j)=∅；PD(k)=Σ_{i<j} comp_k(i,j)；
  父性状 PD = 子性状 PD 的最大值。comp 只在两者都适用时可算。
  假设（原文未明说）：UNKNOWN 视为"可能含任何状态"，comp=0；INAPPLICABLE 的对不计入。
L_min、L_max：DELTA 手册式(1)；L_max=(n-1)(n+2)/(2n) 为 key2 自推，已对 n=2..16 穷举核对
  （survey/checks/test_formulas.py）。仅适用于二歧表。
E_shape=(L_max-L_obs)/(L_max-L_min)：key2 自创线性归一，只作"鉴定效率"，不作分类证据。
E_dicho：Sinh 等 2017 ZooKeys 685:83 的 Pielou 均匀度，p_i=N_i/N，N_i=第 i 个分类单元的鉴定步数。
  多态分类单元在表里出现多次时，取其各叶深度的平均值（假设，原文未涉及）。
"""
from __future__ import annotations

import math
from itertools import combinations

from .build import Node, leaves
from .matrix import INAPPLICABLE, UNKNOWN, Matrix


def comp(m: Matrix, i: int, j: int, ch: int) -> int | None:
    """1=不相容，0=相容，None=不可算（任一方不适用）。"""
    a, b = m.value(i, ch), m.value(j, ch)
    if a == INAPPLICABLE or b == INAPPLICABLE:
        return None
    if a == UNKNOWN or b == UNKNOWN:
        return 0
    assert not isinstance(a, str) and not isinstance(b, str)
    return int(not (a & b))


def pd(m: Matrix, ch: int, taxa: list[int] | None = None) -> int:
    ts = list(range(len(m.taxa))) if taxa is None else taxa
    return sum(c for i, j in combinations(ts, 2) if (c := comp(m, i, j, ch)) is not None)


def parent_pd(child_pds: list[int]) -> int:
    return max(child_pds)


def lmin(n: int) -> float:
    k = int(math.log2(n))
    return k + 2 - 2 ** (k + 1) / n


def lmax(n: int) -> float:
    return (n - 1) * (n + 2) / (2 * n)


def _is_binary(node: Node) -> bool:
    return node.char is None or (len(node.children) == 2 and all(_is_binary(c) for c in node.children.values()))


def step_counts(tree: Node) -> dict[int, float]:
    """分类单元 -> 鉴定步数（出现多次取平均深度）。"""
    acc: dict[int, list[int]] = {}
    for ts, path in leaves(tree):
        for t in ts:
            acc.setdefault(t, []).append(len(path))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def e_shape(tree: Node) -> float:
    if not _is_binary(tree):
        raise ValueError("E_shape 只适用于二歧表")
    steps = step_counts(tree)
    n = len(steps)
    l_obs = sum(steps.values()) / n
    return (lmax(n) - l_obs) / (lmax(n) - lmin(n))


def e_dicho(tree: Node) -> float:
    steps = list(step_counts(tree).values())
    tot = sum(steps)
    ps = [s / tot for s in steps]
    return -sum(p * math.log(p) for p in ps) / math.log(len(ps))
