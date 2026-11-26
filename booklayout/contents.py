"""Structured table of contents: parse, render with tab leaders, check (issue #14).

A contents page flattened into one paragraph is unusable.  Entries are modelled
explicitly (title, level, source page, output page); the output page comes from
final pagination when it is known, and the source-book page is never printed as
if it were an output page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.shared import Mm, Pt

_ENTRY = re.compile(
    r"(?P<title>\S.*?)\s*(?:(?:\.\s*){3,}|…+)\s*(?P<page>\d{1,4}|[ivxlcIVXLC]{1,6})(?=\s|$)",
    re.S,
)
_NUMBERING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
INDENT_MM = 5.0
HANG_MM = 4.0


@dataclass
class ContentsEntry:
    title: str
    level: int = 0
    source_page: str | None = None
    output_page: str | None = None


def parse_contents(text: str) -> tuple[list[ContentsEntry], list[str]]:
    """Return (entries, leftover lines).

    Lines are joined, so a title wrapped over several lines is one entry and
    several entries flattened onto one line are separated again.  The level
    comes from the numbering depth (``2.1.1`` -> 2), else from the indent of
    the entry's first line.  Text that does not end in a page reference is
    returned, not dropped.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    joined = ""
    starts: list[tuple[int, int]] = []  # (offset in joined, indent)
    for ln in lines:
        starts.append((len(joined), len(ln) - len(ln.lstrip())))
        joined += ln.strip() + " "
    entries: list[ContentsEntry] = []
    raw: list[tuple[int, ContentsEntry]] = []
    pos = 0
    for m in _ENTRY.finditer(joined):
        raw.append((m.start("title"), ContentsEntry(
            title=re.sub(r"\s+", " ", m.group("title")).strip(),
            source_page=m.group("page"),
        )))
        pos = m.end()
    indents = sorted({ind for _, ind in starts})
    for offset, entry in raw:
        numbered = _NUMBERING.match(entry.title + " ")
        if numbered:
            entry.level = numbered.group(1).count(".")
        else:
            ind = [i for off, i in starts if off <= offset][-1]
            entry.level = indents.index(ind)
        entries.append(entry)
    rest = joined[pos:].strip()
    return entries, ([ln.strip() for ln in lines if ln.strip() in rest] if rest else [])


_NUM_ONLY = re.compile(r"^\d+(?:\.\d+)*\.?$")
_PAGE_ONLY = re.compile(r"^(?:\d{1,4}|[ivxlc]{1,6})$")
_HEAD_WORDS = re.compile(r"^(?:table of contents|contents|índice|indice|inhalt|sommaire|目录|目\s*录)$", re.I)
ROW_TOL = 3.0
RIGHT_TOL = 15.0


def _spans(page: Any) -> list[tuple[float, float, float, float, str]]:
    """Non-empty spans of a fitz page as (yc, x0, x1, y1, text)."""
    out = []
    for blk in page.get_text("dict").get("blocks", []):
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip():
                    x0, y0, x1, y1 = sp["bbox"]
                    out.append(((y0 + y1) / 2, x0, x1, y1, sp["text"]))
    return out


def _split_columns(spans: list[tuple[float, float, float, float, str]]
                   ) -> list[list[tuple[float, float, float, float, str]]]:
    """Left/right column span lists split at the gutter (docstore.layout); one list if single column."""
    if len(spans) < 8:
        return [spans]
    from docstore.layout import _Box, _find_gutter
    boxes = [_Box(i, [[(s[1], s[0]), (s[2], s[3])]]) for i, s in enumerate(spans)]
    gut = _find_gutter(boxes)
    if gut is None:
        return [spans]
    gc = (gut[0] + gut[1]) / 2
    left = [s for s in spans if (s[1] + s[2]) / 2 < gc]
    right = [s for s in spans if (s[1] + s[2]) / 2 >= gc]
    def texty(side: list[tuple[float, float, float, float, str]]) -> int:
        return len({round(s[0] / ROW_TOL) for s in side if re.search(r"[A-Za-z]{3}", s[4])})
    if texty(left) < 3 or texty(right) < 3:   # page numbers alone on the right are not a column
        return [spans]
    return [left, right]


def _rows(spans: list[tuple[float, float, float, float, str]]) -> list[tuple[float, float, list[str]]]:
    """Rows as (x0, x1, [span texts]), top to bottom; spans on one baseline merged."""
    groups: list[list[tuple[float, float, float, float, str]]] = []
    for s in sorted(spans):
        if groups and abs(groups[-1][0][0] - s[0]) <= ROW_TOL:
            groups[-1].append(s)
        else:
            groups.append([s])
    rows = []
    for g in groups:
        g.sort(key=lambda s: s[1])
        rows.append((g[0][1], max(s[2] for s in g), [s[4].strip() for s in g]))
    return rows


def _column_entries(spans: list[tuple[float, float, float, float, str]],
                    last_level: list[int]) -> list[ContentsEntry]:
    rows = _rows(spans)
    if not rows:
        return []
    right = max(r[1] for r in rows)
    entries: list[ContentsEntry] = []
    pending: list[str] = []
    for _x0, x1, parts in rows:
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", " ".join(parts)).strip()
        toks = text.split()
        if not toks:
            continue
        if _HEAD_WORDS.match(" ".join(t for t in toks if not _PAGE_ONLY.match(t)) or text):
            continue                  # running head such as "Contents ix" / "x Contents"
        at_right = x1 >= right - RIGHT_TOL
        last_span = parts[-1].split()[-1] if parts[-1].split() else ""
        own_span_page = len(parts) > 1 and bool(_PAGE_ONLY.match(last_span)) and parts[-1].strip() == last_span
        is_page = bool(_PAGE_ONLY.match(toks[-1])) and (own_span_page or (
            at_right and (len(toks) > 1 or bool(pending))))
        if _NUM_ONLY.match(text) and not is_page:
            pending = [text]          # chapter number alone: new entry starts here
            continue
        if _NUMBERING.match(text + " ") and len(toks) > 1:
            pending = []              # numbered row: drop author/stray lines gathered above
        if is_page:
            body = " ".join(toks[:-1]).strip()
            title = re.sub(r"\s+", " ", " ".join(pending + ([body] if body else []))).strip()
            pending = []
            if not title or len(title) > 160:   # body-text/table page, not a contents line
                continue
            m = _NUMBERING.match(title + " ")
            if m:
                level = m.group(1).count(".")
                last_level[0] = level
            else:
                level = last_level[0] + 1 if last_level[0] >= 0 else 0
            entries.append(ContentsEntry(title=title, level=level, source_page=toks[-1]))
        else:
            pending.append(text)
    return entries


def contents_from_pdf_page(page: Any) -> list[ContentsEntry]:
    """Contents entries from line geometry (no dot leaders needed).

    Two-column pages are split at the gutter and read left then right.  A row
    is a page-number row when its last span is a bare number (arabic, or lower
    roman), or when its last token is a number ending at the column's right
    edge.  Rows above it that carry no page number are joined into the title;
    a row starting with a chapter number (``7.4``) starts a new entry.
    Level = number segments - 1; an unnumbered entry sits one level below the
    last numbered one.
    """
    last_level = [-1]
    out: list[ContentsEntry] = []
    for col in _split_columns(_spans(page)):
        out += _column_entries(col, last_level)
    return out


def render_contents(doc: Any, entries: Iterable[ContentsEntry], size: float = 10.5,
                    text_w: float | None = None, add_runs: Any = None,
                    genera: Any = None, source_label: str | None = "src. p. ") -> list[Any]:
    """One paragraph per entry: title, tab with dot leader, page flush right."""
    from . import builder

    width = builder.TEXT_W if text_w is None else text_w
    runs = add_runs or builder.add_runs
    out = []
    for e in entries:
        par = doc.add_paragraph()
        pf = par.paragraph_format
        pf.tab_stops.add_tab_stop(Mm(width), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        pf.space_before = Pt(3)
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if e.level:
            # Sub-entries are indented and hang, so a wrapped title stays
            # under its own text.  Top-level entries keep the original look.
            pf.left_indent = Mm(INDENT_MM * e.level + HANG_MM)
            pf.first_line_indent = Mm(-HANG_MM)
        else:
            pf.left_indent = Mm(0)
        runs(par, e.title, size, bold=(e.level == 0), genera=genera)
        par.add_run("\t")
        if e.output_page not in (None, ""):
            page = str(e.output_page)
        elif e.source_page and source_label is not None:
            # Never print a source-book page as if it were an output page.
            page = f"{source_label}{e.source_page}"
        else:
            page = ""
        runs(par, page, size)
        out.append(par)
    return out


def check_contents_paragraphs(paragraphs: Iterable[Any], expected: int | None = None) -> list[dict]:
    """Render-level acceptance check for contents paragraphs already in a DOCX."""
    pars = [p for p in paragraphs if p.text.strip()]
    problems: list[dict] = []
    for p in pars:
        text = p.text
        stops = list(p.paragraph_format.tab_stops)
        has_leader = any(s.alignment == WD_TAB_ALIGNMENT.RIGHT and s.leader == WD_TAB_LEADER.DOTS
                         for s in stops)
        if "\t" not in text or not has_leader:
            problems.append({"reason": "no_tab_leader", "line": text[:70]})
        if re.search(r" {3,}", text) or re.search(r"(?:\.\s*){6,}", text):
            problems.append({"reason": "hand_padding", "line": text[:70]})
        if text.count("\t") == 1 and not text.split("\t")[1].strip():
            problems.append({"reason": "missing_page", "line": text[:70]})
    if expected is not None and len(pars) != expected:
        problems.append({"reason": "entry_count", "expected": expected, "found": len(pars)})
    return problems
