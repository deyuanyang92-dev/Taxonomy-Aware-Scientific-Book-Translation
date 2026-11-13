#!/usr/bin/env python3
"""审计：共识文本相对原始引擎读数（alternates 里的 method=ocr、非 consensus）有哪些大写词/拉丁词被改动。

用法：python3 scripts/lexicon_name_audit.py <书key> [--root DIR] [--out TSV]

逐页按空白分词做 difflib 比对，列出「原词含首字母大写词，或像拉丁学名的小写词」被共识文本改掉的替换。
纯断词合并（Am- phitrite -> Amphitrite）单独计数，不进 TSV。
TSV 列：page, kind, raw, fixed, context（原文上下各 30 字符）。
kind：cap = 原词首字母大写（人名、属名等）；latin = 原词为小写、带拉丁词尾。
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docstore.store import Store  # noqa: E402

TOKEN = re.compile(r"\S+")
LATIN_SUFFIX = re.compile(r"(us|is|ae|ii|um|ensis|icus|ica|ata|atus|alis|ella|ula|ulus|oides|iae|ni|ri)$")


def _core(tok: str) -> str:
    return re.sub(r"^[^A-Za-z]+|[^A-Za-z-]+$", "", tok)


def is_cap(tok: str) -> bool:
    c = _core(tok)
    return len(c) >= 2 and c[0].isupper() and any(ch.islower() for ch in c[1:])


def is_latin_lc(tok: str) -> bool:
    c = _core(tok)
    return len(c) >= 6 and c.islower() and bool(LATIN_SUFFIX.search(c))


def raw_text_of(page: dict) -> str | None:
    """原始引擎读数：主版本之外的、非 consensus 的 ocr 版本里最长的一份。"""
    cands = [v for v in page.get("alternates", [])
             if v.get("method") == "ocr" and not str(v.get("producer") or "").startswith("consensus(")]
    if not cands:
        return None
    return max(cands, key=lambda v: len(v.get("text") or "")).get("text") or ""


def diff_page(raw: str, fixed: str) -> tuple[list[dict], int]:
    rt = [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(raw)]
    ft = [m.group(0) for m in TOKEN.finditer(fixed)]
    sm = difflib.SequenceMatcher(None, [t[0] for t in rt], ft, autojunk=False)
    rows: list[dict] = []
    dehyph = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        rspan = [t[0] for t in rt[i1:i2]]
        fspan = ft[j1:j2]
        joined = "".join(t[:-1] if t.endswith("-") and k < len(rspan) - 1 else t for k, t in enumerate(rspan))
        if joined == "".join(fspan):
            dehyph += 1
            continue
        kind = "cap" if any(is_cap(t) for t in rspan) else ("latin" if any(is_latin_lc(t) for t in rspan) else "")
        if not kind:
            continue
        s, e = rt[i1][1], rt[i2 - 1][2]
        ctx = raw[max(0, s - 30):s] + "[" + raw[s:e] + "]" + raw[e:e + 30]
        rows.append({"kind": kind, "raw": " ".join(rspan), "fixed": " ".join(fspan),
                     "context": ctx.replace("\n", " ")})
    return rows, dehyph


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("key")
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    st = Store(a.root)
    out = Path(a.out) if a.out else Path(f"lexicon_name_changes_{a.key}.tsv")
    n: collections.Counter[str] = collections.Counter()
    pages_hit: set[int] = set()
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["page", "kind", "raw", "fixed", "context"])
        for p in st.page_numbers(a.key):
            pg = st.read_page(a.key, p) or {}
            raw = raw_text_of(pg)
            if raw is None:
                n["pages_without_raw"] += 1
                continue
            n["pages"] += 1
            rows, dh = diff_page(raw, pg.get("text") or "")
            n["dehyphen"] += dh
            for r in rows:
                w.writerow([p, r["kind"], r["raw"], r["fixed"], r["context"]])
                n[r["kind"]] += 1
                pages_hit.add(p)
    print(dict(n), "pages_with_name_changes=%d" % len(pages_hit), "->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
