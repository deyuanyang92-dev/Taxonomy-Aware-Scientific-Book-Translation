#!/usr/bin/env python3
"""Frequency-ranked English morphological term candidates from PDF text layers (zero model).

Usage:
  python3 scripts/term_en_candidates.py DIR [--limit N] [--glossary annikey_terms.tsv] \
      [--yiku ~/.yiku/yiku.db] --out cand_en.tsv --manifest manifest_en.tsv

Method: n-grams (1-4 words) whose LAST word is a head noun taken from the glossary
(e.g. chaetae, lobe, cirri, palp). Text is streamed from pdftotext and never stored;
scanned PDFs (no text layer) are listed in the manifest for docstore OCR, not guessed.
Output TSV: term, freq, docs, in_glossary, in_yiku, example_pdf. Evidence = PDF path.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STOP = set("a an the of and or with without in on at by for from to as is are was were be been this that these those "
           "its their each both all some any no not than then also but may can per via into onto over under between "
           "more less most very often usually rarely only one two three four five six seven eight nine ten first "
           "second third fig figs figure table see et al".split())
# Descriptive words that are not morphology terms: colours, ordinals, position-in-series, other languages.
NOISE = set("black white brown yellow red green blue dark pale orange pink grey gray purple violet golden silvery "
            "last next former latter whole entire fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
            "premier premiere deuxieme une les des du de la le el los las del por para con um uma os dos das "
            "und der die das mit von sehr nur auch wie "
            "above below until relatively usually slightly distinctly strongly well each other same several many few "
            "numerous about around near along across behind beyond within upon while when where which whereas".split())
NORM_RE = re.compile(r"[^a-z\- ]+")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().strip(".,;:()[]\"'")).lower()


def heads_from_glossary(terms: list[str], min_n: int = 2) -> set[str]:
    c = collections.Counter(norm(t).split()[-1] for t in terms if norm(t))
    return {w for w, n in c.items() if n >= min_n and w not in STOP and len(w) > 2}


def ngrams(text: str, heads: set[str], maxn: int = 4) -> collections.Counter[str]:
    text = text.replace("-\n", "").lower()
    out: collections.Counter[str] = collections.Counter()
    for sent in re.split(r"[.;:!?()\[\]\n]{1,}|,", text):
        words = NORM_RE.sub(" ", sent).split()
        for i, w in enumerate(words):
            if w not in heads:
                continue
            for n in range(2, maxn + 1):  # unigrams are just the head nouns
                j = i - n + 1
                if j < 0:
                    break
                g = words[j:i + 1]
                if any(x in STOP or x in NOISE or len(x) < 3 for x in g) or any(x.endswith("ing") for x in g[:-1]):
                    continue
                out[" ".join(g)] += 1
    return out


def pdf_text(path: Path, timeout: int = 90) -> tuple[str, int]:
    try:
        r = subprocess.run(["pdftotext", "-q", str(path), "-"], capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return "", 1
    t = r.stdout.decode("utf8", "replace")
    pages = t.count("\f") or 1
    return t, pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--yiku", default=str(Path.home() / ".yiku" / "yiku.db"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-freq", type=int, default=5)
    ap.add_argument("--min-docs", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args(argv)

    with open(a.glossary, encoding="utf8", newline="") as f:
        gl = [r["term"] for r in csv.DictReader(f, delimiter="\t")]
    gset = {norm(t) for t in gl}
    heads = heads_from_glossary(gl)
    con = sqlite3.connect(a.yiku)
    yset = {r[0] for r in con.execute("SELECT DISTINCT en_norm FROM terms WHERE status!='否决'")}

    pdfs = sorted(Path(a.dir).rglob("*.pdf"))
    if a.limit:
        pdfs = pdfs[: a.limit]
    freq: collections.Counter[str] = collections.Counter()
    docs: collections.Counter[str] = collections.Counter()
    ex: dict[str, str] = {}
    man = []

    def work(p: Path):
        t, pg = pdf_text(p)
        cpp = len(t) / pg
        if cpp < 400:  # no usable text layer
            return p, pg, cpp, None
        return p, pg, cpp, ngrams(t, heads)

    with ThreadPoolExecutor(a.jobs) as ex_:
        for p, pg, cpp, c in ex_.map(work, pdfs):
            man.append((str(p), pg, int(cpp), "text" if c is not None else "scan_or_empty"))
            if c is None:
                continue
            for g, n in c.items():
                freq[g] += n
                docs[g] += 1
                ex.setdefault(g, p.name)
    with open(a.manifest, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["pdf", "pages", "chars_per_page", "layer"])
        w.writerows(man)
    rows = [(g, n, docs[g], int(g in gset), int(g in yset), ex[g]) for g, n in freq.items()
            if n >= a.min_freq and docs[g] >= a.min_docs]
    rows.sort(key=lambda r: (r[3], r[4], -r[1]))  # unknown to glossary/yiku first, then by freq
    with open(a.out, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["term", "freq", "docs", "in_glossary", "in_yiku", "example_pdf"])
        w.writerows(rows)
    print(f"{len(pdfs)} pdfs, text {sum(1 for m in man if m[3] == 'text')}, "
          f"scan/empty {sum(1 for m in man if m[3] != 'text')}, candidates {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
