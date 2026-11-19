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
