"""B1：DELTA KEY 贪心建表（二叉以外的多歧表）。

依据：DELTA User's Guide §5.4（Dallwitz, Paine & Zurcher），公式式(5)：
  K = c + cmin * [ sum_j f_j*log2(n_j) / sum_j f_j + V ]
  V = ((1-v)/v) * ((n+8)/(n*log2 n)) * (sum_j n_j - n) * (1+100m)
  c = RBASE^(5-min(10,reliability))；f_j = 子组内各分类单元权重之和，权重 = ABASE^(abundance-5)
  n = 当前组分类单元数，n_j = 子组 j 的分类单元数，m = 与原组同大小的子组数，v = VARYWT。
默认 RBASE=1.40 ABASE=2.00 VARYWT=0.80（手册 §5.3）。K 最小者入选，并列取性状序号小者。
本实现独立编写，只借公式；未实现 REUSE、强制性状、控制性状（依赖关系）、混合阶元。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .matrix import UNKNOWN, Matrix

RBASE = 1.40
ABASE = 2.00
VARYWT = 0.80


@dataclass
class Node:
    taxa: list[int]  # 本节点剩余分类单元（下标）
    char: int | None = None  # 选用的性状；None = 叶
    children: dict[int, Node] = field(default_factory=dict)  # 状态下标 -> 子节点
    k: float | None = None


def cost(reliability: float, rbase: float = RBASE) -> float:
    return rbase ** (5 - min(10.0, reliability))


def subgroups(m: Matrix, taxa: list[int], ch: int, unknown_all: bool = False) -> dict[int, list[int]] | None:
    """按性状 ch 把 taxa 分子组；任一分类单元不适用则返回 None。

    未知（?）：默认返回 None（该性状在本组不用）；unknown_all=True 时未知的分类单元
    进入该性状的每个状态组（重复出现，由 dupf 惩罚）。open-delta KEY 2.12 实际是后者：
    Travisia 数据上 unknown_all=True 与 KEY 的首条路径、最长 11 步一致，17 个性状中 16 个相同
    （survey/checks/delta_travisia/compare_report.md，2026-11-24）；默认 False 未改，避免改变既有结果。
    """
    groups: dict[int, list[int]] = {}
    unk: list[int] = []
    for t in taxa:
        v = m.value(t, ch)
        if isinstance(v, str):
            if unknown_all and v == UNKNOWN:
                unk.append(t)
                continue
            return None
        for s in sorted(v):
            groups.setdefault(s, []).append(t)
    if unk:
        if not groups:
            return None
        for s in groups:
            groups[s] += unk
    return groups


def kvalue(m: Matrix, taxa: list[int], ch: int, cmin: float, *, rbase: float = RBASE,
           abase: float = ABASE, varywt: float = VARYWT,
           allow_improper: bool = False, unknown_all: bool = False) -> float | None:
    """性状 ch 在当前组 taxa 上的 K；不可用返回 None。"""
    n = len(taxa)
    groups = subgroups(m, taxa, ch, unknown_all)
    if groups is None:
        return None
    sizes = {s: len(g) for s, g in groups.items()}
    if len(sizes) < 2 or any(sz == sum(sizes.values()) for sz in sizes.values()):
        return None  # 只有一个非空子组：不能分
    same = sum(1 for sz in sizes.values() if sz == n)
    if same and not allow_improper:
        return None
    w = {t: abase ** (m.taxa[t].abundance - 5) for t in taxa}
    f = {s: sum(w[t] for t in g) for s, g in groups.items()}
    sup0 = sum(f[s] * math.log2(sizes[s]) for s in groups) / sum(f.values())
    tot = sum(sizes.values())
    dupf = 0.0
    if tot > n:
        varw = (1 - varywt) / varywt if varywt > 0 else 0.0
        dupf = varw * (1 + 100 * same) * (tot - n) * ((n + 8) / (n * math.log2(n)))
    return cost(m.characters[ch].reliability, rbase) + cmin * (sup0 + dupf)


def best_char(m: Matrix, taxa: list[int], chars: list[int], **kw: float | bool) -> tuple[int, float] | None:
    """K 最小的性状；并列取序号小者（open-delta 行为）。"""
    if not chars:
        return None
    rb = float(kw.get("rbase", RBASE))
    cmin = min(cost(m.characters[c].reliability, rb) for c in chars)
    best: tuple[int, float] | None = None
    for c in sorted(chars):
        k = kvalue(m, taxa, c, cmin, **kw)  # type: ignore[arg-type]
        if k is not None and (best is None or k < best[1]):
            best = (c, k)
    return best


def build(m: Matrix, chars: list[int] | None = None, **kw: float | bool) -> Node:
    """递归建表。多态分类单元进入多个子组（重复出现）。"""
    avail = list(range(len(m.characters))) if chars is None else list(chars)

    def rec(taxa: list[int]) -> Node:
        node = Node(taxa=taxa)
        if len(taxa) < 2:
            return node
        pick = best_char(m, taxa, avail, **kw)
        if pick is None:
            return node  # 无可用性状：叶里留多个分类单元（无法区分）
        node.char, node.k = pick
        groups = subgroups(m, taxa, pick[0], bool(kw.get("unknown_all", False))) or {}
        for s in sorted(groups):
            node.children[s] = rec(groups[s])
        return node

    return rec(list(range(len(m.taxa))))


def leaves(node: Node, path: tuple[tuple[int, int], ...] = ()) -> list[tuple[list[int], tuple[tuple[int, int], ...]]]:
    """(叶中分类单元, 路径[(性状,状态)...]) 列表。"""
    if node.char is None:
        return [(node.taxa, path)]
    out = []
    for s, ch in node.children.items():
        out += leaves(ch, path + ((node.char, s),))
    return out
