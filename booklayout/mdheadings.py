"""Markdown heading-hierarchy audit for translated Chinese books (read-only; emits an issue list).

The aligned-JSON builder derives levels in `headings.taxon_level`; translated books kept as plain Markdown
(one file per chapter) get their levels from the translation step and drift: family headings sit at `#` or `###`,
ordinary sub-sections are promoted to `#`, family names are italicised.  This module classifies every heading
and proposes the target level, one row per change, in the `apply_issues` shape (`file/line/old/new/type/reason`).
Nothing is written to the Markdown; rows go to a JSONL that the caller reviews and passes to the gate.

Target scheme: chapter (and, via --section-pattern, numbered section head) -> `#`; family (Latin *-idae* or Chinese
*…科*) -> `##` without italics; an ordinary sub-section wrongly sitting at `#` -> `###`.  Deeper levels are left alone.

    python3 -m booklayout.mdheadings <md_dir> [--out rows.jsonl] [--stats stats.md] [--order manifest.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
LAT_FAM = re.compile(r"\b[A-Z][a-z]+idae\b")
ZH_FAM = re.compile(r"[一-鿿]{1,8}科(?!学|研|技|普)")
CHAPTER = re.compile(r"^(?:第\s*\d+\s*章|附录|附录\s*\d+|第\s*\d+\.\d+\s*节)")
ITALIC = re.compile(r"\*([^*\n]+)\*")


def classify(text: str, section: re.Pattern[str] | None = None) -> str:
    """'family' | 'chapter' | 'section' | 'sub' for one heading text (marker already stripped).

    `section` is an optional book-specific pattern for numbered section heads that must sit at `#`
    (e.g. r"^7\\.\\d+(?![\\d.])" for 7.4 / 7.12 but not 7.4.1); numbered sub-sections like 1.1 stay untouched.
    """
    t = text.strip()
    if LAT_FAM.search(t) or ZH_FAM.search(t):
        return "family"
    if CHAPTER.match(t):
        return "chapter"
    if section is not None and section.match(t):
        return "section"
    return "sub"


def _target(kind: str, level: int, text: str) -> tuple[str | None, str]:
    plain = ITALIC.sub(r"\1", text)
    if kind == "family":
        if level == 2 and plain == text:
            return None, ""
        why = "family heading -> ##" if level != 2 else "family name is not italic"
        if level != 2 and plain != text:
            why += "; strip italics"
        return "## " + plain, why
    if kind in ("chapter", "section"):
        return (None, "") if level == 1 else ("# " + text, "chapter/section head -> #")
    # only a sub-section wrongly promoted to # is demoted; ## numbered sub-sections (1.1 ...) are left alone
    return ("### " + text, "sub-section wrongly at # -> ###") if level == 1 else (None, "")


def scan_text(text: str, key: str, section: re.Pattern[str] | None = None) -> tuple[list[dict[str, Any]], collections.Counter[tuple[int, str]],
                                            list[tuple[int, int]]]:
    """Return (change rows, count per (level, kind), pairs of consecutive level-1 heading lines)."""
    rows: list[dict[str, Any]] = []
    stats: collections.Counter[tuple[int, str]] = collections.Counter()
    dup_open: list[tuple[int, int]] = []
    prev1: int | None = None
    lines = text.splitlines()
    for i, ln in enumerate(lines, 1):
        m = HEAD.match(ln)
        if not m:
            continue
        level, txt = len(m.group(1)), m.group(2).strip()
        kind = classify(txt, section)
        stats[(level, kind)] += 1
        if level == 1:
            if prev1 is not None and i - prev1 <= 2:
                dup_open.append((prev1, i))
            prev1 = i
        new, why = _target(kind, level, txt)
        if new is not None and new != ln:
            rows.append({"file": key + ".md", "line": i, "level": level, "old": ln, "new": new,
                         "type": kind, "reason": why})
    return rows, stats, dup_open


def audit_dir(md_dir: Path, order: list[str] | None = None, section: re.Pattern[str] | None = None) -> dict[str, Any]:
    keys = order or sorted(p.stem for p in md_dir.glob("*.md"))
    rows: list[dict[str, Any]] = []
    stats: collections.Counter[tuple[int, str]] = collections.Counter()
    dups: list[tuple[str, int, int]] = []
    for k in keys:
        p = md_dir / f"{k}.md"
        if not p.exists():
            continue
        r, s, d = scan_text(p.read_text(encoding="utf-8"), k, section)
        rows += r
        stats.update(s)
        dups += [(k, a, b) for a, b in d]
    return {"rows": rows, "stats": stats, "dup_open": dups}


def stats_md(res: dict[str, Any]) -> str:
    kinds = ["chapter", "section", "family", "sub"]
    lv = sorted({lvl for lvl, _ in res["stats"]})
    out = ["# Heading hierarchy audit (read-only)", "", "| level | " + " | ".join(kinds) + " | total |",
           "|---|" + "---:|" * (len(kinds) + 1)]
    for lvl in lv:
        c = [res["stats"][(lvl, k)] for k in kinds]
        out.append(f"| {'#' * lvl} | " + " | ".join(map(str, c)) + f" | {sum(c)} |")
    out += ["", f"Changes proposed: {len(res['rows'])}.",
            f"Consecutive level-1 headings (duplicated section heads): {len(res['dup_open'])}."]
    out += [f"- {k}:{a}-{b}" for k, a, b in res["dup_open"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit Markdown heading levels; write proposed changes as JSONL")
    ap.add_argument("md_dir")
    ap.add_argument("--out", help="JSONL of proposed changes")
    ap.add_argument("--stats", help="statistics Markdown")
    ap.add_argument("--section-pattern", help="regex for numbered section heads that belong at # (book-specific)")
    ap.add_argument("--order", help="manifest.json whose entries have a 'key' (chapter order)")
    a = ap.parse_args(argv)
    order = [m["key"] for m in json.loads(Path(a.order).read_text(encoding="utf-8"))] if a.order else None
    res = audit_dir(Path(a.md_dir), order, re.compile(a.section_pattern) if a.section_pattern else None)
    if a.out:
        Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res["rows"]),
                               encoding="utf-8")
    if a.stats:
        Path(a.stats).write_text(stats_md(res), encoding="utf-8")
    print(f"{len(res['rows'])} changes proposed; {len(res['dup_open'])} consecutive level-1 pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
