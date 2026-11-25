"""Language- and book-independent dichotomous-key graph layer.

Parses key text (page-marked markdown/plain text) into couplets and branches,
normalises lead numbers (1 / 1' / 1a / 1(3) / dash alternates / indented keys),
checks the graph (dangling jumps, cycles, unreachable couplets ...), aligns
a source key with its translation and gates "expected keys" documents.

CLI: python3 -m booklayout.keygraph --source a.md [--translation b.md]
     [--expect-keys] [--entries 1,5] [--out r.json]

Known limits: see ``LIMITS`` at the bottom of the module.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Sequence

PAGE_MARK = re.compile(r"<!--\s*PDF p\.(\d+)\s*-->")
LEADER = re.compile(r"(?:[.…·・⋯]\s*){3,}|(?:[…⋯]\s*){2,}|(?<=\s)(?:\.\s+){2,}(?=\S)")
DASH_CHARS = "—–-•·▪●*"
DASHES = "—–\\-•·▪●*"  # regex character-class form
PRIMES = "'’′´"
HEADING_RE = re.compile(
    r"^\W*(?:[^\W\d]+\s+){0,5}?(?:Keys?|Claves?|Clavis|Cl[eé]fs?|Cl[eé]s?|Bestimmungs\w*|Schl[uü]ssel|"
    r"[Тт]аблица|Ключ\w*|Определител\w*)(?!\w)|.{0,12}?(?:検索|检索|檢索)")
CONT_RE = re.compile(r"continued|cont\.|suite\b|Fortsetzung|continuaci|продолжение|続き|续|續", re.I)
RUNNING_HEAD = re.compile(
    r"^\s*(?:\d{1,4}\s+[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*|"
    r"[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*\s+\d{1,4})\s*$")
PAGE_ONLY = re.compile(r"^\s*(?:\d{1,4}|[ivxlc]+)\s*$", re.I)
JUMP_ONLY = re.compile(r"^\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?$")

_PAGE_WORDS = r"(?:pp?\.|S\.|págs?\.|pags?\.|pág\b|pag\b|páginas?|paginas?|seite|стр\.|с\.|pages?)"
PAGE_RES = [
    re.compile(r"(?<![^\W\d_])\(?\s*" + _PAGE_WORDS + r"\s*(?P<p>\d{1,4})(?:\s*[-–]\s*\d{1,4})?\s*\)?", re.I),
    re.compile(r"\(?\s*第\s*(?P<p>\d{1,4})\s*[页頁]\s*\)?"),
    re.compile(r"\(?\s*(?P<p>\d{1,4})\s*(?:[页頁]|ページ)\s*\)?"),
]
_JUMP_PRE = r"(?:(?:→|->|⇒|see|go to|goto|vide|siehe|voir|ir a|vaya a|转|見|见)\s*)?"
JUMP_RE = re.compile(
    r"^" + _JUMP_PRE + r"(?P<n>\d{1,3})['’′]?(?:\s*(?:[-–—]|to|bis)\s*\d{1,3}['’′]?)?\s*(?:へ)?$", re.I)
TRAIL_ARROW = re.compile(
    r"\s(?P<t>(?:→|->|⇒|see|go to|goto|转|見|见)\s*\d{1,3}['’′]?)\s*$|(?P<j>\d{1,3})へ\s*$", re.I)
TRAIL_TARGET = re.compile(r"[\s(](?P<t>\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?)\s*$")
TRAIL_PAGE = re.compile(
    r"(?<![^\W\d_])(?P<t>\(?\s*(?:" + _PAGE_WORDS + r"\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?|第\s*\d{1,4}\s*[页頁]|"
    r"\d{1,4}\s*(?:[页頁]|ページ))\s*\)?)\s*$", re.I)
GAP_TARGET = re.compile(r"(?:\t|\s{3,})(?P<t>\S.{0,80})$")

_LTAIL = (r"(?:\s+(?:(?:subsp|ssp|var|subvar|fo|cf|aff|sp|spp|nov)\.|"
          r"(?!(?:and|or|und|oder|et|ou|with|the|via)\b)[a-zà-ÿ][a-zà-ÿ\-]{2,}))*")
LATIN_RE = re.compile(r"[A-Z]\.\s*[a-z][a-z\-]{2,}" + _LTAIL + r"|[A-Z][a-zà-ÿ]{2,}" + _LTAIL)

_LET = "[A-Za-zа-яА-ЯёЁ]"
_LEADTOK = re.compile(
    r"^\s*(?P<tok>[" + DASHES + r"]|\d{1,3}(?:" + _LET + r"(?!" + _LET + r"))?(?:\(\d{1,3}\))?[" + PRIMES +
    r"]*(?:\(\d{1,3}\))?[.)、:]?|[IVX]{1,4}[" + PRIMES + r"]?[.)])(?=\s|$|(?<=[.)、:])[^\x00-\x7f])")
_NUM = re.compile(
    r"(?P<n>\d{1,3})(?P<l>" + _LET + r")?(?:\((?P<b1>\d{1,3})\))?(?P<p>[" + PRIMES +
    r"]*)(?:\((?P<b2>\d{1,3})\))?[.)、:]?")
_ROMAN = re.compile(r"(?P<r>[IVX]{1,4})(?P<p>[" + PRIMES + r"]?)[.)]")
_REP_LABEL = re.compile(r"^(?P<l>[A-Za-z])(?P=l)*[.)](?=\s)")
FIG_WORDS = r"(?:図|图|圖|Figs?\.?|рис\.?|Abb\.?|Taf\.?|Pls?\.?|Plates?|Tab\.?)"
_FIGNUM = r"\d+[A-Za-z]?(?:\s*[-–、,&]\s*\d+[A-Za-z]?)*"
FIG_PRE = re.compile(r"^\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?[\s,:;]*", re.I)
FIG_SUF = re.compile(r"[\s,;]*\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?$", re.I)
FIG_TAIL = re.compile(FIG_WORDS + r"\s*$", re.I)
PART_RE = re.compile(r"\s*\((?:part|pars|partim|p\.\s?p\.|in part|部分|一部)\)", re.I)
RANK_WORDS = {"属", "屬", "科", "亚科", "亞科", "族", "目", "纲", "綱", "种", "種", "Genus", "Subgenus", "Family", "Subfamily", "Superfamily", "Tribe", "Order", "Suborder", "Class",
              "Phylum", "Section", "Series", "Род", "Подрод", "Семейство", "Подсемейство", "Отряд"}
RANK_MARKS = {"subsp.", "ssp.", "var.", "subvar.", "f.", "fo.", "forma", "subf.", "sect.", "ser.", "cv."}
QUAL_MARKS = {"cf.", "aff.", "sp.", "spp.", "nov.", "n.", "gen.", "indet.", "inc."}
AUTH_PARTICLES = {"ex", "et", "in", "and", "und", "y", "e", "&", "de", "van", "von", "der", "den", "du", "la", "le"}
COUNT_NOUN = re.compile(
    r"(?:antenn\w*|segments?|pairs?|chaetigers?|chaetae|setae|articles?|teeth|tooth|rays?|spines?|rows?|lobes?|eyes?|"
    r"papillae|numbers?|elytra|rings?|annuli|joints?|cirri|lamellae|tentacles?|palps?|節|节|对|對|个|個|枚|本|条|條)\s*$",
    re.I)
SERIAL_TAXON = re.compile(
    r"(?:^|(?<=[\s—–-]))(?P<t>(?:\d{1,3}|[IVXl]{1,4})[.)]\s*(?:"
    r"(?:(?:Genus|Subgenus|Family|Subfamily|Род|Семейство|Подсемейство)\s+|(?:属|屬|科|亚科|亞科|种|種)\s*)"
    r"\*?[A-ZА-Я][^\d]{2,100}?"
    r"|[A-Z]\.\s*[a-z]{2,}[^\d]{0,60}?"
    r"|[A-Z][a-z]{2,}\s+[a-z]{2,}\s+\(?[A-Z][^\d]{1,60}?)"
    r"(?:,?\s*\d{4}[a-z]?\)?)?(?:\s*\(\s*(?:pp?\.|S\.|стр\.)\s*\d{1,4}\s*\))?)$")
ABBR_TAIL = re.compile(r"(?<=\s)(?P<t>[A-Z]\.\s*[a-z][a-z\-]{2,}(?:\s+[a-z][a-z\-]{2,})?)\s*$")
_BULLET = re.compile(r"^[-*•·▪●–—]\s+")


@dataclass
class GBranch:
    lead: str
    couplet: str = ""
    alt: str = ""
    raw_lead: str = ""
    text: str = ""
    kind: str = "none"
    target: str = ""
    jump: str | None = None
    page: int | None = None
    backref: str | None = None
    src_page: int = 0
    hint: str = ""
    bare: bool = False

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GKey:
    heading: str = ""
    branches: list[GBranch] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)

    def asdict(self) -> dict[str, Any]:
        return {"heading": self.heading, "entries": self.entries, "branches": [b.asdict() for b in self.branches]}


class Target(NamedTuple):
    kind: str  # jump | page | taxon | none
    jump: str | None
    page: int | None
    taxon: str


def _roman(s: str) -> int | None:
    vals = {"I": 1, "V": 5, "X": 10}
    tot = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        tot += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return tot if 0 < tot < 40 else None


def _is_dash(tok: str) -> bool:
    return len(tok) == 1 and tok in DASH_CHARS


def _alt_letter(ch: str) -> str:
    c = ch.lower()
    cyr = "абвгде"
    return "abcdef"[cyr.index(c)] if c in cyr else c


def norm_lead(raw: str, prev_num: str | None) -> tuple[str, str, str | None] | None:
    """Normalise a lead token. Returns (couplet, alt_hint, backref) or None.

    alt_hint: "" plain number, a letter (explicit letter or prime count),
    "+" dash/bullet alternate of prev_num.
    """
    s = unicodedata.normalize("NFKC", raw).strip()
    if not s:
        return None
    if _is_dash(s):
        return (prev_num, "+", None) if prev_num else None
    m = _NUM.fullmatch(s)
    if m:
        hint = ""
        dg = m.group("n")
        if prev_num and not m.group("p") and (
                (m.group("l") in ("l", "I") and str(int(dg)) == prev_num)
                or (not m.group("l") and len(dg) == 2 and dg[0] == dg[1] == prev_num)):
            return prev_num, "b", None  # OCR read a prime as l / I / a second digit
        if m.group("l"):
            hint = _alt_letter(m.group("l"))
        elif m.group("p"):
            hint = chr(min(97 + len(m.group("p")), 122))
        bk = m.group("b1") or m.group("b2")
        return str(int(m.group("n"))), hint, str(int(bk)) if bk else None
    m = _ROMAN.fullmatch(s)
    if m:
        v = _roman(m.group("r"))
        if v is None:
            return None
        return str(v), (chr(min(97 + len(m.group("p")), 122)) if m.group("p") else ""), None
    return None


_KEEP_DOT = re.compile(r"(?:(?<![A-Za-z])(?:sp|spp|cf|aff|ssp|subsp|var|nov|gen|n)|(?<![A-Za-z])[A-Z])\.$")
_NAME_OPEN = re.compile(r"(?:^|\s)(?:[A-Z]\.|[A-Z][a-zà-ÿ]{2,}\s+[a-zà-ÿ]{3,}(?:\s+[a-zà-ÿ]{3,})?)$")
_EPI = re.compile(r"[a-zà-ÿ][a-zà-ÿ\-]{2,}")


def _clean_taxon(s: str) -> str:
    s = s.strip(" \t,;:—–-·…・")
    if s.endswith(".") and not _KEEP_DOT.search(s):
        s = s.rstrip(". ")
    return s


def canon_taxon(s: str) -> str:
    """Canonical taxon text: names, ranks, cf./aff./sp. kept; authorities, years and (part) dropped."""
    s = PART_RE.sub("", s).strip()
    toks = s.split()
    k = 1 if len(toks) > 1 and toks[0] in RANK_WORDS else 0
    if k >= len(toks) or not re.fullmatch(r"[A-ZА-Я][a-zà-ÿа-я\-]*\d{0,2}\.?,?", toks[k]):
        return s
    out = [re.sub(r"(?<=[^\W\d])\d{1,2}(?=\.?,?$)", "", toks[k]).rstrip(",")]  # drop glued footnote digit
    rest = toks[k + 1:]
    if len(rest) > 1 and re.fullmatch(r"\([A-Z][a-zà-ÿ]+\)", rest[0]) and _EPI.fullmatch(rest[1]):
        out.append(rest[0])
        rest = rest[1:]
    auth = False
    for i, t in enumerate(rest):
        tl = t.rstrip(",;")
        nxt_epi = i + 1 < len(rest) and bool(_EPI.fullmatch(rest[i + 1].rstrip(",;")))
        if tl.lower() in RANK_MARKS and nxt_epi:
            auth = False
            out.append(tl)
        elif auth:
            continue
        elif tl in QUAL_MARKS:
            out.append(tl)
        elif tl in AUTH_PARTICLES:
            auth = True
        elif _EPI.fullmatch(tl) or re.fullmatch(r"\d{1,3}", tl) or (
                i == 0 and len(out) == 1 and re.fullmatch(r"[a-zà-ÿ]{2}", tl)):
            out.append(tl)
        else:
            auth = True
    return " ".join(out)


def parse_target(s: str) -> Target:
    """Classify a branch target: jump number, page reference, taxon (+page) or none."""
    t = unicodedata.normalize("NFKC", s or "").strip()
    t = re.sub(r"^[.…·・⋯\s]+", "", t.replace("*", "")).strip()
    t = re.sub(r"^\d{1,3}\s*[.)]\s+(?=[^\W\d_])", "", t)
    t = re.sub(r"^[IVXl]{1,4}[.)]\s+(?=(?:Genus|Subgenus|Family|Род|Семейство)\s)", "", t)  # OCR'd serial
    page: int | None = None
    for rx in PAGE_RES:
        last = None
        for last in rx.finditer(t):
            pass
        if last is not None:
            page = int(last.group("p"))
            t = (t[:last.start()] + " " + t[last.end():]).strip()
            break
    rem = _clean_taxon(t)
    if not JUMP_RE.match(rem):
        rem = _clean_taxon(FIG_SUF.sub("", FIG_PRE.sub("", rem)))
    rem = _clean_taxon(PART_RE.sub("", rem))
    if not rem:
        return Target("page" if page is not None else "none", None, page, "")
    jm = JUMP_RE.match(rem)
    if jm:
        return Target("jump", str(int(jm.group("n"))), page, "")
    rm = re.fullmatch(r"([IVX]{1,4})[" + PRIMES + r"]?", rem)
    if rm and _roman(rm.group(1)):
        return Target("jump", str(_roman(rm.group(1))), page, "")
    return Target("taxon", None, page, canon_taxon(rem))


def _split(text: str) -> tuple[str, str, bool]:
    """(text, target, bare); bare = target is only a trailing number with no leader/gap/arrow."""
    m = None
    for m in LEADER.finditer(text):
        pass
    if m is not None:
        return text[:m.start()].strip(), text[m.end():].strip(), False
    a = TRAIL_ARROW.search(text)
    if a:
        return text[:a.start()].strip(), (a.group("t") or a.group("j")).strip(), False
    g = GAP_TARGET.search(text)
    if g and (JUMP_RE.match(g.group("t").strip()) or LATIN_RE.match(g.group("t").strip())
              or any(r.fullmatch(g.group("t").strip()) for r in PAGE_RES)):
        return text[:g.start()].strip(), g.group("t").strip(), False
    st = SERIAL_TAXON.search(text)
    if st:
        return text[:st.start()].strip(" —–-"), st.group("t").strip(), False
    p = TRAIL_PAGE.search(text)
    if p:
        return text[:p.start()].strip(), p.group("t").strip(), False
    ab = ABBR_TAIL.search(text)
    if ab:
        return text[:ab.start()].strip(), ab.group("t").strip(), False
    t = TRAIL_TARGET.search(text)
    if t and not FIG_TAIL.search(text[:t.start()]) and not COUNT_NOUN.search(text[:t.start()].strip()):
        return text[:t.start()].strip(), t.group("t").strip(), True
    return text.strip(), "", False


def split_target(text: str) -> tuple[str, str]:
    """Split branch text from its target (dot leader, arrow, wide gap, page, abbreviated name, trailing number)."""
    left, target, _ = _split(text)
    return left, target


def _has_target(text: str) -> bool:
    return bool(split_target(text)[1])


def _mk(info: tuple[str, str, str | None], raw_lead: str, text: str, target: str, page: int,
        bare: bool = False) -> GBranch:
    couplet, hint, back = info
    tg = parse_target(target)
    return GBranch(lead=couplet + (hint if hint != "+" else ""), couplet=couplet, alt="", raw_lead=raw_lead,
                   text=text.strip(), kind=tg.kind, target=tg.taxon if tg.kind == "taxon" else target.strip(), jump=tg.jump, page=tg.page,
                   backref=back, src_page=page, hint=hint, bare=bare)


class _Open:
    def __init__(self, info: tuple[str, str, str | None], raw_lead: str, text: str, page: int) -> None:
        self.info, self.raw_lead, self.text, self.page = info, raw_lead, text, page

    def add(self, more: str) -> None:
        a = self.text
        self.text = a[:-1] + more if a.endswith("-") and more[:1].islower() else f"{a} {more}".strip()

    def complete(self) -> bool:
        return _has_target(self.text)

    def done(self) -> GBranch:
        left, target, bare = _split(self.text)
        return _mk(self.info, self.raw_lead, left, target, self.page, bare)


def _match_lead(line: str, prev_num: str | None) -> tuple[tuple[str, str, str | None], str, str, bool] | None:
    """Return (info, raw_lead, rest, weak) for a line starting with a lead token."""
    m = _LEADTOK.match(line)
    if not m:
        return None
    tok = m.group("tok")
    rest = line[m.end():].strip()
    if _is_dash(tok):
        inner = _LEADTOK.match(rest)
        if inner and not _is_dash(inner.group("tok")):
            r2 = _match_lead(rest, prev_num)
            if r2 and not r2[3]:
                return r2
        info = norm_lead(tok, prev_num)
        return (info, tok, rest, False) if info else None
    info = norm_lead(tok, prev_num)
    if info is None:
        return None
    weak = bool(re.fullmatch(r"\d{1,3}", tok))
    return info, tok, rest, weak


def _assign_alts(key: GKey) -> None:
    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
    for b in key.branches:
        groups.setdefault(b.couplet, []).append(b)
    for c, brs in groups.items():
        used: set[str] = set()
        for b in brs:
            h = b.hint
            alt = h if h and h != "+" else next(chr(x) for x in range(97, 123) if chr(x) not in used)
            used.add(alt)
            b.alt = alt
            b.lead = c + alt


def _name_open(target: str) -> bool:
    """Target ends in a name that may still lack its species / subspecies epithet."""
    if _NAME_OPEN.search(target):
        return True
    return bool(re.fullmatch(r"(?:.*\s)?[A-Z][a-zà-ÿ]{3,}", target)) \
        and not re.search(r"(?:idae|inae|aceae|ales|oidea|ini|ida|oidae|ina)$", target)


def _pair_ok(brs: list[GBranch]) -> bool:
    nums = [b.couplet for b in brs]
    if len(brs) < 2 or len(set(nums)) != len(nums) or any(b.backref is None or b.hint != "" for b in brs):
        return False
    pairs = {(b.couplet, b.backref) for b in brs}
    return not any(n == m or (m, n) not in pairs for n, m in pairs)


def _pair_backrefs(key: GKey) -> None:
    """Soviet-style paired numbering 1(8) ... 8(1): bracket = opposite lead, not a back reference."""
    brs = key.branches
    if not _pair_ok(brs):
        return
    by_num = {b.couplet: b for b in brs}

    def cp(n: str) -> str:
        return str(min(int(n), int(by_num[n].backref or n)))
    for b in brs:
        nxt = str(int(b.couplet) + 1)
        if b.kind == "none" and nxt in by_num and nxt != b.backref:
            b.kind, b.jump, b.target = "jump", cp(nxt), cp(nxt)
    for b in brs:
        b.couplet, b.backref = cp(b.couplet), None


def _drop_bare(key: GKey) -> None:
    """A bare trailing number is a jump only when that couplet exists in the key."""
    have = {b.couplet for b in key.branches}
    for b in key.branches:
        if b.bare and b.kind == "jump" and b.jump not in have:
            b.kind, b.jump, b.target = "none", None, ""


def _complete_couplets(key: GKey) -> bool:
    cnt: dict[str, int] = {}
    for b in key.branches:
        cnt[b.couplet] = cnt.get(b.couplet, 0) + 1
    return any(n >= 2 for n in cnt.values())


def _indent(raw: str) -> int:
    w = 0
    for ch in raw:
        if ch == " ":
            w += 1
        elif ch == "\t":
            w += 4
        else:
            break
    return w


def _looks_tree(items: list[tuple[int, str | None]], i: int) -> bool:
    raw = items[i][1]
    if raw is None:
        return False
    if not _REP_LABEL.match(_BULLET.sub("", raw.strip())):
        return False
    for j in range(i + 1, len(items)):
        r = items[j][1]
        if r is None or not r.strip():
            continue
        return bool(_REP_LABEL.match(_BULLET.sub("", r.strip())))
    return False


def parse_text(md: str, heading_re: re.Pattern[str] | None = None) -> list[GKey]:
    """Parse page-marked text into keys (numbered, tabular and indented styles)."""
    hre = heading_re or HEADING_RE
    items: list[tuple[int, str | None]] = []
    page = 0
    for r in md.splitlines():
        pm = PAGE_MARK.search(r)
        if pm:
            page = int(pm.group(1))
            items.append((page, None))
            rest = r[:pm.start()] + r[pm.end():]
            if rest.strip():
                items.append((page, unicodedata.normalize("NFKC", rest)))
        else:
            items.append((page, unicodedata.normalize("NFKC", r)))
    n = len(items)

    def next_sig(i: int) -> int | None:
        for j in range(i + 1, n):
            r = items[j][1]
            if r is None or r.strip():
                return j
        return None

    def next_page_leads(i: int) -> bool:
        nj = next_sig(i)
        if nj is None or items[nj][1] is not None:
            return False
        k = next_sig(nj)
        nxt = items[k][1] if k is not None else None
        return nxt is not None and _match_lead(nxt.strip(), None) is not None

    def at_page_end(i: int) -> bool:
        nj = next_sig(i)
        return nj is None or items[nj][1] is None

    keys: list[GKey] = []
    key: GKey | None = None
    mode = ""
    cur: _Open | None = None
    pending = ""
    last_num = ""
    fresh = False
    hdr_cols: dict[str, int] = {}

    def flush() -> None:
        nonlocal cur
        if cur is not None and key is not None:
            key.branches.append(cur.done())
        cur = None

    def close() -> None:
        nonlocal key, mode, last_num
        flush()
        if key is not None:
            _pair_backrefs(key)
            _drop_bare(key)
            _assign_alts(key)
        key = None
        mode = ""
        last_num = ""

    def open_key(m: str) -> GKey:
        nonlocal key, mode, pending, last_num
        key = GKey(heading=pending)
        keys.append(key)
        pending = ""
        mode = m
        last_num = ""
        return key

    def tree_from(i: int) -> int | None:
        """Consume an indented / letter-hierarchy key starting at item i; return next index or None."""
        stack: list[int] = []
        rows: list[dict[str, Any]] = []
        j = i
        while j < n:
            pg, raw = items[j]
            if raw is None or not raw.strip():
                j += 1
                continue
            line = raw.strip()
            if PAGE_ONLY.match(line):
                if rows and not rows[-1]["target"] and JUMP_ONLY.match(line) and not at_page_end(j):
                    rows[-1]["target"] = line
                j += 1
                continue
            if hre.match(line) and not _LEADTOK.match(line) and len(line) <= 120:
                if CONT_RE.search(line):
                    j += 1
                    continue
                break
            ind = _indent(raw)
            bm = _BULLET.match(line)
            content = line[bm.end():] if bm else line
            lab = _REP_LABEL.match(content)
            raw_lead = ""
            letter = ""
            if lab:
                letter = lab.group("l").lower()
                raw_lead = lab.group(0).strip()
                content = content[lab.end():].strip()
            text, target = split_target(content)
            if rows and not rows[-1]["target"] and not lab and JUMP_ONLY.match(content):
                rows[-1]["target"] = content
                j += 1
                continue
            if rows and not rows[-1]["target"] and not lab and content[:1].islower() and rows[-1]["level"] <= len(stack) + 1:
                rows[-1]["text"] = (rows[-1]["text"] + " " + text).strip()  # hanging continuation line
                rows[-1]["target"] = target
                j += 1
                continue
            nj = next_sig(j)
            nxt = items[nj][1] if nj is not None else None
            deeper = nxt is not None and _indent(nxt) > ind
            if not (target or deeper or lab):
                break
            while stack and stack[-1] > ind:
                stack.pop()
            if not stack or stack[-1] < ind:
                stack.append(ind)
            rows.append({"level": len(stack), "text": text, "target": target, "raw": raw_lead, "page": pg,
                         "letter": letter})
            j += 1
        if not rows:
            return None
        k = open_key("tree")
        st: list[int] = []
        groups: dict[tuple[int, str], str] = {}
        for idx, r in enumerate(rows):
            while st and rows[st[-1]]["level"] >= r["level"]:
                st.pop()
            parent = st[-1] if st else -1
            r["parent"] = parent
            gk = (parent, r["letter"])
            if gk not in groups:
                groups[gk] = str(len(groups) + 1)
                if parent >= 0:
                    pb = rows[parent]["branch"]
                    if pb.kind == "none":
                        pb.kind, pb.target, pb.jump = "jump", groups[gk], groups[gk]
            st.append(idx)
            b = _mk((groups[gk], "", None), r["raw"], r["text"], r["target"], r["page"])
            r["branch"] = b
            k.branches.append(b)
        for r in rows:  # a lone-letter target ("B") jumps to that letter's couplet
            b = r["branch"]
            if b.kind == "taxon" and re.fullmatch(r"[A-Za-z]", b.target):
                lt = b.target.lower()
                dest = groups.get((r["parent"], lt)) or next((v for (p, lg), v in groups.items() if lg == lt), None)
                if dest:
                    b.kind, b.jump, b.target = "jump", dest, dest
        close()
        return j

    i = 0
    while i < n:
        pg, raw = items[i]
        if raw is None:
            fresh = True
            i += 1
            continue
        line = raw.strip()
        first_on_page = fresh and bool(line)
        if line:
            fresh = False
        if not line:
            i += 1
            continue
        incomplete = cur is not None and not cur.complete()
        if first_on_page and (RUNNING_HEAD.match(line) or (
                any(ch.isupper() for ch in line) and line == line.upper() and len(line) >= 4
                and not _LEADTOK.match(line) and not hre.match(line) and not LEADER.search(line))):
            i += 1
            continue
        if key is not None and len(line) <= 120 and hre.match(line) and CONT_RE.search(line):
            i += 1
            continue
        if PAGE_ONLY.match(line):
            if cur is not None and incomplete and not first_on_page and JUMP_ONLY.match(line) \
                    and (not at_page_end(i) or next_page_leads(i)):
                cur.add(line)
            i += 1
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells) and any(cells):
                i += 1
                continue
            lm = _match_lead(cells[0] + " x", last_num or None) if cells and cells[0] else None
            if mode != "table":
                close()
                if lm is None:
                    hdr_cols.clear()
                    for ci, c in enumerate(cells):  # header row: remember taxon / page columns
                        if ci and re.fullmatch(r"(?i)类群|類群|分类群|分類群|taxon|taxa|target|destination|去向", c):
                            hdr_cols["tax"] = ci
                        elif ci and re.fullmatch(r"(?i)页码|頁碼|页|頁|pages?|págs?\.?|seite|стр\.?", c):
                            hdr_cols["page"] = ci
                    i += 1
                    continue
                open_key("table")
            assert key is not None
            if lm is None:
                if key.branches and len(cells) > 1:  # continuation row
                    b = key.branches[-1]
                    b.text = (b.text + " " + " ".join(cells[1:-1] if len(cells) > 2 else cells[1:2])).strip()
                    if len(cells) > 2 and cells[-1]:
                        tg = parse_target(cells[-1])
                        b.target, b.kind, b.jump, b.page = (tg.taxon if tg.kind == "taxon" else cells[-1]), \
                            tg.kind, tg.jump, tg.page
                i += 1
                continue
            info, rl, _, _ = lm
            tc, pc = hdr_cols.get("tax", -1), hdr_cols.get("page", -1)
            if 0 < tc < len(cells):
                target = cells[tc] + (" " + cells[pc] if 0 < pc < len(cells) and cells[pc] else "")
                text = " ".join(c for ci, c in enumerate(cells) if ci not in (0, tc, pc) and c)
            elif len(cells) >= 3:
                text, target = " ".join(cells[1:-1]), cells[-1]
            else:
                text, target = split_target(cells[1] if len(cells) > 1 else "")
            key.branches.append(_mk(info, rl, text, target, pg))
            if not _is_dash(rl):
                last_num = info[0]
            i += 1
            continue
        if mode == "table":
            close()
        if len(line) <= 120 and not incomplete and hre.match(line) and not _LEADTOK.match(line):
            close()
            if pending:
                keys.append(GKey(heading=pending))  # heading never followed by a branch
            pending = line.lstrip("# ").strip().strip("*").strip()
            hdr_cols.clear()
            i += 1
            continue
        lm = _match_lead(line, last_num or None)
        if lm is not None and mode != "tree":
            info, rl, rest, weak = lm
            ok = True
            if weak:
                exp = int(last_num) if last_num else 0
                want = {b.jump for b in key.branches} if key is not None else set()
                if cur is not None:
                    want.add(parse_target(_split(cur.text)[1]).jump)
                if key is None and not pending:
                    ok = False
                elif info[0] in want and key is not None:
                    ok = True
                elif incomplete and int(info[0]) != exp + 1:
                    ok = False
                elif incomplete and cur is not None and key is not None \
                        and not any(b.couplet == cur.info[0] for b in key.branches):
                    ok = False  # a couplet needs two branches: a lone open branch cannot be followed by a new one
                elif key is not None and int(info[0]) not in (exp, exp + 1):
                    ok = False
            if ok and _ROMAN.fullmatch(rl) and key is None and not pending:
                ok = False
            if ok:
                flush()
                if key is not None and info[0] == "1" and info[1] in ("", "a") and last_num != "1" \
                        and _complete_couplets(key):
                    close()
                elif key is not None and info[2] is not None and _pair_ok(key.branches) \
                        and info[0] in {b.couplet for b in key.branches}:
                    close()  # a closed paired-number key: numbering restarts, so a new key begins
                if key is None:
                    open_key("num")
                cur = _Open(info, rl, rest, pg)
                if not _is_dash(rl):
                    last_num = info[0]
                i += 1
                continue
        if key is None and (pending or _looks_tree(items, i)):
            j = tree_from(i)
            if j is not None:
                pending = ""
                i = j
                continue
        if key is None:
            i += 1
            continue
        if cur is not None and incomplete:
            cur.add(line)
        elif cur is not None and _EPI.fullmatch(line) and _name_open(_split(cur.text)[1]):
            cur.add(line)  # species / subspecies epithet wrapped onto its own line
        else:
            close()
        i += 1
    close()
    if pending:
        keys.append(GKey(heading=pending))
    for k in keys:
        if not any(ch.isalnum() for b in k.branches for ch in b.text + b.target):
            k.branches = []  # lost glyphs only: no valid branch
    keys = [k for k in keys if k.heading or k.branches]
    return [k for k in keys if k.heading or len(k.branches) != 1 or k.branches[0].kind != "none"]


# ---------------------------------------------------------------- checks

def _cnum(c: str) -> int:
    return int(c) if c.isdigit() else 10 ** 6


def _f(code: str, severity: str, lead: str, detail: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "lead": lead, "detail": detail}


def check(key: GKey, entries: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Graph problems of one key (single_branch ... backref_mismatch)."""
    out: list[dict[str, Any]] = []
    if key.heading and not key.branches:
        out.append(_f("empty_key", "error", "", f"key '{key.heading}' has a heading but no valid branch"))
        return out
    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
    for b in key.branches:
        groups.setdefault(b.couplet, []).append(b)
    for c, brs in groups.items():
        alts = [b.alt for b in brs]
        if "a" not in alts:
            out.append(_f("lone_alternate", "error", brs[0].lead, f"couplet {c} has alternate(s) {alts} but no 'a'"))
        if len(brs) == 1:
            out.append(_f("single_branch", "error", brs[0].lead, f"couplet {c} has one branch"))
    seen: dict[str, int] = {}
    for b in key.branches:
        seen[b.lead] = seen.get(b.lead, 0) + 1
    for lead, cnt in seen.items():
        if cnt > 1:
            out.append(_f("duplicate_lead", "error", lead, f"{lead} appears {cnt} times"))
    for b in key.branches:
        if b.kind == "none":
            out.append(_f("no_target", "error", b.lead, f"no target (p.{b.src_page})"))
    edges: dict[str, list[str]] = {c: [] for c in groups}
    incoming: dict[str, list[GBranch]] = {}
    for b in key.branches:
        if b.kind == "jump" and b.jump is not None:
            if b.jump not in groups:
                out.append(_f("dangling_jump", "error", b.lead, f"jump to missing couplet {b.jump}"))
                continue
            edges[b.couplet].append(b.jump)
            incoming.setdefault(b.jump, []).append(b)
    for b in key.branches:
        if b.backref is not None and not any(x.jump == b.couplet for x in groups.get(b.backref, [])):
            out.append(_f("backref_mismatch", "error", b.lead, f"backref {b.backref} does not jump to {b.couplet}"))
    ents = [e for e in (entries or key.entries or []) if e in groups]
    if not ents and groups:
        ents = [min(groups, key=_cnum)]
    reach: set[str] = set()
    todo = list(ents)
    while todo:
        c = todo.pop(0)
        if c in reach:
            continue
        reach.add(c)
        todo += [t for t in edges.get(c, []) if t not in reach]
    for c in groups:
        if c not in reach:
            out.append(_f("unreachable", "error", c, f"couplet {c} unreachable from {ents}"))
    out += _cycles(groups, edges)
    for t, srcs in incoming.items():
        if len(srcs) >= 2:
            out.append(_f("multi_parent", "warn", t, f"couplet {t} entered from {[s.lead for s in srcs]}"))
    return out


def _cycles(groups: OrderedDict[str, list[GBranch]], edges: dict[str, list[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    color: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()
    for root in sorted(groups, key=_cnum):
        if color.get(root):
            continue
        path = [root]
        iters = [iter(sorted(set(edges[root]), key=_cnum))]
        color[root] = 1
        while path:
            nxt = next(iters[-1], None)
            if nxt is None:
                color[path.pop()] = 2
                iters.pop()
                continue
            st = color.get(nxt, 0)
            if st == 1:
                cyc = path[path.index(nxt):]
                r = cyc.index(min(cyc, key=_cnum))
                canon = tuple(cyc[r:] + cyc[:r])
                if canon not in reported:
                    reported.add(canon)
                    out.append(_f("cycle", "error", canon[0], "cycle " + ">".join(canon + (canon[0],))))
            elif st == 0:
                color[nxt] = 1
                path.append(nxt)
                iters.append(iter(sorted(set(edges[nxt]), key=_cnum)))
    return out


# ---------------------------------------------------------------- align

def latin_names(s: str) -> list[str]:
    return [re.sub(r"\s+", " ", m.group(0)) for m in LATIN_RE.finditer(s or "")]


def _ta(b: GBranch) -> tuple[Any, ...]:
    taxon = canon_taxon(parse_target(b.target).taxon)
    names = tuple(latin_names(taxon)) or ((taxon,) if re.search(r"[A-Za-z]", taxon) else ())
    return (b.kind, b.jump, b.page, names, tuple(re.findall(r"\d+", taxon)))


def align(src_keys: Sequence[GKey], tgt_keys: Sequence[GKey]) -> list[dict[str, Any]]:
    """Compare source and translated keys branch by branch."""
    out: list[dict[str, Any]] = []
    if len(src_keys) != len(tgt_keys):
        out.append({**_f("key_count", "error", "", f"source {len(src_keys)} keys, translation {len(tgt_keys)}"),
                    "key": 0})
    for ki, (s, t) in enumerate(zip(src_keys, tgt_keys), start=1):
        tmap: dict[str, GBranch] = {}
        for b in t.branches:
            tmap.setdefault(b.lead, b)
        smap: dict[str, GBranch] = {}
        for b in s.branches:
            smap.setdefault(b.lead, b)
        for lead, b in smap.items():
            o = tmap.get(lead)
            if o is None:
                out.append({**_f("missing_branch", "error", lead, "missing in translation"), "key": ki})
            elif _ta(b) != _ta(o):
                out.append({**_f("target_changed", "error", lead, f"{b.target!r} -> {o.target!r}"), "key": ki})
        for lead in tmap:
            if lead not in smap:
                out.append({**_f("extra_branch", "error", lead, "not in source"), "key": ki})
        so = [x for x in dict.fromkeys(b.lead for b in s.branches) if x in tmap]
        to = [x for x in dict.fromkeys(b.lead for b in t.branches) if x in smap]
        if so != to:
            out.append({**_f("order_changed", "error", "", f"{so} -> {to}"), "key": ki})
    return out


def gate(keys: Sequence[GKey], expect_keys: bool) -> list[dict[str, Any]]:
    """no_keys when keys are expected but none were recognised."""
    if expect_keys and not keys:
        return [_f("no_keys", "error", "", "keys expected but none recognised")]
    return []


# ---------------------------------------------------------------- CLI

def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m booklayout.keygraph", description="dichotomous key graph check")
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--translation", type=Path)
    ap.add_argument("--expect-keys", action="store_true")
    ap.add_argument("--entries", default="", help="comma-separated entry couplets")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    entries = [e.strip() for e in a.entries.split(",") if e.strip()]
    src = parse_text(a.source.read_text(encoding="utf-8"))
    findings: list[dict[str, Any]] = gate(src, a.expect_keys)
    for i, k in enumerate(src, 1):
        findings += [{**f, "key": i} for f in check(k, entries or None)]
    report: dict[str, Any] = {"keys": [k.asdict() for k in src]}
    if a.translation:
        tgt = parse_text(a.translation.read_text(encoding="utf-8"))
        findings += align(src, tgt)
        report["translation_keys"] = [k.asdict() for k in tgt]
    report["findings"] = findings
    errs = sum(1 for f in findings if f["severity"] == "error")
    report["ok"] = errs == 0
    if a.out:
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} errors={errs} "
          f"warnings={len(findings) - errs}")
    return 1 if errs else 0


LIMITS = [
    "indented keys: wrapped (multi-line) branch text is read as child lines",
    "headingless indented keys unsupported; headingless letter-label keys need two consecutive labels",
    "taxon target without dot leader / wide gap / table cell is not separated from text",
    "Latin-name extraction is regex based; author names count as names",
    "bare trailing number counts as a jump only if that couplet exists (a count equal to a couplet no. is misread)",
    "OCR prime read as a doubled digit / l is recognised only right after the same number (11. after 1.)",
    "paired numbering 1(8)..8(1): needs every branch bracketed and symmetric; one malformed lead disables it",
    "wrapped epithet joined only when it is a single lowercase word after an abbreviated genus or binomial or a full genus name",
    "leaderless serial taxon (N. Genus X Author) is recognised only at sentence end; count-noun list is finite",
    "heading with no valid branch is kept as an empty key (empty_key error), also for lost-glyph or image-only tables",
]

if __name__ == "__main__":
    sys.exit(main())
