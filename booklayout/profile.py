"""Versioned style profile and generic block schema (issue #27).

Every page-design constant of the builder lives here.  ``StyleProfile()``
reproduces the historical Vol. 48 layout exactly, so existing aligned JSON
builds unchanged; a JSON/TOML file overrides any subset of fields.  The
profile is hashed into the build report (``profile_sha256``).

Fields (mm unless noted):

========================  ===================================================
page_w / page_h           trim size (default 170 x 240)
margin_top/bottom/left/right, header_distance, footer_distance
body_font                 Latin font; ``cjk_font`` East Asian font (None: same
                          as body_font, or env BOOKLAYOUT_CJK_FONT)
font_fallback             advisory chain recorded in the report
body_size, header_size, footer_size, index_size   points
lang / lang_east_asia     w:lang values
hyphenation               auto-hyphenation on/off
caption_prefixes          regex alternation of caption labels (per language)
note_italic               False: translator notes set like captions (roman, left, no indent)
taxonomic                 True: taxonomy-specific behaviour (italic genera,
                          taxonomic index) stays on; False for other books
========================  ===================================================
Text width is derived: ``page_w - margin_left - margin_right``.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PROFILE_VERSION = 1

# Roles of the generic block model.  The first group is the historical Vol. 48
# vocabulary and stays valid unchanged.
# "couplet" and "legend" are written by the Imajima volumes' pipeline (2550 + 776 blocks in
# the three real books) and rendered by the builder, so the schema must accept them.
LEGACY_ROLES = frozenset({"heading", "body", "caption", "key", "ref", "entry", "citation",
                          "index", "note", "couplet", "legend"})
NEW_ROLES = frozenset({"table", "list", "quote", "box", "footnote", "figure_group"})
ROLES = LEGACY_ROLES | NEW_ROLES


PARA_FIELDS = frozenset({"size", "bold", "italic", "align", "first", "left", "before", "after",
                         "line", "keep_together", "keep_with_next", "size_follows_body"})
PARA_FIELD_DEFAULTS: dict[str, Any] = {
    "size": 10.5, "bold": False, "italic": False, "align": "left", "first": 0.0, "left": 0.0,
    "before": 0.0, "after": 0.0, "line": 1.0, "keep_together": False, "keep_with_next": False,
    "size_follows_body": False,
}
# Defaults equal the values the builder used to hard-code per role, so output is unchanged.
PARA_STYLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "Body": {"size": 10.5, "align": "justify", "first": 5.0, "line": 1.02},
    "Body Cont": {"size": 10.5, "align": "justify", "line": 1.02},
    "Note": {"size": 9.5, "italic": True, "align": "justify", "first": 5.0, "before": 4.0, "after": 4.0},
    "Note Roman": {"size": 9.5, "align": "left", "before": 4.0, "after": 4.0},
    "Citation": {"size": 9.2, "left": 4.0, "first": -4.0, "before": 1.0},
    "Ref": {"size": 7.6, "left": 4.0, "first": -4.0, "after": 1.5, "line": 0.95},
    "Entry": {"size": 10.2, "left": 4.0, "first": -4.0, "after": 2.0},
    "Entry Appendix": {"size": 9.2, "left": 4.0, "first": -4.0, "after": 2.0},
    "Taxon": {"size": 10.0, "after": 0.4, "keep_with_next": True},
    "Caption": {"size": 9.5, "before": 12.0, "after": 7.0, "line": 1.05, "keep_together": True},
    "Key": {"size": 8.3},
    "Key Note": {"size": 9.5},
    "Key Couplet": {"size": 10.5, "size_follows_body": True, "left": 16.0, "first": -7.0, "line": 1.15,
                    "keep_together": True},
    "Key Table": {"size": 9.2, "line": 1.1, "keep_together": True},
    "Key Heading": {"size": 10.5, "bold": True, "keep_with_next": True},
    "List Item": {"size": 10.5, "size_follows_body": True, "left": 6.0, "first": -4.0, "after": 1.0},
    "Quote": {"size": 10.0, "size_follows_body": True, "italic": True, "align": "justify", "left": 8.0,
              "before": 3.0, "after": 3.0},
    "Box Text": {"size": 10.0, "size_follows_body": True, "left": 3.0, "before": 4.0, "after": 4.0},
    "Footnote Text": {"size": 8.5, "size_follows_body": True, "before": 1.0, "after": 1.0},
    "Table Note": {"size": 9.0, "size_follows_body": True, "italic": True, "before": 2.0, "after": 6.0},
    "Index": {"size": 8.6},
    "Index Intro": {"size": 8.8, "italic": True, "align": "justify", "after": 8.0},
    "Index Correction": {"size": 8.8, "left": 4.0, "first": -4.0, "after": 3.0},
    "Section Title": {"size": 13.0, "bold": True, "align": "center", "after": 10.0},
}


@dataclass
class StyleProfile:
    version: int = PROFILE_VERSION
    name: str = "vol48-default"
    page_w: float = 170.0
    page_h: float = 240.0
    margin_top: float = 20.0
    margin_bottom: float = 19.0
    margin_left: float = 18.0
    margin_right: float = 18.0
    header_distance: float = 9.0
    footer_distance: float = 10.0
    body_font: str = "Garamond"
    cjk_font: str | None = None
    font_fallback: list[str] = field(default_factory=lambda: ["Times New Roman", "SimSun"])
    body_size: float = 10.5
    header_size: float = 8.0
    footer_size: float = 9.0
    index_size: float = 9.0
    lang: str = "en-US"
    lang_east_asia: str = "en-US"
    hyphenation: bool = True
    caption_prefixes: str = r"Fig|L[aá]m|Tabla|Plate|图|図|表"
    taxonomic: bool = True
    note_italic: bool = True   # False: translator notes set in roman (Imajima)
    # Named Word styles "Heading 1/2/3": one entry per level, the single source of
    # truth for every same-level heading in DOCX, HTML and restyle.  Keys are
    # "1".."3" (JSON/TOML object keys are strings).  Fields: size (pt, for a 10.5 pt
    # body; scaled with body_size), before/after (pt), align (left|center|right),
    # bold, italic, small_caps, color (hex RRGGBB).
    heading_styles: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "1": {"size": 15, "before": 0, "after": 10, "align": "center", "small_caps": True},
        "2": {"size": 12, "before": 14, "after": 7},
        "3": {"size": 10.8, "before": 10, "after": 4},
        "4": {"size": 10, "before": 6, "after": 2, "italic": True},
    })
    # "center": page number centred in the footer, running titles in the header
    # (Vol. 48 / Imajima baselines).  "folio": ruled footer, odd/even pages mirrored
    # (even: page number left, series right; odd: volume left, page number right),
    # no header; the first page carries no folio.
    footer_style: str = "center"
    # Named Word paragraph styles for every non-heading role (design 2026-11-26 C).  One entry
    # per style name; a paragraph only references its style.  Fields: size (pt for a 10.5 pt body,
    # scaled with body_size), bold, italic, align (left|center|right|justify), first (first-line
    # indent, mm), left (left indent, mm), before/after (pt), line (spacing multiple),
    # keep_together, keep_with_next, size_follows_body (size is relative to body_size, as the
    # builder's former hard-coded body_size - n sizes were).  Entries given here override the
    # defaults of PARA_STYLE_DEFAULTS field by field.
    para_styles: dict[str, dict[str, Any]] = field(default_factory=dict)
    # "source": use the level stored in the aligned JSON; "taxon": derive 1-4 from the
    # heading text (booklayout.headings.taxon_level), for sources with flat levels.
    heading_levels: str = "source"
    # True: body blocks that start like a figure caption ("Fig. 3." / "图3") are set as captions.
    promote_captions: bool = False
    # "tabs": one tabbed line per key couplet with a dot leader (Imajima/Vol. 45/48
    # baselines).  "table": a borderless 3-column table (marker | characters | target),
    # one row per couplet, the target flush right in its own column, so a long
    # couplet can never strand its target or leader (Google sample, user 2026-11-23).
    # "couplet": hanging marker, text, one dot-leader right tab, the address
    # ("Name (p. N)" or a couplet number) flush right as one unit (Fauna Ibérica).
    unwrap_lines: bool = False  # join hard line breaks inside body/caption/note blocks
    key_style: str = "tabs"
    citation_before: float = 1.0  # mm-free pt gap above a citation/synonymy line
    key_headers: list[str] = field(default_factory=lambda: ["", "", ""])
    toc_headings: bool = False  # contents lists headings (levels 1..toc_depth) with page numbers
    toc_depth: int = 3
    word_toc_title: str = "Índice de apartados"
    word_toc_after_page: int = 0  # word_toc: TOC page goes after this many source pages (1 = after the cover)
    word_toc: bool = False  # add a Word TOC field page (outline levels) when the source contents is printed as-is

    @property
    def text_w(self) -> float:
        return self.page_w - self.margin_left - self.margin_right

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(blob).hexdigest()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StyleProfile":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"unknown style profile fields: {unknown}")
        prof = cls(**raw)
        prof.validate()
        return prof

    @classmethod
    def from_file(cls, path: Path) -> "StyleProfile":
        text = path.read_text(encoding="utf-8")
        raw = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
        return cls.from_dict(raw)

    def heading_style(self, level: int) -> dict[str, Any]:
        """Effective style of heading `level` (defaults fill missing fields)."""
        base = {"size": 10.5, "before": 0, "after": 0, "align": "left",
                "bold": True, "italic": False, "small_caps": False, "color": "000000"}
        base.update(self.heading_styles.get(str(level), {}))
        return base

    def para_style(self, name: str) -> dict[str, Any]:
        """Effective paragraph style `name` (PARA_STYLE_DEFAULTS, then profile overrides)."""
        base = dict(PARA_FIELD_DEFAULTS)
        base.update(PARA_STYLE_DEFAULTS[name])
        if name == "Citation":
            base["before"] = self.citation_before
        base.update(self.para_styles.get(name, {}))
        return base

    def validate(self) -> None:
        if self.version != PROFILE_VERSION:
            raise ValueError(f"unsupported profile version {self.version}")
        if self.text_w <= 20 or self.page_h - self.margin_top - self.margin_bottom <= 20:
            raise ValueError("margins leave no usable text area")
        if min(self.body_size, self.header_size, self.footer_size, self.index_size) <= 0:
            raise ValueError("type sizes must be positive")
        if self.heading_levels not in ("source", "taxon"):
            raise ValueError(f"heading_levels must be source or taxon, not {self.heading_levels!r}")
        if self.key_style not in ("tabs", "table", "couplet"):
            raise ValueError(f"key_style must be 'tabs', 'table' or 'couplet', not {self.key_style!r}")
        if len(self.key_headers) != 3:
            raise ValueError("key_headers needs exactly 3 strings (marker, characters, target)")
        if self.footer_style not in ("center", "folio"):
            raise ValueError(f"footer_style must be 'center' or 'folio', not {self.footer_style!r}")
        for key, st in self.para_styles.items():
            if key not in PARA_STYLE_DEFAULTS:
                raise ValueError(f"para_styles key {key!r}: unknown style (known: {sorted(PARA_STYLE_DEFAULTS)})")
            bad = sorted(set(st) - PARA_FIELDS)
            if bad:
                raise ValueError(f"para_styles[{key}]: unknown fields {bad}")
            if st.get("align", "left") not in ("left", "center", "right", "justify"):
                raise ValueError(f"para_styles[{key}].align must be left/center/right/justify")
        for key, st in self.heading_styles.items():
            if key not in ("1", "2", "3", "4"):
                raise ValueError(f"heading_styles key {key!r}: only levels 1-4 exist")
            bad = sorted(set(st) - {"size", "before", "after", "align", "bold", "italic", "small_caps", "color"})
            if bad:
                raise ValueError(f"heading_styles[{key}]: unknown fields {bad}")
            if st.get("align", "left") not in ("left", "center", "right"):
                raise ValueError(f"heading_styles[{key}].align must be left/center/right")


def validate_aligned(data: dict[str, Any]) -> list[str]:
    """Schema check for aligned JSON; legacy files must return []."""
    errors: list[str] = []
    pages = data.get("pages")
    if not isinstance(pages, list):
        return ["`pages` must be a list"]
    seen: set[str] = set()
    for pi, page in enumerate(pages):
        if "page" not in page or "blocks" not in page:
            errors.append(f"pages[{pi}]: needs `page` and `blocks`")
            continue
        for bi, b in enumerate(page["blocks"]):
            where = f"page {page['page']} block {bi}"
            role = b.get("role")
            if role not in ROLES:
                errors.append(f"{where}: unknown role {role!r}")
                continue
            bid = b.get("block_id")
            if bid is not None:
                if bid in seen:
                    errors.append(f"{where}: duplicate block_id {bid}")
                seen.add(bid)
            if role == "table":
                rows = b.get("rows")
                if not isinstance(rows, list) or not rows or not all(isinstance(r, list) for r in rows):
                    errors.append(f"{where}: table needs non-empty `rows` (list of cell lists)")
                else:
                    for cell in (c for r in rows for c in r):
                        cs = cell.get("colspan", 1) if isinstance(cell, dict) else 1
                        if isinstance(cs, bool) or not isinstance(cs, int) or cs < 1:
                            errors.append(f"{where}: table cell colspan must be a positive integer, got {cs!r}")
                            break
                    else:
                        widths = b.get("col_widths_mm")
                        if widths is not None:
                            ncols = max(sum((c.get("colspan", 1) if isinstance(c, dict) else 1) for c in r)
                                        for r in rows)
                            if not isinstance(widths, list) or len(widths) > ncols:
                                errors.append(f"{where}: col_widths_mm has more entries than the table has "
                                              f"columns ({ncols})")
            elif role == "list":
                if not isinstance(b.get("items"), list):
                    errors.append(f"{where}: list needs `items`")
            elif role == "figure_group":
                if not isinstance(b.get("figures"), list):
                    errors.append(f"{where}: figure_group needs `figures`")
            elif "translation" not in b and "text" not in b:
                errors.append(f"{where}: needs `text` or `translation`")
            if data.get("schema") == ALIGNED_V2:
                errors.extend(f"{where}: {e}" for e in _check_v2_block(b))
    return errors


ALIGNED_V2 = "aligned/2"
_LEVEL_SOURCES = frozenset({"font", "number", "taxon", "engine", "manual"})
_ORIGINS = frozenset({"native", "ocr", "manual"})


def _check_v2_block(b: dict[str, Any]) -> list[str]:
    """Optional aligned/2 fields (design 2026-11-26 B.1); absent fields are fine, wrong ones are not."""
    errs: list[str] = []
    if "style" in b and not (b["style"] is None or isinstance(b["style"], str)):
        errs.append("style must be a string or null")
    if "level_source" in b and b["level_source"] not in _LEVEL_SOURCES:
        errs.append(f"level_source {b['level_source']!r} not in {sorted(_LEVEL_SOURCES)}")
    src = b.get("src")
    if src is not None:
        if not isinstance(src, dict):
            errs.append("src must be an object")
        else:
            if src.get("origin") not in _ORIGINS:
                errs.append(f"src.origin {src.get('origin')!r} not in {sorted(_ORIGINS)}")
            bb = src.get("bbox")
            if bb is not None and not (isinstance(bb, list) and len(bb) == 4
                                       and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bb)):
                errs.append("src.bbox must be 4 numbers")
            conf = src.get("conf")
            if conf is not None and not (isinstance(conf, (int, float)) and 0 <= conf <= 1):
                errs.append("src.conf must be within 0..1 or null")
    if "font" in b and not (isinstance(b["font"], dict) and {"family", "size"} <= set(b["font"])):
        errs.append("font needs family and size")
    runs = b.get("runs")
    if runs is not None and not (isinstance(runs, list) and all(isinstance(r, dict) and "t" in r for r in runs)):
        errs.append("runs must be a list of {t, ...}")
    return errs
