#!/usr/bin/env python3
"""Per-family English term table from Rouse 2022 and the Handbook of Zoology (baseline), merged with
other sources (N-drive candidates, ANNiKEY glossary, yiku). Zero model; re-runnable.

Usage:
  python3 scripts/term_en_master.py --glossary annikey_terms.tsv [--ndrive cand_en_taxonomy.tsv] \
      --out-dir DIR            # writes by_family_en_terms.tsv and master_en_terms.tsv

Units: Rouse = one chapter per family/order (章节清单.json titles); Handbook = numbered headings
containing a family name (-idae/-inae) inside s7_*.txt, other chapters by their heading.
Source evidence per row: book, unit heading, file. (src_en has no page markers; page ranges for Rouse are in
章节清单.json.) Baseline = Rouse + Handbook; everything else is supplementary, not "wrong".
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sqlite3
from pathlib import Path

import term_en_candidates as T

ROOT = Path("/mnt/p/翻译-译作")
FAM_RE = re.compile(r"\b([A-Z][a-z]+(?:idae|inae))\b")
HEAD_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+([A-Z].{2,110})$")
IRREG = {"cirri": "cirrus", "uncini": "uncinus", "radioli": "radiolus", "setae": "seta", "chaetae": "chaeta"}


def lemma(term: str) -> str:
    """Singular form of the last word only (chaetae->chaeta, lobes->lobe, cirri->cirrus)."""
    w = term.split()
    x = w[-1]
    if x in IRREG:
        x = IRREG[x]
    elif x.endswith("ae") and len(x) > 4:
        x = x[:-2] + "a"
    elif x.endswith("ies"):
        x = x[:-3] + "y"
    elif x.endswith("s") and not x.endswith(("ss", "us", "is")) and len(x) > 3:
        x = x[:-1]
    return " ".join(w[:-1] + [x])


GL_ENTRY = re.compile(r"^([a-z][A-Za-z\-' /()]{1,60}?(?:, [a-z][A-Za-z\-' ]{1,40})*): (\S.*)$")


def parse_rouse_glossary(text: str) -> list[tuple[str, str]]:
    """Rouse 2022 glossary: 'term[, plural]: definition', wrapped lines, hyphen line-breaks. -> (term, definition)."""
    body = text.split("\n", 1)[1] if text.startswith("GLOSSARY") else text
    entries: list[list[str]] = []
    for line in body.splitlines():
        line = line.rstrip()
        if re.fullmatch(r"(\d+\s+GLOSSARY|GLOSSARY\s+\d+)", line.strip()):  # running page header
            continue
        m = GL_ENTRY.match(line)
        if m and not line.startswith(("See ", "(See ")):
            entries.append([m.group(1), m.group(2)])
        elif entries and line.strip():
            entries[-1][1] += "\n" + line
    out = []
    for term, d in entries:
        d = re.sub(r"-\n", "", d)
        out.append((term.split(",")[0].strip(), re.sub(r"\s+", " ", d).strip()))
    return out


def rouse_units(rdir: Path) -> list[tuple[str, str, str, str]]:
    """(book, family_or_topic, unit_heading, text)"""
    meta = json.loads((rdir / "章节清单.json").read_text(encoding="utf8"))
    out = []
    for k, m in meta.items():
        if not k.isdigit():  # front / glossary / plates
            continue
        f = rdir / "src_en" / f"ch{int(k):02d}.txt"
        if not f.exists():
            continue
        title = m["title_en"].strip()
        fam = title.title() if re.search(r"(IDAE|INAE|IDA|IFORMIA|ODRILUS|GORDIUS)$", title) or len(title.split()) == 1 else "General: " + title.title()
        out.append(("Rouse2022", fam, f"ch{int(k):02d} {title}", f.read_text(encoding="utf8", errors="replace")))
    return out


def handbook_units(hdir: Path) -> list[tuple[str, str, str, str]]:
    out = []
    for f in sorted((hdir / "src_en").glob("*.txt")):
        fam, head = f"General: {f.stem}", f.stem
        buf: list[str] = []
        def flush():
            if buf:
                out.append(("Handbook", fam, f"{head} [{f.name}]", "\n".join(buf)))
        for line in f.read_text(encoding="utf8", errors="replace").splitlines():
            m = HEAD_RE.match(line.strip())
            fm = FAM_RE.search(m.group(2)) if m else None
            general = m is not None and f.name.startswith(("ch", "apx")) and not re.search(r"[,()]", m.group(2)) \
                and len(m.group(2).split()) <= 8 and m.group(2) != "References"
            if m is not None and (fm or general):
                flush()
                buf = []
                head = f"{m.group(1)} {m.group(2)}"
                fam = fm.group(1) if fm else f"General: {m.group(2)}"
                continue
            buf.append(line)
        flush()
    return out


def read_tsv(p: Path) -> list[dict[str, str]]:
    with open(p, encoding="utf8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--ndrive")
    ap.add_argument("--yiku", default=str(Path.home() / ".yiku" / "yiku.db"))
    ap.add_argument("--rouse", default=str(ROOT / "Rouse2022_Annelida"))
    ap.add_argument("--handbook", default=str(ROOT / "Handbook_Annelida"))
    ap.add_argument("--min-freq", type=int, default=2)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dump-rouse-glossary", help="also write Rouse glossary as TSV (term, definition, ...) for yiku gloss import")
    a = ap.parse_args(argv)

    gl = read_tsv(Path(a.glossary))
    gset = {T.norm(r["term"]) for r in gl}
    rstd: dict[str, str] = {}
    for p in sorted((Path(a.rouse) / "术语库").glob("形态术语*.tsv")):
        for r in read_tsv(p):
            en = T.norm(next(iter(r.values())) or "")
            if en:
                rstd.setdefault(en, list(r.values())[1])
    con = sqlite3.connect(a.yiku)
    ymap: dict[str, str] = {}
    for en, zh in con.execute("SELECT en_norm, zh FROM terms WHERE status!='否决' ORDER BY status='已核' DESC, id"):
        ymap.setdefault(en, zh)
    rgl = parse_rouse_glossary((Path(a.rouse) / "src_en" / "glossary.txt").read_text(encoding="utf8"))
    rgl_def = {T.norm(t): d for t, d in rgl}
    gdef = {T.norm(r["term"]): r.get("definition", "") for r in gl}
    if a.dump_rouse_glossary:
        with open(a.dump_rouse_glossary, "w", encoding="utf8", newline="") as fh:
            w0 = csv.writer(fh, delimiter="\t")
            w0.writerow(["term", "definition", "applicable", "abbr", "source"])
            w0.writerows([t, d, "Annelida", "", "Rouse 2022 Glossary"] for t, d in rgl)
    heads = T.heads_from_glossary([r["term"] for r in gl] + list(rstd) + [t for t, _ in rgl], min_n=2)

    units = rouse_units(Path(a.rouse)) + handbook_units(Path(a.handbook))
    long_rows: list[tuple] = []
    for book, fam, unit, text in units:
        for g, n in T.ngrams(text, heads).items():
            if n >= a.min_freq:
                long_rows.append((fam, book, unit, g, n))

    nd: dict[str, tuple[int, int]] = {}
    if a.ndrive:
        for r in read_tsv(Path(a.ndrive)):
            k = lemma(r["term"])
            f0, d0 = nd.get(k, (0, 0))
            nd[k] = (f0 + int(r["freq"]), d0 + int(r["docs"]))

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = ["family", "book", "unit", "term", "freq", "in_glossary", "in_yiku", "zh_yiku", "zh_rouse_std"]
    with open(out / "by_family_en_terms.tsv", "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(cols)
        for fam, book, unit, g, n in sorted(long_rows, key=lambda r: (r[0], -r[4], r[3])):
            k = lemma(g)
            w.writerow([fam, book, unit, g, n, int(k in gset or g in gset or g in rgl_def or k in rgl_def),
                        int(g in ymap or k in ymap),
                        ymap.get(g, ymap.get(k, "")), rstd.get(g, rstd.get(k, ""))])

    agg: dict[str, dict] = {}
    for fam, book, unit, g, n in long_rows:
        e = agg.setdefault(lemma(g), {"forms": set(), "fam": collections.Counter(), "R": 0, "H": 0, "src": []})
        e["forms"].add(g)
        e["fam"][fam] += n
        e["R" if book == "Rouse2022" else "H"] += n
        if len(e["src"]) < 4:
            e["src"].append(f"{book}:{unit}")
    for t in list(rgl_def) + list(gdef):  # glossary terms never seen in running text still belong in the master
        agg.setdefault(lemma(t), {"forms": {t}, "fam": collections.Counter(), "R": 0, "H": 0, "src": []})
    gl_lem = {lemma(t) for t in gset}
    rgl_lem = {lemma(t) for t in rgl_def}
    mcols = ["term", "forms", "n_families", "top_families", "rouse_freq", "handbook_freq", "baseline_freq",
             "ndrive_freq", "ndrive_docs", "in_rouse_glossary", "in_annikey", "in_yiku", "zh_yiku", "zh_rouse_std",
             "def_en", "def_source", "sources"]
    with open(out / "master_en_terms.tsv", "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(mcols)
        rows = []
        for k, e in agg.items():
            nf, nds = nd.get(k, (0, 0))
            fm = e["forms"] | {k}
            rd = next((rgl_def[x] for x in fm if x in rgl_def), "")
            ad = next((gdef[x] for x in fm if gdef.get(x)), "")
            srcs = list(e["src"]) + (["Rouse2022:glossary"] if k in rgl_lem else []) + (
                ["ANNiKEY:glossary"] if k in gl_lem else [])
            rows.append([k, "|".join(sorted(e["forms"])), len(e["fam"]),
                         "; ".join(f"{x}({c})" for x, c in e["fam"].most_common(5)), e["R"], e["H"], e["R"] + e["H"],
                         nf, nds, int(k in rgl_lem), int(k in gl_lem), int(any(x in ymap for x in fm)),
                         next((ymap[x] for x in fm if x in ymap), ""), next((rstd[x] for x in fm if x in rstd), ""),
                         rd or ad, "Rouse2022 glossary" if rd else ("ANNiKEY" if ad else ""), " | ".join(srcs)])
        rows.sort(key=lambda r: (-(r[9] + r[10]), -r[2], -r[6]))
        w.writerows(rows)
    print(f"units {len(units)}, by_family rows {len(long_rows)}, master terms {len(agg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
