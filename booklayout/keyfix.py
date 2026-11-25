"""Deterministic repair of identification-key pages whose blocks were mis-filed.

Seen in Fauna Iberica Vol. 21 (2026-11-23): on key pages the aligner tagged some
couplets ``index`` and cut the target ("P. papillosa (p. 278)") off into a block of
its own.  The builder drops ``index`` blocks on chapter pages, so whole couplets
vanished from the printed key, and the three reviews never noticed.  This module
puts the couplets back: it is applied by the builder and by ``qa``, so both see
the same repaired page, and every repair is counted.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

LEADER = " ..... "
_PAREN = re.compile(r"\s*[（(]\s*(?:第\s*\d+\s*页|p\.\s*\d+|pp\.\s*[\d\-–, ]+)\s*[）)]\s*$")
_KEY_TITLE = re.compile(r"检索表|^Clave\b|^Key\b", re.I)
_MARKER = re.compile(r"^\s*(?:\d+[.．、)]|[•·*\-–—])")
_TRAIL_DOTS = re.compile(r"\s*(?:\.\s*){3,}$")
_LATIN = re.compile(r"^[A-Za-z][A-Za-z.\- ]*$")


def is_target_only(text: str) -> bool:
    """A block that is only a key target: a taxon name plus a page reference."""
    text = (text or "").strip()
    m = _PAREN.search(text)
    if not m or len(text) > 70:
        return False
    head = text[: m.start()].strip().strip("*")
    return bool(head) and bool(_LATIN.match(head))


def is_index_dominant(page: dict[str, Any]) -> bool:
    """True for alphabetical-index pages (their lines also carry leaders)."""
    idx = [b for b in page.get("blocks", []) if b.get("role") == "index"]
    led = [b for b in idx if re.search(r"(?:\.\s*){3,}|…", b.get("translation") or "")]
    return len(idx) >= 3 and len(led) * 2 >= len(idx)


def is_key_page(page: dict[str, Any]) -> bool:
    roles = [b.get("role") for b in page.get("blocks", [])]
    return "key" in roles and not is_index_dominant(page)


def repair_key_page(page: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Return (page, counts).  Pages that are not key pages are returned unchanged."""
    counts = {"index_to_key": 0, "targets_merged": 0, "title_to_heading": 0, "orphan_targets": 0,
              "body_to_key": 0, "continuations_merged": 0}
    if not is_key_page(page):
        return page, counts
    out = deepcopy(page)
    # after a key heading, short body blocks are couplet lines the aligner failed to tag
    under_key = False
    for b in out["blocks"]:
        if b.get("role") == "heading":
            under_key = bool(_KEY_TITLE.search((b.get("translation") or b.get("text") or "").strip()))
        elif under_key and b.get("role") == "body" and 0 < len((b.get("translation") or "").strip()) <= 160:
            b["role"] = "key"
            counts["body_to_key"] += 1
        elif b.get("role") not in ("key", "index"):
            under_key = False
    blocks: list[dict[str, Any]] = []
    prev_key: dict[str, Any] | None = None
    for i, b in enumerate(out["blocks"]):
        role = b.get("role")
        tr = (b.get("translation") or "").strip()
        nxt = out["blocks"][i + 1] if i + 1 < len(out["blocks"]) else {}
        if (role == "key" and tr and prev_key is not None and not _MARKER.match(tr) and not is_target_only(tr)
                and not _PAREN.search(prev_key["translation"])):
            # a wrapped line of the previous couplet that the aligner cut into its own block
            prev_key["translation"] = prev_key["translation"].rstrip() + " " + tr
            counts["continuations_merged"] += 1
            continue
        if role in ("index", "key") and tr and is_target_only(tr):
            if prev_key is not None:
                prev_key["translation"] = _TRAIL_DOTS.sub("", prev_key["translation"].rstrip()) + LEADER + tr
                if b.get("text") and prev_key.get("text") is not None:
                    prev_key["text"] = prev_key["text"].rstrip() + LEADER + b["text"].strip()
                counts["targets_merged"] += 1
                continue
            counts["orphan_targets"] += 1
        if role == "index" and tr:
            short_title = len(tr) <= 14 and not re.search(r"[.…\d]", tr) and not blocks
            if short_title and nxt.get("role") == "key":
                b["role"], b["level"] = "heading", 2
                counts["title_to_heading"] += 1
                blocks.append(b)
                prev_key = None
                continue
            b["role"] = "key"
            counts["index_to_key"] += 1
            role = "key"
        blocks.append(b)
        prev_key = b if role == "key" and tr else (None if role != "key" else prev_key)
    out["blocks"] = blocks
    return out, counts
