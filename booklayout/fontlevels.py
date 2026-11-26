"""Heading levels from native PDF font data: family + bold + size ladder (issue #60).

Handbook-style books set many headings in the body size, so size alone is not
enough: a heading is a single-style line whose style differs from the body style
by size (>= 1.15x) or by bold plus a sans/serif switch.  Numbered headings
("7.4.1 Name") get their level from the number depth; others from the style
ladder.  Disagreements (number vs style, taxon_level vs style) are reported in
``conflict``, never overridden.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from booklayout.furniture import signature
from booklayout.headings import taxon_level
from booklayout.nativefonts import span_style

SIZE_RATIO = 1.15
MAX_LEN = 120
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TRAIL_DIGITS = re.compile(r"\d+$")
_NUMBER = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+\S")
_PAGENO = re.compile(r"^(\d+|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")
_SANS = re.compile(r"sans|arial|helvet|calibri|verdana|gothic|meta(?!serif)|univers|frutiger", re.I)
_SERIF = re.compile(r"serif|times|roman|georgia|garamond|palatino|minion|cambria|simsun|book", re.I)
EDGE_BAND = 0.08


def family_of(font: str) -> str:
    f = _TRAIL_DIGITS.sub("", _SUBSET.sub("", font))
    f = re.sub(r"[-,]?(Bold|Regular|Italic|Oblique|Roman|Reg|Regul)?$", "", f, flags=re.I)
    return f.rstrip("-,") or font


def is_serif(font: str, flags: int = 0) -> bool:
    if re.search(r"serif", font, re.I) and not re.search(r"sans", font, re.I):
        return True
    if _SANS.search(font):
        return False
    if _SERIF.search(font):
        return True
    return bool(flags & 4)


def _lines(page: Any) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            styles = set()
            for s in spans:
                _it, bd = span_style(s)
                styles.add((family_of(s["font"]), round(s["size"], 1), bd, is_serif(s["font"], s["flags"])))
            out.append(dict(
                text=" ".join("".join(s["text"] for s in ln["spans"]).split()),
                styles=styles, spans=spans, y0=ln["bbox"][1], y1=ln["bbox"][3],
                height=page.rect.height))
    return out


def body_style(pages: list[Any]) -> dict:
    """Most frequent (family, size) by characters -> {family,size,bold,serif}."""
    cnt: Counter = Counter()
    for page in pages:
        for ln in _lines(page):
            for s in ln["spans"]:
                _it, bd = span_style(s)
                key = (family_of(s["font"]), round(s["size"], 1), bd, is_serif(s["font"], s["flags"]))
                cnt[key] += len(s["text"].strip())
    if not cnt:
        return {"family": "", "size": 0.0, "bold": False, "serif": True}
    (fam, size, bold, serif), _n = cnt.most_common(1)[0]
    return {"family": fam, "size": size, "bold": bold, "serif": serif}


def number_depth(text: str) -> tuple[str, int] | None:
    m = _NUMBER.match(text.strip())
    if not m:
        return None
    return m.group(1), m.group(1).count(".") + 1


def _edge_signatures(pages: list[Any]) -> set[str]:
    seen: dict[str, set[int]] = {}
    for n, page in enumerate(pages):
        for ln in _lines(page):
            h = ln["height"]
            if ln["y1"] < h * EDGE_BAND or ln["y0"] > h * (1 - EDGE_BAND):
                seen.setdefault(signature(ln["text"]), set()).add(n)
    return {s for s, p in seen.items() if len(p) >= 3}


def heading_candidates(page: Any, body: dict, furniture: set[str] | None = None,
                       page_no: int | None = None) -> list[dict]:
    out = []
    bsty = (body["family"], body["size"], body["bold"])
    for ln in _lines(page):
        text = ln["text"]
        if len(ln["styles"]) != 1 or not text or len(text) > MAX_LEN:
            continue
        fam, size, bold, serif = next(iter(ln["styles"]))
        if (fam, size, bold) == bsty or _PAGENO.match(text) or text.endswith(":"):
            continue
        if furniture and signature(text) in furniture:
            continue
        if not (size >= body["size"] * SIZE_RATIO or (bold and serif != body["serif"])):
            continue
        num = number_depth(text)
        out.append(dict(
            page=page_no if page_no is not None else page.number + 1, text=text,
            style={"family": fam, "size": size, "bold": bold},
            number=num[0] if num else None, depth=num[1] if num else None))
    return out


def assign_levels(cands: list[dict]) -> dict:
    """Return {headings, ladder, conflicts}; ladder ranks styles by size desc, bold first."""
    styles = {(c["style"]["family"], c["style"]["size"], c["style"]["bold"]) for c in cands}
    order = sorted(styles, key=lambda s: (-s[1], not s[2], s[0]))
    rank = {s: i + 1 for i, s in enumerate(order)}
    count = Counter((c["style"]["family"], c["style"]["size"], c["style"]["bold"]) for c in cands)
    ladder = [dict(family=s[0], size=s[1], bold=s[2], level=rank[s], count=count[s]) for s in order]
    depths = [c["depth"] for c in cands if c["depth"]]
    min_depth = min(depths) if depths else 1
    heads, conflicts = [], []
    for c in cands:
        s = (c["style"]["family"], c["style"]["size"], c["style"]["bold"])
        style_lv = rank[s]
        notes = []
        if c["depth"]:
            level, source = c["depth"] - min_depth + 1, "number"
            if level != style_lv:
                notes.append(f"number={level} vs style={style_lv}")
        else:
            level, source = style_lv, "style"
        tx = taxon_level(c["text"], default=0)
        if tx and tx != level:
            notes.append(f"taxon={tx} vs style={level}")
        h = dict(page=c["page"], text=c["text"], level=level, style=c["style"],
                 number=c["number"], depth=c["depth"], source=source,
                 conflict="; ".join(notes) or None)
        heads.append(h)
        if notes:
            conflicts.append(h)
    return {"headings": heads, "ladder": ladder, "conflicts": conflicts}


def analyse(pages: list[Any]) -> dict:
    """Run the whole pipeline on fitz pages; body style is measured on these pages."""
    body = body_style(pages)
    furn = _edge_signatures(pages)
    cands: list[dict] = []
    for page in pages:
        cands.extend(heading_candidates(page, body, furn))
    res = assign_levels(cands)
    res["body"] = body
    return res


def parse_pages(spec: str, n: int) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.extend(range(max(lo, 1), min(hi, n) + 1))
    return out


def cmd_heading_levels(a: Any) -> int:
    import json

    import fitz

    doc = fitz.open(str(a.pdf))
    nums = parse_pages(a.pages, len(doc)) if a.pages else list(range(1, len(doc) + 1))
    res = analyse([doc.load_page(i - 1) for i in nums])
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    b = res["body"]
    print(f"body: {b['family']} {b['size']}pt  headings={len(res['headings'])}  conflicts={len(res['conflicts'])}")
    for r in res["ladder"]:
        print(f"  L{r['level']} {r['family']} {r['size']}pt{' bold' if r['bold'] else ''} x{r['count']}")
    for h in res["headings"]:
        print(f"  p{h['page']} L{h['level']} [{h['source']}] {h['text'][:70]}" + (f"  !! {h['conflict']}" if h["conflict"] else ""))
    return 0


def add_parser(sub: Any) -> None:
    from pathlib import Path

    p = sub.add_parser("heading-levels", help="heading levels from font family/bold/size + numbering")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", help="1-based, e.g. 13-40 or 3,7,10-12 (default: all)")
    p.add_argument("--json", type=Path, help="write full result here")
    p.set_defaults(func=cmd_heading_levels)
