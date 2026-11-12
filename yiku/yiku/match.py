"""在原文里找出术语库收录的术语，生成注入提示词的术语表；对照译文检查术语一致性。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Hit, candidates

_LATIN_PLURAL = (("us", "i"), ("um", "a"), ("on", "a"), ("a", "ae"), ("is", "es"), ("y", "ies"))


def forms(en: str) -> set[str]:
    """英文词形：单复数、拉丁复数。只变化最后一个词。"""
    t = en.lower()
    f = {t, t + "s", t + "es"}
    for a, b in _LATIN_PLURAL:
        if t.endswith(a):
            f.add(t[: -len(a)] + b)
    return f


def _pattern(en: str) -> re.Pattern:
    alts = sorted((re.escape(x).replace(r"\ ", r"[\s-]+") for x in forms(en)), key=len, reverse=True)
    # 前后不能紧挨字母或数字：图号 38.2f 里的 f 不是缩写 f.（变型）
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(alts) + r")(?![A-Za-z0-9])", re.I)


def find_terms(con, text: str, domain: str = "*") -> dict[str, int]:
    """原文中出现的、库里有译名的术语 -> 出现次数。长术语优先，避免 'palp' 抢 'palpal organ'。"""
    text = text.replace("-\n", "")
    ens = [r[0] for r in con.execute(
        "SELECT DISTINCT en_norm FROM terms WHERE status!='否决' AND (domain='*' OR domain=?)", (domain,))]
    found: dict[str, int] = {}
    masked = text
    for en in sorted(ens, key=len, reverse=True):
        pat = _pattern(en)
        n = len(pat.findall(masked))
        if n:
            found[en] = n
            masked = pat.sub(" ", masked)
    return found


def _ctx(h: Hit, n: int = 60) -> str:
    c = (h.context or "").replace("|", "｜").replace("\n", " ").strip()
    return c[:n] + "…" if len(c) > n else c


def _rank(h: Hit) -> tuple:
    return (h.status, h.domain, h.scope, h.tier, h.year)  # 同层级不同年份：新版优先，不算冲突


def term_table(con, text: str, domain: str = "*", scope: set[str] | None = None) -> str:
    """Markdown 术语表，供任何模型的提示词使用。

    术语按「英文 + 义项」理解：表中给出出处语境，译者先判断本书此处的义项是否与出处相同，再决定是否采用。
    同级（状态、领域、类群、来源层级都相同）的已核译名不一致时标「冲突」，不替译者默认选第一个。"""
    rows = []
    for en, n in sorted(find_terms(con, text, domain).items()):
        c = candidates(con, en, domain, scope)
        if not c:
            continue
        b = c[0]
        rivals = [h for h in c[1:] if h.zh != b.zh and h.status == "已核" and _rank(h) == _rank(b)]
        if rivals:
            flag = "⚠冲突：另有 " + "、".join(sorted({h.zh for h in rivals}))
        else:
            flag = b.status
        others = "；".join(sorted({f"{h.zh}（{h.cite()}）" for h in c[1:] if h.zh != b.zh}))
        rows.append(f"| {b.en} | {b.zh} | {b.cite()} | {flag} | {_ctx(b)} | {others} |")
    head = (f"领域：{domain}；类群：{'、'.join(sorted(scope)) if scope else '通用'}\n"
            "用法：义项与出处语境相同才用（已核必用，候选可用）；否则按本书语境译并登记。\n\n"
            "| 英文 | 译名 | 依据 | 状态 | 出处语境 | 其他译名 |\n|---|---|---|---|---|---|")
    return head + ("\n" + "\n".join(rows) if rows else "\n| （原文未命中术语库） | | | | | |")


@dataclass
class Issue:
    en: str
    expected: str
    found_alternatives: list[str]
    count_en: int

    def line(self) -> str:
        alt = f"；译文用了落选译名：{'、'.join(self.found_alternatives)}" if self.found_alternatives else ""
        return f"{self.en}（原文 {self.count_en} 次）应译「{self.expected}」，译文中未出现{alt}"


def variants(zh: str) -> set[str]:
    """译名在正文中可接受的形式：去括注、去词尾「的」、去词头「具/呈」、门纲级可省阶元字。"""
    v = {zh, re.sub(r"[（(][^）)]*[）)]", "", zh)}
    for x in list(v):
        v.add(x[:-1] if x.endswith("的") and len(x) > 2 else x)
    for x in list(v):
        v.add(x[1:] if x[:1] in "具呈" and len(x) > 2 else x)
        v.add(re.sub(r"(动物门|门|亚纲|纲)$", lambda m: "动物" if m.group(1) == "动物门" else "", x) or x)
    return {x for x in v if len(x) >= 2} | {zh}


def check(con, src: str, zh: str, domain: str = "*", scope: set[str] | None = None) -> list[Issue]:
    """只检查已核术语：原文出现、而译文里没有采用译名的，报出来；同时指出译文里出现的落选译名。"""
    issues = []
    for en, n in sorted(find_terms(con, src, domain).items()):
        c = candidates(con, en, domain, scope)
        if not c or c[0].status != "已核":
            continue
        b = c[0]
        if any(x in zh for x in variants(b.zh)):
            continue
        alts = sorted({h.zh for h in c[1:] if h.zh != b.zh and h.zh in zh})
        issues.append(Issue(b.en, b.zh, alts, n))
    return issues
