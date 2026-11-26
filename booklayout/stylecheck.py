"""Style gate for a built DOCX: the v8 sample (Imajima 1-12) is the floor.

Counts violations of the format rules in docs/booklayout-standard.md.
Exit 1 if any count is non-zero.  Usage: python3 -m booklayout.stylecheck X.docx
"""
from __future__ import annotations

import re
import sys

from docx import Document

_HAN = re.compile("[" + chr(0x4E00) + "-" + chr(0x9FFF) + "]")
_HALF_PAREN_CJK = re.compile(
    r"\([^()]*?\)(?=\s*[" + chr(0x4E00) + "-" + chr(0x9FFF) + chr(0xFF0C) + chr(0x3002) + chr(0xFF1B) + chr(0xFF1A) + chr(0x3001) + "])")
_LABELS = ("形态", "生态", "分类", "分布")
_IDEOSPACE = chr(0x3000)


def _paras(doc):
    """Yield (paragraph, in_table, after_table)."""
    for p in doc.paragraphs:
        prev = p._p.getprevious()
        yield p, False, prev is not None and prev.tag.endswith("}tbl")
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    yield p, True, False


def check_docx(path: str) -> dict[str, list[str]]:
    doc = Document(path)
    res: dict[str, list[str]] = {k: [] for k in (
        "italic_cjk", "label_not_bold", "halfwidth_paren_before_cjk",
        "fullwidth_space", "blank_paragraph", "caption_style_mismatch")}
    cap_styles: set = set()
    for p, in_table, after_table in _paras(doc):
        t = p.text
        if not t.strip():
            xml = p._p.xml
            if in_table or after_table or any(k in xml for k in ("graphic", "w:br", "sectPr")):
                continue
            res["blank_paragraph"].append("(empty paragraph)")
            continue
        if _IDEOSPACE in t:
            res["fullwidth_space"].append(t[:30])
        if _HALF_PAREN_CJK.search(t):
            res["halfwidth_paren_before_cjk"].append(t[:40])
        for r in p.runs:
            if r.italic and _HAN.search(r.text) and not re.search(r"[A-Za-z]", r.text):
                res["italic_cjk"].append(r.text[:30])
            if r.text.strip() in _LABELS and not r.bold:
                res["label_not_bold"].append(r.text)
        if re.match(r"^图[A-Z0-9]{1,2}\s+(?:[a-z]：|\S+图)", t):
            cap_styles.add((p.alignment, p.paragraph_format.first_line_indent))
    if len(cap_styles) > 1:
        res["caption_style_mismatch"].append(f"caption styles differ: {cap_styles}")
    return res


def direct_format_warnings(path: str) -> list[str]:
    """Paragraphs of a named style that carry direct size/spacing/indent (design 2026-11-26 C.3).

    Such paragraphs ignore `booklayout restyle` and Word style edits.  Tab/line-break-only
    runs are exempt (the builder pins them at the Normal size on purpose).  A warning, not an
    error: it does not change the exit code.
    """
    from .profile import PARA_STYLE_DEFAULTS

    doc = Document(path)
    out: list[str] = []
    for p, _in_table, _after in _paras(doc):
        name = p.style.name if p.style is not None else ""
        if name not in PARA_STYLE_DEFAULTS or not p.text.strip():
            continue
        pf = p.paragraph_format
        bad = [k for k, v in (("space_before", pf.space_before), ("space_after", pf.space_after),
                              ("line_spacing", pf.line_spacing), ("left_indent", pf.left_indent),
                              ("first_line_indent", pf.first_line_indent)) if v is not None]
        if any(r.font.size is not None and r.text.strip() for r in p.runs):
            bad.append("run_size")
        if bad:
            out.append(f"[{name}] {','.join(bad)}: {p.text[:30]!r}")
    return out


def main(argv: list[str]) -> int:
    res = check_docx(argv[1])
    warn = direct_format_warnings(argv[1])
    if warn:
        print(f"{'direct_format (warning)':30s} {len(warn)}", "e.g. " + repr(warn[0]))
    bad = 0
    for k, v in res.items():
        print(f"{k:30s} {len(v)}", ("e.g. " + repr(v[0])) if v else "")
        bad += len(v)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
