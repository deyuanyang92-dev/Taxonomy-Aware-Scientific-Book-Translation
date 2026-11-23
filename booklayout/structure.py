"""Uncertain paragraph alignment across page boundaries (issue #16).

``normalize`` joins a sentence that continues over a page break when the
evidence is clear (previous block unfinished, next block starts lower-case).
Everything else it cannot decide is reported here so that a release stops
instead of guessing.  A reviewer clears a record by setting
``"boundary_reviewed": true`` on the first block of the boundary.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_TERMINAL = re.compile(r"""[.!?…:;]["')\]”’]*$""")
SINGLE_BLOCK_CHARS = 1800


def _flow(blocks: list[dict]) -> list[dict]:
    return [b for b in blocks if b.get("role") != "caption"]


def uncertain_boundaries(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return records for page boundaries whose paragraph structure is unclear."""
    pages = data.get("pages", [])
    found: list[dict[str, Any]] = []
    for prev, nxt in zip(pages, pages[1:]):
        if prev.get("chapter") != nxt.get("chapter"):
            continue
        pa, pb = prev.get("page"), nxt.get("page")
        if isinstance(pa, int) and isinstance(pb, int) and pb - pa > 1:
            continue  # sampled/non-contiguous pages: the paragraph cannot continue across a gap
        a_flow, b_flow = _flow(prev.get("blocks") or []), _flow(nxt.get("blocks") or [])
        if not a_flow or not b_flow:
            continue
        a, b = a_flow[-1], b_flow[0]
        if a.get("role") != "body" or a.get("boundary_reviewed"):
            continue
        text = (a.get("translation") or "").rstrip()
        if not text or _TERMINAL.search(text):
            continue
        head = (b.get("translation") or "").lstrip()
        if b.get("role") == "body" and head[:1].islower():
            continue  # clear continuation (normalize joins it)
        reason = {
            "heading": "unfinished_before_heading",
            "body": "unfinished_before_capital",
        }.get(str(b.get("role")), "unfinished_before_other")
        found.append({
            "page": prev.get("page"), "next_page": nxt.get("page"), "reason": reason,
            "block_id": a.get("block_id"), "next_block_id": b.get("block_id"),
            "tail": text[-40:], "head": head[:40],
        })
    for page in pages:
        blocks = page.get("blocks") or []
        if len(blocks) == 1 and blocks[0].get("role") == "body" and not blocks[0].get("boundary_reviewed") \
                and len(blocks[0].get("translation") or "") > SINGLE_BLOCK_CHARS:
            found.append({"page": page.get("page"), "reason": "page_is_single_block",
                          "block_id": blocks[0].get("block_id")})
    return found
