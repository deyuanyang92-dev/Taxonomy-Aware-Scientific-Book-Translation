"""Running headers and folios: detect, strip, keep as provenance (issue #15).

Running furniture is the page header/footer printed on every (or every other)
page of the source.  It is not part of the text: if it stays, it lands in the
middle of a sentence that continues over the page break.

Detection uses *position* and *repetition* together, so legitimate body text
that happens to equal a header is never removed:

* a line is a candidate only when it sits in the top/bottom band of the page
  (original coordinates ``y0``/``y1`` against ``height``), or, without
  coordinates, is one of the first/last ``edge_lines`` lines of the page;
* its signature (digits -> ``#``, spaces collapsed) must repeat on at least
  ``min_repeat`` pages.  Alternating left/right headers repeat on every other
  page and are found the same way; a bare folio has signature ``#``;
* ``known_headers`` lists extra phrases (other languages) that count as
  furniture at an edge even with fewer repeats.

Input pages: ``{"page": n, "height": H?, "lines": [{"text", "y0"?, "y1"?}]}``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

_ROMAN = re.compile(r"^[ivxlcdm]{1,7}$", re.I)
MAX_FURNITURE_CHARS = 100
_TERMINAL = re.compile(r"""[.!?…:;]["')\]”’]*$""")


def signature(text: str) -> str:
    t = unicodedata.normalize("NFC", text).strip()
    if t.isdigit() or (_ROMAN.match(t) and len(t) <= 4 and t.lower() == t):
        return "#"
    t = re.sub(r"\d+", "#", t)
    return re.sub(r"\s+", " ", t)


def _phrase(sig: str) -> str:
    return re.sub(r"\s*#\s*", " ", sig).strip(" .,;:-–—")


@dataclass
class FurnitureReport:
    signatures: dict[str, int] = field(default_factory=dict)
    phrases: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    band: float = 0.1
    edge_lines: int = 2


def _edge_kind(line: dict, index: int, n: int, height: float | None, band: float,
               edge_lines: int) -> str | None:
    if height and line.get("y0") is not None and line.get("y1") is not None:
        if line["y1"] <= band * height:
            return "header"
        if line["y0"] >= (1 - band) * height:
            return "footer"
        return None
    if index < edge_lines:
        return "header"
    if index >= n - edge_lines:
        return "footer"
    return None


def _candidates(page: dict, band: float, edge_lines: int):
    lines = page.get("lines", [])
    for i, line in enumerate(lines):
        text = (line.get("text") or "").strip()
        if not text or len(text) > MAX_FURNITURE_CHARS:
            continue
        kind = _edge_kind(line, i, len(lines), page.get("height"), band, edge_lines)
        if kind:
            yield i, line, kind, text


def detect_furniture(pages: Sequence[dict], min_repeat: int = 3,
                     known_headers: Iterable[str] = (), band: float = 0.1,
                     edge_lines: int = 2) -> FurnitureReport:
    known = [k for k in known_headers if k]
    seen: dict[str, set] = {}
    for page in pages:
        for _i, _line, _kind, text in _candidates(page, band, edge_lines):
            seen.setdefault(signature(text), set()).add(page.get("page"))
    sigs = {s: len(p) for s, p in seen.items() if len(p) >= min_repeat}
    for page in pages:
        for _i, _line, _kind, text in _candidates(page, band, edge_lines):
            if any(k.casefold() in text.casefold() for k in known):
                sigs.setdefault(signature(text), len(seen[signature(text)]))
    phrases = sorted({p for p in (_phrase(s) for s in sigs) if p} | set(known))
    return FurnitureReport(signatures=sigs, phrases=phrases, known=known, band=band,
                           edge_lines=edge_lines)


def strip_furniture(pages: Sequence[dict], report: FurnitureReport):
    """Return (clean pages, provenance {page: [{text, kind, signature}]})."""
    clean: list[dict] = []
    provenance: dict[Any, list[dict]] = {}
    for page in pages:
        drop: dict[int, str] = {}
        for i, _line, kind, text in _candidates(page, report.band, report.edge_lines):
            sig = signature(text)
            if sig in report.signatures:
                drop[i] = "folio" if sig == "#" else kind
        out = dict(page)
        out["lines"] = [ln for i, ln in enumerate(page.get("lines", [])) if i not in drop]
        clean.append(out)
        if drop:
            provenance[page.get("page")] = [
                {"text": page["lines"][i]["text"], "kind": k,
                 "signature": signature(page["lines"][i]["text"])}
                for i, k in sorted(drop.items())
            ]
    return clean, provenance


def body_stream(pages: Sequence[dict]) -> list[str]:
    """Join the remaining lines into paragraphs; a sentence that continues
    over a page break is joined, a finished sentence followed by a capital
    starts a new paragraph."""
    paras: list[str] = []
    for page in pages:
        for line in page.get("lines", []):
            text = (line.get("text") or "").strip()
            if not text:
                continue
            if paras:
                prev = paras[-1]
                if prev.endswith("-") and text[:1].islower():
                    paras[-1] = prev[:-1] + text
                    continue
                if not _TERMINAL.search(prev) or text[:1].islower():
                    paras[-1] = prev + " " + text
                    continue
            paras.append(text)
    return paras


def check_body_paragraphs(paragraphs: Iterable[str], report: FurnitureReport,
                          allow_phrases: Iterable[str] = ()) -> list[dict]:
    """Rendered body paragraphs must contain no running-header tokens.

    The match is exact-case: a header is printed in its own casing
    ("FAUNA IBÉRICA"), while the same words in a sentence ("Fauna Ibérica
    project") are legitimate text and stay.  ``allow_phrases`` lists further
    exceptions.
    """
    allowed = set(allow_phrases)
    problems: list[dict] = []
    for i, text in enumerate(paragraphs):
        for phrase in report.phrases:
            if phrase in allowed or len(phrase) < 4:
                continue
            if phrase in text:
                problems.append({"paragraph": i, "phrase": phrase, "excerpt": text[:80]})
    return problems


FURNITURE_ROLES = {"header", "footer", "furniture", "folio"}


def aligned_furniture_blocks(data: dict, min_repeat: int = 3) -> list[dict]:
    """Aligned-JSON blocks that are running furniture but carry a body role.

    Lines are the source texts of each page's blocks in vertical order.  A
    block flagged here would be rendered into the translated body; blocks
    already given a furniture role are provenance and are not reported.
    """
    pages = []
    for page in data.get("pages", []):
        blocks = sorted(page.get("blocks", []), key=lambda b: b.get("y0") or 0)
        pages.append({
            "page": page.get("page"), "height": page.get("height"),
            "lines": [{"text": b.get("text") or "", "y0": b.get("y0"),
                       "y1": b.get("y1", b.get("y0")), "_block": b} for b in blocks],
        })
    report = detect_furniture(pages, min_repeat=min_repeat, edge_lines=1)
    found: list[dict] = []
    for page in pages:
        for i, line, _kind, text in _candidates(page, report.band, report.edge_lines):
            block = line["_block"]
            if block.get("role") in FURNITURE_ROLES:
                continue
            if signature(text) in report.signatures and (block.get("translation") or "").strip():
                found.append({"page": page["page"], "block_id": block.get("block_id"), "text": text,
                              "index": i})
    return found
