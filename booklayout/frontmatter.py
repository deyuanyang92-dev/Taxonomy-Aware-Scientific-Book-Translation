"""Front-matter page typography for scanned books (title, copyright, board, author list).

OCR gives one block per visual group, lines joined by newlines.  The generic
body path unwraps them into one running paragraph, which loses the printed
structure: bold names over regular affiliations, centred title page, small
copyright text.  `BookMeta.front_pages` lists the source pages set here; each
line becomes its own paragraph, styled by what the line is.
"""
from __future__ import annotations

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH as ALIGN

AFFIL = re.compile(
    r"^(Departamento|Department|Universidad|Universidade|Universit|Centro|Instituto|Museo|"
    r"Unidad|Servicio|Consejo|Institut)\b")
ROLE_TAIL = re.compile(r"^(.+?),\s*((?:Asesor|Secretar)[^,]*)$")
ROLE_ONLY = re.compile(r"^(Ilustradores|Evaluadores|Fotomicrograf)")
FIG_TAIL = re.compile(r"^(.+?)\s+(Figuras?\s+\d.*)$")


RUN_TOGETHER = re.compile(
    r"^[A-ZÁÉÍÓÚÑ][^,;.\d]{2,45}?\s+(?:Departamento|Department|Universidad|Universidade|Museo Nacional|Centro de|Instituto)\b")


def run_together_lines(pdf, front_pages) -> list[dict]:
    """Printed PDF lines on front pages where a name runs on into its affiliation.

    The scan sets name and affiliation on separate lines; a paragraph that merged them (the generic body path)
    prints "Name Departamento de ..." as one line.
    """
    import fitz

    bad = []
    doc = fitz.open(pdf)
    for pg in sorted(set(front_pages)):
        if pg > len(doc):
            continue
        for line in doc[pg - 1].get_text().split("\n"):
            s = line.strip()
            m = RUN_TOGETHER.match(s)
            if m and not AFFIL.match(s) and sum(w[:1].isupper() for w in m.group(0).rsplit(None, 1)[0].split()) >= 2:
                bad.append({"page": pg, "line": s[:90]})
    return bad


def _lines(text: str) -> list[str]:
    return [s.strip() for s in text.split("\n") if s.strip()]


def front_block(doc, page: int, b: dict, text: str, genera, ctx: dict) -> None:
    """Render one block of a front-matter page.  `ctx` carries per-page state."""
    from .builder import para

    role = b.get("role")
    lines = _lines(text)
    centred = ctx.get("centred", False)
    al = ALIGN.CENTER if centred else ALIGN.LEFT
    if role == "heading":
        level = int(b.get("level", 2) or 2)
        big = {1: 32, 2: 14}.get(level, 11)
        if level == 1:
            for i, s in enumerate(lines):
                para(doc, s, size=big, align=al, before=30 if i == 0 else 0, after=2 if i < len(lines) - 1 else 8,
                     line=1.05, keep=True)
        elif centred:
            para(doc, text.replace("\n", " "), size=big, align=al, before=16, after=8, keep=True)
        else:
            para(doc, text.replace("\n", " "), size=11, bold=True, align=al, before=12, after=6, keep=True)
        return
    if ctx.get("half_title") and centred:  # half-title page: a word or two, set large
        para(doc, text, size=24 if ctx.get("first") else 15, bold=not ctx.get("first"), align=al,
             before=70 if ctx.get("first") else 3, after=2)
        return
    if any(re.match(r"^Madrid \d{4}$", s) for s in lines):  # publisher block of the title page
        for i, s in enumerate(lines):
            last = re.match(r"^Madrid", s)
            para(doc, s, size=12 if last else 14, bold=not last, align=al,
                 before=22 if i == 0 else 0, after=1, line=1.1)
        return
    if centred and any(ROLE_ONLY.match(s) or ROLE_TAIL.match(s) for s in lines):
        _credits(doc, lines, al, genera)
    elif centred:
        _people(doc, lines, al, genera)
    else:
        _prose(doc, page, lines, role, genera)


def _credits(doc, lines: list[str], al, genera) -> None:
    """Small print at the foot of the board page: bold names, regular role line under them."""
    from .builder import para

    for i, s in enumerate(lines):
        m = ROLE_TAIL.match(s)
        if ROLE_ONLY.match(s):
            para(doc, s, size=8, align=al, after=3, genera=genera)
        elif m:
            para(doc, f"**{m.group(1)}**, {m.group(2)}", size=8, align=al, genera=genera)
        else:
            para(doc, s, size=8, bold=True, align=al, before=14 if i == 0 else 0, genera=genera)


def _people(doc, lines: list[str], al, genera) -> None:
    from .builder import para

    first = True
    for i, s in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if AFFIL.match(s) and i > 0:
            para(doc, s, size=9.5, align=al, after=1.5, genera=genera)
        elif nxt and AFFIL.match(nxt) and not AFFIL.match(s):
            para(doc, s, size=11.5, bold=True, align=al, before=0 if first else 5, genera=genera, keep=True)
        elif ROLE_ONLY.match(s):
            para(doc, s, size=7.8, align=al, after=3, genera=genera)
        else:
            m = ROLE_TAIL.match(s)
            if m:
                p = para(doc, f"**{m.group(1)}**, {m.group(2)}", size=7.8, align=al, genera=genera)
                p.paragraph_format.space_after = None
            else:
                para(doc, s, size=7.8, bold=True, align=al, before=2 if first else 0, genera=genera)
        first = False


def _prose(doc, page: int, lines: list[str], role: str | None, genera) -> None:
    """Copyright page and author lists: left aligned, small, one paragraph per printed line group."""
    from .builder import para

    for i, s in enumerate(lines):
        m = FIG_TAIL.match(s)
        if m:  # "Name   Figuras 1-3": bold name, plain figure list
            para(doc, f"**{m.group(1)}** {m.group(2)}", size=8.3, align=ALIGN.LEFT, after=1.5, genera=genera,
                 left=0)
        elif page == 5 and i == 0 and len(lines) > 1:
            para(doc, s, size=9, bold=True, align=ALIGN.LEFT, before=7, after=0.5, keep=True, genera=genera)
        else:
            cite = bool(re.search(r"\b(19|20)\d\d\.", s)) and page == 3
            para(doc, s, size=8.3, align=ALIGN.LEFT, left=5 if cite else 0,
                 before=0 if i else 7, after=1.5, genera=genera, line=1.05)
