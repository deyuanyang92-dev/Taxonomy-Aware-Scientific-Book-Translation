#!/usr/bin/env python3
"""Annelid English term table v2: concept entries with type/domain, tier, and chapter location.

Sources (no literature): ANNiKEY glossary, Rouse 2022 glossary, Rouse 2022 + Handbook running text
(by_family_en_terms.tsv from term_en_master.py --min-freq 1). N-drive candidates are NOT used.

v2 changes (2026-11-25, user request: record which chapter a family / term is in):
  - every running-text hit carries its location: Rouse chapter id + title + printed page range
    (章节清单.json), Handbook section number + file.
  - outputs (v3): 01 terms, 02 zh evidence, 03 sources/locations, 04 family chapters, 05 location long table.
  - tiers: glossary (ANNiKEY or Rouse glossary) / multi_unit (>=2 chapters) / single_unit.
  - type rule uses the head noun (last word): structure heads vs descriptive (character_state) heads.

Usage:
  python3 scripts/term_en_classify.py --by-family DIR/by_family_en_terms.tsv --annikey ANN.tsv \
      --rouse-glossary RG.tsv --rouse-dir ROUSE_DIR --labels labels.tsv --out-dir OUT
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

import term_en_candidates as T

RANK_WORDS = {"family", "genus", "species", "order", "class", "subclass", "suborder", "superfamily",
              "subfamily", "tribe", "phylum", "subphylum", "subspecies", "clade", "subgenus"}

DOMAIN_RULES = [
    ("chaetae", r"chaet|\bseta|uncin|aciculum|acicul|\bspine|\bhook|crotchet|capillar|falciger|spiniger|bristle"),
    ("appendage", r"cirr|palp|antenn|parapod|notopod|neuropod|branchi|elytr|tentacul|\blobe|\bgill|proboscis|vestimen|pygidi|palea|papill|radiol|ceratophore|verruca"),
    ("digestive", r"pharyn|\bgut\b|intestin|stomach|gizzard|esophag|oesophag|midgut|typhlosol|buccal|proventric|\bcrop\b|mastax|maxill|\bjaw|\bmouth|\banus|digest|mandib"),
    ("circulatory", r"blood|vessel|\bheart|circulat|hemoglobin|haemoglobin|coelom|vascular|hemal|chloragogen|perivascular"),
    ("excretory", r"nephrid|excret|cyrtocyt"),
    ("nervous", r"nerv|ganglion|\bbrain|neuro|commissur|neuropil|cerebr|fibre|fiber"),
    ("reproductive", r"sperm|ovar|testi|oocyt|gonad|\begg|reproduct|genital|spermathec|prostate|copulat|male|female|oviduct|gonoduct|seminal|clitell|pubert|gamet|embryo|brood|\bsac\b|schizogamy|larva"),
    ("sensory", r"\beye|ocell|sensor|nuchal|\bcilia|cilium|photo|statocyst|receptor|sense|ciliary"),
    ("body_region", r"segment|somite|peristom|prostom|thorax|abdom|region|metamer|\bring|collar|trunk|\bbody|anterior|posterior|dorsal|ventral|lateral|median|mid-body|sucker|pygid|rim|head"),
    ("behaviour_ecology", r"habitat|burrow|\btube|feed|behavio|predat|swim|locomot|symbio|parasit|commensal|benthic|seep|area"),
    ("taxonomy_method", r"character|diagnos|synonym|identif|\bkey\b|sensu|holotype|specimen|descript|remark|morpholog|terminolog|nomenclat|clade"),
]
DOMAIN_RE = [(d, re.compile(p, re.I)) for d, p in DOMAIN_RULES]
TAXON_RE = re.compile(r"^[A-Z][a-z]+(idae|inae|oidea|ini|ata)$")
STRUCT_HEADS = set("""chaeta chaetae seta setae cirrus cirri palp palpus lobe segment gland cell muscle organ ring fold
groove ridge plate sac duct jaw tooth hook papilla region pore cavity vesicle tube eye cilium cilia apparatus
larva mouth gut crop pharynx nephridium coelom ganglion nerve membrane layer epidermis cuticle lamella sheath
spine spur tentacle antenna parapodium notopodium neuropodium branchia gill proboscis sucker tubercle bristle
uncinus aciculum spiniger falciger ceratophore radiole plaque plaque verruca mandible sabre sabres
muscle fibre fiber commissure neuropil cuticle eggs egg sperm oocyte rim head clitellum prostomium
peristomium pygidium thorax abdomen collar trunk body mass tooth""".split())
STATE_SUFFIX = ("ate", "ose", "ous", "ed", "al", "ar", "oid", "like", "form", "ic", "ing", "ly")


def read_tsv(p: Path) -> list[dict[str, str]]:
    with open(p, encoding="utf8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rules_label(term: str) -> tuple[str, list[str]]:
    """(type, domains). type '' = no rule decided it; the caller sends such terms to a model."""
    low = term.lower().strip()
    if low in RANK_WORDS:
        return "rank", []
    if TAXON_RE.match(term.strip()):
        return "taxon_name", []
    doms = [d for d, rx in DOMAIN_RE if rx.search(low)]
    words = low.split()
    head = words[-1] if words else ""
    if doms == ["taxonomy_method"]:
        return "method", doms
    if head in STRUCT_HEADS:
        return "structure", doms[:2]
    if len(words) >= 1 and (head.endswith(STATE_SUFFIX) or (len(words) > 1 and words[0].endswith(STATE_SUFFIX) and not doms)):
        return "character_state", doms[:2]
    if not doms:
        return "", []
    return "", doms[:2]  # domain known, type not decided by rule


def locate(unit: str, rouse_meta: dict, book: str) -> dict:
    """Location of a running-text unit. Rouse unit 'ch07 SIGALIONIDAE' -> chapter id, title, printed pages.
    Handbook unit '3.2 Family [s7_3.txt]' -> section number and file (no page numbers in the text files)."""
    if book == "Rouse2022":
        m = re.match(r"ch(\d+)\s*(.*)", unit)
        k = str(int(m.group(1))) if m else ""
        meta = rouse_meta.get(k, {})
        pages = f"{meta.get('start', '')}-{meta.get('end', '')}" if meta else ""
        return {"book": book, "section": f"ch{int(k):02d}" if k else unit, "title": meta.get("title_en", unit),
                "pages": pages, "file": f"ch{int(k):02d}.txt" if k else ""}
    m = re.match(r"^(\S+)\s+(.*)\[(.*)\]$", unit)
    sec = m.group(1) if m else unit
    title = m.group(2).strip() if m else unit
    f = m.group(3) if m else ""
    return {"book": book, "section": sec, "title": title, "pages": "", "file": f}


def build(by_family: Path, annikey: Path, rouse_gl: Path, rouse_meta: dict, min_body_freq: int,
          excluded: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    an, rg, body = read_tsv(annikey), read_tsv(rouse_gl), read_tsv(by_family)
    C: dict[str, dict] = {}

    def conc(term: str) -> dict:
        k = T.lemma(term.lower().strip())
        return C.setdefault(k, {"key": k, "forms": set(), "def_en": "", "def_source": "", "abbr": "", "scope": "",
                                "in_annikey": 0, "in_rouse_gl": 0, "rouse_freq": 0, "hb_freq": 0,
                                "fam": collections.Counter(), "zh_yiku": "", "zh_rouse": "", "src": set(),
                                "ann_def": "", "rouse_def": "", "locs": [], "maxu": 0})

    for r in an:
        c = conc(r["term"])
        c["forms"].add(r["term"].strip())
        c["in_annikey"] = 1
        c["scope"] = c["scope"] or r.get("applicable", "")
        c["abbr"] = c["abbr"] or r.get("abbr", "")
        c["ann_def"] = c["ann_def"] or r.get("definition", "")
        c["src"].add("ANNiKEY:glossary")
    for r in rg:
        c = conc(r["term"])
        c["forms"].add(r["term"].strip())
        c["in_rouse_gl"] = 1
        c["rouse_def"] = c["rouse_def"] or r.get("definition", "")
        c["src"].add("Rouse2022:glossary")
    family_locs: dict[str, dict] = {}
    for r in body:
        c = conc(r["term"])
        c["forms"].add(r["term"].strip())
        n = int(r["freq"])
        c["maxu"] = max(c["maxu"], n)
        loc = locate(r["unit"], rouse_meta, r["book"])
        c["locs"].append((loc, n))
        if r["book"] == "Rouse2022":
            c["rouse_freq"] += n
            c["src"].add("Rouse2022:running")
        else:
            c["hb_freq"] += n
            c["src"].add("Handbook:running")
        if not r["family"].startswith("General"):
            c["fam"][r["family"]] += n
            fl = family_locs.setdefault(r["family"], {"rouse": None, "hb": {}, "concepts": set(), "glossary": set()})
            if loc["book"] == "Rouse2022":
                fl["rouse"] = loc
            else:
                fl["hb"].setdefault(loc["section"] + " " + loc["title"], loc)
            fl["concepts"].add(c["key"])
        c["zh_yiku"] = c["zh_yiku"] or r.get("zh_yiku", "")
        c["zh_rouse"] = c["zh_rouse"] or r.get("zh_rouse_std", "")
    out = []
    for c in C.values():
        units = {(loc["book"], loc["section"]) for loc, _ in c["locs"]}
        if not (c["in_annikey"] or c["in_rouse_gl"] or c["maxu"] >= min_body_freq):
            continue
        if not (c["in_annikey"] or c["in_rouse_gl"]) and len(c["key"].split()) > 3:  # body-only phrases of 4+ words are noise
            continue
        if not c["key"][:1].isalpha():  # fragments like '-chaetiger larva' (from '6-chaetiger larva') are not terms
            if excluded is not None:
                excluded.append({"term": c["key"], "tier": "glossary" if (c["in_annikey"] or c["in_rouse_gl"])
                                 else ("multi_unit" if len(units) >= 2 else "single_unit"),
                                 "reason": "leading_non_letter", "freq": c["rouse_freq"] + c["hb_freq"]})
            continue
        c["def_en"], c["def_source"] = ((c["ann_def"], "ANNiKEY") if c["ann_def"] else
                                        (c["rouse_def"], "Rouse2022 glossary") if c["rouse_def"] else ("", ""))
        typ, doms = rules_label(c["key"])
        c["type"], c["domain"] = typ, doms
        c["classify_source"] = "rule" if (typ and doms) or typ in ("rank", "taxon_name", "method") else ""
        c["tier"] = "glossary" if (c["in_annikey"] or c["in_rouse_gl"]) else ("multi_unit" if len(units) >= 2 else "single_unit")
        c["n_units"] = len(units)
        out.append(c)
    out.sort(key=lambda c: c["key"])
    return out, family_chapters(family_locs, C)


def family_chapters(fl: dict, C: dict) -> list[dict]:
    rows = []
    for fam, d in sorted(fl.items()):
        g = [k for k in d["concepts"] if C[k]["in_annikey"] or C[k]["in_rouse_gl"]]
        rows.append({"family": fam,
                     "rouse_chapter": (f"{d['rouse']['section']} {d['rouse']['title']}" if d["rouse"] else ""),
                     "rouse_pages": (d["rouse"]["pages"] if d["rouse"] else ""),
                     "handbook_sections": "; ".join(sorted(d["hb"])),
                     "handbook_files": "; ".join(sorted({v["file"] for v in d["hb"].values()})),
                     "n_concepts": len(d["concepts"]), "n_glossary_concepts": len(g)})
    return rows


RAW_COLS = ["occ_id", "book", "unit_raw", "unit_kind", "unit_id", "unit_title", "rouse_chapter_no", "rouse_oso_id",
            "rouse_page_start", "rouse_page_end", "source_file", "hb_section_no", "hb_section_title", "family",
            "term_raw", "term_key", "freq", "in_annikey", "annikey_term", "annikey_def_en", "in_rouse_glossary",
            "rouse_glossary_term", "rouse_glossary_def_en", "in_yiku", "zh_yiku", "zh_rouse_std"]
# 26 columns, in the order of the raw-table design.


def write_raw_occurrences(by_family: Path, annikey: Path, rouse_gl: Path, rouse_meta: dict, out_path: Path) -> int:
    """Raw middle table: one row per (book, unit, term_raw) hit in running text, plus one 'glossary_only' row
    per ANNiKEY / Rouse glossary term never seen in running text. Returns the row count.
    unit_kind: 'general' when by_family.family starts with 'General' (mapped as given, never guessed), else 'family'."""
    def first_by_key(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        d: dict[str, dict[str, str]] = {}
        for r in rows:
            d.setdefault(T.lemma(r["term"].lower().strip()), r)
        return d

    ann, rgl = first_by_key(read_tsv(annikey)), first_by_key(read_tsv(rouse_gl))
    oso = {k: v.get("id", "") for k, v in rouse_meta.items()}
    rows: list[list] = []
    seen: set[str] = set()

    def gl_cells(key: str) -> list:
        a, g = ann.get(key), rgl.get(key)
        return [int(bool(a)), a["term"] if a else "", a.get("definition", "") if a else "",
                int(bool(g)), g["term"] if g else "", g.get("definition", "") if g else ""]

    for r in read_tsv(by_family):
        key = T.lemma(r["term"].lower().strip())
        seen.add(key)
        loc = locate(r["unit"], rouse_meta, r["book"])
        general = r["family"].startswith("General")
        rouse = r["book"] == "Rouse2022"
        m = re.match(r"ch(\d+)", r["unit"]) if rouse else None
        kn = str(int(m.group(1))) if m else ""
        meta = rouse_meta.get(kn, {}) if rouse else {}
        rows.append([r["book"], r["unit"], "general" if general else "family", loc["section"], loc["title"],
                     int(kn) if kn else "", oso.get(kn, "") if rouse else "",
                     meta.get("start", ""), meta.get("end", ""), loc["file"],
                     "" if rouse else loc["section"], "" if rouse else loc["title"],
                     "" if general else r["family"], r["term"], key, r["freq"],
                     *gl_cells(key), r.get("in_yiku", ""), r.get("zh_yiku", ""),
                     r.get("zh_rouse_std", "")])
    for key in sorted(set(ann) | set(rgl)):
        if key in seen:
            continue
        term = ann[key]["term"] if key in ann else rgl[key]["term"]
        rows.append(["Rouse2022" if key in rgl else "ANNiKEY", "", "glossary_only", "", "", "", "", "", "", "", "", "",
                     "", term, key, 0, *gl_cells(key), "", "", ""])
    out = [[f"OCC{i:06d}", *row] for i, row in enumerate(rows, 1)]
    assert all(len(x) == len(RAW_COLS) for x in out), (len(out[0]), len(RAW_COLS))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tsv(out_path, RAW_COLS, out)
    return len(out)


def zh_status(c: dict) -> str:
    y, r = c["zh_yiku"].strip(), c["zh_rouse"].strip()
    if y and r:
        return "一致" if y == r else "冲突待裁"
    if y or r:
        return "仅一源待核"
    return "无"


def tsv_to_xlsx(tsv: Path, xlsx: Path) -> None:
    """Excel-safe copy. Opening a TSV directly in Excel evaluates cells that start with - + = @
    (e.g. '-day-old larva' -> #VALUE!). In xlsx every cell is stored as a text string, so the
    term text survives unchanged."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "terms"
    with open(tsv, encoding="utf8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            ws.append(row)
    for r in ws.iter_rows():
        for c in r:
            c.data_type = "s"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for c in ws[1]:
        c.font = Font(bold=True)
    for col in ws.columns:
        w = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(60, max(8, w + 2))
    wb.save(xlsx)

def _write_tsv(p: Path, head: list[str], rows: list[list]) -> None:
    with open(p, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(head)
        w.writerows(rows)


def load_labels(paths: list[str]) -> dict[str, dict]:
    """Merge several label files by term key (column 'key' or 'term'). Later files override earlier
    non-empty fields only where they have a value; empty cells never erase."""
    merged: dict[str, dict] = {}
    for p in paths:
        for r in read_tsv(Path(p)):
            raw = (r.get("key") or r.get("term") or "").strip()
            if not raw:
                continue
            k = T.lemma(raw.lower())
            cur = merged.setdefault(k, {"type": "", "domain": "", "is_term": ""})
            for f in ("type", "domain", "is_term"):
                v = (r.get(f) or "").strip()
                if v:
                    cur[f] = v
    return merged


def write_outputs(concepts: list[dict], fams: list[dict], out: Path, labels: dict[str, dict] | None = None) -> None:
    """Five files in out: 01 English terms (xlsx+tsv), 02 zh evidence, 03 sources/locations, 04 family chapters,
    05 location long table (tsv)."""
    labels = labels or {}
    out.mkdir(parents=True, exist_ok=True)
    c01 = ["concept_id", "term", "forms", "is_taxon", "type", "domain", "classify_source", "tier", "n_units",
           "def_en", "def_source", "abbr", "scope_annikey", "in_annikey", "in_rouse_glossary", "model_is_term"]
    c02 = ["concept_id", "term", "zh_yiku", "zh_rouse_std", "zh_status"]
    c03 = ["concept_id", "term", "rouse_freq", "handbook_freq", "n_families", "attested_families",
           "rouse_chapters", "handbook_sections", "sources"]
    r01, r02, r03, loc_rows = [], [], [], []
    for i, c in enumerate(concepts, 1):
        cid = f"ANL{i:05d}"
        lab = labels.get(c["key"])
        typ, doms, src, mit = c["type"], c["domain"], c["classify_source"], ""
        if lab and (not typ or not doms):
            typ = typ or lab["type"]
            doms = doms or [d for d in lab["domain"].split("|") if d]
            src = src or "model"
            mit = lab.get("is_term", "")
        fam = "; ".join(f"{k}({v})" for k, v in c["fam"].most_common(8))
        byunit = collections.Counter()
        for loc, n in c["locs"]:
            byunit[(loc["book"], loc["section"], loc["title"], loc["pages"], loc["file"])] += n
            loc_rows.append([cid, c["key"], loc["book"], loc["section"], loc["title"], loc["pages"], loc["file"], n])
        rch = "; ".join(f"{s}{'(' + p + ')' if p else ''}" for (b, s, t, p, _), _n in byunit.most_common(6) if b == "Rouse2022")
        hbs = "; ".join(f"{s} {t}" for (b, s, t, p, _), _n in byunit.most_common(6) if b != "Rouse2022")
        r01.append([cid, c["key"], "|".join(sorted(c["forms"])), int(typ in ("taxon_name", "rank")), typ,
                    "|".join(doms), src, c["tier"], c["n_units"], c["def_en"], c["def_source"], c["abbr"],
                    c["scope"], c["in_annikey"], c["in_rouse_gl"], mit])
        r02.append([cid, c["key"], c["zh_yiku"], c["zh_rouse"], zh_status(c)])
        r03.append([cid, c["key"], c["rouse_freq"], c["hb_freq"], len(c["fam"]), fam, rch, hbs, "|".join(sorted(c["src"]))])
    c04 = ["family", "rouse_chapter", "rouse_pages", "handbook_sections", "handbook_files", "n_concepts", "n_glossary_concepts"]
    r04 = [[f[k] for k in c04] for f in fams]
    c05 = ["concept_id", "term", "book", "section", "title", "pages", "file", "freq"]
    _write_tsv(out / "01_英文术语.tsv", c01, r01)
    _write_tsv(out / "02_中文译名证据.tsv", c02, r02)
    _write_tsv(out / "03_来源与出现位置.tsv", c03, r03)
    _write_tsv(out / "04_科章节定位.tsv", c04, r04)
    _write_tsv(out / "05_出现位置明细.tsv", c05, loc_rows)
    for stem in ("01_英文术语", "02_中文译名证据", "03_来源与出现位置", "04_科章节定位"):
        tsv_to_xlsx(out / f"{stem}.tsv", out / f"{stem}.xlsx")
        if stem != "01_英文术语":
            (out / f"{stem}.tsv").unlink()  # only 01 keeps a tsv next to xlsx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by-family", required=True)
    ap.add_argument("--annikey", required=True)
    ap.add_argument("--rouse-glossary", required=True)
    ap.add_argument("--rouse-dir", required=True, help="dir containing 章节清单.json")
    ap.add_argument("--min-body-freq", type=int, default=2)
    ap.add_argument("--labels", action="append", default=[], help="repeatable; columns key or term, type, domain, is_term")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    meta = json.loads((Path(a.rouse_dir) / "章节清单.json").read_text(encoding="utf8"))
    excluded: list[dict] = []
    cs, fams = build(Path(a.by_family), Path(a.annikey), Path(a.rouse_glossary), meta, a.min_body_freq, excluded)
    exc_path = Path(a.out_dir) / "中间" / "excluded_terms.tsv"
    exc_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tsv(exc_path, ["term", "tier", "reason", "freq"],
               [[e["term"], e["tier"], e["reason"], e["freq"]] for e in sorted(excluded, key=lambda e: e["term"])])
    print(f"excluded {len(excluded)} -> {exc_path}")
    labels = load_labels(a.labels) if a.labels else None
    write_outputs(cs, fams, Path(a.out_dir), labels)
    raw_path = Path(a.out_dir) / "中间" / "raw_term_occurrences.tsv"
    n_raw = write_raw_occurrences(Path(a.by_family), Path(a.annikey), Path(a.rouse_glossary), meta, raw_path)
    print(f"raw occurrences {n_raw} -> {raw_path}")
    print(f"concepts {len(cs)}; families {len(fams)}; rule-decided {sum(1 for c in cs if c['classify_source'] == 'rule')}; "
          f"undecided {sum(1 for c in cs if not (c['type'] and c['domain']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
