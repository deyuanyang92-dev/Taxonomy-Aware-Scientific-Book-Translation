"""术语分类：HARD（必用，不得改译）与 SOFT（须按语境判断义项，并登记决策）。

HARD：
  1. 学名（科、属、种等拉丁名）：自域最优一组（状态、层级、出版年相同）译名一致即 HARD——
     新旧版、不同层级来源不一致时，按层级与出版年取最优的一组；候选译名只要来自名录以上层级（tier<=4）也算。
  2. 非学名：自域内「所有」已核来源给出同一个中文名（回退领域和候选不参与）。
SOFT：其余一切 —— 自域已核译名不止一个、只有候选、只在回退领域有、库里没有。
  自域已核译名不止一个时分两种：同级冲突（reason=conflict）；层级不同（reason=tier-split，
  最优一组一致，preferred=其译名，用户规则：杨德渐、孙瑞平等一级来源在环节动物书里永远优先于名词委、译本）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Hit

HARD = "HARD"
SOFT = "SOFT"
TAXON_MAX_TIER = 4  # 学名的候选译名要来自名录（checklist=3）、名词委（standard=4）及以上才算 HARD

# 属名/科名/高阶元：首字母大写的拉丁词；可带 (亚属)、cf./aff./sp./nov. 和小写的种加词（至多 3 个）
_GENUS = r"[A-Z][a-z]+"
_TAXON = re.compile(rf"^{_GENUS}(?: \({_GENUS}\))?(?: (?:cf\.|aff\.|sp\.|nov\.|[a-z]{{3,}})){{0,3}}$")
# 英语/学说名词的构词尾（Lamarckism、Biospecies、Hennigian）不是拉丁学名
_NOT_LATIN = re.compile(r"(ism|ist|ian|ic|ous|ive|ment|tion|ness|ity|type|species|logy)$")


def is_taxon_name(en: str) -> bool:
    """en 是否形如分类单元的拉丁学名。启发式：大写开头的拉丁词（可带亚属、cf.、种加词），排除英语构词尾。"""
    en = en.strip()
    if not _TAXON.match(en):
        return False
    words = en.split()
    return not _NOT_LATIN.search(words[0].lower()) and "species" not in words[1:]


@dataclass
class TermClass:
    kind: str                 # HARD / SOFT
    reason: str               # taxon | verified | conflict | tier-split | multi-zh | candidate-only | fallback-only | none
    zh: str | None = None     # HARD 的必用译名
    preferred: str | None = None  # SOFT tier-split：最高层级已核来源一致给出的译名（首选，但义项不同时可另选）


def rank_key(h: Hit) -> tuple:
    """同一「级别」：状态、领域、类群、来源层级、出版年全相同。"""
    return (h.status, h.domain, h.scope, h.tier, h.year)


def top_group(hits: list[Hit]) -> list[Hit]:
    """自域（非回退）命中里排第一的那一级别的全部命中。hits 须已按 db.candidates 排序。"""
    own = [h for h in hits if not h.fallback]
    return [h for h in own if rank_key(h) == rank_key(own[0])] if own else []


def classify(hits: list[Hit]) -> TermClass:
    own = [h for h in hits if not h.fallback]
    top = top_group(hits)
    if not top:
        return TermClass(SOFT, "fallback-only" if hits else "none")
    first = top[0]
    top_zh = {h.zh for h in top}
    if any(is_taxon_name(h.en) for h in top) and len(top_zh) == 1 and (first.status == "已核" or first.tier <= TAXON_MAX_TIER):
        return TermClass(HARD, "taxon", first.zh)
    verified = {h.zh for h in own if h.status == "已核"}
    if len(verified) == 1:
        return TermClass(HARD, "verified", first.zh)
    if len(verified) > 1:
        if first.status == "已核" and len(top_zh) == 1:
            return TermClass(SOFT, "tier-split", preferred=first.zh)
        return TermClass(SOFT, "conflict")
    return TermClass(SOFT, "multi-zh" if len(top_zh) > 1 else "candidate-only")
