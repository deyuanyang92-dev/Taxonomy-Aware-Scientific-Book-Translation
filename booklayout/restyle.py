"""Fast restyle of a finished DOCX (design 2026-11-26 C/T4).

Paragraphs only reference named styles (Body, Caption, Heading 2 ...), so rewriting the
style definitions restyles the whole book in seconds, without re-typesetting.
`--style Body.size=11` style overrides are applied to a copy of the profile.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .profile import PARA_FIELDS, PARA_STYLE_DEFAULTS, StyleProfile

HEADING_FIELDS = frozenset({"size", "before", "after", "align", "bold", "italic", "small_caps", "color"})


def _value(text: str) -> Any:
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(text)
    except ValueError:
        return text.strip()


def parse_override(spec: str) -> tuple[str, str, Any]:
    """`'Body.size=11'` -> (`'Body'`, `'size'`, 11.0); style names may contain spaces."""
    left, sep, right = spec.partition("=")
    name, dot, field = left.rpartition(".")
    if not sep or not dot or not name.strip() or not field.strip():
        raise ValueError(f"bad --style {spec!r}: expected 'Style Name.field=value'")
    return name.strip(), field.strip(), _value(right)


def apply_overrides(profile: StyleProfile, specs: list[str]) -> StyleProfile:
    """Copy of `profile` with every override applied and validated (the original is untouched)."""
    prof = copy.deepcopy(profile)
    for spec in specs or []:
        name, field, value = parse_override(spec)
        if name.startswith("Heading ") and name[8:] in ("1", "2", "3", "4", "5", "6"):
            if field not in HEADING_FIELDS:
                raise ValueError(f"{spec!r}: unknown heading field {field!r} (known: {sorted(HEADING_FIELDS)})")
            prof.heading_styles.setdefault(name[8:], {})[field] = value
        elif name in PARA_STYLE_DEFAULTS:
            if field not in PARA_FIELDS:
                raise ValueError(f"{spec!r}: unknown field {field!r} (known: {sorted(PARA_FIELDS)})")
            prof.para_styles.setdefault(name, {})[field] = value
        else:
            raise ValueError(f"{spec!r}: unknown style {name!r} (known: {sorted(PARA_STYLE_DEFAULTS)} + Heading 1-4)")
    prof.validate()
    return prof


def restyle_docx(docx: Path, out: Path, profile: StyleProfile, overrides: list[str] | None = None) -> StyleProfile:
    """Rewrite every named style of `docx` from `profile` (+ overrides) and save to `out`."""
    from docx import Document
    from docx.shared import Pt

    from .builder import apply_profile, define_styles

    prof = apply_overrides(profile, overrides or [])
    apply_profile(prof)
    doc = Document(str(docx))
    doc.styles["Normal"].font.size = Pt(prof.body_size)
    define_styles(doc, prof)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return prof
