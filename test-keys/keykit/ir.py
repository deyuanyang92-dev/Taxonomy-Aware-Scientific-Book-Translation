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


_PAGEREF = re.compile(r"[（(]\s*(?:p\.?|pp\.?|第)\s*\d+[\d\s,–-]*(?:页)?\s*[）)]\s*$")
_NAME_ONLY = re.compile(r"[A-Z][A-Za-z.\xa0 ()-]{1,60}[（(]\s*(?:p\.?|第)\s*\d+\s*(?:页)?\s*[）)]\s*$")
_LEAD_TEXT = re.compile(r"\s*(?:(\d+)['′]?\s*[.．、]|[•·●])\s*(.+)", re.S)
_PAGE_TAIL = re.compile(r"\s*([（(]\s*(?:p\.?|pp\.?|第)\s*\d+[\d\s,–-]*(?:页)?\s*[）)])\s*$")
_DOTS = re.compile(r"\s*[.…·．]{3,}\s*(\S.*)$")


def split_dest(target: str) -> tuple[str, str]:
    """去向末尾的图号或页码括注拆出（括注进 Lead.fig，排版时内部禁断，不会折成「（第」/「51 页）」）。"""
    tg, fig = split_fig(target)
    if fig:
        return tg, fig
    m = _PAGE_TAIL.search(target)
    return (target[: m.start()], m.group(1)) if m and target[: m.start()].strip() else (target, "")


def _couplet_lead(b: dict[str, Any], field: str) -> tuple[int | None, Lead]:
    """role=couplet 块 -> (显式序号或 None=沿用上一偶句, Lead)。

    marker：'3.' 为序号；'•'/空 = 同一偶句的第二支。
    name+target 约定：target 数字 -> jump；target 为页码括注（'(p. 413)'）-> 名字与页码合成去向；
    target 为拉丁学名 -> 名字当中文名；target 空而 name 非空 -> name 即去向（含「（第49页）」）。
    """
    c = b.get("couplet") or {}
    num = _int(c.get("lead")) or _int(c.get("marker"))
    tgt = str(c.get("target") or "").strip()
    name = str(c.get("name") or "").strip()
    if not re.search(r"\w", name):
        name = ""  # 仅标点（'.'）不是名字
    txt = b.get(field) or b.get("text", "")
    if re.fullmatch(r"\d+", tgt):
        return num, Lead(txt, "jump", tgt)
    if tgt and name and _PAGEREF.fullmatch(tgt):
        return num, Lead(txt, "taxon", name, fig=tgt)
    if tgt:
        tg, fig = split_fig(tgt)
        return num, Lead(txt, "taxon", tg, fig=fig, name_zh=name)
    if name:
        tg, fig = split_dest(name)
        return num, Lead(txt, "taxon", tg, fig=fig)
    return num, Lead(txt, "none", "")


def from_imajima_json(path: Path | str, lang: str = "zh", field: str = "translation") -> list[KeyIR]:
    """aligned/Imajima JSON -> KeyIR 列表。

    分表：heading 块；INDEX 块以「检索表」结尾；偶句序号回到 1（上一表已有 >=2 偶句）。
    吸收被误标成 INDEX/BODY 的偶句行：纯去向行补到上一支缺去向的 lead；
    「N. 正文」「• 正文」行成新 lead；「正文 ..... 去向」行补全上一支。
    """
    d = json.loads(Path(path).read_text("utf-8"))
    out: list[KeyIR] = []
    cur: KeyIR | None = None
    by_key: dict[int, Couplet] = {}
    last_num = 0
    chain = False  # 上一块仍属检索表（偶句或被吸收的行）：只有此时才吸收 INDEX/BODY 误标行

    def new_key(h: str) -> KeyIR:
        nonlocal cur, by_key, last_num
        cur = KeyIR(h, [], lang, "")
        out.append(cur)
        by_key, last_num = {}, 0
        return cur

    def add(num: int | None, ld: Lead) -> None:
        nonlocal last_num
        k = cur if cur is not None else new_key("")
        restart = (num == 1 and len(k.couplets) >= 2 and by_key.get(1) is not None
                   and len(by_key[1].leads) >= 2 and last_num > 1)
        # 序号跳号（5 -> 19）：中间的表缺失，前后不是同一张表
        gap = num is not None and k.couplets and num not in by_key and num > max(by_key) + 1
        if restart or gap:
            k = new_key("")
        n = num if num is not None else (last_num or len(k.couplets) + 1)
        cp = by_key.get(n)
        if cp is None:
            cp = Couplet(n, None, [])
            by_key[n] = cp
            k.couplets.append(cp)
        cp.leads.append(ld)
        last_num = n

    def last_lead() -> Lead | None:
        if cur is None or not cur.couplets:
            return None
        return cur.couplets[-1].leads[-1] if cur.couplets[-1].leads else None

    def absorb(lines: list[str]) -> bool:
        """把 INDEX/BODY 行当检索表行吸收；全部行都认得才算（返回 True）。"""
        multi = len(lines) > 1
        for i, ln in enumerate(lines):
            ll = last_lead()
            if _NAME_ONLY.fullmatch(ln) and ll is not None and ll.kind == "none":
                ll.kind = "taxon"
                ll.target, ll.fig = split_dest(ln)
                continue
            m = _LEAD_TEXT.fullmatch(ln)
            if m:
                body = m.group(2).strip()
                dm = _DOTS.search(body)
                if dm:
                    tg, fig = split_dest(dm.group(1).strip())
                    ld = Lead(body[: dm.start()].strip(), "taxon", tg, fig=fig)
                else:
                    ld = Lead(body, "none", "")
                add(int(m.group(1)) if m.group(1) else None, ld)
                continue
            dm = _DOTS.search(ln)
            if dm and ll is not None and ll.kind == "none":
                ll.text = (ll.text + ln[: dm.start()]).strip()
                ll.kind = "taxon"
                ll.target, ll.fig = split_dest(dm.group(1).strip())
                continue
            if multi and i > 0 and ll is not None and ll.kind != "none":
                add(None, Lead(ln, "none", ""))  # 多行块里去向行之后的无标记行 = 同偶句下一支
                continue
            return False
        return True

    for pg in d.get("pages", []):
        for b in pg.get("blocks", []):
            role = b.get("role")
            txt = (b.get(field) or b.get("text", "")).strip()
            was_chain, chain = chain, role == "couplet"
            titled = txt.endswith("检索表") and len(txt) < 40
            if role == "heading" or (str(role).lower() == "index" and titled):
                if cur is None or not cur.couplets or re.search("检索|[Kk]ey", txt):
                    new_key(txt)
                    chain = True  # 紧随标题的 INDEX/BODY 行也是本表的偶句行
                # else：种名等标题夹在表中，不拆表、不当表标题
            elif role == "couplet":
                num, ld = _couplet_lead(b, field)
                add(num, ld)
            elif str(role).lower() in ("index", "body"):
                lines = [s.strip() for s in txt.split("\n") if s.strip()]
                if not lines:
                    continue
                if was_chain and cur is not None:
                    chain = absorb(lines)
                elif (len(lines) > 1 and (m0 := _LEAD_TEXT.fullmatch(lines[0])) and m0.group(1)
                        and _NAME_ONLY.fullmatch(lines[1])):
                    new_key("")  # 无标题、无偶句块的表尾：整块都是检索表行才起新表
                    chain = absorb(lines)
    return [k for k in out if k.couplets]
