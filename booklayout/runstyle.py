"""Generic gate: a run of same-kind short lines must print in one style.

Added 2026-11-25 (generalises taxonlist.pdf_list_style_mismatches, Vol. 21 p. 35).
A run = >= MIN_RUN consecutive short lines with the same left edge (+-1.5 pt) and an
even line pitch (+-20 %), page furniture skipped, may cross pages.  Inside a run
every line must share the dominant font size (rounded to 0.5 pt); head and tail lines
that differ are neighbouring headings and are ignored.  Bold is judged by the
taxon gate only: contents / reference lists legitimately bold a lead-in.
"""
from __future__ import annotations

import re

MIN_RUN = 6
MAX_CHARS = 110

_CAPTION = re.compile(r"^(?:图|表|Fig(?:ura|ure)?s?\.?|Tab(?:la|le)?\.?|L[aá]m(?:ina)?\.?|Plate)\s*\d", re.I)


def _lines(pdf: str):
    import fitz

    with fitz.open(pdf) as doc:
        for pno, page in enumerate(doc, 1):
            h = page.rect.height
            for blk in page.get_text("dict")["blocks"]:
                for ln in blk.get("lines", []):
                    x0, y0, x1, y1 = ln["bbox"]
                    if y0 < 0.07 * h or y1 > 0.93 * h:
                        continue
                    spans = [s for s in ln["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    size = round(max(s["size"] for s in spans) * 2) / 2
                    yield pno, text, x0, y0, y1, size


def run_style_mismatches(pdf: str, min_run: int = MIN_RUN) -> list[dict]:
    out: list[dict] = []
    run: list[tuple] = []

    def flush() -> None:
        if len(run) >= min_run:
            sizes: dict[float, int] = {}
            for r in run:
                sizes[r[5]] = sizes.get(r[5], 0) + 1
            major = max(sizes, key=lambda s: sizes[s])
            idx = [k for k, r in enumerate(run) if r[5] == major]
            odd = [r for r in run[idx[0]:idx[-1] + 1] if r[5] != major]
            if odd and sizes[major] >= min_run - 1:
                out.append({"first_page": run[0][0], "lines": len(run), "majority_size": major,
                            "odd": [{"page": r[0], "size": r[5], "text": r[1][:60]} for r in odd[:8]]})
        run.clear()

    for ln in _lines(pdf):
        pno, text, x0, y0, y1, size = ln
        if (len(text) > MAX_CHARS or text.endswith((".", ":", "。")) and len(text) > 60
                or _CAPTION.match(text)):
            flush()
            continue
        if run:
            p = run[-1]
            pitch = y1 - p[4] if pno == p[0] else None
            ok = abs(x0 - p[2]) <= 1.5 and (pno != p[0] or 0 < y0 - p[3] < 2.2 * (p[4] - p[3]))
            if ok and pitch is not None and len(run) >= 2:
                prev_pitch = p[4] - run[-2][4] if run[-2][0] == p[0] else None
                if prev_pitch and abs(pitch - prev_pitch) > 0.2 * prev_pitch + 1.5:
                    ok = False
            if not ok:
                flush()
        run.append(ln)
    flush()
    return out
