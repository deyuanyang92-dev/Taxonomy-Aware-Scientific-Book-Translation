"""Running footer (folio) checks.

A folio line is the ruled footer: page number at the outer edge, running text at
the inner edge (even: number + right text; odd: left text + number). Errors seen
on Fauna Ibérica Vol. 25 (2026-11-25, MISTAKES H8) and caught here:

* the right-hand item sat at the Footer style's default centre tab, not flush
  with the text block;
* front pages that the source prints without a footer got one;
* page numbers ran 3 lower than the printed source numbers.

`qa_problems` checks the built PDF against the metadata; `source_baseline` reads
the footers of the scanned source from the Tesseract TSV cache (by position:
the bottom band of the page) and `compare_source` checks the PDF against it.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

TAG = re.compile(r"</?[a-z]+>")
SOURCE_BAND = 0.89  # source scan: footer words start below this fraction of the page height
OUTPUT_BAND = 0.92  # built PDF without a profile: footer words start below this fraction
FLUSH_TOL = 2.5  # pt


def _get(meta: Any, key: str, default: Any = None) -> Any:
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def plain(s: str) -> str:
    """Running text without <i> markup, folded to ASCII capitals, single-spaced."""
    s = unicodedata.normalize("NFKD", TAG.sub("", s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _number(tok: str) -> int | None:
    t = tok.strip(".,;:·-–—()[]|")
    return int(t) if t.isdigit() and 0 < len(t) <= 4 else None


def blank_pages(meta: Any, pages: list[int] | None = None) -> set[int]:
    """Output pages that must carry no footer: the first page, and every page before
    folio_first_page (front pages are own pages, so output page == source page)."""
    first = int(_get(meta, "folio_first_page", 0) or 0)
    start = int(_get(meta, "body_start_page", 1) or 1)
    if first > 1 and pages:  # source pages may have gaps (blank scans): count the pages present
        return {1} | set(range(1, sum(1 for p in pages if start <= p < first) + 1))
    return {1} | set(range(1, first - start + 1)) if first > 1 else {1}


# ---------- built PDF ----------

def front_heads(pdf: Path, meta: Any, pages: list[int], band_bottom: float) -> list[dict[str, Any]]:
    """Running heads printed on the leading front-matter pages (cover, title, copyright...), which
    carry none in the source.  Front pages are own pages, so output page k is the k-th source page."""
    import fitz

    # contents pages too: the source sets them without the book running head (Handbook, 2026-11-27)
    front = set(_get(meta, "front_pages", []) or []) | set(_get(meta, "toc_pages", []) or [])
    start = int(_get(meta, "body_start_page", 1) or 1)
    lead = 0
    for p in sorted(x for x in pages if x >= start):
        if p not in front:
            break
        lead += 1
    out: list[dict[str, Any]] = []
    with fitz.open(str(pdf)) as doc:
        for i in range(min(lead, len(doc))):
            words = [w[4] for w in doc[i].get_text("words") if w[3] <= band_bottom]
            if words:
                out.append({"page": i + 1, "kind": "running_head_on_front_page", "found": " ".join(words)[:60]})
    return out


def output_footers(pdf: Path, band_top: float | None = None) -> tuple[list[dict[str, Any]], int, float, float]:
    """Footer line of every page, the page count and the text block's left/right edges (pt).

    band_top: y (pt from top) where the footer band begins; default OUTPUT_BAND of the height.
    """
    import fitz

    feet: list[dict[str, Any]] = []
    lefts: list[float] = []
    rights: list[float] = []
    with fitz.open(str(pdf)) as doc:
        n = len(doc)
        for i, page in enumerate(doc, 1):
            top = band_top if band_top is not None else page.rect.height * OUTPUT_BAND
            words = page.get_text("words")
            body = [w for w in words if w[1] < top]
            foot = sorted((w for w in words if w[1] >= top), key=lambda w: w[0])
            if len(body) >= 40:
                lefts.append(min(w[0] for w in body))
                rights.append(max(w[2] for w in body))
            if not foot:
                continue
            nums = [(_number(w[4]), w) for w in (foot[0], foot[-1])]
            num = next((v for v, _ in nums if v is not None), None)
            text = " ".join(w[4] for w in foot if _number(w[4]) is None or w not in (foot[0], foot[-1]))
            feet.append({"page": i, "number": num, "text": text,
                         "x0": round(foot[0][0], 1), "x1": round(foot[-1][2], 1)})
    left = median(lefts) if lefts else 0.0
    right = median(rights) if rights else 0.0
    return feet, n, left, right


def expected_text(meta: Any, number: int) -> str:
    """The builder prints running_left on odd pages and running_right on even pages."""
    return plain(_get(meta, "running_left" if number % 2 else "running_right", ""))


def qa_problems(feet: list[dict[str, Any]], n_pages: int, left: float, right: float,
                meta: Any, pages: list[int] | None = None) -> list[dict[str, Any]]:
    """Footer problems the metadata alone can detect: presence, number, text, flush edges."""
    start = int(_get(meta, "folio_start", 1) or 1)
    blank = blank_pages(meta, pages)
    by_page = {f["page"]: f for f in feet}
    out: list[dict[str, Any]] = []
    for pg in range(1, n_pages + 1):
        f = by_page.get(pg)
        if pg in blank:
            if f:
                out.append({"page": pg, "kind": "footer_on_front_page", "found": f["text"] or f["number"]})
            continue
        if not f:
            out.append({"page": pg, "kind": "missing_footer"})
            continue
        want = pg + start - 1
        if f["number"] != want:
            out.append({"page": pg, "kind": "wrong_folio", "found": f["number"], "expected": want})
        exp = expected_text(meta, want)
        if exp and plain(f["text"]) != exp:
            out.append({"page": pg, "kind": "wrong_running_text", "found": f["text"], "expected": exp})
        if left and right and (abs(f["x0"] - left) > FLUSH_TOL or abs(f["x1"] - right) > FLUSH_TOL):
            out.append({"page": pg, "kind": "footer_not_flush", "x0": f["x0"], "x1": f["x1"],
                        "text_block": [round(left, 1), round(right, 1)]})
    return out


def lo_parity_copy(docx: Path, tmpdir: Path) -> Path | None:
    """A copy of docx for LibreOffice whose odd/even footer references are swapped, or None.

    Word picks the odd or even footer by the printed page number; LibreOffice picks it by
    the physical page.  When the first page is numbered even (Vol. 25: pdf page 1 prints 4),
    the two disagree and LibreOffice printed every footer on the wrong side (2026-11-25,
    verified by rendering the same docx in MS Word).  The docx stays right for Word; the PDF
    is made from this copy.  qa's wrong_running_text check still guards the result.
    """
    import zipfile

    with zipfile.ZipFile(docx) as z:
        names = z.namelist()
        settings = z.read("word/settings.xml").decode("utf-8") if "word/settings.xml" in names else ""
        body = z.read("word/document.xml").decode("utf-8")
        if "w:evenAndOddHeaders" not in settings or 'w:val="false"' in settings.split("w:evenAndOddHeaders", 1)[1][:30]:
            return None
        m = re.search(r'<w:pgNumType\b[^>]*\bw:start="(\d+)"', body)
        if not m or int(m.group(1)) % 2:
            return None
        swapped = re.sub(r'(<w:(?:footer|header)Reference\b[^>]*\bw:type=")(default|even)"',
                         lambda x: x.group(1) + ("even" if x.group(2) == "default" else "default") + '"', body)
        out = Path(tmpdir) / Path(docx).name
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
            for n in names:
                w.writestr(n, swapped if n == "word/document.xml" else z.read(n))
    return out


def summarize(problems: list[dict[str, Any]]) -> str:
    kinds = Counter(p["kind"] for p in problems)
    first: dict[str, int] = {}
    for p in problems:
        first.setdefault(p["kind"], p["page"])
    return "; ".join(f"{k} x{v} (first page {first[k]})" for k, v in kinds.items())


# ---------- scanned source ----------

def _lev1(a: str, b: str) -> bool:
    """True when a and b differ by at most one edit (OCR: I/1/l, dropped accent)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return any(t[:i] + t[i + 1:] == s for i in range(len(t)))


def _matches(head: str, toks: list[str]) -> bool:
    """At least half of the running text's words (3+ letters) appear among the band tokens."""
    words = [w for w in plain(head).split() if len(w) >= 3]
    if not words:
        return False
    folded = [plain(t) for t in toks]
    hit = sum(any(_lev1(w, t) for t in folded) for w in words)
    return hit * 2 >= len(words)


def source_footer(tsv: Path, page: int, meta: Any) -> dict[str, Any]:
    """Footer of one scanned page from its Tesseract TSV: running text side and printed number."""
    rows = [r.split("\t") for r in tsv.read_text(encoding="utf-8").splitlines()[1:]]
    width = height = 0
    toks: list[tuple[int, int, int, str]] = []
    for r in rows:
        if len(r) < 12:
            continue
        if r[0] == "1":
            width, height = int(r[8]), int(r[9])
        elif r[0] == "5" and r[11].strip():
            toks.append((int(r[6]), int(r[6]) + int(r[8]), int(r[7]), r[11].strip()))
    band = [t for t in toks if height and t[2] > height * SOURCE_BAND]
    words = [t[3] for t in band]
    num = None
    for x0, x1, _y, w in band:
        v = _number(w)
        if v is not None and (x0 < width * 0.2 or x1 > width * 0.8):  # outer edge only, not "POLYCHAETA 1"
            num = v
    side = None
    if _matches(_get(meta, "running_left", ""), words):
        side = "left"
    elif _matches(_get(meta, "running_right", ""), words):
        side = "right"
    return {"page": page, "number": num, "side": side, "has_footer": bool(num is not None or side)}


def source_baseline(tsvs: dict[int, Path], meta: Any) -> dict[str, Any]:
    feet = [source_footer(t, p, meta) for p, t in sorted(tsvs.items())]
    offs = Counter(f["number"] - f["page"] for f in feet if f["number"] is not None)
    offset, votes = offs.most_common(1)[0] if offs else (None, 0)
    parity: Counter[tuple[int, str]] = Counter()
    if offset is not None:
        for f in feet:
            if f["side"]:
                parity[((f["page"] + offset) % 2, f["side"])] += 1
    odd = max(("left", "right"), key=lambda s: parity[(1, s)] + parity[(0, "right" if s == "left" else "left")])
    return {"offset": offset if votes >= 2 else None, "offset_votes": votes,
            "odd_side": odd if parity else None,
            "no_footer": [f["page"] for f in feet if not f["has_footer"]], "pages": feet}


def compare_source(base: dict[str, Any], feet: list[dict[str, Any]], n_pages: int,
                   meta: Any) -> list[dict[str, Any]]:
    """The built PDF against the source footers: numbering offset, which text goes on odd
    pages, and which leading own pages print without a footer."""
    out: list[dict[str, Any]] = []
    by_page = {f["page"]: f for f in feet}
    # output page 1 is the first checked source page; the leading own pages map page for page
    start = min((p["page"] for p in base.get("pages", [])), default=1)
    if base.get("offset") is not None:
        bad = [f for f in feet if f["number"] is not None and f["number"] - f["page"] != base["offset"] + start - 1]
        if bad:
            f = bad[0]
            out.append({"page": f["page"], "kind": "folio_differs_from_source", "found": f["number"],
                        "expected": f["page"] + base["offset"] + start - 1, "pages": len(bad)})
    if base.get("odd_side"):
        want = plain(_get(meta, "running_" + base["odd_side"], ""))
        odd = [f for f in feet if f["number"] and f["number"] % 2 and plain(f["text"]) != want]
        if odd:
            out.append({"page": odd[0]["page"], "kind": "odd_text_differs_from_source",
                        "found": odd[0]["text"], "expected": want, "pages": len(odd)})
    own = set(_get(meta, "own_pages", []) or []) | set(_get(meta, "image_pages", []) or [])
    no_src = set(base.get("no_footer", []))
    for s in sorted(p["page"] for p in base.get("pages", [])):
        if s not in own:
            break  # past the leading own pages the output no longer maps page for page
        o = s - start + 1
        if o < 1 or o > n_pages:
            continue
        if s in no_src and o in by_page and o != 1:
            out.append({"page": o, "kind": "footer_not_in_source", "source_page": s})
        elif s not in no_src and o not in by_page:
            out.append({"page": o, "kind": "footer_missing_vs_source", "source_page": s})
    return out
