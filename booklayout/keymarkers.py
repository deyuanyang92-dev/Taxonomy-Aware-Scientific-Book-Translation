"""Detect identification-key pages whose couplet markers were lost (issue #36).

A page OCRed before short boxes were kept can lose ``1.``, ``6.`` and ``—``
markers while the dot leaders survive.  Every later step then sees one long
paragraph; a gate that only compares marker sequences between versions reads
"no markers anywhere" as "consistent".  This module looks at one text alone:
leaders without markers mean something was lost.

Rules (deterministic, no model):

* ``walled_paragraph``: one paragraph holds >= 3 leader runs and fewer than
  half as many inline couplet markers.
* ``leaders_without_markers``: >= 3 paragraphs on a page contain a leader,
  but at most one paragraph starts with a couplet marker.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# >= 4 dots (spaced or not), or >= 2 ellipsis characters.  A single ellipsis
# is ordinary prose and does not count.
LEADER = re.compile(r"(?:[.．·・]\s?){4,}|(?:…\s*){2,}|⋯{2,}")
MARKER = re.compile(
    r"(?:\d{1,3}['′]?[.)．、]|[—–―•①-⑳])\s*"
)
MARKER_START = re.compile(r"^\s*" + MARKER.pattern)
MIN_LEADERS = 3


def _inline_markers(text: str) -> int:
    return len(re.findall(r"(?:^|\s)" + MARKER.pattern, text))


def check_lost_markers(pages: Mapping[Any, Iterable[str]]) -> list[dict[str, Any]]:
    """Return one finding per suspect page (and rule), page order preserved."""
    findings: list[dict[str, Any]] = []
    for page, texts in pages.items():
        paras = [t for t in texts if t and t.strip()]
        with_leader = [t for t in paras if LEADER.search(t)]
        starting = [t for t in paras if MARKER_START.match(t)]
        for t in with_leader:
            n = len(LEADER.findall(t))
            if n >= MIN_LEADERS and _inline_markers(t) * 2 < n:
                findings.append({
                    "page": page, "reason": "walled_paragraph", "leaders": n,
                    "markers": _inline_markers(t), "excerpt": t[:60],
                })
        if len(with_leader) >= MIN_LEADERS and len(starting) <= 1:
            findings.append({
                "page": page, "reason": "leaders_without_markers",
                "leaders": len(with_leader), "markers": len(starting),
                "excerpt": with_leader[0][:60],
            })
    return findings


def _is_index_page(page: Mapping[str, Any]) -> bool:
    """Alphabetical index page: ``name ..... 191, 537`` lines have leaders but no couplet markers."""
    blocks = page.get("blocks") or []
    return bool(blocks) and sum(b.get("role") == "index" for b in blocks) * 4 >= len(blocks)


def lost_marker_pages(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run the check over an aligned JSON, on the source and on the translation."""
    findings: list[dict[str, Any]] = []
    for side in ("text", "translation"):
        pages = {
            p["page"]: [b.get(side) or "" for b in p.get("blocks", [])]
            for p in data.get("pages", [])
            if not _is_index_page(p)
        }
        for f in check_lost_markers(pages):
            f["side"] = side
            findings.append(f)
    return findings
