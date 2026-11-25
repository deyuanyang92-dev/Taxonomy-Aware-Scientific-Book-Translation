"""Deterministic paragraph and reference-list repairs (issue #37).

Three independent helpers, all pure functions:

* ``merge_continuation_paragraphs``: OCR line breaks inside a paragraph
  (typically a Latin-only line in Japanese text) were taken as paragraph
  breaks.  Merge a paragraph into the previous one when the previous has no
  terminal punctuation and the next is not a heading, list item or table row.
* ``split_reference_entries``: split a reference block holding several
  numbered entries (``32. ... 40. ...``) into one string per entry.
* ``kana_residue``: report kana in non-reference blocks of an English book.
"""
from __future__ import annotations

import re
from typing import Any

_TERMINAL = re.compile(r"[。．.！？!?」』）:：;；]\s*$")
_STRUCTURAL = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d{1,4}['’]?[.．、)]\s|<!--|\|)")
_KANA = re.compile(r"[぀-ヿㇰ-ㇿｦ-ﾟ]")
# an entry number: 1-3 digits (optionally primed) then a dot and a space
_NO_TAIL = r"(?:(?:\.|．)|(?<=['’]))"
_ENTRY_NO = re.compile(r"(?:(?<=[.。)\]])|(?<=\s))\s*(\d{1,3})['’]?" + _NO_TAIL + r"\s+(?=\S)")


def merge_continuation_paragraphs(paragraphs: list[str]) -> list[str]:
    out: list[str] = []
    for para in paragraphs:
        text = para.strip()
        if not text:
            out.append(para)
            continue
        prev = out[-1] if out else ""
        if (prev.strip() and not _TERMINAL.search(prev) and not _STRUCTURAL.match(prev)
                and not _STRUCTURAL.match(text)):
            joiner = " " if (re.search(r"[A-Za-z0-9,&]$", prev.strip())
                             or re.match(r"[A-Za-z0-9(]", text)) else ""
            out[-1] = prev.rstrip() + joiner + text
        else:
            out.append(text)
    return out


def split_reference_entries(text: str) -> list[str]:
    """Split on increasing entry numbers; one entry is returned unchanged."""
    text = text.strip()
    first = re.match(r"(\d{1,3})['’]?" + _NO_TAIL + r"\s", text)
    if not first:
        return [text] if text else []
    last = int(first.group(1))
    cuts: list[int] = []
    for m in _ENTRY_NO.finditer(text, first.end()):
        n = int(m.group(1))
        # must follow the previous number and the previous entry must be
        # closed by a period ("Bull. No. 12. Tokyo" has 12 < 57: rejected)
        if n > last and n - last <= 60 and text[:m.start()].rstrip()[-1:] in ".。)":
            cuts.append(m.start() if m.start() else 0)
            last = n
    if not cuts:
        return [text]
    bounds = [0] + [c for c in cuts] + [len(text)]
    return [text[a:b].strip() for a, b in zip(bounds, bounds[1:]) if text[a:b].strip()]


def kana_residue(data: dict[str, Any], allowed_roles: tuple[str, ...] = ("ref",)) -> list[dict]:
    """Blocks outside ``allowed_roles`` whose translation still holds kana."""
    found: list[dict] = []
    for page in data.get("pages", []):
        for b in page.get("blocks", []):
            if b.get("role") in allowed_roles:
                continue
            tr = b.get("translation") or ""
            m = _KANA.search(tr)
            if m:
                found.append({"page": page.get("page"), "block_id": b.get("block_id"),
                              "role": b.get("role"), "text": tr[:120]})
    return found
