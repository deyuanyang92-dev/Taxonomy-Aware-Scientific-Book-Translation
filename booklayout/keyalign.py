"""Re-cut key (identification couplet) pages from the translated page text.

The structural aligner anchors headings, citations and entries, but a key page
has no such anchors between couplets.  One line of drift there shifts every
later couplet on the page, and the damage is invisible to word-count coverage
checks because no text is lost.  The translated page in the markdown master
still contains the couplets in reading order, and each source couplet ends in a
page reference or a couplet number, so the run can be re-cut deterministically
from the page text.

This module is deliberately separate from :mod:`normalize`: it needs the
markdown master, not just the aligned JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LEADER_RE = re.compile(r"(?:[.…�]\s*){2,}")
START_RE = re.compile(r"(•|\d{1,2}\.)\s")
START_AT_RE = re.compile(r"^\s*(?:•|\d{1,2}\.)\s")
_JUNK = re.compile(r"[\x00-\x08\x0b-\x1f\xad]")
_PAGE_MARK = "<!-- PDF p.{n} -->"
_HEADERS = (
    re.compile(r"^\d{1,3}\s+FAUNA IB[EÉ]RICA\s*"),
    re.compile(r"^\d{1,3}\s+IBERIAN FAUNA\s*"),
    re.compile(r"^ANNELIDA,?\s+POLYCHAETA\s+[IVX]+\s+\d{1,3}\s*"),
    re.compile(r"^\d{1,3}\s+[A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ ,.-]{6,}?\s+(?=[A-ZÁÉÍÓÚ][a-z])"),
)


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", _JUNK.sub("", str(text or "").replace(" ", " "))).strip()


def clean_segment(text: str) -> str:
    """Replace OCR dot leaders with a printable ellipsis."""
    return LEADER_RE.sub(" … ", text).replace("… …", "…").strip()


def page_text(markdown: str, number: int) -> str:
    """Return one page of the translated markdown, running header removed."""
    start = markdown.find(_PAGE_MARK.format(n=number))
    if start < 0:
        return ""
    start = markdown.find("\n", start)
    end = markdown.find(_PAGE_MARK.format(n=number + 1), start)
    raw = markdown[start:end if end >= 0 else len(markdown)]
    text = norm(raw)
    for pattern in _HEADERS:
        stripped = pattern.sub("", text, count=1)
        if stripped != text:
            text = stripped
            break
    return text


def source_anchor(source: str) -> re.Pattern[str] | None:
    """Regex matching the translated end of one source key line."""
    text = norm(source).rstrip("•").strip()
    match = re.search(r"\(\s*p\.\s*(\d+)\s*\)\s*$", text)
    if match:
        return re.compile(r"\(\s*p\.\s*" + match.group(1) + r"\s*\)")
    match = re.search(r"([A-Za-z][A-Za-z.-]*)\s*\(\s*(\d{4})\s*\)\s*$", text)
    if match:
        return re.compile(re.escape(match.group(1)) + r"\s*\(\s*" + match.group(2) + r"\s*\)")
    # Imajima: "Genus species (図34)" / "(Fig. 12)" — anchor on the Latin epithet.
    match = re.search(
        r"([A-Z][a-z][A-Za-z-]*)(?:\s+\(?([a-z][a-z-]+)\)?)?\s*"
        r"[\(（]\s*(?:Fig\.?|Figs?\.?|図|图)\s*[^)）]*[\)）]\s*$",
        text,
    )
    if match:
        epithet = match.group(2) or match.group(1)
        return re.compile(r"(?<!\w)" + re.escape(epithet) + r"(?!\w)")
    match = re.search(r"(?<![A-Za-z])(\d{1,2})\s*$", text)
    if match:
        return re.compile(r"(?:[.…�]\s*){2,}" + match.group(1) + r"\b")
    match = re.search(r"([A-Za-z][A-Za-z0-9.-]+)\s*\*?\s*$", text)
    if match:
        return re.compile(r"(?<!\w)" + re.escape(match.group(1)) + r"(?!\w)")
    return None


def _complete(source: str) -> bool:
    """True when a source line already carries its page reference/number."""
    return bool(LEADER_RE.search(source) or re.search(r"[.!?)]\s*$", source))


def key_groups(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group blocks that together carry one source key line."""
    groups: list[list[dict[str, Any]]] = []
    for block in blocks:
        role = block.get("role")
        source = norm(block.get("text"))
        if role not in ("key", "heading", "citation", "body", "entry"):
            continue
        has_leader = bool(LEADER_RE.search(source))
        if not has_leader and role != "key":
            continue
        if not groups:
            groups.append([block])
            continue
        previous = groups[-1][-1]
        previous_source = norm(previous.get("text"))
        if START_AT_RE.match(source) or has_leader:
            if not _complete(previous_source):
                groups[-1].append(block)
            else:
                groups.append([block])
        elif previous.get("role") == "key" and not _complete(previous_source):
            groups[-1].append(block)
    return [
        group
        for group in groups
        if LEADER_RE.search(" ".join(norm(b.get("text")) for b in group))
    ]


def _marker(group: list[dict[str, Any]]) -> str | None:
    for block in group:
        match = re.match(r"^\s*(•|\d{1,2}\.)\s", norm(block.get("text")))
        if match:
            return match.group(1)
    return None


def _structural_stop(page: dict[str, Any], rest: str, start: int) -> int:
    """Position where the block after the key begins, or ``len(rest)``.

    The last footnote has no following footnote number, so without this stop
    it would absorb the next heading, citation and body text.
    """
    stop = len(rest)
    for block in page.get("blocks", []):
        if block.get("role") not in ("heading", "citation"):
            continue
        words = norm(block.get("translation")).split()
        if len(words) < 3:
            continue
        anchor = re.compile(r"\s+".join(re.escape(word) for word in words[:4]))
        found = anchor.search(rest, start)
        if found is not None and found.start() < stop:
            stop = found.start()
    return stop


def align_page(
    page: dict[str, Any], markdown: str, next_text: str = ""
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (changes, messages) for one page.

    ``changes`` are ``{"block_id", "translation", "role"}`` updates that callers
    apply to the aligned JSON.
    """
    number = int(page["page"])
    text = page_text(markdown, number)
    if not text:
        return [], [{"page": number, "message": "no markdown page"}]
    groups = key_groups(page.get("blocks", []))
    if not groups:
        return [], []
    messages: list[dict[str, Any]] = []
    stream = text
    if next_text:
        stream = (text + " " + next_text).strip()

    segments: list[str] = []
    pos = 0
    for index, group in enumerate(groups):
        anchor = source_anchor(norm(group[-1].get("text")))
        if anchor is None:
            messages.append({"page": number, "message": f"{group[0]['block_id']}: no anchor"})
            return [], messages
        found = anchor.search(stream, pos)
        if found is None and next_text and not stream.endswith(next_text):
            found = anchor.search(stream, pos)
        if found is None:
            messages.append(
                {"page": number, "message": f"{group[0]['block_id']}: anchor not found"}
            )
            return [], messages
        start = pos
        marker = _marker(group)
        if marker is not None:
            pattern = re.compile(r"(?<!\w)" + re.escape(marker) + r"\s")
            candidates = [
                match
                for match in pattern.finditer(stream, pos, found.start())
                if START_RE.match(stream, match.start())
            ]
            if candidates:
                # The first line must skip page material before the key (the
                # heading or a contents list); later lines start right after
                # the previous line's target.
                start = candidates[-1].start() if index == 0 else candidates[0].start()
        elif index > 0:
            # Some source lines lost their leading bullet during OCR and keep
            # it as a stray mark mid-line; the translated line still starts at
            # the first bullet after the previous line's target.
            bullet = re.compile(r"•\s").search(stream, pos, found.start())
            if bullet is not None:
                start = bullet.start()
        segment = stream[start : found.end()].strip()
        continuation = index == 0 and marker is None
        if not segment or not (
            START_AT_RE.match(segment) or (continuation and segment[:1].islower())
        ):
            messages.append(
                {"page": number, "message": f"{group[0]['block_id']}: bad segment"}
            )
            return [], messages
        segments.append(clean_segment(segment))
        pos = found.end()
    if pos > len(text):
        messages.append({"page": number, "message": "cross-page line"})

    changes: list[dict[str, Any]] = []
    for group, segment in zip(groups, segments):
        first = group[0]
        if norm(first.get("translation")) != segment:
            changes.append(
                {"block_id": first["block_id"], "translation": segment, "role": "key"}
            )
        elif first.get("role") != "key":
            changes.append({"block_id": first["block_id"], "role": "key"})
        for extra in group[1:]:
            if norm(extra.get("translation")) or extra.get("role") != "key":
                changes.append(
                    {
                        "block_id": extra["block_id"],
                        "translation": "",
                        "role": "key",
                        "_drop": True,
                    }
                )

    # Blocks the run did not claim are the key's introductory note or its
    # footnotes; their source has no leader and no couplet marker.  Footnotes
    # are re-cut from the page text after the last couplet, because the old
    # alignment had folded a line target into their first sentence.
    grouped = {block["block_id"] for group in groups for block in group}
    rest = text[pos:].strip() if pos < len(text) else ""
    ungrouped = [
        block
        for block in page.get("blocks", [])
        if block["block_id"] not in grouped
        and block.get("role") == "key"
        and not LEADER_RE.search(norm(block.get("text")))
        and not START_AT_RE.match(norm(block.get("text")))
    ]
    notes = [
        (block, match.group(1))
        for block in ungrouped
        if (match := re.match(r"^\s*(\d{1,2})\s", norm(block.get("text"))))
    ]
    for index, (block, note_number) in enumerate(notes):
        pattern = re.compile(r"(?<!\w)" + re.escape(note_number) + r"\s+(?=[A-ZÁÉÍÓÚ])")
        found = pattern.search(rest) if rest else None
        if not found:
            continue
        end = len(rest)
        if index + 1 < len(notes):
            next_number = notes[index + 1][1]
            following = re.compile(
                r"(?<!\w)" + re.escape(next_number) + r"\s+(?=[A-ZÁÉÍÓÚ])"
            ).search(rest, found.end())
            if following:
                end = following.start()
        else:
            end = _structural_stop(page, rest, found.end())
        note_text = rest[found.start() : end].strip()
        rest = rest[end:].strip()
        if norm(block.get("translation")) != note_text:
            changes.append(
                {"block_id": block["block_id"], "translation": note_text, "role": "note"}
            )
    for block in ungrouped:
        if any(block is note for note, _ in notes):
            continue
        if block.get("role") != "note":
            changes.append({"block_id": block["block_id"], "role": "note"})
    return changes, messages


def align_document(
    aligned: dict[str, Any], markdown: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply :func:`align_page` to every page; returns a new document."""
    pages = aligned.get("pages", [])
    out = json.loads(json.dumps(aligned))
    by_number = {int(page["page"]): page for page in out.get("pages", [])}
    report: list[dict[str, Any]] = []
    for page in pages:
        number = int(page["page"])
        following = page_text(markdown, number + 1)
        changes, messages = align_page(page, markdown, following)
        report.extend(messages)
        target = by_number[number]
        index = {block["block_id"]: block for block in target["blocks"]}
        for change in changes:
            block = index.get(change["block_id"])
            if block is None:
                continue
            if "translation" in change:
                block["translation"] = change["translation"]
            if "role" in change:
                block["role"] = change["role"]
            if change.get("_drop"):
                block["_drop"] = True
            report.append(
                {
                    "page": number,
                    "block_id": change["block_id"],
                    "rule": "key_align",
                }
            )
    return out, report


def main(aligned_path: str, translation_path: str, out_path: str, report_path: str) -> int:
    aligned = json.loads(Path(aligned_path).read_text(encoding="utf-8"))
    markdown = Path(translation_path).read_text(encoding="utf-8")
    out, report = align_document(aligned, markdown)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(report_path).write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in report) + "\n",
        encoding="utf-8",
    )
    failures = [item for item in report if "message" in item]
    print(f"key-align: {len(report) - len(failures)} blocks updated, {len(failures)} warnings")
    for item in failures[:20]:
        print("  warning:", item)
    return 0
