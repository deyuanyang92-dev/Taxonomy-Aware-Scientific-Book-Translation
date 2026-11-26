#!/usr/bin/env python3
"""Frequency-ranked English term candidates from PDF text layers or page text files (zero model).

Usage:
  python3 scripts/term_en_candidates.py DIR --glossary annikey_terms.tsv [--limit N] \
      [--yiku ~/.yiku/yiku.db] --out cand_en.tsv --manifest manifest_en.tsv
  python3 scripts/term_en_candidates.py PAGEDIR --pages [--glob '*_p????.txt'] [--glossary g.tsv] \
      --out cand_en.tsv [--json per_page.json] [--min-freq 1 --min-docs 1]

Labels (column "label"):
  A  morphology: n-grams (1-4 words) whose LAST word is a glossary head noun (chaetae, lobe, cirri,
     palp...). Text and heads are compared after lemma() (palps->palp, antennae->antenna), so a
     singular-only glossary still matches plurals; a head that occurs once in the glossary counts.
  B  taxonomic vocabulary from the fixed seed list TAXO_SEEDS (see its comment for the basis).
  C  proper names, kept in original case: family-group names (-idae/-inae/-oidea), binomials
     (Nereis pelagica, N. pelagica), author-year citations (Rieger 1981; Orsted, 1843;
     Kerbl et al. 2015), journal/institution names (Bulletin of ..., ... Museum). Citations and
     every candidate on a reference-list line get citation=1 so they can be filtered out.
Unigrams of A are the head nouns themselves (only via --pages/extract(); legacy ngrams() keeps 2-4).
Multiword A terms also get a C-value (Frantzi et al. 2000) for nested-fragment ranking.

Deterministic: same input, same output (rows sorted with a full tie-break). Optional spaCy POS
filter (--spacy) degrades silently to the plain heuristics when spaCy or its model is missing.
Text is streamed from pdftotext and never stored; scanned PDFs (no text layer) are listed in the
manifest for docstore OCR, not guessed.
Output TSV: term, freq, docs, in_glossary, in_yiku, example_pdf, label, kind, citation, cvalue,
source_page (first page seen: "p0213" from *_pNNNN.txt, or "file.pdf#12" for PDFs).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
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

# ---------------------------------------------------------------- lemma
# Latin/Greek plurals common in invertebrate morphology; checked before the suffix rules.
IRREG = {"cirri": "cirrus", "uncini": "uncinus", "radioli": "radiolus", "setae": "seta", "chaetae": "chaeta",
         "cilia": "cilium", "nephridia": "nephridium", "protonephridia": "protonephridium",
         "metanephridia": "metanephridium", "parapodia": "parapodium", "peristomia": "peristomium",
         "prostomia": "prostomium", "pygidia": "pygidium", "solenocytes": "solenocyte", "ova": "ovum",
         "ganglia": "ganglion", "stomata": "stoma", "genera": "genus", "species": "species", "series": "series",
         "teeth": "tooth", "feet": "foot", "processes": "process", "apices": "apex", "testes": "testis",
         "vertices": "vertex", "syntypes": "syntype", "lamellae": "lamella", "data": "data"}


def lemma(term: str) -> str:
    """Singular form of the last word only (chaetae->chaeta, lobes->lobe, cirri->cirrus, palps->palp)."""
    w = term.split()
    if not w:
        return term
    x = w[-1]
    if x in IRREG:
        x = IRREG[x]
    elif x.endswith("ae") and len(x) > 4:
        x = x[:-2] + "a"
    elif x.endswith("ies") and len(x) > 4:
        x = x[:-3] + "y"
    elif x.endswith(("sses", "ches", "shes", "xes")) and len(x) > 4:
        x = x[:-2]
    elif x.endswith("s") and not x.endswith(("ss", "us", "is")) and len(x) > 3:
        x = x[:-1]
    return " ".join(w[:-1] + [x])


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().strip(".,;:()[]\"'")).lower()


def heads_from_glossary(terms: list[str], min_n: int = 1) -> set[str]:
    """Last words of glossary terms. min_n=1 (default) keeps heads seen once (protonephridium)."""
    c = collections.Counter(norm(t).split()[-1] for t in terms if norm(t))
    return {w for w, n in c.items() if n >= min_n and w not in STOP and len(w) > 2}


def _head_match(heads: set[str]) -> set[str]:
    return set(heads) | {lemma(h) for h in heads}


def _is_head(w: str, hl: set[str]) -> bool:
    return w in hl or lemma(w) in hl


def _a_grams(text: str, heads: set[str], maxn: int = 4, unigrams: bool = False):
    """Yield (surface n-gram) for label A; unigrams only when asked."""
    hl = _head_match(heads)
    text = text.replace("-\n", "").lower()
    for sent in re.split(r"[.;:!?()\[\]\n]{1,}|,", text):
        words = NORM_RE.sub(" ", sent).split()
        for i, w in enumerate(words):
            if not _is_head(w, hl):
                continue
            if unigrams and len(w) > 2 and w not in STOP:
                yield w
            for n in range(2, maxn + 1):
                j = i - n + 1
                if j < 0:
                    break
                g = words[j:i + 1]
                if any(x in STOP or x in NOISE or len(x) < 3 for x in g) or any(x.endswith("ing") for x in g[:-1]):
                    continue
                yield " ".join(g)


def ngrams(text: str, heads: set[str], maxn: int = 4) -> collections.Counter[str]:
    """Surface 2-4-grams ending in a head noun (heads matched by lemma). Interface used by term_en_master."""
    return collections.Counter(_a_grams(text, heads, maxn))


# ---------------------------------------------------------------- B: taxonomic vocabulary
# Fixed seed list, no model. Basis: section headings and nomenclatural terms of the ICZN Code
# (4th ed., 1999; Glossary: holotype, paratype, syntype, lectotype, neotype, type species, synonym,
# homonym, nomen nudum, ...) and the standard section headings of taxonomic papers (Zootaxa /
# ZooKeys author guidelines: Diagnosis, Description, Remarks, Etymology, Material examined,
# Distribution, Habitat, Type locality). Abbreviations (sp. nov. ...) are matched separately.
TAXO_SEEDS = ("kingdom phylum subphylum class subclass order suborder superfamily family subfamily tribe genus "
              "subgenus species subspecies variety taxon clade synonym homonym synonymy holotype paratype "
              "syntype lectotype paralectotype neotype allotype topotype hapantotype diagnosis description "
              "redescription remarks etymology distribution habitat ecology biology nomenclature "
              "classification phylogeny monophyly key").split() + [
    "type species", "type genus", "type locality", "type material", "type specimen", "type series",
    "material examined", "additional material", "comparative material", "non-type material",
    "original description", "new species", "new genus", "new combination", "new record", "new synonym",
    "junior synonym", "senior synonym", "objective synonym", "subjective synonym", "valid name",
    "available name", "nomen nudum", "nomen dubium", "species inquirenda", "incertae sedis",
    "differential diagnosis", "generic diagnosis", "emended diagnosis", "identification key",
    "geographical distribution", "sister group"]
TAXO_ABBR = re.compile(r"\b(sp|gen|comb|stat|nom|syn|subsp|fam|subgen)\.\s?(nov|n|rev|emend)\.|\bn\.\s?(sp|gen)\."
                       r"|\b(sensu (?:lato|stricto)|s\.\s?(?:l|str)\.|incertae sedis|nomen (?:nudum|dubium))\b", re.I)


def _seed_index():
    multi: dict[tuple[str, ...], str] = {}
    for s in TAXO_SEEDS:
        multi[tuple(lemma(s).split())] = s  # text words are lemmatised too (remarks -> remark)
    return multi, max(len(k) for k in multi)


_SEEDS, _SEED_MAXN = _seed_index()

# ---------------------------------------------------------------- C: proper names
_UP = "A-ZÀ-ÖØ-Þ"
_LO = "a-zß-öø-ÿ"
_NAME = rf"[{_UP}][{_LO}'’\-]+"
CITE_RE = re.compile(
    rf"\b(?:(?:de|van|von|da|du|le|la|von der|van der)\s)?({_NAME}"
    rf"(?:\s(?:&|and)\s(?:(?:de|van|von)\s)?{_NAME}|\set\sal\.?)?),?\s\(?((?:1[6-9]|20)\d\d)[a-z]?\b")
FAMILY_RE = re.compile(rf"\b([{_UP}][{_LO}]+(?:idae|inae|oidea|oidae))\b")
BINOM_RE = re.compile(rf"\b([{_UP}][{_LO}]{{2,}}|[{_UP}]\.)\s(\([{_UP}][{_LO}]+\)\s)?([a-z]{{3,}})\b")
JOURNAL_RE = re.compile(
    rf"\b((?:[{_UP}][\w\-]+\s)*(?:Bulletin|Annals|Journal|Proceedings|Transactions|Memoirs|Records|Contributions|"
    rf"Archives|Reports?|Zeitschrift|Mitteilungen|Bolet[ií]n|Revista)\sof\s(?:the\s)?[{_UP}][\w\-]+"
    rf"(?:\s(?:of\s|the\s|and\s|&\s|for\s)*[{_UP}][\w\-]+)*)"
    rf"|\b((?:[{_UP}][\w\-]+\s){{1,4}}(?:Museum|University|Institute|Institution|Society|Academy|Survey))\b")
# Reference-list entry: "Surname, I.J. ... (1977) ..." or "Surname I. 1959. ...".
REFLINE_RE = re.compile(
    rf"^\s*(?:(?:de|van|von|da|du|le|la)\s)?([{_UP}][{_LO}'’\-]+(?:[ \-][{_UP}][{_LO}'’\-]+)?),?\s"
    rf"(?:[{_UP}]\.\s?-?)+.*?\(?((?:1[6-9]|20)\d\d)[a-z]?\)?(?:[.,:;]|\s|$)")
LATIN_END = ("a", "ae", "us", "um", "is", "i", "ii", "ensis", "x")
GENUS_NOT = ("al", "ar", "ary", "ous", "ive", "ed", "ing", "ly", "ent", "ant", "ior", "ern", "ful", "less", "ion",
             "ure", "ness", "ment", "ic", "ical", "ile", "ose", "eal", "ial")
EN_LATINISH = set("area data media formula this his thus plus bus minus basis axis analysis genus corpus focus "
                  "status virus stimulus radius sinus apparatus via idea extra ultra comma"
                  " villus lumen fauna flora larva incertae sedis aus della".split())
CAP_STOP = STOP | NOISE | set(
    "fig figs figure figures table tables plate plates page pages vol volume chapter section appendix since after "
    "before during however although therefore thus there here they we our it in on see also note notes according "
    "january february march april may june july august september october november december spring summer autumn "
    "winter year years ca circa approximately".split())


def _cap_ok(name: str) -> bool:
    return name.split()[0].lower().strip(".") not in CAP_STOP


def _proper(text: str):
    """Yield (term, kind, citation) for label C on case-preserved text."""
    t = text.replace("-\n", "")
    for line in t.splitlines():
        rm = REFLINE_RE.match(line)
        ref = bool(rm)
        if rm:
            yield f"{rm.group(1)}, {rm.group(2)}", "citation", 1
        for m in FAMILY_RE.finditer(line):
            yield m.group(1), "family", int(ref)
        for m in BINOM_RE.finditer(line):
            g, sub, ep = m.group(1), m.group(2) or "", m.group(3)
            gl = g.lower().strip(".")
            if (not ep.endswith(LATIN_END) or ep in STOP or ep in NOISE or ep in EN_LATINISH
                    or gl in CAP_STOP or (len(gl) > 1 and gl.endswith(GENUS_NOT)) or FAMILY_RE.fullmatch(g)):
                continue
            yield f"{g} {sub}{ep}", "binomial", int(ref)
        for m in CITE_RE.finditer(line):
            name = m.group(1)
            if not _cap_ok(name):
                continue
            yield re.sub(r"\s+", " ", f"{name}, {m.group(2)}"), "citation", 1
        for m in JOURNAL_RE.finditer(line):
            j = (m.group(1) or m.group(2)).strip()
            if _cap_ok(j):
                yield j, "journal" if m.group(1) else "institution", 1 if ref else 0


def _taxo(text: str):
    """Yield (seed term) for label B."""
    for m in TAXO_ABBR.finditer(text):
        yield re.sub(r"\s+", " ", m.group(0).lower()).replace(". ", ".")
    low = text.replace("-\n", "").lower()
    for sent in re.split(r"[.;:!?()\[\]\n]{1,}|,", low):
        words = [lemma(w) for w in NORM_RE.sub(" ", sent).split()]
        i = 0
        while i < len(words):
            for n in range(min(_SEED_MAXN, len(words) - i), 0, -1):  # longest match first
                k = tuple(words[i:i + n])
                if k in _SEEDS:
                    yield _SEEDS[k]
                    i += n
                    break
            else:
                i += 1


# ---------------------------------------------------------------- optional spaCy POS filter
_NLP: list = []


def _nlp():
    """spaCy English model or None (missing package/model => plain heuristics, no error)."""
    if not _NLP:
        try:
            import spacy  # type: ignore
            _NLP.append(spacy.load("en_core_web_sm", disable=["ner", "parser"]))
        except Exception:  # ImportError, OSError (model not installed), anything else
            _NLP.append(None)
    return _NLP[0]


def _pos_ok(term: str, nlp) -> bool:
    toks = list(nlp(term))
    return bool(toks) and toks[-1].pos_ in ("NOUN", "PROPN") and all(
        t.pos_ in ("ADJ", "NOUN", "PROPN", "VERB") for t in toks[:-1])


# ---------------------------------------------------------------- extraction
def extract(text: str, heads: set[str], maxn: int = 4, use_spacy: bool = False) -> dict[str, dict]:
    """All candidates of one text unit (page). Key = lemma for A/B, case-preserved surface for C.
    Value: {term, label, kind, citation, freq}. C wins over B wins over A for the same key."""
    out: dict[str, dict] = {}

    def add(term: str, label: str, kind: str, cit: int = 0):
        d = out.get(term)
        if d is None:
            out[term] = {"term": term, "label": label, "kind": kind, "citation": cit, "freq": 1}
            return
        d["freq"] += 1
        if "CBA".index(label) < "CBA".index(d["label"]):
            d.update(label=label, kind=kind)
        d["citation"] = max(d["citation"], cit)

    for g in _a_grams(text, heads, maxn, unigrams=True):
        add(lemma(g), "A", "morph" if " " in g else "head")
    nlp = _nlp() if use_spacy else None
    if nlp is not None:
        for k in [k for k, d in out.items() if d["label"] == "A" and " " in k]:
            if not _pos_ok(k, nlp):
                del out[k]
    for s in _taxo(text):
        add(s, "B", "taxo")
    for term, kind, cit in _proper(text):
        add(term, "C", kind, cit)
    return out


def cvalues(freq: dict[str, int]) -> dict[str, float]:
    """C-value for multiword terms: log2|a| * (f(a) - mean f(b) over distinct longer candidates b
    that contain a as a contiguous word sequence). Unigrams are not scored (log2 1 = 0)."""
    multi = {t: f for t, f in freq.items() if " " in t}
    contained: dict[str, list[int]] = collections.defaultdict(list)
    for b, fb in multi.items():
        w = b.split()
        subs = {" ".join(w[i:j]) for i in range(len(w)) for j in range(i + 2, len(w) + 1) if j - i < len(w)}
        for s in subs:
            if s in multi:
                contained[s].append(fb)
    res = {}
    for a, fa in multi.items():
        ln = math.log2(len(a.split()))
        tb = contained.get(a)
        res[a] = round(ln * (fa - (sum(tb) / len(tb) if tb else 0)), 2)
    return res


def page_label(path: Path) -> str:
    m = re.search(r"_p(\d{3,5})\.txt$", path.name)
    return f"p{m.group(1)}" if m else path.stem


def read_page(path: Path) -> str:
    """Page text file; leading '# ' header lines (docstore export) are dropped."""
    lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    while lines and lines[0].startswith("# "):
        lines.pop(0)
    return "\n".join(lines)


def pdf_text(path: Path, timeout: int = 90) -> tuple[str, int]:
    try:
        r = subprocess.run(["pdftotext", "-q", str(path), "-"], capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return "", 1
    t = r.stdout.decode("utf8", "replace")
    pages = t.count("\f") or 1
    return t, pages


def load_yiku(path: str) -> set[str]:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return {r[0] for r in con.execute("SELECT DISTINCT en_norm FROM terms WHERE status!='否决'")}
    except sqlite3.Error:
        return set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--glossary", help="TSV with a 'term' column (required for PDF mode)")
    ap.add_argument("--yiku", default=str(Path.home() / ".yiku" / "yiku.db"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-freq", type=int, default=5)
    ap.add_argument("--min-docs", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", help="PDF mode: text-layer manifest TSV (required for PDF mode)")
    ap.add_argument("--pages", action="store_true", help="DIR holds page text files (*_pNNNN.txt), not PDFs")
    ap.add_argument("--glob", default="*.txt", help="page file pattern in --pages mode")
    ap.add_argument("--json", help="write per-page candidates JSON (pages/PDF pages)")
    ap.add_argument("--labels", default="ABC", help="labels to keep in TSV, e.g. A or AB")
    ap.add_argument("--no-citation", action="store_true", help="drop citation=1 rows from the TSV")
    ap.add_argument("--spacy", action="store_true", help="optional POS filter for A n-grams; skipped if spaCy missing")
    a = ap.parse_args(argv)
    if not a.pages and (not a.glossary or not a.manifest):
        ap.error("PDF mode needs --glossary and --manifest")

    gl: list[str] = []
    if a.glossary:
        with open(a.glossary, encoding="utf8", newline="") as f:
            gl = [r["term"] for r in csv.DictReader(f, delimiter="\t")]
    gset = {norm(t) for t in gl} | {lemma(norm(t)) for t in gl}
    heads = heads_from_glossary(gl)
    yset = load_yiku(a.yiku)

    # units: (doc name, page label, text) produced lazily
    man = []
    per_page: list[dict] = []
    freq: collections.Counter[str] = collections.Counter()
    docs: collections.Counter[str] = collections.Counter()
    meta: dict[str, dict] = {}
    ex: dict[str, tuple[str, str]] = {}
    seen: set[tuple[str, str]] = set()

    def take(doc: str, pg: str, text: str):
        c = extract(text, heads, use_spacy=a.spacy)
        if a.json:
            per_page.append({"file": doc, "page": pg,
                             "candidates": sorted(c.values(), key=lambda d: (d["label"], -d["freq"], d["term"]))})
        for k, d in c.items():
            freq[k] += d["freq"]
            if (k, doc) not in seen:  # docs = PDFs (PDF mode) or page files (--pages)
                seen.add((k, doc))
                docs[k] += 1
            ex.setdefault(k, (doc, pg))
            m = meta.setdefault(k, dict(d))
            if "CBA".index(d["label"]) < "CBA".index(m["label"]):
                m.update(label=d["label"], kind=d["kind"])
            m["citation"] = max(m["citation"], d["citation"])

    if a.pages:
        files = sorted(Path(a.dir).rglob(a.glob))
        if a.limit:
            files = files[: a.limit]
        for p in files:
            take(p.name, page_label(p), read_page(p))
        n_units = f"{len(files)} page files"
    else:
        pdfs = sorted(Path(a.dir).rglob("*.pdf"))
        if a.limit:
            pdfs = pdfs[: a.limit]

        def work(p: Path):
            t, pg = pdf_text(p)
            return p, pg, len(t) / pg, t

        with ThreadPoolExecutor(a.jobs) as ex_:
            for p, pg, cpp, t in ex_.map(work, pdfs):
                ok = cpp >= 400  # else no usable text layer
                man.append((str(p), pg, int(cpp), "text" if ok else "scan_or_empty"))
                if not ok:
                    continue
                for i, pt in enumerate(t.split("\f"), 1):
                    if pt.strip():
                        take(p.name, f"{p.name}#{i}", pt)
        with open(a.manifest, "w", encoding="utf8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["pdf", "pages", "chars_per_page", "layer"])
            w.writerows(man)
        n_units = (f"{len(pdfs)} pdfs, text {sum(1 for m in man if m[3] == 'text')}, "
                   f"scan/empty {sum(1 for m in man if m[3] != 'text')}")

    cv = cvalues({k: n for k, n in freq.items() if meta[k]["label"] == "A"})
    rows = []
    for k, n in freq.items():
        m = meta[k]
        if n < a.min_freq or docs[k] < a.min_docs or m["label"] not in a.labels:
            continue
        if a.no_citation and m["citation"]:
            continue
        key = k if m["label"] == "C" else k.lower()
        rows.append((k, n, docs[k], int(key in gset), int(key in yset), ex[k][0], m["label"], m["kind"],
                     m["citation"], cv.get(k, ""), ex[k][1]))
    rows.sort(key=lambda r: (r[3], r[4], r[6], -r[1], r[0]))  # unknown first, then label, freq, term
    with open(a.out, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["term", "freq", "docs", "in_glossary", "in_yiku", "example_pdf", "label", "kind",
                    "citation", "cvalue", "source_page"])
        w.writerows(rows)
    if a.json:
        with open(a.json, "w", encoding="utf8") as f:
            json.dump({"pages": per_page}, f, ensure_ascii=False, indent=1)
    print(f"{n_units}, candidates {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
