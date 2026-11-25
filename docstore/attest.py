"""目标语用法佐证（0 token）：某个短语在本地库某语种资料里出现在多少页、多少份资料。

用户 2026-11-15：「我本机有大量英文分类文献，如果不消耗 tokens 你可以学习」。
用途：① 两个候选译法（setal blades / seta terminals）取本地英文分类文献里实际用得多的；
② 译文里从未在英文分类文献出现过的短语（crirrels、skinned vagina）标为风险。
实现：docstore 的 FTS5 trigram 索引按子串召回，再按整词边界复核（trigram 会把 seta 算进 setae）。
"""

from __future__ import annotations

import re

from .store import Store


def attest(store: Store, phrase: str, lang: str = "en", kind: str | None = None, cap: int = 5000) -> dict:
    """返回 {phrase, pages, docs, sample_keys}。phrase ≥3 个字符；大小写不敏感；整词匹配。"""
    p = phrase.strip()
    if len(p) < 3:
        return {"phrase": p, "pages": 0, "docs": 0, "sample_keys": []}
    q = '"' + p.replace('"', '""') + '"'
    where = "fts MATCH ? AND d.lang = ?"
    args: list = [q, lang]
    if kind:
        where += " AND d.kind = ?"
        args.append(kind)
    rows = store.con.execute(
        f"SELECT p.key, p.text FROM fts JOIN pages p ON p.id = fts.rowid JOIN docs d ON d.key = p.key "
        f"WHERE {where} LIMIT ?", (*args, cap)).fetchall()
    rx = re.compile(r"(?<![\w-])" + r"\s+".join(map(re.escape, p.split())) + r"(?![\w-])", re.I)
    keys: dict[str, int] = {}
    n = 0
    for key, text in rows:
        if rx.search(re.sub(r"-\n\s*", "", text or "")):
            n += 1
            keys[key] = keys.get(key, 0) + 1
    return {"phrase": p, "pages": n, "docs": len(keys), "sample_keys": sorted(keys, key=lambda k: keys[k], reverse=True)[:5],
            "capped": len(rows) >= cap}


def prefer(store: Store, candidates: list[str], lang: str = "en") -> list[tuple[str, int, int]]:
    """候选译法按本地库佐证排序：[(候选, 资料数, 页数)]，资料数优先（防一本书反复出现）。"""
    res = [(c, *(lambda r: (r["docs"], r["pages"]))(attest(store, c, lang))) for c in candidates]
    return sorted(res, key=lambda x: (-x[1], -x[2]))
