"""Page-marked source/translation Markdown -> aligned JSON (issue #13).

The generic bridge between ``docstore export --translate`` / ``auto_translate``
output and ``booklayout build``.  Both Markdown files carry ``<!-- PDF p.N -->``
markers; paragraphs are separated by blank lines.  Per page the paragraphs are
paired by position.  When the counts differ the page becomes ONE block with
``misaligned: true`` (listed in the report) instead of a guessed pairing.

Roles are assigned by deterministic rules only (``#`` headings, figure-label
captions, key branch lines via :mod:`booklayout.keymodel`, else ``body``); a
book that needs more (references, entries, index) refines the JSON with
``booklayout normalize`` / ``patch-blocks``.  Chapter = last level-1 heading.

CLI: ``python3 -m booklayout align-md --source src.md --translation tgt.md --out aligned.json``
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .keymodel import HEADING_RE, LEAD_RE, PAGE_MARK
from .pdffigures import CAPTION_RE

_PAGE_SPLIT = re.compile(r"(<!--\s*PDF p\.\d+[^>]*-->)")


def split_pages(markdown: str) -> dict[int, str]:
    parts = _PAGE_SPLIT.split(markdown)
    pages: dict[int, str] = {}
    for marker, body in zip(parts[1::2], parts[2::2]):
        m = PAGE_MARK.search(marker)
        if m:
            pages[int(m.group(1))] = body.strip("\n")
    return pages


def split_units(page_text: str) -> list[str]:
    """Paragraphs; a paragraph holding key branch lines is split one branch per unit."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", page_text.strip()):
        lines = [x.strip() for x in para.splitlines() if x.strip()]
        if not lines:
            continue
        if any(LEAD_RE.match(x) for x in lines):
            cur: list[str] = []
            for x in lines:
                if LEAD_RE.match(x) and cur:
                    units.append(" ".join(cur))
                    cur = []
                cur.append(x)
            units.append(" ".join(cur))
        else:
            units.append(" ".join(lines))
    return units


def classify(unit: str) -> tuple[str, int | None]:
    if unit.startswith("#"):
        level = len(unit) - len(unit.lstrip("#"))
        return "heading", level
    if CAPTION_RE.match(unit):
        return "caption", None
    if HEADING_RE.match(unit) and len(unit) < 120:
        return "heading", 2
    if LEAD_RE.match(unit):
        return "key", None
    return "body", None


def align_markdown(src_md: str, tgt_md: str) -> tuple[dict[str, Any], dict[str, Any]]:
    src, tgt = split_pages(src_md), split_pages(tgt_md)
    pages: list[dict[str, Any]] = []
    report: dict[str, Any] = {"misaligned_pages": [], "missing_translation_pages": [],
                              "extra_translation_pages": sorted(set(tgt) - set(src))}
    chapter = "Front matter"
    for n in sorted(src):
        su = split_units(src[n])
        if n not in tgt:
            report["missing_translation_pages"].append(n)
            tu: list[str] = [""] * len(su)
        else:
            tu = split_units(tgt[n])
        mis = len(su) != len(tu)
        if mis:
            report["misaligned_pages"].append({"page": n, "source_units": len(su), "translation_units": len(tu)})
            su, tu = ([" ".join(su)] if su else []), ([" ".join(tu)] if tu else [])
        blocks = []
        for i, (s, t) in enumerate(zip(su, tu)):
            role, level = classify(s)
            if role == "heading" and level == 1:
                chapter = re.sub(r"^#+\s*", "", s)[:80]
            b: dict[str, Any] = {"block_id": f"p{n}-b{i + 1}", "role": "body" if mis else role,
                                 "text": re.sub(r"^#+\s*", "", s), "translation": re.sub(r"^#+\s*", "", t),
                                 "y0": float(i * 10)}
            if role == "heading" and not mis:
                b["level"] = level or 2
            if mis:
                b["misaligned"] = True
            blocks.append(b)
        pages.append({"page": n, "chapter": chapter, "kind": "chapter", "blocks": blocks})
    report["pages"] = len(pages)
    report["blocks"] = sum(len(p["blocks"]) for p in pages)
    report["ok"] = not (report["misaligned_pages"] or report["missing_translation_pages"]
                        or report["extra_translation_pages"])
    return {"pages": pages}, report


def add_parser(sub: Any) -> None:
    a = sub.add_parser("align-md", help="page-marked source + translation Markdown -> aligned JSON")
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--translation", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--report", type=Path)
    a.set_defaults(func=cmd_align_md)


def cmd_align_md(args: Any) -> int:
    data, rep = align_markdown(args.source.read_text(encoding="utf-8"), args.translation.read_text(encoding="utf-8"))
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.report:
        args.report.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pages={rep['pages']} blocks={rep['blocks']} misaligned={len(rep['misaligned_pages'])} ok={rep['ok']}")
    return 0 if rep["ok"] else 1
