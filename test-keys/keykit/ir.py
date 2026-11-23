"""检索表中间表示（IR）：Lead / Couplet / KeyIR 及三种读入。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .keygraph import GKey


@dataclass
class Lead:
    text: str
    kind: str = "none"  # jump | taxon | none
    target: str = ""
    page: int | None = None
    fig: str = ""
    name_zh: str = ""


@dataclass
class Couplet:
    num: int
    backref: int | None = None
    leads: list[Lead] = field(default_factory=list)


@dataclass
class KeyIR:
    heading: str = ""
    couplets: list[Couplet] = field(default_factory=list)
    lang: str = "zh"
    source_style: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> KeyIR:
        cps = [
            Couplet(int(c["num"]), c.get("backref"), [Lead(**ld) for ld in c.get("leads", [])])
            for c in d.get("couplets", [])
        ]
        return cls(d.get("heading", ""), cps, d.get("lang", "zh"), d.get("source_style", ""))


def dump_irs(irs: list[KeyIR], path: Path) -> None:
    Path(path).write_text(json.dumps({"keys": [k.to_json() for k in irs]}, ensure_ascii=False, indent=1), "utf-8")


def load_irs(path: Path) -> list[KeyIR]:
    d = json.loads(Path(path).read_text("utf-8"))
    return [KeyIR.from_json(k) for k in d["keys"]]


def _int(s: Any) -> int | None:
    m = re.match(r"\s*(\d+)", str(s)) if s not in (None, "") else None
    return int(m.group(1)) if m else None


_FIG = re.compile(r"\s*([（(]\s*(?:图|Fig\.?|figs?\.?)\s*[\d\w, –-]+[）)])\s*$")


def split_fig(target: str) -> tuple[str, str]:
    """去向末尾的图号括注拆出：('Genus sp. （图12）') -> ('Genus sp.', '（图12）')。"""
    m = _FIG.search(target)
    return (target[: m.start()], m.group(1)) if m else (target, "")


def from_keygraph(key: GKey, lang: str = "zh") -> KeyIR:
    from .profile import detect_style

    order: list[str] = []
    groups: dict[str, list[Any]] = {}
    for b in key.branches:
        c = b.couplet or str(len(order) + 1)
        if c not in groups:
            order.append(c)
            groups[c] = []
        groups[c].append(b)
    cps: list[Couplet] = []
    for i, c in enumerate(order, 1):
        bs = groups[c]
        num = _int(c) or i
        bref = next((_int(b.backref) for b in bs if b.backref), None)
        leads = []
        for b in bs:
            if b.kind == "jump" and (b.jump or b.target):
                ld = Lead(b.text, "jump", str(b.jump or b.target), b.page)
            elif b.kind in ("taxon", "page") and b.target:
                tg, fig = split_fig(b.target)
                ld = Lead(b.text, "taxon", tg, b.page, fig)
            else:
                ld = Lead(b.text, "none", b.target or "", b.page)
            leads.append(ld)
        cps.append(Couplet(num, bref, leads))
    style = detect_style([b.raw_lead for b in key.branches if b.raw_lead]) or ""
    return KeyIR(key.heading, cps, lang, style)


def from_markdown(md: str, lang: str = "zh") -> list[KeyIR]:
    from .keygraph import parse_text

    return [from_keygraph(k, lang) for k in parse_text(md)]


def from_imajima_json(path: Path | str, lang: str = "zh", field: str = "translation") -> list[KeyIR]:
    d = json.loads(Path(path).read_text("utf-8"))
    out: list[KeyIR] = []
    cur: KeyIR | None = None
    by_key: dict[int, Couplet] = {}
    for pg in d.get("pages", []):
        for b in pg.get("blocks", []):
            role = b.get("role")
            if role == "heading":
                cur = KeyIR(b.get(field) or b.get("text", ""), [], lang, "")
                out.append(cur)
                by_key = {}
            elif role == "couplet":
                if cur is None:
                    cur = KeyIR("", [], lang, "")
                    out.append(cur)
                c = b.get("couplet") or {}
                num = _int(c.get("lead")) or _int(c.get("marker")) or len(cur.couplets) + 1
                tgt = str(c.get("target") or "").strip()
                txt = b.get(field) or b.get("text", "")
                if re.fullmatch(r"\d+", tgt):
                    ld = Lead(txt, "jump", tgt)
                elif tgt:
                    tg, fig = split_fig(tgt)
                    ld = Lead(txt, "taxon", tg, fig=fig, name_zh=c.get("name") or "")
                else:
                    ld = Lead(txt, "none", "")
                cp = by_key.get(num)
                if cp is None:
                    cp = Couplet(num, None, [])
                    by_key[num] = cp
                    cur.couplets.append(cp)
                cp.leads.append(ld)
    return out
