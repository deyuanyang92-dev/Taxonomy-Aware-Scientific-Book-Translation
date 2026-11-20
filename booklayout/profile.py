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

    def validate(self) -> None:
        if self.version != PROFILE_VERSION:
            raise ValueError(f"unsupported profile version {self.version}")
        if self.text_w <= 20 or self.page_h - self.margin_top - self.margin_bottom <= 20:
            raise ValueError("margins leave no usable text area")
        if min(self.body_size, self.header_size, self.footer_size, self.index_size) <= 0:
            raise ValueError("type sizes must be positive")


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
            elif role == "list":
                if not isinstance(b.get("items"), list):
                    errors.append(f"{where}: list needs `items`")
            elif role == "figure_group":
                if not isinstance(b.get("figures"), list):
                    errors.append(f"{where}: figure_group needs `figures`")
            elif "translation" not in b and "text" not in b:
                errors.append(f"{where}: needs `text` or `translation`")
    return errors
