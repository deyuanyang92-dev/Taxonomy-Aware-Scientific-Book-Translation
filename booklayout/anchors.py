"""Structure anchors for native PDFs: outline page numbers, printed contents, number depth, font ladder.

Priority (docs/research/2026-11-27_结构提取_cursor调研.md): (1) the PDF outline is trusted for its PAGE numbers only
(titles are often ids, levels all 1); (2) printed contents entries are matched in order to the headings found in
the body and give their level (toc_level + 1); (3) headings without a contents entry take the level that the
other headings of the same font style got; (4) the font ladder fills the rest.  A heading whose number depth
disagrees with the contents is left alone and the disagreement is recorded, never silently overwritten.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

MAX_LEVEL = 6
WINDOW_NUMBERED = 400     # a numbered heading may match a contents entry this far ahead
WINDOW_PLAIN = 12         # an unnumbered one ("Introduction") only this far, or repeated titles would jump
_LEAD_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
_EYEBROW = re.compile(r"^(chapter|part|appendix|section)\s+(\d+|[ivxlc]+)\.?$", re.I)
_NONLET = re.compile(r"[\W\d_]+")


def _number(text: str) -> str | None:
    m = _LEAD_NUM.match(text)
    return m.group(1) if m else None


def _key(text: str) -> str:
    t = _LEAD_NUM.sub("", re.sub(r"[\x00-\x1f\x7f]+", " ", text))
    return _NONLET.sub("", t.lower())


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 6 and (long_.startswith(short) or long_.endswith(short)):
        return True       # a wrapped or truncated heading line
    return len(short) >= 8 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def match_headings(toc: list[tuple[str, int]], heads: list[tuple[Any, ...]]) -> list[int | None]:
    """For every heading (text first) the index of its contents entry, or None.  Order-preserving."""
    out: list[int | None] = []
    ptr = 0
    for h in heads:
        text = h[0]
        k, num = _key(text), _number(text)
        found = None
        win = WINDOW_NUMBERED if num else WINDOW_PLAIN
        for j in range(ptr, min(len(toc), ptr + win)):
            etext = toc[j][0]
            if num and _number(etext) not in (None, num):
                continue
            if _same(k, _key(etext)) and (not num or _number(etext) == num or _number(etext) is None):
                found = j
                break
        if found is not None:
            ptr = found + 1
        out.append(found)
    return out


def _style_key(b: dict) -> tuple:
    f = b.get("font", {})
    return (f.get("family"), round(f.get("size", 0), 1), f.get("bold"), f.get("italic"))


def apply_anchors(pages: list[dict], outline: list[tuple[int, str, int]]) -> dict:
    """Set heading levels from the printed contents and the `chapter` field from outline page anchors (in place)."""
    toc = [(b["text"], int(b.get("toc_level", 0))) for pg in pages if pg.get("kind") == "toc"
           for b in pg["blocks"] if b["role"] == "toc_entry"]
    report: dict = {"toc_entries": len(toc), "matched": 0, "propagated": 0, "conflicts": [], "chapter_anchors": []}
    heads = [(pg, b) for pg in pages if pg.get("kind") != "toc" for b in pg["blocks"]
             if b["role"] == "heading" and not _EYEBROW.match(b["text"])]
    if toc and heads:
        idx = match_headings(toc, [(b["text"],) for _pg, b in heads])
        by_style: dict[tuple, set[int]] = {}
        # numbered headings were levelled by number depth relative to the shallowest heading met; when the
        # sample lacks the top rung (7.4.x without "7") every one is off by the same constant.  That is a
        # missing context, not a conflict: follow the contents.  Outliers are recorded.
        deltas = [min(toc[j][1] + 1, MAX_LEVEL) - b["level"] for (_pg, b), j in zip(heads, idx)
                  if j is not None and b.get("level_source") == "number"]
        shift = 0
        if len(deltas) >= 2:
            d0 = max(set(deltas), key=deltas.count)
            if d0 != 0 and deltas.count(d0) >= 0.6 * len(deltas):
                shift = d0
        for (pg, b), j in zip(heads, idx):
            if j is None:
                continue
            report["matched"] += 1
            want = min(toc[j][1] + 1, MAX_LEVEL)
            etext = toc[j][0]
            if b.get("level_source") == "number":
                if shift and want - b["level"] == shift:
                    b.setdefault("level_font", b["level"])
                    b["level"], b["style"] = want, f"Heading {want}"
                elif b["level"] != want:
                    report["conflicts"].append({"page": pg["page"], "text": b["text"], "level": b["level"],
                                                "toc_level": want, "toc_title": etext})
                continue
            if len(_key(etext)) > len(_key(b["text"])) and _key(etext).endswith(_key(b["text"])) \
                    and _number(etext) and not _number(b["text"]):
                b["text"] = re.sub(r"\s+", " ", etext).strip()   # wrapped heading: the first line was lost
            b.setdefault("level_font", b["level"])
            b["level"], b["style"], b["level_anchor"] = want, f"Heading {want}", "toc"
            by_style.setdefault(_style_key(b), set()).add(want)
        matched_n: dict[tuple, int] = {}
        for (_pg, b), j in zip(heads, idx):
            if j is not None:
                matched_n[_style_key(b)] = matched_n.get(_style_key(b), 0) + 1
        for (pg, b), j in zip(heads, idx):
            ks = _style_key(b)
            if j is None and b.get("level_source") != "number" and len(by_style.get(ks, ())) == 1 \
                    and matched_n.get(ks, 0) >= 2:
                want = next(iter(by_style[ks]))
                if b["level"] != want:
                    b.setdefault("level_font", b["level"])
                    b["level"], b["style"] = want, f"Heading {want}"
                    report["propagated"] += 1
    nums = {pg["page"] for pg in pages}
    starts = sorted({p for _lv, _t, p in outline if p in nums})
    if len(starts) >= 2 or (starts and len(pages) > 1):
        by_page = {pg["page"]: pg for pg in pages}
        for p in starts:
            pg = by_page[p]
            hs = [b for b in pg["blocks"] if b["role"] == "heading" and not _EYEBROW.match(b["text"])
                  and pg.get("kind") != "toc"]
            if hs:
                best = min(hs, key=lambda b: b["level"])
                report["chapter_anchors"].append({"page": p, "title": best["text"]})
        anchors = report["chapter_anchors"]
        for pg in pages:
            cur = [a for a in anchors if a["page"] <= pg["page"]]
            if cur and pg.get("kind") != "toc":
                pg["chapter"] = cur[-1]["title"]
    return report
