"""Compare two layout fingerprints: is the output laid out like the source?

Characters differ between a source and its translation, so only structure is
compared.  Tier A mismatches fail; tier B only warn; tier C (fonts, absolute
sizes, page count, folios) is recorded, never compared.  Per-book differences
go in a config file (`likeness.json`), never in this code.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from booklayout import fontlevels
from booklayout.fingerprint import fingerprint


@dataclass
class LikenessConfig:
    role_ratio_min: float = 0.8
    level_tol: int = 0
    figure_tol: int = 0
    caption_tol: int = 0
    compare_book: bool = False   # contents-page presence: only meaningful for whole books
    columns_out: int | None = None  # fixed column count of the output (e.g. 1); source's is then not compared
    skip: list[str] = field(default_factory=list)  # field names not to check


def load_config(path: Path | None) -> LikenessConfig:
    if path is None:
        return LikenessConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {f.name for f in fields(LikenessConfig)}
    bad = sorted(set(data) - names)
    if bad:
        raise ValueError(f"unknown likeness config keys: {bad}")
    return LikenessConfig(**data)


def _plain_levels(roles: list[str]) -> list[str]:
    """Collapse H1..H9 to H, then merge repeats the way the fingerprint does."""
    seq = ["H" if len(r) == 2 and r[0] == "H" and r[1].isdigit() else r for r in roles]
    return [r for i, r in enumerate(seq) if i == 0 or seq[i - 1] != r]


def compare(src: dict, out: dict, cfg: LikenessConfig | None = None) -> dict:
    """Return {pass, n_fail, n_warn, items:[{field,tier,ok,src,out,rule}], info}."""
    cfg = cfg or LikenessConfig()
    items: list[dict] = []

    def add(name: str, tier: str, ok: bool, s: Any, o: Any, rule: str) -> None:
        if name in cfg.skip:
            return
        items.append({"field": name, "tier": tier, "ok": ok, "src": s, "out": o, "rule": rule})

    # Heading rung numbers come from each document's own font ladder (rung 6 of the source can
    # be rung 4 of the output), so the sequence compares "heading or not"; the number of rungs
    # is its own check (heading.n_levels).
    s_roles, o_roles = _plain_levels(src["roles"]), _plain_levels(out["roles"])
    ratio = difflib.SequenceMatcher(None, s_roles, o_roles, autojunk=False).ratio()
    add("roles", "A", ratio >= cfg.role_ratio_min, len(s_roles), len(o_roles),
        f"role sequence ratio {ratio:.2f} >= {cfg.role_ratio_min} (heading rungs not compared)")
    sl, ol = src["heading"]["n_levels"], out["heading"]["n_levels"]
    add("heading.n_levels", "A", abs(sl - ol) <= cfg.level_tol, sl, ol, f"|diff| <= {cfg.level_tol}")
    add("heading.numbered", "B", src["heading"]["numbered"] == out["heading"]["numbered"],
        src["heading"]["numbered"], out["heading"]["numbered"], "numbering present on both or neither")
    add("figures", "A", abs(src["figures"] - out["figures"]) <= cfg.figure_tol, src["figures"], out["figures"],
        f"|diff| <= {cfg.figure_tol}")
    add("captions", "A", abs(src["captions"] - out["captions"]) <= cfg.caption_tol, src["captions"], out["captions"],
        f"|diff| <= {cfg.caption_tol}")
    if cfg.columns_out is not None:
        add("columns", "A", out["columns"] == cfg.columns_out, src["columns"], out["columns"],
            f"output must have {cfg.columns_out} column(s); source value not compared")
    else:
        add("columns", "A", src["columns"] == out["columns"], src["columns"], out["columns"], "modal column count equal")
    fs, fo = src["furniture"], out["furniture"]
    ts = (fs["position"], fs["kinds"], fs["folio_rule"])
    to = (fo["position"], fo["kinds"], fo["folio_rule"])
    add("furniture.type", "A", ts == to, ts, to, "position + kind + folio rule equal")
    add("furniture.head_rule_line", "B", fs["head_rule_line"] == fo["head_rule_line"],
        fs["head_rule_line"], fo["head_rule_line"], "running-head rule present on both or neither")
    add("italic.present", "A", src["italic"]["present"] == out["italic"]["present"], src["italic"], out["italic"],
        "italic scientific names present on both or neither")
    if cfg.compare_book:
        add("book.contents", "A", bool(src["book"]["contents_page"]) == bool(out["book"]["contents_page"]),
            src["book"]["contents_page"], out["book"]["contents_page"], "contents page present on both or neither")
    return {
        "pass": all(i["ok"] for i in items if i["tier"] == "A"),
        "n_fail": sum(not i["ok"] for i in items if i["tier"] == "A"),
        "n_warn": sum(not i["ok"] for i in items if i["tier"] == "B"),
        "n_a": sum(i["tier"] == "A" for i in items),
        "items": items,
        "info": {"not_compared": {"src": src["allowed_info"], "out": out["allowed_info"],
                                  "pages": [src["n_pages"], out["n_pages"]]}},
    }


def _pages(pdf: Path, spec: str | None) -> list[int] | None:
    import fitz

    if not spec:
        return None
    d = fitz.open(str(pdf))
    n = len(d)
    d.close()
    return fontlevels.parse_pages(spec, n)


def run(src: Path, out: Path, src_pages: str | None = None, out_pages: str | None = None,
        config: Path | None = None) -> dict:
    """Fingerprint both PDFs and compare; used by the CLI, `qa` and `make`."""
    return compare(fingerprint(src, _pages(src, src_pages)), fingerprint(out, _pages(out, out_pages)),
                   load_config(config))


def failures(res: dict) -> list[str]:
    return [f"likeness {i['field']}: src={i['src']} out={i['out']} ({i['rule']})"
            for i in res["items"] if not i["ok"] and i["tier"] == "A"]


def cmd_likeness(a: Any) -> int:
    res = run(a.src, a.out, a.src_pages, a.out_pages, a.config)
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ok_a = res["n_a"] - res["n_fail"]
    print(f"likeness {'PASS' if res['pass'] else 'FAIL'}: tier A {ok_a}/{res['n_a']}, warnings {res['n_warn']}")
    for i in res["items"]:
        if not i["ok"]:
            print(f"  [{i['tier']}] {i['field']}: src={i['src']} out={i['out']}  ({i['rule']})")
    return 0 if res["pass"] else 1


def add_parser(sub: Any) -> None:
    p = sub.add_parser("likeness", help="is the output PDF laid out like the source PDF (structure, not characters)")
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--src-pages")
    p.add_argument("--out-pages")
    p.add_argument("--config", type=Path, help="likeness.json (tolerances, columns_out, skip)")
    p.add_argument("--json", type=Path)
    p.set_defaults(func=cmd_likeness)
