#!/usr/bin/env python3
"""Extract frequency-ranked term candidates from docstore page JSON (zero model).

Usage:
  python3 scripts/term_candidates.py --lang ja --key Imajima2001 --key Imajima2007 \
      --min-freq 5 --min-pages 3 --out cand_ja.tsv

Output TSV columns: lang, term, freq, pages, first_key, first_page, en (blank, to be
filled by a human or model). Evidence for every row is the docstore key + page.
Pages are read straight from pages/<key>/pNNNN.json; the store is never written.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
from pathlib import Path

DEFAULT_ROOT = Path("/mnt/p/翻译-译作/参考资料/_资料库")


def _rng(lo: int, hi: int) -> str:
    return chr(lo) + "-" + chr(hi)


# lang -> regex of candidate tokens. Add a language by adding a pattern.
PATTERNS: dict[str, re.Pattern[str]] = {
    "ja": re.compile("[" + _rng(0x30A0, 0x30FF) + "]{3,}|[" + _rng(0x4E00, 0x9FFF) + "]{2,8}"),
    "ru": re.compile("[" + _rng(0x0430, 0x044F) + chr(0x0451) + "-]{5,}", re.IGNORECASE),
}


def extract(pages: list[tuple[str, int, str]], lang: str) -> dict[str, dict]:
    """pages: (key, page_no, text). Returns term -> {freq, pages:set, first:(key,page)}."""
    pat = PATTERNS[lang]
    out: dict[str, dict] = {}
    for key, no, text in pages:
        for term in pat.findall(text or ""):
            if lang == "ru":
                term = term.lower()
            e = out.setdefault(term, {"freq": 0, "pages": set(), "first": (key, no)})
            e["freq"] += 1
            e["pages"].add((key, no))
    return out


def rank(cands: dict[str, dict], min_freq: int, min_pages: int) -> list[tuple[str, int, int, str, int]]:
    rows = [
        (t, e["freq"], len(e["pages"]), e["first"][0], e["first"][1])
        for t, e in cands.items()
        if e["freq"] >= min_freq and len(e["pages"]) >= min_pages
    ]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def load_pages(root: Path, key: str) -> list[tuple[str, int, str]]:
    res = []
    for f in sorted((root / "pages" / key).glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        res.append((key, int(f.stem[1:]), d.get("text") or ""))
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", required=True, choices=sorted(PATTERNS))
    ap.add_argument("--key", action="append", required=True, help="docstore key, repeatable")
    ap.add_argument("--root", default=os.environ.get("DOCSTORE_ROOT", str(DEFAULT_ROOT)))
    ap.add_argument("--min-freq", type=int, default=5)
    ap.add_argument("--min-pages", type=int, default=3)
    ap.add_argument("--top", type=int, default=0, help="keep only top N (0 = all)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pages: list[tuple[str, int, str]] = []
    for k in a.key:
        pages += load_pages(Path(a.root), k)
    rows = rank(extract(pages, a.lang), a.min_freq, a.min_pages)
    if a.top:
        rows = rows[: a.top]
    c = collections.Counter(r[3] for r in rows)
    with open(a.out, "w", encoding="utf-8", newline="") as fh:
        fh.write("lang\tterm\tfreq\tpages\tfirst_key\tfirst_page\ten\n")
        for t, f, p, k, n in rows:
            fh.write(f"{a.lang}\t{t}\t{f}\t{p}\t{k}\t{n}\t\n")
    print(f"{len(rows)} terms from {len(pages)} pages; first-seen by key: {dict(c)}")


if __name__ == "__main__":
    main()
