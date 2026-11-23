"""Rendered identification-key check: the seven layout rules, measured on the PDF.

Why (2026-11-23): key layout was judged by eye and by tuned millimetre
constants (a self-made "leader >= 40 mm" rule), and the basic format was never
written down.  The user had to point out each defect.  These are the format
rules of a dichotomous key as set in the Imajima originals and Chinese keys;
every defect found so far maps to one of them.

  KR1 columns   marker column, text column, address column; the text of every
                lead starts at one x, whatever the marker ("1.", "10.", "—").
                (history: "1. " text at x=86, "— " at x=90, wraps at x=96, because
                clean_text turned the marker tab into a space)
  KR2 wrap      wrapped lines start at the text column, not at the marker.
  KR3 leader    the dots follow the text directly; a line that wraps on to a
                leader line is filled with dots to the margin, no blank tail.
                (history: 40 mm rule forced a break and left the tail blank)
  KR4 address   the address ends at the right margin and is not split across
                lines.  (history: "Aphrodita3" glued, "L. / torquata" split)
  KR5 complete  every lead ends with dots + address; no dots without an address.
  KR6 type      taxon names in the address italic (authors, family and subfamily
                names roman); a number stays on the line of its measure word.
                (history: "M. fragilis" roman; "13 / 对" split)
  KR7 pairs     the two leads of a couplet are on one page; no lead breaks
                across a page.

Usage:
    python3 -m booklayout.keyrender book.pdf [--pages 3-4] [--report r.json]
    exit 1 when any rule fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GLUE = chr(0x202F)
TOL = 1.5  # pt: rendering jitter allowed in an alignment
MARKER = re.compile(r"^(?:\d{1,3}[.．]|[—•])$")
LEADER = re.compile(r"^[.·…\s]{3,}$")
HAN = re.compile(f"[{chr(0x3400)}-{chr(0x9FFF)}]")
RULES = {
    "KR1": "text column: every lead's text starts at the same x",
    "KR2": "wrapped lines start at the text column",
    "KR3": "dots follow the text; no blank tail before a leader line",
    "KR4": "address flush right and on one line",
    "KR5": "every lead ends with dots + address",
    "KR6": "taxon names italic; number not split from its measure word",
    "KR7": "a couplet's two leads on one page",
}


@dataclass
class Span:
    text: str
    x0: float
    x1: float
    italic: bool
    size: float
    chars: list[tuple[str, float, float]] = field(default_factory=list)

    @property
    def leader(self) -> bool:
        return bool(LEADER.match(self.text)) and any(c in self.text for c in ".·…")


@dataclass
class Row:
    page: int
    y: float
    spans: list[Span]

    @property
    def x0(self) -> float:
        return self.spans[0].x0

    @property
    def x1(self) -> float:
        return self.spans[-1].x1

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


@dataclass
class Lead:
    rows: list[Row]
    marker: str
    text_x: float  # x where the lead's text starts on its first row

    @property
    def page(self) -> int:
        return self.rows[0].page


def rows_of(page: Any, number: int) -> list[Row]:
    """Visual rows (same baseline) of a PyMuPDF page, spans with char boxes."""
    by_y: dict[float, list[Span]] = {}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                chars = [(c["c"], c["bbox"][0], c["bbox"][2]) for c in s["chars"]]
                text = "".join(c[0] for c in chars)
                if not text.strip():
                    continue
                y = round(s["origin"][1])
                ital, size = bool(s["flags"] & 2), round(s["size"], 1)
                by_y.setdefault(y, []).extend(_split_leader(chars, ital, size))
    rows = []
    for y in sorted(by_y):
        spans = sorted(by_y[y], key=lambda s: s.x0)
        rows.append(Row(number, y, spans))
    return rows


def _split_leader(chars: list[tuple[str, float, float]], italic: bool, size: float) -> list[Span]:
    """Cut a PDF span at runs of leader dots, so dots, text and address are separate spans."""
    text = "".join(c[0] for c in chars)
    out: list[Span] = []
    pos = 0
    for m in re.finditer(r"[.·…]{3,}", text):
        for a, b in ((pos, m.start()), (m.start(), m.end())):
            if text[a:b].strip():
                part = chars[a:b]
                out.append(Span(text[a:b], part[0][1], part[-1][2], italic, size, part))
        pos = m.end()
    if text[pos:].strip():
        part = chars[pos:]
        out.append(Span(text[pos:], part[0][1], part[-1][2], italic, size, part))
    return out


def _marker_of(row: Row) -> tuple[str, float] | None:
    """(marker, x where the text starts) when the row opens a lead."""
    first = row.spans[0].text.strip()
    head = first.split()[0] if first.split() else ""
    if not MARKER.match(head):
        return None
    span = row.spans[0]
    rest = span.text.strip()[len(head):]
    if rest.strip():  # text in the same span: start of the first char after the marker and spaces
        idx = len(span.text) - len(span.text.lstrip()) + len(head)
        while idx < len(span.chars) and not span.chars[idx][0].strip():
            idx += 1
        return head, span.chars[idx][1] if idx < len(span.chars) else span.x1
    nxt = row.spans[1] if len(row.spans) > 1 else None
    return head, nxt.x0 if nxt else span.x1


def leads_of(rows: list[Row]) -> list[Lead]:
    """Group rows into leads; a key needs body-size rows that open with markers."""
    sizes = Counter(r.spans[0].size for r in rows if _marker_of(r))
    if sum(sizes.values()) < 2:
        return []
    body = sizes.most_common(1)[0][0]
    leads: list[Lead] = []
    cur: Lead | None = None
    for r in rows:
        m = _marker_of(r)
        same = abs(r.spans[0].size - body) < 0.3
        if m and same:
            cur = Lead([r], m[0], m[1])
            leads.append(cur)
        elif cur and same and r.x0 > cur.rows[0].x0 + TOL and not cur_closed(cur):
            cur.rows.append(r)
        else:
            cur = None
    return leads


def cur_closed(lead: Lead) -> bool:
    """A lead is closed once a row ends with an address after dots."""
    last = lead.rows[-1]
    return any(s.leader for s in last.spans) and not last.spans[-1].leader


def _address(lead: Lead) -> list[Span]:
    last = lead.rows[-1].spans
    idx = max((i for i, s in enumerate(last) if s.leader), default=-1)
    return last[idx + 1:] if idx >= 0 else []


def _plain(spans: list[Span]) -> tuple[str, list[bool], list[tuple[float, float]]]:
    text, ital, boxes = "", [], []
    for s in spans:
        for c, x0, x1 in s.chars:
            text += c
            ital.append(s.italic)
            boxes.append((x0, x1))
    return text, ital, boxes


def check_page_leads(leads: list[Lead], right: float) -> list[dict]:
    from .builder import italicize_key_address  # one rule for builder and check

    out: list[dict] = []

    def bad(rule: str, lead: Lead, detail: str) -> None:
        out.append({"rule": rule, "page": lead.page + 1, "lead": (lead.marker + " " + lead.rows[0].text)[:60],
                    "detail": detail})

    if not leads:
        return out
    col = Counter(round(ld.text_x) for ld in leads).most_common(1)[0][0]
    for ld in leads:
        if abs(ld.text_x - col) > TOL:
            bad("KR1", ld, f"text starts at x={ld.text_x:.1f}, column at x={col}")
        for r in ld.rows[1:]:
            if abs(r.x0 - ld.text_x) > TOL and abs(r.x0 - col) > TOL:
                bad("KR2", ld, f"wrapped line starts at x={r.x0:.1f}, text column x={col}")
        addr = _address(ld)
        last = ld.rows[-1]
        if not addr:
            bad("KR5", ld, "lead has no dots + address" if not last.spans[-1].leader else "dots without address")
            continue
        if abs(last.x1 - right) > TOL:
            bad("KR4", ld, f"address ends at x={last.x1:.1f}, margin x={right:.1f}")
        for a, b in zip(ld.rows, ld.rows[1:]):
            if b.spans[0].leader and not a.spans[-1].leader and right - a.x1 > 3 * 72 / 25.4:
                bad("KR3", ld, f"blank tail of {(right - a.x1) * 25.4 / 72:.1f} mm before the leader line")
            ta, tb = a.text.rstrip(" " + GLUE), b.text.lstrip()
            if ta[-1:].isdigit() and HAN.match(tb[:1]):
                bad("KR6", ld, f"number split from its measure word: '{ta[-6:]} / {tb[:4]}'")
            if re.search(r"(?:^|\s)[A-Z][a-z]*\.?$", ta) and re.match(r"[a-z]", tb) and not b.spans[0].leader:
                bad("KR4", ld, f"address split across lines: '{ta[-12:]} / {tb[:12]}'")
        text, ital, boxes = _plain(addr)
        flat = text.replace(GLUE, " ")
        if re.search(r"[A-Za-z][0-9]", flat):
            bad("KR4", ld, f"address words glued: '{flat.strip()}'")
        if flat.count("（") != flat.count("）") or flat.count("(") != flat.count(")"):
            bad("KR4", ld, f"unpaired brackets in address: '{flat.strip()}'")
        for i, ch in enumerate(text):
            if ch in (" ", GLUE) and 0 < i < len(text) - 1 and text[i - 1].strip() and text[i + 1].strip():
                if boxes[i + 1][0] - boxes[i - 1][1] < 0.15 * addr[0].size:
                    bad("KR4", ld, f"space in address renders near zero: '{flat.strip()}'")
                    break
        lead_off = len(flat) - len(flat.lstrip())
        want = italicize_key_address(flat.strip())
        m = re.match(r"\*([^*]+)\*", want)
        if m:
            seg = range(lead_off, lead_off + len(m.group(1)))
            if not all(ital[i] for i in seg if flat[i].strip()):
                bad("KR6", ld, f"taxon name not italic: '{m.group(1)}'")
    return out


def check_pdf(pdf: Path, pages: range | None = None, stats: dict[str, int] | None = None) -> list[dict]:
    """Findings of every page; `stats` (if given) receives the recognised branch/page totals."""
    import fitz

    if stats is not None:
        stats.update({"branches": 0, "pages_with_keys": 0})
    doc = fitz.open(pdf)
    findings: list[dict] = []
    prev: Lead | None = None
    for n in pages or range(doc.page_count):
        if n >= doc.page_count:
            break
        leads = leads_of(rows_of(doc[n], n))
        if not leads:
            prev = None
            continue
        if stats is not None:
            stats["branches"] += len(leads)
            stats["pages_with_keys"] += 1
        right = max(ld.rows[-1].x1 for ld in leads)
        findings += check_page_leads(leads, right)
        first = leads[0]
        if prev is not None and first.marker == "—" and prev.marker != "—":
            findings.append({"rule": "KR7", "page": n + 1, "lead": first.rows[0].text[:60],
                             "detail": f"couplet {prev.marker} split over pages {n} and {n + 1}"})
        prev = leads[-1]
    return findings


def _pages(spec: str | None) -> range | None:
    if not spec:
        return None
    a, _, b = spec.partition("-")
    return range(int(a) - 1, int(b or a))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m booklayout.keyrender", description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", help="1-based range, e.g. 3-4")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    stats: dict[str, int] = {}
    found = check_pdf(args.pdf, _pages(args.pages), stats)
    summary = {rule: sum(f["rule"] == rule for f in found) for rule in RULES}
    if args.report:
        args.report.write_text(json.dumps({"rules": RULES, "summary": summary, "findings": found,
                                           "branches": stats["branches"],
                                           "pages_with_keys": stats["pages_with_keys"]},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    for rule, text in RULES.items():
        print(f"{rule} {'OK ' if not summary[rule] else 'FAIL'} {summary[rule]:3d}  {text}")
    for f in found[:40]:
        print(f"  p{f['page']} {f['rule']} {f['detail']} | {f['lead']}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
