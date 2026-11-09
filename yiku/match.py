"""在原文里找出术语库收录的术语，生成注入提示词的术语表；对照译文检查术语一致性。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .db import candidates

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
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?![A-Za-z])", re.I)


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


def term_table(con, text: str, domain: str = "*", scope: set[str] | None = None) -> str:
    """Markdown 术语表，供任何模型的提示词使用。"""
    rows = []
    for en, n in sorted(find_terms(con, text, domain).items()):
        c = candidates(con, en, domain, scope)
        if not c:
            continue
        b = c[0]
        others = "；".join(sorted({f"{h.zh}（{h.cite()}）" for h in c[1:] if h.zh != b.zh}))
        flag = "" if b.status == "已核" else "⚠候选：保留英文并登记待核"
        rows.append(f"| {b.en} | {b.zh} | {b.cite()} | {b.status}{flag} | {others or ''} |")
    head = (f"领域：{domain}；类群：{'、'.join(sorted(scope)) if scope else '通用'}\n\n"
            "| 英文 | 采用中文 | 依据 | 状态 | 落选译名 |\n|---|---|---|---|---|")
    return head + ("\n" + "\n".join(rows) if rows else "\n| （原文未命中术语库） | | | | |")


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
