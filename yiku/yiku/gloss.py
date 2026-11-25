"""英文术语清单（无中文译名）：从权威英文来源（如 ANNiKEY Online 术语表）收集，供翻译时识别「必须谨慎」的术语。

与 terms 表分开：terms 每条必须有中文译名；本表只记英文、释义、适用类群、缩写、出处。
翻译时：原文出现清单内术语而 terms 里没有译名 -> 提示词里列出，要求保留英文并标「暂定」，不得自拟。
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

from .db import norm
from .match import _pattern

GAP_HEAD = ("\n\n## 未定名术语（英文清单内、术语库无中文译名）\n"
            "遇到下列术语：保留英文并标「暂定」，不得自拟译名；释义仅帮助理解词义。\n"
            "| 英文 | 释义（英文来源） | 适用类群 | 出处 |\n|---|---|---|---|\n")


def _clean(s: str, term: str) -> str:
    s = s.replace("{{!!title}}", term)
    s = re.sub(r"\{\{([^}]*)\}\}", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def import_tsv(con: sqlite3.Connection, tsv: str | Path, source: str) -> tuple[int, int]:
    """列：term, definition, applicable, abbr, source。返回（新增，已存在）。"""
    new = old = 0
    with open(tsv, encoding="utf8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            en = (r.get("term") or "").strip()
            if not en:
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO en_glossary(en,en_norm,definition,applicable,abbr,source,ref) VALUES(?,?,?,?,?,?,?)",
                (en, norm(en), _clean(r.get("definition", ""), en), (r.get("applicable") or "").strip(),
                 (r.get("abbr") or "").strip(), source, _clean(r.get("source", ""), en)))
            if cur.rowcount:
                new += 1
            else:
                old += 1
    con.commit()
    return new, old


def find_gaps(con: sqlite3.Connection, text: str) -> list[sqlite3.Row]:
    """原文出现、en_glossary 有、terms 里（任何领域，非否决）没有译名的术语；长术语优先。"""
    text = text.replace("-\n", "")
    low = text.lower()
    have = {r[0] for r in con.execute("SELECT DISTINCT en_norm FROM terms WHERE status!='否决'")}
    rows = con.execute("SELECT * FROM en_glossary ORDER BY length(en_norm) DESC, en_norm, (source LIKE 'rouse%') DESC, id").fetchall()
    out, seen, masked = [], set(), text
    for r in rows:
        k = r["en_norm"]
        if k in have or k in seen or (k.endswith("a") and k[:-1] + "um" in have):  # acicula/aciculum
            continue
        if not all(w[: max(len(w) - 3, 1)] in low for w in re.split(r"[\s-]+", k) if w):
            continue
        pat = _pattern(k)
        if pat.search(masked):
            masked = pat.sub(" ", masked)
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: r["en_norm"])


def _see_hint(con: sqlite3.Connection | None, d: str) -> str:
    """释义为「see X」且 X 在术语库有译名时，附上译名（术语同义线索，仍须译者判断）。"""
    m = re.fullmatch(r"see ([^,;.]+)", d.strip(), re.I)
    if not m or con is None:
        return ""
    x = norm(m.group(1))
    zh = [r[0] for r in con.execute(
        "SELECT DISTINCT zh FROM terms WHERE status!='否决' AND (en_norm=? OR en_norm=?) ORDER BY status='已核' DESC LIMIT 2",
        (x, x.rstrip("s")))]
    return f"（库中 {m.group(1)} 译作：{'、'.join(zh)}）" if zh else ""


def render_gaps(rows: list[sqlite3.Row], def_chars: int = 160, con: sqlite3.Connection | None = None) -> str:
    if not rows:
        return ""
    lines = []
    for r in rows:
        d = (r["definition"] or "")
        hint = _see_hint(con, d)
        d = d if len(d) <= def_chars else d[:def_chars].rstrip() + "…"
        d = d + hint if hint else d
        cell = lambda s: (s or "").replace("|", "/")  # noqa: E731
        lines.append(f"| {cell(r['en'])} | {cell(d)} | {cell(r['applicable'])} | {cell(r['source'])} |")
    return GAP_HEAD + "\n".join(lines)
