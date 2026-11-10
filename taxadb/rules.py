"""切分规则：读 TOML，编译正则。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover  (Python < 3.11)
    import tomli as tomllib  # type: ignore[no-redef]

RULES_DIR = Path(__file__).resolve().parent / "rules"


@dataclass
class Rules:
    raw: dict[str, Any]
    path: str
    body_pages: tuple[int, int]
    page_offset: int
    expected_species: int | None
    inventory_source: str
    inventory_pages: tuple[int, int] | None
    inventory_line: re.Pattern | None
    species: re.Pattern
    max_wrap_lines: int
    stop: list[re.Pattern]
    genus: re.Pattern | None
    family: re.Pattern | None
    subfamily: re.Pattern | None
    section_names: dict[str, str]
    section_fuzzy: dict[str, str]
    sentence_end: str
    legend_start: re.Pattern
    legend_item: re.Pattern
    legend_inner: re.Pattern
    legend_tail: re.Pattern
    legend_short_tail: int
    header_max_lines: int
    header: list[re.Pattern]
    noise: list[re.Pattern]
    range_dash: bool
    zh_suffix: re.Pattern | None = None
    merge: bool = False
    merge_max_insert: int = 2
    fields: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)


def _re(s: str | None) -> re.Pattern | None:
    return re.compile(s) if s else None


def resolve_rules_path(name: str | Path) -> Path:
    p = Path(name)
    if p.exists():
        return p
    q = RULES_DIR / (str(name) if str(name).endswith(".toml") else f"{name}.toml")
    if q.exists():
        return q
    raise FileNotFoundError(f"找不到规则文件：{name}（也查过 {RULES_DIR}）")


def load_rules(name: str | Path) -> Rules:
    path = resolve_rules_path(name)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    w, inv, h, s, lg, pg = (raw.get(k, {}) for k in ("work", "inventory", "heading", "sections", "legend", "page"))
    names = dict(s.get("names", {}))
    fields: list[str] = []
    for v in list(names.values()) + list(s.get("fuzzy", {}).values()):
        if v not in fields:
            fields.append(v)
    bp = w.get("body_pages") or [1, 100000]
    ip = inv.get("pages")
    return Rules(
        raw=raw, path=str(path),
        body_pages=(int(bp[0]), int(bp[1])),
        page_offset=int(w.get("page_offset", 0)),
        expected_species=inv.get("expected_species"),
        inventory_source=inv.get("source", ""),
        inventory_pages=(int(ip[0]), int(ip[1])) if ip else None,
        inventory_line=_re(inv.get("line")),
        species=re.compile(h["species"]),
        max_wrap_lines=int(h.get("max_wrap_lines", 2)),
        stop=[re.compile(x) for x in h.get("stop", [])],
        genus=_re(h.get("genus")),
        family=_re(h.get("family")),
        subfamily=_re(h.get("subfamily")),
        section_names=names,
        section_fuzzy=dict(s.get("fuzzy", {})),
        sentence_end=s.get("sentence_end", "。"),
        legend_start=re.compile(lg["start"]),
        legend_item=re.compile(lg["item"]),
        legend_inner=re.compile(lg["inner_item"]),
        legend_tail=re.compile(lg.get("tail", r"^\s*[（(]仿")),
        legend_short_tail=int(lg.get("short_tail", 12)),
        header_max_lines=int(pg.get("header_max_lines", 5)),
        header=[re.compile(x) for x in pg.get("header", [])],
        noise=[re.compile(x) for x in pg.get("noise", [])],
        range_dash=bool(raw.get("normalize", {}).get("range_dash", False)),
        fields=fields,
        required=list(s.get("required", fields)),
        zh_suffix=_re(h.get("zh_suffix")),
        merge=bool(raw.get("merge", {}).get("enabled", False)),
        merge_max_insert=int(raw.get("merge", {}).get("max_insert", 2)),
    )
