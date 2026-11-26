#!/usr/bin/env python3
"""Spanish term candidates from raw_term_occurrences.tsv.

Subcommand `candidates`: fold plural variants of unigrams, filter by
frequency/page thresholds, write cand_uni.tsv, batches/uni_NN.tsv, cand_ngram.tsv.
Subcommand `classify`: rule-based (no model) classification of the candidates into
taxon / person / general / domain / specialised / english / other (unigrams) and
phrase / ... (n-grams); writes classified_uni.tsv, classified_ngram.tsv, classify_stats.txt.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

DEFAULT_DIR = Path("参考资料/术语来源/西班牙语/中间")
UNI_MIN_FREQ, UNI_MIN_PAGES = 5, 3
NG_MIN_FREQ, NG_MIN_PAGES = 10, 5
BATCH = 400
CAND_COLS = ["term", "forms", "freq", "n_pages", "n_vols", "vols",
             "top_families", "sections", "example_vol", "example_page"]
TERMS_FINAL = Path("/mnt/p/翻译-译作/yanjie/work/iberica_terms/terms_final.tsv")
CLASS_COLS = ["term", "kind", "class", "rule", "freq", "n_pages", "n_vols", "vols"]
TAXON_RANKS = {"género", "especie", "familia", "subfamilia", "orden", "suborden"}
TAXON_SUFFIX = re.compile(r"(idae|inae|idea|ida|iformes|ata|ae)$")
TAXON_SUFFIX_MINLEN = 6
SPECIALISED_MINLEN = 4
# section column of raw data only has Biología / Distribución geográfica / empty
DOMAIN_SECTIONS = {"descripción", "diagnosis", "biología"}
DOMAIN_MIN_VOLS = 5
DOMAIN_MIN_SHARE = 0.90   # share of occurrences inside DOMAIN_SECTIONS
DOMAIN_SHARE_RATIO = 1.15  # ...and at least this multiple of the corpus-wide share
AUTHOR_MINLEN = 4
WORD_RE = re.compile(r"^[^\W\d_]+$")
BATCH_COLS = ["term", "forms", "freq", "n_vols", "top_families", "example"]


def singular_of(t: str, vocab) -> str:
    """Return the singular form present in vocab, else t itself."""
    if t.endswith("ciones") and t[:-6] + "ción" in vocab:
        return t[:-6] + "ción"
    if t.endswith("es") and t[:-2] in vocab:
        return t[:-2]
    if t.endswith("s") and t[:-1] in vocab:
        return t[:-1]
    return t


class Agg:
    __slots__ = ("freq", "pages", "fam", "sec", "forms", "form_freq")

    def __init__(self):
        self.freq = 0
        self.pages = set()
        self.fam = Counter()
        self.sec = Counter()
        self.forms = Counter()


def read_rows(path: Path, kinds):
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["kind"] in kinds:
                yield r


def aggregate(rows, fold: bool):
    rows = list(rows)
    if fold:
        vocab = {r["term"] for r in rows}
        keymap = {t: singular_of(t, vocab) for t in vocab}
    else:
        keymap = {}
    aggs: dict[str, Agg] = defaultdict(Agg)
    for r in rows:
        a = aggs[keymap.get(r["term"], r["term"])]
        n = int(r["n"] or 1)
        a.freq += n
        a.forms[r["term"]] += n
        a.pages.add((r["vol"], int(r["page"])))
        if r["family"]:
            a.fam[r["family"]] += n
        if r["section"]:
            a.sec[r["section"]] += n
    out = []
    for key, a in aggs.items():
        canon = max(a.forms.items(), key=lambda kv: (kv[1], -len(kv[0])))[0] if fold else key
        out.append((canon, a))
    return out


def top(c: Counter, k=3) -> str:
    return "; ".join(f"{x}:{n}" for x, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k])


def to_row(term, a: Agg) -> dict:
    vols = sorted({v for v, _ in a.pages})
    ex = sorted(a.pages)[0]
    forms = sorted(a.forms, key=lambda f: (-a.forms[f], f))
    return {"term": term, "forms": "|".join(forms), "freq": a.freq,
            "n_pages": len(a.pages), "n_vols": len(vols), "vols": ",".join(vols),
            "top_families": top(a.fam), "sections": top(a.sec),
            "example_vol": ex[0], "example_page": ex[1]}


def write_tsv(path: Path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def select(items, min_freq, min_pages):
    rows = [to_row(t, a) for t, a in items if a.freq >= min_freq and len(a.pages) >= min_pages]
    rows.sort(key=lambda r: (-r["freq"], r["term"]))
    return rows


def candidates(d: Path) -> dict:
    raw = d / "raw_term_occurrences.tsv"
    uni = select(aggregate(read_rows(raw, {"uni"}), True), UNI_MIN_FREQ, UNI_MIN_PAGES)
    write_tsv(d / "cand_uni.tsv", CAND_COLS, uni)
    nb = 0
    for i in range(0, len(uni), BATCH):
        nb += 1
        part = [dict(r, example=f"{r['example_vol']}:{r['example_page']}") for r in uni[i:i + BATCH]]
        write_tsv(d / "batches" / f"uni_{nb:02d}.tsv", BATCH_COLS, part)
    ng = select(aggregate(read_rows(raw, {"bi", "tri"}), False), NG_MIN_FREQ, NG_MIN_PAGES)
    write_tsv(d / "cand_ngram.tsv", CAND_COLS, ng)
    return {"uni": len(uni), "batches": nb, "ngram": len(ng)}


class Ctx(NamedTuple):
    taxa: frozenset        # genus/species/family names + single words of them (lowercase)
    epithets: frozenset    # second word of binomials
    authors: frozenset     # words of taxon author strings
    unknown_es: frozenset  # words aspell -l es does not know
    unknown_en: frozenset  # words aspell -l en does not know
    glossary: frozenset    # es_glossary + terms_final words
    stats: dict            # word -> (n_domain, n_total, n_vols)
    base_share: float      # corpus-wide share of domain-section occurrences


def is_taxon_suffix(w: str) -> bool:
    return len(w) >= TAXON_SUFFIX_MINLEN and bool(TAXON_SUFFIX.search(w))


def domain_by_section(word: str, ctx: Ctx) -> bool:
    nd, nt, nv = ctx.stats.get(word, (0, 0, 0))
    if nt == 0 or nv < DOMAIN_MIN_VOLS:
        return False
    share = nd / nt
    return share >= DOMAIN_MIN_SHARE and share >= ctx.base_share * DOMAIN_SHARE_RATIO


def classify_word(w: str, ctx: Ctx) -> tuple[str, str]:
    """Return (class, rule) for one lowercase word."""
    if not WORD_RE.match(w):
        return "other", "non_alpha"
    if w in ctx.taxa:
        return "taxon", "taxa_headings"
    unk = w in ctx.unknown_es
    if unk and is_taxon_suffix(w):
        return "taxon", "taxon_suffix"
    if unk and w in ctx.epithets:
        return "taxon", "species_epithet"
    if w in ctx.authors:
        return "person", "taxon_author"
    if not unk:
        if w in ctx.glossary:
            return "domain", "glossary"
        if domain_by_section(w, ctx):
            return "domain", "section_profile"
        return "general", "aspell_es"
    if w not in ctx.unknown_en and w not in ctx.glossary:
        return "english", "aspell_en"
    if len(w) >= SPECIALISED_MINLEN:
        return "specialised", "aspell_unknown"
    return "other", "short_unknown"


def classify_term(term: str, forms: str, ctx: Ctx) -> tuple[str, str]:
    """Unigram: classify the term, also trying its folded forms for taxon/glossary hits."""
    c, r = classify_word(term, ctx)
    if c in {"general", "specialised", "other"}:
        for f in forms.split("|"):
            if f != term:
                c2, r2 = classify_word(f, ctx)
                if c2 in {"taxon", "domain", "person"}:
                    return c2, r2
    return c, r


def classify_ngram(words: list[str], ctx: Ctx) -> tuple[str, str]:
    cls = [classify_word(w, ctx) for w in words]
    for bad in ("taxon", "person", "english", "other"):
        for w, (c, _) in zip(words, cls):
            if c == bad:
                return bad, f"word_{bad}"
    if cls[0][0] == "general" or cls[-1][0] == "general":
        return "general", "edge_general"
    if any(c in {"specialised", "domain"} for c, _ in cls):
        return "phrase", "has_specialised_or_glossary"
    return "general", "no_specialised"


def aspell_unknown(words, lang: str) -> set:
    """Words that `aspell -l lang list` does not recognise (batch via stdin)."""
    ws = sorted({w for w in words if WORD_RE.match(w)})
    if not ws:
        return set()
    r = subprocess.run(["aspell", "-l", lang, "list"], input="\n".join(ws) + "\n",
                       capture_output=True, text=True, check=True)
    return set(r.stdout.split())


def load_taxa(path: Path):
    taxa, epi, auth = set(), set(), set()
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["rank"] not in TAXON_RANKS:
                continue
            parts = r["name"].lower().split()
            taxa.add(r["name"].lower())
            taxa.update(p for p in parts[:1])
            if r["rank"] == "especie" and len(parts) > 1:
                epi.update(parts[1:])
            for a in re.findall(r"[^\W\d_]+", (r.get("author") or "").lower()):
                if len(a) >= AUTHOR_MINLEN:
                    auth.add(a)
    return frozenset(taxa), frozenset(epi), frozenset(auth - taxa)


def load_glossary() -> set:
    spec = importlib.util.spec_from_file_location("es_glossary", Path(__file__).with_name("es_glossary.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    terms = set(mod.EN_OF)
    if TERMS_FINAL.exists():
        with open(TERMS_FINAL, encoding="utf-8", newline="") as f:
            terms.update(r["term"].lower() for r in csv.DictReader(f, delimiter="\t") if r.get("term"))
    words = set(terms)
    for t in terms:
        words.update(t.split())
    return words


def section_stats(raw: Path):
    dom, tot, vols = Counter(), Counter(), defaultdict(set)
    for r in read_rows(raw, {"uni"}):
        n = int(r["n"] or 1)
        t = r["term"]
        tot[t] += n
        vols[t].add(r["vol"])
        if r["section"].lower() in DOMAIN_SECTIONS:
            dom[t] += n
    stats = {t: (dom[t], tot[t], len(vols[t])) for t in tot}
    all_t = sum(tot.values())
    return stats, (sum(dom.values()) / all_t if all_t else 0.0)


def classify(d: Path) -> dict:
    uni = list(csv.DictReader(open(d / "cand_uni.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    ng = list(csv.DictReader(open(d / "cand_ngram.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    words = {w for r in uni for w in [r["term"], *r["forms"].split("|")]}
    words |= {w for r in ng for w in r["term"].split()}
    taxa, epi, auth = load_taxa(d / "taxa_headings.tsv")
    stats, base = section_stats(d / "raw_term_occurrences.tsv")
    ctx = Ctx(taxa, epi, auth, frozenset(aspell_unknown(words, "es")),
              frozenset(aspell_unknown(words, "en")), frozenset(load_glossary()), stats, base)
    out_u, out_n = [], []
    for r in uni:
        c, rule = classify_term(r["term"], r["forms"], ctx)
        out_u.append(dict(r, kind="uni", **{"class": c, "rule": rule}))
    for r in ng:
        ws = r["term"].split()
        c, rule = classify_ngram(ws, ctx)
        out_n.append(dict(r, kind="bi" if len(ws) == 2 else "tri", **{"class": c, "rule": rule}))
    write_tsv(d / "classified_uni.tsv", CLASS_COLS, out_u)
    write_tsv(d / "classified_ngram.tsv", CLASS_COLS, out_n)
    cu, cn = Counter(r["class"] for r in out_u), Counter(r["class"] for r in out_n)
    lines = ["[uni]"] + [f"{k}\t{v}" for k, v in sorted(cu.items())]
    lines += ["[ngram]"] + [f"{k}\t{v}" for k, v in sorted(cn.items())]
    (d / "classify_stats.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"uni": dict(cu), "ngram": dict(cn)}


DELIVER_CLASSES = ("taxon", "specialised", "domain", "person")
D01_COLS = ["term", "type", "kind", "forms", "freq", "n_pages", "n_vols", "vols"]
D03_COLS = ["term", "type", "freq", "n_vols", "vols", "top_families", "sections",
            "example_vol", "example_page"]
EN_CLASSIFY = Path(__file__).with_name("term_en_classify.py")


def _tsv_to_xlsx():
    import sys
    sys.path.insert(0, str(EN_CLASSIFY.parent))  # term_en_classify imports its sibling modules
    spec = importlib.util.spec_from_file_location("term_en_classify", EN_CLASSIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.tsv_to_xlsx


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def deliver(d: Path, out: Path) -> dict:
    """Same layout as the English baseline (参考资料/术语来源/README.md): one file per purpose,
    xlsx via term_en_classify.tsv_to_xlsx (frozen header, filter, bold, auto width)."""
    to_xlsx = _tsv_to_xlsx()
    out.mkdir(parents=True, exist_ok=True)
    cand = {}
    for name in ("cand_uni.tsv", "cand_ngram.tsv"):
        for r in _read(d / name):
            cand[r["term"]] = r
    rows = []
    for name in ("classified_uni.tsv", "classified_ngram.tsv"):
        for r in _read(d / name):
            if r["class"] in DELIVER_CLASSES:
                rows.append(dict(r, type=r["class"], forms=cand.get(r["term"], {}).get("forms", "")))
    rows.sort(key=lambda r: (DELIVER_CLASSES.index(r["type"]), -int(r["freq"]), r["term"]))
    r3 = [dict(cand.get(r["term"], {}), term=r["term"], type=r["type"]) for r in rows]
    taxa = _read(d / "taxa_headings.tsv")
    files = {
        "01_西语术语": (D01_COLS, rows),
        "03_来源与出现位置": (D03_COLS, r3),
        "04_科章节定位": (list(taxa[0].keys()) if taxa else [], taxa),
    }
    counts = {}
    for stem, (cols, data) in files.items():
        write_tsv(out / f"{stem}.tsv", cols, data)
        to_xlsx(out / f"{stem}.tsv", out / f"{stem}.xlsx")
        (out / f"{stem}.tsv").unlink()
        counts[stem] = len(data)
    shutil.copyfile(d / "raw_term_occurrences.tsv", out / "05_出现位置明细.tsv")
    return counts


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    k = sub.add_parser("classify")
    k.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    v = sub.add_parser("deliver")
    v.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    v.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    if args.cmd == "deliver":
        print(deliver(args.dir, args.out or args.dir.parent))
        return 0
    if args.cmd == "classify":
        res = classify(args.dir)
        print(f"uni={res['uni']} ngram={res['ngram']}")
        return 0
    res = candidates(args.dir)
    print(f"uni={res['uni']} batches={res['batches']} ngram={res['ngram']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
