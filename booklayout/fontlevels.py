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
# "2.1 Morphology", "7.4.1 Name", and the bare one-level "1 Introduction" / "1. Introduction" (an
# upper-case word must follow, so "12 mm long" or "3 setae" are not numbers).
_NUMBER = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+\S")
_NUMBER_BARE = re.compile(r"^(\d{1,2})\.?\s+(?=[A-Z\xc0-\xde])")
BARE_MAX_LEN = 60       # a bare "1 Xxx" line longer than this is a key couplet / list row, not a heading
SAME_SIZE_MAX_LEN = 80  # a same-size bold line longer than this is run-in prose, not a heading
_LEADERS = re.compile(r"(?:\.\s*){3,}|…")
_PAGENO = re.compile(r"^(\d+|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")
_SANS = re.compile(r"sans|arial|helvet|calibri|verdana|gothic|meta(?!serif)|univers|frutiger|simhei|heiti|yahei|黑|sourcehansans|notosanscjk", re.I)
_SERIF = re.compile(r"serif|times|roman|georgia|garamond|palatino|minion|cambria|simsun|book", re.I)
EDGE_BAND = 0.08


def family_of(font: str) -> str:
    f = _TRAIL_DIGITS.sub("", _SUBSET.sub("", font))
    # every trailing weight/slant token: "Meta-BoldItalic" is the family "Meta", not "Meta-Bold"
    f = re.sub(r"(?:[-,]?(?:Bold|Regular|Italic|Oblique|Roman|Regul|Reg))+(?:PS)?(?:MT)?$", "", f, flags=re.I)
    return f.rstrip("-,") or font


def is_serif(font: str, flags: int = 0) -> bool:
    if re.search(r"serif", font, re.I) and not re.search(r"sans", font, re.I):
        return True
    if _SANS.search(font):
        return False
    if _SERIF.search(font):
        return True
    return bool(flags & 4)


def _line_styles(spans: list[dict]) -> set[tuple]:
    """Styles of one line, tolerant of two common heading constructions.

    * faux small caps: same family and weight, several sizes -> the largest size;
    * mixed scripts at one size (CJK sans + Latin serif) -> the style carrying
      most characters.
    Anything else keeps every distinct style, so mixed body lines stay rejected.
    """
    chars: Counter = Counter()
    for s in spans:
        _it, bd = span_style(s)
        chars[(family_of(s["font"]), round(s["size"], 1), bd, is_serif(s["font"], s["flags"]))] += len(s["text"].strip())
    if len(chars) <= 1:
        return set(chars)
    if len({(f, b, sf) for f, _z, b, sf in chars}) == 1:
        f, _z, b, sf = next(iter(chars))
        return {(f, max(z for _f, z, _b, _s in chars), b, sf)}
    sizes = [z for _f, z, _b, _s in chars]
    if len({b for _f, _z, b, _s in chars}) > 1 and not any(0x3400 <= ord(c) <= 0x9fff for s in spans for c in s["text"]):
        return set(chars)   # bold and light text in one line: a run-in head ("Prostomium. The ..."), not a heading
    if max(sizes) - min(sizes) < 0.3:
        return {chars.most_common(1)[0][0]}
    return set(chars)


def _in_edge(ln: dict) -> bool:
    h = ln["height"]
    return ln["y1"] < h * EDGE_BAND or ln["y0"] > h * (1 - EDGE_BAND)


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")   # a stray BEL inside "7.7 Sedentaria" must not make the line differ from ingest's text


def _lines(page: Any) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            styles = _line_styles(spans)
            out.append(dict(
                text=" ".join(_CTRL.sub("", "".join(s["text"] for s in ln["spans"])).split()),
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
    t = text.strip()
    m = _NUMBER.match(t)
    if not m:
        m = _NUMBER_BARE.match(t)
        if not m or len(t) > BARE_MAX_LEN or _LEADERS.search(t):
            return None
    return m.group(1), m.group(1).count(".") + 1


def _edge_signatures(pages: list[Any]) -> set[str]:
    seen: dict[str, set[int]] = {}
    for n, page in enumerate(pages):
        for ln in _lines(page):
            if _in_edge(ln):
                seen.setdefault(signature(ln["text"]), set()).add(n)
    return {s for s, p in seen.items() if len(p) >= 3}


def _bold_short_line(text: str, bold: bool, body: dict, num: Any) -> bool:
    """A single-style bold line in the body's own size/serif class ("1.1 Methods" in Times bold over
    Times roman).  Guards against prose and keys: short, no leaders, no sentence end (unless numbered),
    no lowercase start, not a bare page-number-ended row."""
    if not bold or body["bold"] or len(text) > SAME_SIZE_MAX_LEN or _LEADERS.search(text):
        return False
    if text[:1].islower() or not re.search(r"[A-Za-z\xc0-\xff]{2}", text):
        return False
    if num is None and (text[-1] in ".,;" or re.search(r"\s\d{1,4}$", text)):
        return False
    return True


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
        # position AND repetition: a chapter title equal to the running head but
        # set in the page body is a heading, not furniture
        if furniture and signature(text) in furniture and _in_edge(ln):
            continue
        num = number_depth(text)
        if not (size >= body["size"] * SIZE_RATIO or (bold and serif != body["serif"])
                or _bold_short_line(text, bold, body, num)):
            continue
        out.append(dict(
            page=page_no if page_no is not None else page.number + 1, text=text,
            style={"family": fam, "size": size, "bold": bold},
            number=num[0] if num else None, depth=num[1] if num else None))
    return out


def merge_levels(styles: dict[Any, tuple[Any, list[int]]]) -> tuple[dict[Any, int], int]:
    """Merge number depth and the font ladder into one level scale.

    `styles` maps a style key to (sort key, raw levels of its numbered members); a smaller sort key
    is a bigger style.  A style with numbered members takes their most common level; an unnumbered
    style takes the level of the next bigger numbered style (one rung down when the numbered levels
    leave a gap), so a bigger unnumbered chapter title never ranks below a smaller numbered section;
    unnumbered styles above every numbered one take the levels above them.  Levels are then shifted
    so the top is 1.  Returns ({style key: level}, shift); numbered headings use own raw level + shift.
    """
    order = sorted(styles, key=lambda k: (styles[k][0], str(k)))
    raw: dict[Any, int] = {}
    nums = [k for k in order if styles[k][1]]
    for k in nums:
        cnt = Counter(styles[k][1])
        raw[k] = min(cnt, key=lambda lv: (-cnt[lv], lv))
    if not nums:
        raw = {k: i + 1 for i, k in enumerate(order)}
    else:
        pos = {k: i for i, k in enumerate(order)}
        for k in order:
            if k in raw:
                continue
            above = [n for n in nums if pos[n] < pos[k]]
            below = [n for n in nums if pos[n] > pos[k]]
            run = [x for x in order if x not in nums and (not above or pos[x] > pos[above[-1]])
                   and (not below or pos[x] < pos[below[0]])]
            i = run.index(k)
            if above and below:
                gap = raw[below[0]] - raw[above[-1]]
                raw[k] = raw[above[-1]] + min(i, max(gap - 1, 0))
            elif above:
                raw[k] = raw[above[-1]] + 1 + i
            else:
                raw[k] = raw[below[0]] - (len(run) - i)
    shift = max(0, 1 - min(raw.values())) if raw else 0
    return {k: v + shift for k, v in raw.items()}, shift


def assign_levels(cands: list[dict]) -> dict:
    """Return {headings, ladder, conflicts}; number depth and the style ladder share one scale."""
    skey = lambda c: (c["style"]["family"], c["style"]["size"], c["style"]["bold"])  # noqa: E731
    depths = [c["depth"] for c in cands if c["depth"]]
    min_depth = min(depths) if depths else 1
    groups: dict[tuple, tuple[Any, list[int]]] = {}
    for c in cands:
        s = skey(c)
        _k, nl = groups.setdefault(s, ((-s[1], not s[2], s[0]), []))
        if c["depth"]:
            nl.append(c["depth"] - min_depth + 1)
    rank, shift = merge_levels(groups)
    count = Counter(skey(c) for c in cands)
    ladder = [dict(family=s[0], size=s[1], bold=s[2], level=rank[s], count=count[s])
              for s in sorted(groups, key=lambda s: (rank[s], -s[1], not s[2], s[0]))]
    heads, conflicts = [], []
    for c in cands:
        style_lv = rank[skey(c)]
        notes = []
        if c["depth"]:
            level, source = c["depth"] - min_depth + 1 + shift, "number"
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
