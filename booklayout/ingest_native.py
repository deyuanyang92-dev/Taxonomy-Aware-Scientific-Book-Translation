"""Native PDF -> aligned/2 (design 2026-11-26 section B.5): no OCR, spans carry the evidence.

Per page: lines from PyMuPDF spans -> furniture dropped (edge lines repeated on >= 3 pages, bare
page numbers) -> column order via docstore.layout gutter -> blocks (same style, normal leading,
no indent break) -> role/level from fontlevels (number depth > font ladder) -> aligned/2 blocks.

Inline markdown (`*italic*`, `**bold**`) in `text` stays the only channel that drives typesetting;
`runs` is evidence only.  Pure functions take fitz pages, so tests need no files.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from booklayout import fontlevels
from booklayout.furniture import signature
from booklayout.nativefonts import span_style

SCHEMA = "aligned/2"
GAP_BREAK = 0.5       # paragraph break when vertical gap > this x font size
INDENT_BREAK = 0.8    # ... or first-line indent > this x font size after a full line
FULL_LINE = 0.85      # previous line counts as full when it spans this share of the block width
_MARKER = re.compile(r"^\s*[◂▸◀▶►◄]\s*")  # the Handbook's caption bullet; not in the body fonts (falls back to DejaVu)
_CAPTION = re.compile(r"^(fig(?:ure)?s?\.?|tab(?:le)?s?\.?|plate)\s*\d", re.I)
_PAGENO = re.compile(r"^(\d+|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")
_LET = "A-Za-z\xc0-\xff"
_GLUED = re.compile(r"^\d{2,4}(?=[A-Z][a-z])")   # folio fused to a title in one span: '413Index'
_EYEBROW = re.compile(r"^(chapter|part|appendix|section)\s+(\d+|[ivxlc]+)\.?$", re.I)
DISPLAY_RATIO = 1.6   # heading size / body size from which all headings share the top level
TOP_SMALL, BOTTOM_SMALL = 0.85, 0.75   # isolated edge lines smaller than this x body size are furniture


def _engine() -> str:
    import fitz

    return f"pymupdf-{fitz.VersionBind}"


def _page_lines(page: Any) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = ln["spans"]  # whitespace-only spans stay: they carry the word gaps
            if not any(s["text"].strip() for s in spans):
                continue
            x0, y0, x1, y1 = ln["bbox"]
            out.append(dict(spans=spans, x0=x0, y0=y0, x1=x1, y1=y1,
                            text=unglue(" ".join("".join(s["text"] for s in ln["spans"]).split()))
                            if len(spans) == 1 else " ".join("".join(s["text"] for s in ln["spans"]).split())))
    return out


def unglue(text: str) -> str:
    """'413Index' -> 'Index': a page number fused to the word that follows it."""
    return _GLUED.sub("", text)


def _dominant(spans: list[dict]) -> tuple[str, float, bool, bool]:
    """(family, size, bold, italic) weighted by characters."""
    cnt: Counter = Counter()
    for s in spans:
        it, bd = span_style(s)
        cnt[(fontlevels.family_of(s["font"]), round(s["size"], 1), bd, it)] += len(s["text"].strip())
    return cnt.most_common(1)[0][0]


def _at_edge(page: Any, ln: dict) -> bool:
    h = page.rect.height
    return ln["y1"] < h * fontlevels.EDGE_BAND or ln["y0"] > h * (1 - fontlevels.EDGE_BAND)


def edge_furniture(pages: list[Any], min_pages: int = 3) -> set[str]:
    seen: dict[str, set[int]] = {}
    for n, page in enumerate(pages):
        for ln in _page_lines(page):
            if _at_edge(page, ln):
                seen.setdefault(signature(ln["text"]), set()).add(n)
    return {s for s, p in seen.items() if len(p) >= min_pages}


def edge_only_styles(pages: list[Any], min_pages: int = 3) -> set[tuple]:
    """(family, size, bold, italic) seen in the top/bottom band on >= min_pages pages and (almost) nowhere
    else: running heads whose text changes from page to page.  Italic is part of the key so italic
    sub-headings in the same face do not make an upright running head look like body text."""
    edge: dict[tuple, set[int]] = {}
    inner: Counter = Counter()
    for n, page in enumerate(pages):
        for ln in _page_lines(page):
            key = _dominant(ln["spans"])
            if _at_edge(page, ln):
                edge.setdefault(key, set()).add(n)
            else:
                inner[key] += 1
    return {k for k, p in edge.items() if len(p) >= min_pages and inner[k] <= len(p) // 2}


def _is_furniture(page: Any, ln: dict, furniture: set[str], styles: set[tuple]) -> bool:
    if not _at_edge(page, ln):
        return False
    return bool(_PAGENO.match(ln["text"]) or signature(ln["text"]) in furniture or _dominant(ln["spans"]) in styles)


def small_edge_lines(page: Any, lines: list[dict], body_size: float) -> set[int]:
    """Ids of isolated edge lines set clearly smaller than body text: running heads and DOI/copyright
    strips that repeat on too few pages for the signature test (2-page samples).  Top band: < 0.85 x
    body; bottom band (footnotes live there): < 0.75 x body.  Isolated = clear gap to the next line."""
    if not body_size or not lines:
        return set()
    h = page.rect.height
    srt = sorted(lines, key=lambda ln: ln["y0"])
    out: set[int] = set()
    for i, ln in enumerate(srt):
        size = _dominant(ln["spans"])[1]
        top, bottom = ln["y1"] < h * fontlevels.EDGE_BAND, ln["y0"] > h * (1 - fontlevels.EDGE_BAND)
        if not ((top and size < TOP_SMALL * body_size) or (bottom and size < BOTTOM_SMALL * body_size)):
            continue
        nxt = srt[i + 1] if top and i + 1 < len(srt) else None
        prv = srt[i - 1] if bottom and i > 0 else None
        gap = (nxt["y0"] - ln["y1"]) if nxt else ((ln["y0"] - prv["y1"]) if prv else 1e9)
        if gap > 1.2 * size:
            out.add(id(ln))
    return out


def drop_furniture(page: Any, lines: list[dict], furniture: set[str],
                   styles: set[tuple] | None = None, body_size: float = 0.0) -> list[dict]:
    small = small_edge_lines(page, lines, body_size)
    return [ln for ln in lines if id(ln) not in small and not _is_furniture(page, ln, furniture, styles or set())]


def order_lines(lines: list[dict]) -> tuple[list[dict], int]:
    """Reading order: full-width lines separate segments; inside a segment left column then right."""
    if not lines:
        return [], 1
    from docstore.layout import _Box, _find_gutter

    boxes = [_Box(i, [[(ln["x0"], ln["y0"]), (ln["x1"], ln["y1"])]]) for i, ln in enumerate(lines)]
    gut = _find_gutter(boxes) or _narrow_gutter(lines)
    if gut is None:
        for ln in lines:
            ln["col"] = 0
        return sorted(lines, key=lambda ln: (round(ln["y0"]), ln["x0"])), 1
    g0, g1 = gut
    mid = (g0 + g1) / 2
    for ln in lines:
        ln["col"] = -1 if (ln["x0"] < g0 and ln["x1"] > g1) else (0 if (ln["x0"] + ln["x1"]) / 2 < mid else 1)
    ordered: list[dict] = []
    seg: list[dict] = []

    def flush() -> None:
        for c in (0, 1):
            ordered.extend(sorted((ln for ln in seg if ln["col"] == c), key=lambda ln: ln["y0"]))
        seg.clear()

    for ln in sorted(lines, key=lambda ln: (ln["y0"], ln["x0"])):
        if ln["col"] == -1:
            flush()
            ordered.append(ln)
        else:
            seg.append(ln)
    flush()
    return ordered, 2


def _narrow_gutter(lines: list[dict], min_gap: float = 6.0, min_side: int = 5,
                   max_cross: float = 0.05) -> tuple[float, float] | None:
    """Fallback when docstore.layout finds no gutter (a full-width figure/caption spoils its coverage
    test): the widest x-gap, in the middle 40% of the text width, that at most `max_cross` of the
    column-width lines cross (a stray short line over the gutter must not hide it; issue #67).
    Lines that do cross stay full-width segment breaks in `order_lines`."""
    x0, x1 = min(ln["x0"] for ln in lines), max(ln["x1"] for ln in lines)
    width = x1 - x0
    if width <= 0:
        return None
    narrow = [(ln["x0"], ln["x1"]) for ln in lines if ln["x1"] - ln["x0"] < 0.6 * width]
    if len(narrow) < 2 * min_side:
        return None
    lo, hi = int(x0 + 0.3 * width), int(x1 - 0.3 * width)
    limit = max(1, int(max_cross * len(narrow)))
    free = [x for x in range(lo, hi + 1) if sum(1 for a, b in narrow if a < x + 1 and b > x) <= limit]
    best: tuple[float, float] | None = None
    run: list[int] = []
    for x in [*free, -1]:
        if run and (x != run[-1] + 1):
            if best is None or run[-1] + 1 - run[0] > best[1] - best[0]:
                best = (float(run[0]), float(run[-1] + 1))
            run = []
        if x >= 0:
            run.append(x)
    if best is None or best[1] - best[0] < min_gap:
        return None
    mid = (best[0] + best[1]) / 2
    left = sum(1 for a, b in narrow if b <= mid)
    right = sum(1 for a, b in narrow if a >= mid)
    return best if left >= min_side and right >= min_side else None


def _full(prev: dict, group: list[dict]) -> bool:
    width = max(ln["x1"] for ln in group) - min(ln["x0"] for ln in group)
    return width > 0 and (prev["x1"] - prev["x0"]) >= FULL_LINE * width


def group_blocks(lines: list[dict], heads: dict[str, dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for ln in lines:
        ln["style"] = _dominant(ln["spans"])
        ln["head"] = heads.get(_key(ln["text"]))
        if groups:
            prev = groups[-1][-1]
            size = ln["style"][1]
            gap = ln["y0"] - prev["y1"]
            same_style = prev["style"][:3] == ln["style"][:3]
            if prev["head"] or ln["head"]:
                # wrapped heading: same style, unnumbered continuation line
                brk = not (prev["head"] and ln["head"] and same_style and ln["head"]["number"] is None
                           and gap <= GAP_BREAK * size)
            else:
                brk = not (prev.get("col") == ln.get("col") and same_style and gap <= GAP_BREAK * size)
                if not brk and ln["x0"] - min(ln["x0"] for ln in groups[-1]) > INDENT_BREAK * size \
                        and _full(prev, groups[-1]):
                    brk = True
            if not brk:
                groups[-1].append(ln)
                continue
        groups.append([ln])
    return groups


def _runs(lines: list[dict]) -> list[dict]:
    runs: list[dict] = []
    for li, ln in enumerate(lines):
        for si, s in enumerate(ln["spans"]):
            it, bd = span_style(s)
            t = s["text"]
            if si == 0 and li > 0:
                t = " " + t.lstrip()
            if runs and runs[-1].get("i", False) == it and runs[-1].get("b", False) == bd:
                runs[-1]["t"] += t
            else:
                r: dict = {"t": t}
                if it:
                    r["i"] = True
                if bd:
                    r["b"] = True
                runs.append(r)
    for r in runs:  # 'seg- ment' across a line break -> 'segment' (next word lowercase only)
        r["t"] = re.sub(rf"([{_LET}])- ([a-z])", r"\1\2", r["t"])
    return runs


def _mark(runs: list[dict], whole_bold: bool) -> str:
    out = []
    for r in runs:
        t = r["t"]
        core = t.strip()
        if not core:
            out.append(t)
            continue
        lead, trail = t[: len(t) - len(t.lstrip())], t[len(t.rstrip()):]
        if r.get("i"):
            core = f"*{core}*"
        if r.get("b") and not whole_bold:
            core = f"**{core}**"
        out.append(lead + core + trail)
    return " ".join("".join(out).split())


def _plain(lines: list[dict]) -> str:
    t = lines[0]["text"]
    for ln in lines[1:]:
        nxt = ln["text"]
        t = t[:-1] + nxt if re.search(rf"[{_LET}]-$", t) and nxt[:1].islower() else t + " " + nxt
    return t


def _key(text: str) -> str:
    return "".join(text.split())


def build_page(page: Any, page_no: int, furniture: set[str], heads: dict[str, dict], engine: str,
               styles: set[tuple] | None = None, body_size: float = 0.0) -> dict:
    lines = drop_furniture(page, _page_lines(page), furniture, styles, body_size)
    ordered, ncols = order_lines(lines)
    blocks = []
    for gi, grp in enumerate(group_blocks(ordered, heads)):
        fam, size, bold, italic = _dominant([s for ln in grp for s in ln["spans"]])
        runs = _runs(grp)
        head = grp[0]["head"]
        plain = _MARKER.sub("", _plain(grp))
        if runs and _MARKER.match(runs[0]["t"]):
            runs[0]["t"] = _MARKER.sub("", runs[0]["t"])
        whole_bold = bold and all(r.get("b") for r in runs if r["t"].strip())
        text = _mark(runs, whole_bold)
        level = lsrc = None
        if head:
            role, level, lsrc = "heading", head["level"], ("number" if head["source"] == "number" else "font")
            style, text = f"Heading {level}", " ".join(plain.split())
        elif _CAPTION.match(plain):
            role, style = "caption", "Caption"
        else:
            role, style = "body", "Body"
        x0, y0 = min(ln["x0"] for ln in grp), min(ln["y0"] for ln in grp)
        x1, y1 = max(ln["x1"] for ln in grp), max(ln["y1"] for ln in grp)
        b: dict = {
            "block_id": f"p{page_no:04d}-b{gi + 1:02d}", "role": role, "style": style, "text": text,
            "src": {"origin": "native", "engine": engine, "page": page_no,
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    "hash": hashlib.sha1(" ".join(plain.split()).lower().encode("utf-8")).hexdigest()[:16]},
            "font": {"family": fam, "size": size, "bold": bold, "italic": italic},
        }
        if level is not None:
            b["level"], b["level_source"] = level, lsrc
        if any(r.get("i") or r.get("b") for r in runs):
            b["runs"] = runs
        blocks.append(b)
    return {"page": page_no, "columns": ncols, "blocks": blocks}


def refine_levels(pages: list[dict], body_size: float) -> None:
    """Compact the font-ladder levels of unnumbered headings (in place).

    fontlevels ranks every (family, size, bold) it meets, so one book gave 6-7 levels: a 14 pt
    'CHAPTER 12' label, an 18 pt back-matter title and a 24 pt chapter title each took a rung, and an
    italic sub-heading outranked a medium-weight one.  Here: (1) headings set >= 1.6 x body share
    level 1 (display tier); (2) a bare 'CHAPTER n' label takes the level of the heading after it on
    the page and uses no rung; (3) the rest are ranked by size, then weight (bold > medium > regular),
    then upright before italic.  Books with numbered headings keep the number-depth levels
    (number > font, design B.1) and are left alone."""
    heads = [(pg, b) for pg in pages for b in pg["blocks"] if b["role"] == "heading"]
    if not heads or any(b.get("level_source") == "number" for _pg, b in heads):
        return

    def weight(b: dict) -> int:
        fam = b["font"]["family"]
        return 2 if b["font"]["bold"] else (1 if re.search(r"medium|semi|demi", fam, re.I) else 0)

    def key(b: dict) -> tuple:
        f = b["font"]
        if body_size and f["size"] >= DISPLAY_RATIO * body_size:
            return (0,)
        return (1, -f["size"], -weight(b), f["italic"])

    rungs = sorted({key(b) for _pg, b in heads if not _EYEBROW.match(b["text"])})
    rank = {k: i + 1 for i, k in enumerate(rungs)}
    for pg in pages:
        bl = pg["blocks"]
        for i, b in enumerate(bl):
            if b["role"] != "heading":
                continue
            if _EYEBROW.match(b["text"]):
                nxt = next((x for x in bl[i + 1:] if x["role"] == "heading" and not _EYEBROW.match(x["text"])), None)
                b["level"] = rank[key(nxt)] if nxt else 1
            else:
                b["level"] = rank[key(b)]
            b["style"] = f"Heading {b['level']}"


def ingest(pdf: Path, pages: list[int] | None = None) -> dict:
    """Return an aligned/2 dict for the 1-based `pages` (default all)."""
    import fitz

    doc = fitz.open(str(pdf))
    nums = pages or list(range(1, len(doc) + 1))
    fpages = [doc.load_page(n - 1) for n in nums]
    furn = edge_furniture(fpages)
    styles = edge_only_styles(fpages)
    # headings are analysed after furniture removal so running heads never enter the style ladder
    dropped: set[str] = set()
    body = fontlevels.body_style(fpages)
    for pg in fpages:
        lines = _page_lines(pg)
        small = small_edge_lines(pg, lines, body["size"])
        for ln in lines:
            if id(ln) in small or _is_furniture(pg, ln, furn, styles):
                dropped.add(signature(ln["text"]))
                dropped.add(signature(_key(ln["text"])))
    cands: list[dict] = []
    for n, pg in zip(nums, fpages):
        cands.extend(fontlevels.heading_candidates(pg, body, dropped, page_no=n))
    res = fontlevels.assign_levels(cands)
    heads: dict[int, dict[str, dict]] = {}
    for h in res["headings"]:
        h["text"] = unglue(h["text"])
        heads.setdefault(h["page"], {})[_key(h["text"])] = h
    eng = _engine()
    out_pages = [build_page(pg, n, furn, heads.get(n, {}), eng, styles, body["size"])
                 for n, pg in zip(nums, fpages)]
    refine_levels(out_pages, body["size"])
    cur = pdf.stem  # legacy `chapter` key (builder reads it): last level-1 heading, carried forward
    for pg in out_pages:
        for b in pg["blocks"]:
            if b["role"] == "heading" and b.get("level") == 1 and not _EYEBROW.match(b["text"]):
                cur = b["text"]
                break
        pg["chapter"] = cur
        pg["kind"] = "index" if cur.strip().lower().endswith("index") else "chapter"  # legacy page key
    sha = hashlib.sha1(pdf.read_bytes()).hexdigest()
    return {"schema": SCHEMA, "source": {"pdf": pdf.name, "sha1": sha, "kind": "native"},
            "pages": out_pages}


def cmd_ingest_native(a: Any) -> int:
    from booklayout.profile import validate_aligned

    pages = None
    if a.pages:
        import fitz

        pages = fontlevels.parse_pages(a.pages, len(fitz.open(str(a.pdf))))
    data = ingest(a.pdf, pages)
    errs = validate_aligned(data)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    nb = sum(len(p["blocks"]) for p in data["pages"])
    nh = sum(1 for p in data["pages"] for b in p["blocks"] if b["role"] == "heading")
    print(f"ingest-native: {len(data['pages'])} pages, {nb} blocks, {nh} headings -> {a.out}"
          + (f"  schema errors: {len(errs)}" if errs else ""))
    return 1 if errs else 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("ingest-native", help="native PDF -> aligned/2 from font data (no OCR)")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", help="1-based, e.g. 13-40 or 3,7,10-12 (default: all)")
    p.add_argument("-o", "--out", type=Path, required=True)
    p.set_defaults(func=cmd_ingest_native)
