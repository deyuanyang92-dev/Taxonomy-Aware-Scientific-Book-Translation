# -*- coding: utf-8 -*-
"""Static multi-level TOC support for build_docx: entry collection + Word bookmark anchors.

Why: collect_pages.py measures pages by Heading-1 text, so same-named headings collide and section/family
levels cannot be measured.  Here every TOC entry gets a stable bookmark name (PREFIX_0001 ...) planted on its
heading paragraph; collect_pages.py --bookmarks PREFIX_ reads the real page of each bookmark.

Pure functions (python-docx imported lazily) so they are unit-testable without Word.  Book-specific patterns
are parameters, not constants.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FAMILY = re.compile(r"\b[A-Z][a-z]+idae\b")
CHAPTER = re.compile(r"^(?:第\s*\d+\s*章|附录)")


def vol_units(manifest: Path, vol: str) -> list[str]:
    """Unit keys of one volume, in manifest order (glob order is wrong for cross-volume units)."""
    man = json.loads(Path(manifest).read_text(encoding="utf-8"))
    return [m["key"] for m in man if any(p.get("vol") == vol for p in m.get("parts", []))]


def classify_title(body: str, marks: int, section: re.Pattern[str] | None = None) -> int | None:
    """TOC level: 1 chapter/appendix, 2 numbered section head (needs `section`), 3 numbered family; else None.
    Family = leading number + Latin *-idae*, so ordinary numbered sub-sections never enter the TOC."""
    if marks == 1:
        if CHAPTER.match(body):
            return 1
        if section is not None and section.match(body):
            return 2
        return None
    if marks in (2, 3) and re.match(r"^\d+(?:\.\d+)+", body) and FAMILY.search(body):
        return 3
    return None


def toc_label(title: str) -> str:
    """'第 3 章 X' -> '3  X'; other titles unchanged (italic marks kept for the renderer)."""
    t = title.lstrip("#").strip()
    m = re.match(r"^第\s*(\d+)\s*章\s*(.*)$", t)
    return f"{m.group(1)}  {m.group(2).strip()}" if m else t


def collect_entries(md_dir: Path, units: list[str], section: re.Pattern[str] | None = None,
                    prefix: str = "TOC_") -> list[dict[str, Any]]:
    """Scan unit files once; return [{key, level, label, anchor}] with stable anchors prefix+0001.."""
    out: list[dict[str, Any]] = []
    for key in units:
        text = (Path(md_dir) / f"{key}.md").read_text(encoding="utf-8").replace(chr(0x3000), "  ")
        for ln in text.split("\n"):
            m = re.match(r"^(#{1,3})\s+(.*)$", ln.strip())
            if not m:
                continue
            body = m.group(2).strip()
            lvl = classify_title(body, len(m.group(1)), section)
            if lvl is not None:
                out.append({"key": key, "level": lvl, "label": toc_label(body),
                            "anchor": f"{prefix}{len(out) + 1:04d}"})
    return out


def add_bookmark(p: Any, name: str, bid: int) -> None:
    """Wrap a python-docx paragraph's content in a Word bookmark (unique integer id bid)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    st = OxmlElement("w:bookmarkStart")
    st.set(qn("w:id"), str(bid))
    st.set(qn("w:name"), name)
    en = OxmlElement("w:bookmarkEnd")
    en.set(qn("w:id"), str(bid))
    pPr = p._p.find(qn("w:pPr"))
    if pPr is not None:
        pPr.addnext(st)
    else:
        p._p.insert(0, st)
    p._p.append(en)


def bookmark_names(docx_path: Path, prefix: str) -> list[str]:
    """Bookmark names starting with prefix, read from document.xml (no Word needed; for verification)."""
    import zipfile
    xml = zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8")
    return [n for n in re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', xml) if n.startswith(prefix)]
