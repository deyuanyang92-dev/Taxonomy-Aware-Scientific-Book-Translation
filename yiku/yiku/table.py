"""术语表渲染：HARD（必用）与 SOFT（先判义项再取舍）两节，带出处、层级、状态、定义语境、中文用例，并限制总长。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import db as D
from .classify import HARD, TermClass, classify, top_group

DEFAULT_MAX_CHARS = 9000    # 整张表的目标长度（约一块 9000 字符原文配一张表）；只约束 SOFT 节，HARD 永不截断
MIN_SOFT_BUDGET = 3000      # HARD 很长时 SOFT 至少保留的预算
MAX_ROWS_PER_TERM = 5       # 同一英文术语最多列几行（自域与回退分行，同一译名同领域合并为一行）
MAX_EXAMPLE_TERMS = 30      # 至多为多少个 SOFT 术语去查用例（控制 docstore 检索次数）
EXAMPLE_RESERVE = 0.2       # 有资料库时，预算的这一部分留给中文用例，不让候选行占满
ALT_ZH_CHARS = 14           # HARD 行「其他译名」里单个译名最多显示的字数（候选里常混入抽取残句）
CTX_CHARS = 100
OMIT_LIST = 15
SEP = "；"

HOW_TO = (
    "使用规则（HARD 与 SOFT 两类，务必区分）：\n"
    "- HARD：必用。原文出现该术语，就用表中译名，不得改译、不得另造；「其他译名」是落选译名，不用。\n"
    "- SOFT：译名或义项不唯一，或只是候选、只来自其他领域。先读「定义/出处语境」，判断本书此处的义项是否与出处相同，"
    "再从列出的译名中取舍；都不合适就按本书语境译。〔回退〕＝来自其他领域的译名，仅在本领域没有合适译名且义项吻合时参考，"
    "不得压过本领域已核译名。状态栏带 ⚠ 的＝同级已核来源给出不同译名，须按语境判断；带 ★首选 的＝本领域最高层级的已核译名"
    "（层级数字越小越权威；环节动物书里杨德渐、孙瑞平等 1–2 级来源优先于名词委、译本），义项相同就用它，义项不同才另选。"
    "取舍须按本次任务的要求登记为术语决策。"
)


def _cell(s: str | None) -> str:
    return (s or "").replace("|", "｜").replace("\r", " ").replace("\n", " ").strip()


def _ctx(s: str | None, n: int = CTX_CHARS) -> str:
    c = _cell(s)
    return c[:n] + "…" if len(c) > n else c


def _cites(hits: list[D.Hit], cap: int = 3) -> str:
    seen: list[str] = []
    for h in hits:
        c = h.cite() + ("〔回退〕" if h.fallback else "")
        if c not in seen:
            seen.append(c)
    s = SEP.join(seen[:cap])
    return _cell(s + (f"等{len(seen)}处" if len(seen) > cap else ""))


@dataclass
class _Row:
    en: str
    zh: str
    hits: list[D.Hit]
    flag: str = ""  # 状态栏附注：⚠冲突 / ★首选
    examples: list[str] = field(default_factory=list)

    @property
    def tier(self) -> int:
        return min(h.tier for h in self.hits)

    @property
    def status(self) -> str:
        return "已核" if any(h.status == "已核" for h in self.hits) else "候选"

    @property
    def fallback(self) -> bool:
        return all(h.fallback for h in self.hits)

    def line(self) -> str:
        ctx = next((h.context for h in self.hits if h.context), None)
        status = self.status + (f" {self.flag}" if self.flag else "")
        ex = " ◇ ".join(self.examples)
        return (f"| {_cell(self.en)} | {_cell(self.zh)} | {_cites(self.hits)} | {self.tier} | {status} | "
                f"{_ctx(ctx)} | {ex} |")


def _soft_rows(hits: list[D.Hit], cls: TermClass) -> tuple[list[_Row], int]:
    """每个（译名, 是否回退）一行，按排序后的首次出现为序；超出 MAX_ROWS_PER_TERM 的并入省略计数。"""
    top_zh = {h.zh for h in top_group(hits)}
    flag = {"conflict": "⚠冲突", "tier-split": "★首选"}.get(cls.reason, "")
    flagged = top_zh if flag else set()
    groups: dict[tuple[str, bool], list[D.Hit]] = {}
    for h in hits:
        groups.setdefault((h.zh, h.fallback), []).append(h)
    rows = [_Row(hs[0].en, zh, hs, flag if zh in flagged and not fb else "") for (zh, fb), hs in groups.items()]
    return rows[:MAX_ROWS_PER_TERM], max(len(rows) - MAX_ROWS_PER_TERM, 0)


def _priority(rows: list[_Row], cls: TermClass) -> int:
    """越小越先保留：同级冲突/层级分歧 < 有已核译名或回退但多译名 < 其余有已核/回退 < 只有候选的单一译名。"""
    if cls.reason in ("conflict", "tier-split"):
        return 0
    if len({r.zh for r in rows}) > 1 and any(r.status == "已核" for r in rows):
        return 1
    if any(r.status == "已核" for r in rows) or all(r.fallback for r in rows):
        return 2
    return 3


def _hard_line(hits: list[D.Hit], cls: TermClass) -> str:
    top = top_group(hits)
    alts: list[tuple[str, str]] = []
    for h in hits:
        if not h.fallback and h.zh != cls.zh and h.zh not in [a[0] for a in alts]:
            alts.append((h.zh, h.cite()))
    alt = SEP.join(f"{z[:ALT_ZH_CHARS]}{'…' if len(z) > ALT_ZH_CHARS else ''}（{c}）" for z, c in alts[:3]) + (f"等{len(alts)}个" if len(alts) > 3 else "")
    return f"| {_cell(top[0].en)} | {_cell(cls.zh)} | {_cites(top)} | {top[0].status} | {_cell(alt)} |"


def render_table(con: Any, found: dict[str, int], domain: str, scope: set[str] | None, fb: list[str],
                 usage: Any = None, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    hard: list[str] = []
    soft: list[tuple[int, int, str, list[_Row], int]] = []
    for en, n in sorted(found.items()):
        hits = D.candidates(con, en, domain, scope, fb)
        if not hits:
            continue
        cls = classify(hits)
        if cls.kind == HARD:
            hard.append(_hard_line(hits, cls))
        else:
            rows, extra = _soft_rows(hits, cls)
            soft.append((_priority(rows, cls), -n, en, rows, extra))
    soft.sort(key=lambda x: x[:3])

    head = (f"领域：{domain}；类群：{'、'.join(sorted(scope)) if scope else '通用'}；"
            f"回退领域：{'、'.join(fb) if fb else '无'}\n{HOW_TO}\n")
    if not hard and not soft:
        return head + "\n| （原文未命中术语库） | | | | |"

    hard_sec = ("\n## HARD（必用）\n| 英文 | 译名 | 依据 | 状态 | 其他译名（不用） |\n|---|---|---|---|---|\n"
                + ("\n".join(hard) if hard else "| （无） | | | | |"))
    soft_head = ("\n\n## SOFT（先判义项，再取舍）\n| 英文 | 译名 | 依据 | 层级 | 状态 | 定义/出处语境 | 中文用例 |\n"
                 "|---|---|---|---|---|---|---|\n")
    budget = max(max_chars - len(head) - len(hard_sec) - len(soft_head), MIN_SOFT_BUDGET)

    kept: list[tuple[int, list[_Row], int]] = []
    omitted: list[str] = []
    used = 0
    can_example = usage is not None and getattr(usage, "store", True) is not None
    row_budget = int(budget * (1 - EXAMPLE_RESERVE)) if can_example else budget
    for prio, _n, en, rows, extra in soft:
        cost = sum(len(r.line()) + 1 for r in rows) + (len(f"| {en} | …另有 {extra} 个译名省略 |") if extra else 0)
        if used + cost > row_budget:
            omitted.append(rows[0].en)
            continue
        used += cost
        kept.append((prio, rows, extra))
    # 余量用来补中文用例：先给优先级高的（冲突、多译名）
    if can_example:
        done = 0
        for prio, rows, _extra in kept:
            if prio >= 3 or done >= MAX_EXAMPLE_TERMS:
                continue
            done += 1
            seen_zh: set[str] = set()
            for r in rows:
                if r.zh in seen_zh:  # 同一译名的自域行与回退行用例相同，只在第一行给
                    continue
                seen_zh.add(r.zh)
                longer = [o.zh for o in rows if o.zh != r.zh and r.zh in o.zh]
                ex = usage.examples(r.zh, sorted({h.source for h in r.hits}), 2, longer)
                if not ex:
                    continue
                before = len(r.line())
                r.examples = ex
                grow = len(r.line()) - before
                if used + grow > budget:
                    r.examples = []
                else:
                    used += grow
    lines: list[str] = []
    for _prio, rows, extra in kept:
        lines.extend(r.line() for r in rows)
        if extra:
            lines.append(f"| {_cell(rows[0].en)} | …另有 {extra} 个译名省略 | | | | | |")
    body = "\n".join(lines) if lines else "| （无） | | | | | | |"
    tail = ""
    if omitted:
        names = "、".join(omitted[:OMIT_LIST]) + ("等" if len(omitted) > OMIT_LIST else "")
        tail = (f"\n（SOFT 另有 {len(omitted)} 个术语因篇幅省略：{names}。遇到时按本书语境自行判断，并照常登记术语决策。）")
    return head + hard_sec + soft_head + body + tail
