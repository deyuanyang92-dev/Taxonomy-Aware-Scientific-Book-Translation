"""学名校正（零模型）：抽页内拉丁名，对照本地 WoRMS 缓存，结果每名一行写进页面 JSON 的 extra.names。

不改页面正文。status：exact（缓存精确命中）/ fuzzy（同属内编辑距离≤2 的唯一候选）/ unresolved（像学名条目但缓存里无）。
缓存 worms_taxa.valid_name 存的是有效名（异名行也指向有效名），所以只能核「有效名」；异名命中不到时标 unresolved，
不据此改名。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DEFAULT_CACHE = Path.home() / ".specimen_inventory" / "worms_cache.sqlite"
MAX_DIST = 2  # 种加词
MAX_DIST_HIGHER = 1  # 属、科：短词，距离 2 就会串到别的类群（Acoetidae→Acinetidae）

_BINOMIAL = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z]{3,})\b(?:\s+([A-Z][\w.'’\-]+(?:[^\n]{0,60}?)),?\s*(\d{4}))?")
_GENUS_HEAD = re.compile(r"^([A-Z][a-z]{3,})\s+[A-Z][^\n]{0,60}?,\s*\d{4}\s*$", re.M)
_FAMILY = re.compile(r"\b([A-Z][a-z]{3,}(?:idae|inae|oidea))\b")


def _dist(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def extract(text: str) -> list[tuple[str, bool]]:
    """返回 [(OCR 名, 是否带作者+年份)]，同名去重，保持出现顺序。"""
    seen: dict[str, bool] = {}
    for m in _BINOMIAL.finditer(text):
        nm = f"{m.group(1)} {m.group(2)}"
        seen[nm] = seen.get(nm, False) or bool(m.group(4))
    for m in _GENUS_HEAD.finditer(text):
        seen.setdefault(m.group(1), True)
    for m in _FAMILY.finditer(text):
        seen.setdefault(m.group(1), False)
    return list(seen.items())


class Worms:
    def __init__(self, path: Path | str = DEFAULT_CACHE):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def exact(self, name: str) -> tuple[str, int] | None:
        r = self.db.execute("SELECT valid_name, COALESCE(valid_aphia_id, aphia_id) FROM worms_taxa "
                            "WHERE valid_name = ? COLLATE NOCASE LIMIT 1", (name,)).fetchone()
        return (r[0], r[1]) if r else None

    def _names(self, sql: str, args: tuple) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.db.execute(sql, args)]

    def fuzzy(self, name: str) -> tuple[str, int] | None:
        """同属（或同首字母属）内编辑距离≤MAX_DIST 的唯一候选；有并列或无候选返回 None。"""
        parts = name.split()
        if len(parts) == 2:
            genus = parts[0]
            g = self.exact(genus)
            genera = [genus] if g else [x for x, _ in self._names(
                "SELECT DISTINCT valid_name, 0 FROM worms_taxa WHERE rank='Genus' AND valid_name LIKE ? COLLATE NOCASE",
                (genus[0] + "%",)) if _dist(x, genus) <= MAX_DIST_HIGHER]
            cands: dict[str, int] = {}
            for gn in genera:
                for vn, aid in self._names(
                        "SELECT valid_name, COALESCE(valid_aphia_id, aphia_id) FROM worms_taxa "
                        "WHERE valid_name LIKE ? COLLATE NOCASE AND rank='Species'", (gn + " %",)):
                    if _dist(vn, name) <= MAX_DIST:
                        cands[vn] = aid
            return next(iter(cands.items())) if len(cands) == 1 else None
        rank = "Family" if name.endswith(("idae", "inae", "oidea")) else "Genus"
        cands = {vn: aid for vn, aid in self._names(
            "SELECT valid_name, COALESCE(valid_aphia_id, aphia_id) FROM worms_taxa WHERE rank=? "
            "AND valid_name LIKE ? COLLATE NOCASE", (rank, name[0] + "%")) if _dist(vn, name) <= MAX_DIST_HIGHER}
        return next(iter(cands.items())) if len(cands) == 1 else None


def fix_text(text: str, worms: Worms) -> list[dict]:
    """逐名核对，返回要写进 extra.names 的行。不像学名条目的未命中词（英文词等）不记。"""
    out: list[dict] = []
    for ocr, has_auth in extract(text):
        hit = worms.exact(ocr)
        if hit:
            out.append({"ocr": ocr, "worms": hit[0], "aphia_id": hit[1], "status": "exact"})
            continue
        hit = worms.fuzzy(ocr)
        if hit:
            out.append({"ocr": ocr, "worms": hit[0], "aphia_id": hit[1], "status": "fuzzy"})
        elif has_auth:
            out.append({"ocr": ocr, "worms": None, "aphia_id": None, "status": "unresolved"})
    return out
