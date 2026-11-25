"""性状矩阵中间表示（B1 建表用）。

每个性状是多态编码：taxon -> 性状 -> 状态集合。
- 值是状态下标的 frozenset（多于 1 个 = 种内变异/多态）。
- UNKNOWN：未知；INAPPLICABLE：不适用。两者在建表时都使该性状在含该种的分组里不可用
  （本模块的默认；open-delta 实测并不丢弃含未知的性状，而是把未知种放进每个状态组，对应 build(unknown_all=True)，见 survey/PLAN_DELTA.md）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN = "?"
INAPPLICABLE = "-"

Value = frozenset[int] | str


@dataclass
class Character:
    name: str
    states: list[str]
    reliability: float = 5.0  # DELTA: 1..10，越大越可靠


@dataclass
class Taxon:
    name: str
    values: dict[int, Value] = field(default_factory=dict)  # 性状下标 -> 值
    abundance: float = 5.0  # DELTA: 1..10，权重 ABASE^(abundance-5)


@dataclass
class Matrix:
    characters: list[Character]
    taxa: list[Taxon]

    def value(self, taxon: int, char: int) -> Value:
        return self.taxa[taxon].values.get(char, UNKNOWN)
