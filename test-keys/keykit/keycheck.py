"""Identification-key check and repair over an aligned book JSON (one IR, one pass).

Why this module exists (2026-11-23): key couplets were parsed in five places
(builder key_para/parse_key_rows, keyfix, keyalign, keymodel,
transqa.taxonomy.key_edges), each with its own regexes and each looking at one
page or one block.  Nobody checked a whole key as a graph, nobody compared the
translation's targets with the source's, and index pages were filed as keys.
This module reads every key lead of a book once into a small IR, checks it as a
whole, and applies only deterministic repairs (each logged).  Anything that
needs judgement is reported, never guessed.

IR: Table (one key) -> Lead (one line: marker, couplet number, text, target).
A target is a jump number (goto) or a taxon name with an optional page
reference.  Source and translation are parsed into the same IR.

Checks (error blocks delivery, warn needs a look, info is counted):

  K_INDEX_AS_KEY   error  index line "(Name) ..... 534" filed as a key block
  K_HIDDEN_LEAD    error  lead filed as index (builder never prints it) / warn as body
  K_SPLIT_TARGET   error  a lead's target sits in its own block ("P. elegans (p. 285)")
  K_SPLIT_LEAD     error  a lead's text continues in a separate block
  K_GLUED_LEADS    error  "<target> • <next lead>" in one block
  K_LOST_MARKER    error  alternative lead whose bullet was lost
  K_MARKER_OCR     error  couplet numbers garbled (1,2,3,4 / 1,2,2,3) where 1,•,2,• checks clean
  K_SEQ_GAP        error  couplet numbers missing inside a key
  K_DUP_LEAD       error  a couplet number opens twice
  K_ALT_MISSING    error  a couplet has only one lead
  K_NO_TARGET      error  a lead ends without jump number or taxon
  K_DANGLING       error  jump to a couplet that does not exist
  K_BACKWARD       error  jump to the same or an earlier couplet (loop)
  K_UNREACHED      error  couplet no lead jumps to (orphan)
  K_MULTI_IN       warn   couplet reached from more than one lead
  K_TR_GOTO        error  translation jump number differs from the source
  K_TR_NAME        error  translation taxon (Latin) differs from the source
  K_TR_PAGE        error  translation page reference differs from the source
  K_TR_MARKER      error  translation couplet marker differs from the source
  K_TR_NO_TARGET   error  source lead has a target, translation has none
  K_TR_PAGEFMT     warn   "(p. N)" left inside a CJK translation
  K_TR_NO_LEADER   warn   translation target not separated by a dot leader
  K_SRC_NO_LEADER  info   source target not separated by a dot leader
  K_NAME_SPELL     warn   taxon name looks like an OCR misspelling of a known name
  K_TR_DIGITS      warn   numbers in the lead text differ (figure refs, counts)

Auto-fixes (--fix; written to a new file, input untouched, every change logged):
structural repairs first (a lead filed as body/index set back to key; a target or
continuation split into its own block merged back; a lost bullet restored; OCR-garbled
couplet numbers re-paired when only the paired reading checks clean), then
translation targets copied from the source (jump numbers and Latin names are not
translated); page references put in the translation's style; dot leader inserted
before a recognised target; index lines filed back as index; a name misspelling
corrected only when exactly one known name is within OCR distance.

Usage:
    python3 -m booklayout.keycheck aligned.json [--names names.txt]
        [--report report.json] [--fix fixed.json] [--fail-on error]
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

LEADER = re.compile(r"\s*(?:(?:[.．·・]\s?){3,}|(?:[…⋯]\s*)+)\s*")
MARK = re.compile(
    r"^\s*(?:(?P<num>\d{1,3})(?:(?P<prime>['′’])|(?P<ab>[ab]))?"
    r"(?:\s*[（(](?P<back>\d{1,3})[）)])?\s*(?P<p>[.)．、])?|(?P<bul>[•·—–―-](?=\s)))\s*"
)
PAGE = re.compile(r"[（(]\s*(?:(?:p|pp|pág|S)\.\s*(?P<a>\d{1,4})|第\s*(?P<b>\d{1,4})\s*页)\s*(?:[）)]|$)")
GOTO = re.compile(r"^(?P<n>\d{1,3})\s*['′’]?$")
LATIN_WORD = re.compile(r"[A-Z][a-z]+|(?<![A-Za-z])[a-z]{3,}")
GENUS = re.compile(r"\b[A-Z][a-z]{3,}\b")
INDEX_LINE = re.compile(r"^\s*\([^)]{1,60}\)\s*(?:[.．…]\s*){3,}\s*\d{1,4}(?:\s*[,，]\s*\d{1,4})*\s*$")
# "Eunereis (p. 321)" / "A. (S.) abyssalis (p. 184)" glued to the text without a leader
TAIL_NAME_PAGE = re.compile(
    r"(?:[\s,，。.;；）)]|(?<=[一-鿿]))\s*(?P<name>(?:[A-Z][a-z]*\.?\s*)(?:[（(][A-Z][a-z]*\.?[）)]\s*)?(?:[a-z]{1,2}\.\s*)?(?:[a-z]{3,}\s*){0,2})"
    r"\s*(?P<page>[（(]\s*(?:(?:p|pp|pág|S)\.\s*\d{1,4}|第\s*\d{1,4}\s*页)\s*(?:[）)]|$))\s*$"
)
CJK = re.compile(r"[一-鿿]")
KEY_ROLES = ("key", "couplet")
KEY_TITLE = re.compile(r"检索表|\bClave\b|\bKey\b|検索表", re.I)
OCR_PAIRS = {("h", "b"), ("rn", "m"), ("l", "i"), ("l", "1"), ("c", "e"), ("u", "n"), ("cl", "d"),
             ("i", "j"), ("o", "c"), ("v", "y"), ("f", "t"), ("ii", "u")}


@dataclass
class Target:
    goto: int | None = None
    name: str = ""
    page: str = ""

    @property
    def empty(self) -> bool:
        return self.goto is None and not self.name and not self.page

    def latin(self) -> str:
        return " ".join(LATIN_WORD.findall(self.name))


@dataclass
class Side:
    marker: str = ""
    num: int | None = None
    alt: bool = False
    back: int | None = None
    body: str = ""
    target: Target = field(default_factory=Target)
    leader: bool = False


@dataclass
class Lead:
    page: Any
    bi: int
    role: str
    src: Side
    tr: Side | None
    couplet: int | None = None   # couplet this lead belongs to (alt leads inherit)
    parts: list[tuple[Any, int]] = field(default_factory=list)  # target blocks read into this lead
    tr_raw: str = ""


@dataclass
class Table:
    title: str
    leads: list[Lead] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    level: str
    page: Any
    bi: int | None
    msg: str
    fix: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {"code": self.code, "level": self.level, "page": self.page, "block": self.bi, "msg": self.msg}
        if self.fix:
            d["fix"] = self.fix
        return d


# ---------------------------------------------------------------- parsing
def parse_target(rhs: str) -> Target:
    rhs = rhs.strip().strip("*").strip()
    m = GOTO.match(rhs)
    if m:
        return Target(goto=int(m.group("n")))
    t = Target()
    pm = PAGE.search(rhs)
    if pm:
        t.page = pm.group("a") or pm.group("b") or ""
        rhs = (rhs[: pm.start()] + rhs[pm.end():]).strip()
    t.name = rhs.strip(" ,，.。*")
    return t


def parse_line(text: str) -> Side:
    """One key line ("5. text ..... Name (p. 57)") -> Side.  Never raises."""
    s = Side()
    text = (text or "").replace("�", "…").strip()
    m = MARK.match(text)
    if m and (m.group("bul") or m.group("p") or m.group("back") or m.group("prime") or m.group("ab")):
        s.marker = m.group(0).strip()
        if m.group("num"):
            s.num = int(m.group("num"))
            s.alt = bool(m.group("prime") or m.group("ab") == "b")
            s.back = int(m.group("back")) if m.group("back") else None
        else:
            s.alt = True
        text = text[m.end():]
    leaders = list(LEADER.finditer(text))
    if leaders:
        lm = leaders[-1]
        rhs = text[lm.end():]
        if rhs.strip():
            s.leader = True
            s.body = text[: lm.start()].strip()
            s.target = parse_target(rhs)
            return s
    tm = TAIL_NAME_PAGE.search(text)
    if tm and tm.group("name").strip():
        s.body = text[: tm.start() + 1].strip(" ,，")
        s.target = parse_target(tm.group("name") + " " + tm.group("page"))
        return s
    s.body = text.strip()
    return s


def _is_index_dominant(page: dict[str, Any]) -> bool:
    blocks = page.get("blocks") or []
    idx = sum(b.get("role") == "index" for b in blocks)
    return idx >= 3 and idx * 3 >= len(blocks)


def _couplet_rhs(block: dict[str, Any]) -> str:
    c = block.get("couplet")
    if block.get("role") == "couplet" and isinstance(c, dict):
        return " ".join(x for x in (c.get("name"), c.get("target")) if x).strip()
    return ""


def _tr_side(block: dict[str, Any], extra: str = "") -> tuple[Side | None, str]:
    """Translation side as the builder prints it (couplet: text + couplet.name/target)."""
    tr = block.get("translation")
    if tr is None:
        return None, ""
    rhs = _couplet_rhs(block)
    if block.get("role") == "couplet":
        if not parse_target(rhs).empty:
            side = parse_line(tr)
            side.target, side.leader = parse_target(rhs), True
            side.marker = side.marker or (block["couplet"].get("marker") or "").strip()
            return side, rhs
        rhs = ""
    raw = f"{tr} ..... {extra}" if extra else tr
    side = parse_line(raw)
    if block.get("role") == "couplet":
        side.marker = side.marker or (block["couplet"].get("marker") or "").strip()
    return side, rhs or raw


_LEAD_DOTS = re.compile(r"^\s*(?:[.．…⋯·]\s*){2,}")
GLUED = re.compile(r"^(?P<t>[^•]{2,90}?[（(]\s*(?:(?:p|pp|pág|S)\.\s*\d{1,4}|第\s*\d{1,4}\s*页)\s*[）)])\s*(?P<rest>[•·].+)$",
                   re.S)


def _lone_target(text: str) -> Target | None:
    """A block that is only a target ("A. (S.) sardai (p. 214)", ".....7"), split off its lead."""
    s = text.strip()
    if not s or len(s) > 110 or _has_marker(s):
        return None
    dotted = bool(_LEAD_DOTS.match(s))
    s = _LEAD_DOTS.sub("", s)
    if LEADER.search(s):
        return None  # text continuation + its own target: a split lead, not a lone target
    t = parse_target(s)
    if t.goto is not None and (dotted or len(s) <= 4):
        return t
    if t.page and t.latin() and len(t.name) <= 80:
        return t
    return None


def _ends_with_target(text: str) -> bool:
    s = parse_line(text)
    return not s.target.empty


def _has_marker(text: str) -> bool:
    return bool(parse_line(text).marker)


def read_tables(data: dict[str, Any]) -> tuple[list[Table], list[Finding]]:
    """All keys of the book in reading order, plus findings about blocks the key lost.

    A key region opens at a key-title heading (or the first key/couplet block) and
    closes at the next other heading or at a block that has no key shape.  Inside a
    region, a lead may be filed as body/index (index is never printed), its target may
    sit in the next block, or its bullet may be lost; all of these are read back into
    the lead and reported with a repair.
    """
    tables: list[Table] = []
    found: list[Finding] = []
    cur: Table | None = None
    title = ""
    region = False
    pages_by = {p.get("page"): p for p in data.get("pages", [])}

    def new_table(pg: Any) -> Table:
        nonlocal title
        t = Table(title or f"key@p{pg}")
        tables.append(t)
        title = ""
        return t

    for page in data.get("pages", []):
        index_page = _is_index_dominant(page)
        pg = page.get("page")
        blocks = page.get("blocks", [])
        for bi, b in enumerate(blocks):
            role = b.get("role")
            text = b.get("text") or ""
            if b.get("keycheck") == "merged":
                continue
            if role == "heading":
                region = bool(KEY_TITLE.search(text + (b.get("translation") or "")))
                if region:
                    title, cur = text.strip(), None
                continue
            if index_page and role in ("key", "index") and not _has_marker(text):
                if role == "key":
                    found.append(Finding("K_INDEX_AS_KEY", "error", pg, bi,
                                         f"index line filed as key: {text[:60]}", {"role": "index"}))
                continue
            if role == "key" and INDEX_LINE.match(text):
                found.append(Finding("K_INDEX_AS_KEY", "error", pg, bi,
                                     f"index line filed as key: {text[:60]}", {"role": "index"}))
                continue
            keyish = role in KEY_ROLES
            if not keyish and not (region and role in ("body", "index")):
                if role not in ("caption", "note") and not (role == "index" and index_page):
                    region = False
                continue
            src = parse_line(text)
            last = cur.leads[-1] if cur and cur.leads else None
            # 1. a block that is only the target of the previous lead
            lone = _lone_target(text) if not src.marker else None
            if lone is not None and last is not None and last.src.target.empty:
                last.src.target, last.src.leader = lone, False
                tr_t = (b.get("translation") or "").strip()
                lb = pages_by[last.page]["blocks"][last.bi]
                last.tr, last.tr_raw = _tr_side(lb, _LEAD_DOTS.sub("", tr_t))
                last.parts.append((pg, bi))
                found.append(Finding("K_SPLIT_TARGET", "error", last.page, last.bi,
                                     f"target {text.strip()[:50]!r} sits in its own {role} block (p{pg} b{bi})",
                                     {"merge": [pg, bi]}))
                continue
            # 2. "<target of previous lead> • <next lead>" glued in one block
            gm = GLUED.match(text.strip()) if not src.marker else None
            if gm and last is not None and last.src.target.empty and "•" in (b.get("translation") or ""):
                last.src.target = parse_target(gm.group("t"))
                tr_head = (b.get("translation") or "").split("•", 1)[0].strip()
                lb = pages_by[last.page]["blocks"][last.bi]
                last.tr, last.tr_raw = _tr_side(lb, tr_head)
                found.append(Finding("K_GLUED_LEADS", "error", pg, bi,
                                     f"target of p{last.page} b{last.bi} and the next lead share one block",
                                     {"split_glued": [last.page, last.bi]}))
                src = parse_line(gm.group("rest"))
                tr_rest = "•" + (b.get("translation") or "").split("•", 1)[1]
                lead = Lead(pg, bi, "key", src, parse_line(tr_rest), tr_raw=tr_rest)
                if cur is None:
                    cur = new_table(pg)
                cur.leads.append(lead)
                region = True
                continue
            if not src.marker:
                if keyish or _ends_with_target(text):
                    if last is not None and last.src.target.empty and not keyish:
                        # continuation of a lead whose text broke into two blocks
                        found.append(Finding("K_SPLIT_LEAD", "error", last.page, last.bi,
                                             f"lead continues in a separate {role} block (p{pg} b{bi})",
                                             {"merge": [pg, bi]}))
                        tr_t = (b.get("translation") or "").strip()
                        lb = pages_by[last.page]["blocks"][last.bi]
                        last.src = parse_line(((lb.get("text") or "") + " " + text).strip())
                        last.tr, last.tr_raw = _tr_side(lb, "")
                        if last.tr is not None:
                            last.tr = parse_line(((lb.get("translation") or "") + " " + tr_t).strip())
                            last.tr_raw = tr_t
                        last.parts.append((pg, bi))
                        continue
                    if last is not None and not last.src.target.empty and region:
                        # an alternative lead whose bullet was lost
                        found.append(Finding("K_LOST_MARKER", "error", pg, bi,
                                             f"lead without marker: {text[:50]!r}", {"prefix": "• "}))
                        src.marker, src.alt = "•", True
                    elif not keyish:
                        if role == "index":
                            found.append(Finding("K_HIDDEN_LEAD", "error", pg, bi,
                                                 f"key text filed as index is not printed: {text[:50]!r}",
                                                 {"role": "key"}))
                        region = False
                        continue
                elif not keyish:
                    region = False
                    continue
            elif not keyish:
                lvl = "error" if role == "index" else "warn"
                why = "is not printed" if role == "index" else "is printed as a body paragraph"
                found.append(Finding("K_HIDDEN_LEAD", lvl, pg, bi, f"lead filed as {role} {why}: {text[:50]!r}",
                                     {"role": "key"}))
            tr, tr_raw = _tr_side(b)
            lead = Lead(pg, bi, role if keyish else "key", src, tr, tr_raw=tr_raw)
            restart = src.num == 1 and not src.alt and cur is not None and any(
                x.src.num is not None for x in cur.leads)
            if cur is None or restart:
                cur = new_table(pg)
            cur.leads.append(lead)
            region = True
    for t in tables:
        _assign_couplets(t)
    return tables, found


def _assign_couplets(t: Table) -> None:
    last: int | None = None
    for ld in t.leads:
        s = ld.src
        if s.num is not None:
            ld.couplet = s.num
            if not s.alt:
                last = s.num
        else:
            ld.couplet = last  # bullet alternative, or a line without marker


# ---------------------------------------------------------------- checks
def _digits(s: str) -> Counter[str]:
    return Counter(re.findall(r"\d+", s))


def check_table(t: Table) -> list[Finding]:
    out: list[Finding] = []
    leads = [ld for ld in t.leads if ld.src.marker]
    by: dict[int, list[Lead]] = defaultdict(list)
    primary: Counter[int] = Counter()
    for ld in leads:
        if ld.couplet is not None:
            by[ld.couplet].append(ld)
            if not ld.src.alt and ld.src.num is not None:
                primary[ld.couplet] += 1
    nums = sorted(by)
    if not nums:
        return out
    first = nums[0]
    tag = f"[{t.title[:40]}]"
    for n in range(first, nums[-1] + 1):
        if n not in by:
            near = next(by[m][0] for m in nums if m > n)
            out.append(Finding("K_SEQ_GAP", "error", near.page, near.bi, f"{tag} couplet {n} missing"))
    for n, c in primary.items():
        if c > 1:
            ld = by[n][-1]
            out.append(Finding("K_DUP_LEAD", "error", ld.page, ld.bi, f"{tag} couplet {n} opens {c} times"))
    incoming: Counter[int] = Counter()
    for n in nums:
        group = by[n]
        if len(group) < 2:
            out.append(Finding("K_ALT_MISSING", "error", group[0].page, group[0].bi,
                               f"{tag} couplet {n} has {len(group)} lead"))
        for ld in group:
            g = ld.src.target.goto
            if ld.src.target.empty:
                out.append(Finding("K_NO_TARGET", "error", ld.page, ld.bi,
                                   f"{tag} {ld.src.marker} lead ends without target: ...{ld.src.body[-40:]}"))
            elif g is not None:
                if g not in by:
                    out.append(Finding("K_DANGLING", "error", ld.page, ld.bi,
                                       f"{tag} couplet {n} -> {g}: no such couplet"))
                elif g <= n:
                    out.append(Finding("K_BACKWARD", "error", ld.page, ld.bi, f"{tag} couplet {n} -> {g}: jumps back"))
                else:
                    incoming[g] += 1
            if not ld.src.target.empty and not ld.src.leader:
                out.append(Finding("K_SRC_NO_LEADER", "info", ld.page, ld.bi, f"{tag} source target without leader"))
            out.extend(_check_translation(ld, tag))
    for n in nums:
        if n == first:
            continue
        ld = by[n][0]
        if incoming[n] == 0:
            out.append(Finding("K_UNREACHED", "error", ld.page, ld.bi, f"{tag} no lead jumps to couplet {n}"))
        elif incoming[n] > 1:
            out.append(Finding("K_MULTI_IN", "warn", ld.page, ld.bi, f"{tag} couplet {n} reached {incoming[n]} times"))
    return out


def _norm_marker(m: str) -> str:
    m = m.strip().rstrip(".)．、 ")
    return "•" if m in {"•", "·", "—", "–", "―", "-"} else m


def _check_translation(ld: Lead, tag: str) -> list[Finding]:
    out: list[Finding] = []
    s, r = ld.src, ld.tr
    if r is None:
        return out
    pg, bi = ld.page, ld.bi
    fix = {"target": "from_source"}
    if ld.role == "key" and s.marker and r.marker and _norm_marker(s.marker) != _norm_marker(r.marker):
        out.append(Finding("K_TR_MARKER", "error", pg, bi, f"{tag} marker {s.marker!r} -> {r.marker!r}", fix))
    if not s.target.empty and r.target.empty:
        out.append(Finding("K_TR_NO_TARGET", "error", pg, bi, f"{tag} {s.marker} target lost in translation", fix))
        return out
    st, rt = s.target, r.target
    if st.goto is not None and st.goto != rt.goto:
        out.append(Finding("K_TR_GOTO", "error", pg, bi, f"{tag} jump {st.goto} -> {rt.goto}", fix))
    sl, rl = st.latin(), rt.latin()
    if sl and sl not in rl and rl not in sl:
        out.append(Finding("K_TR_NAME", "error", pg, bi, f"{tag} taxon {sl!r} -> {rl!r}", fix))
    if st.page and rt.page and st.page != rt.page:
        out.append(Finding("K_TR_PAGE", "error", pg, bi, f"{tag} page {st.page} -> {rt.page}", fix))
    if rt.page and CJK.search(r.body) and re.search(r"[（(]\s*(?:p|pp|pág|S)\.\s*\d", ld.tr_raw):
        out.append(Finding("K_TR_PAGEFMT", "warn", pg, bi, f"{tag} '(p. {rt.page})' in CJK text", fix))
    if ld.role == "key" and not rt.empty and not r.leader and not ld.parts:
        out.append(Finding("K_TR_NO_LEADER", "warn", pg, bi, f"{tag} translation target has no leader", fix))
    sd, rd = _digits(s.body), _digits(r.body)
    miss, extra = sorted((sd - rd).elements()), sorted((rd - sd).elements())
    if miss or extra:
        out.append(Finding("K_TR_DIGITS", "warn", pg, bi, f"{tag} numbers lost {miss} added {extra}"))
    return out


# ---------------------------------------------------------------- names
def _ocr_dist(a: str, b: str) -> float:
    """Edit distance where common OCR confusions (h/b, rn/m, ...) cost 0.5."""
    la, lb = len(a), len(b)
    d = [[0.0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = float(i)
    for j in range(lb + 1):
        d[0][j] = float(j)
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            x, y = a[i - 1], b[j - 1]
            sub = 0.0 if x == y else (0.5 if (x, y) in OCR_PAIRS or (y, x) in OCR_PAIRS else 1.0)
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + sub)
            if i >= 2 and ((a[i - 2:i], y) in OCR_PAIRS or (y, a[i - 2:i]) in OCR_PAIRS):
                d[i][j] = min(d[i][j], d[i - 2][j - 1] + 0.5)
            if j >= 2 and ((b[j - 2:j], x) in OCR_PAIRS or (x, b[j - 2:j]) in OCR_PAIRS):
                d[i][j] = min(d[i][j], d[i - 1][j - 2] + 0.5)
    return d[la][lb]


WORD = re.compile(r"\b[A-Za-z]{4,}\b")


def known_names(data: dict[str, Any], extra: Iterable[str] = ()) -> Counter[str]:
    """Latin-like words of the source text with their counts; a supplied name list counts high."""
    c: Counter[str] = Counter()
    for page in data.get("pages", []):
        for b in page.get("blocks", []):
            c.update(WORD.findall(b.get("text") or ""))
    for n in extra:
        for w in WORD.findall(n):
            c[w] += 100
    return c


def check_names(tables: list[Table], names: Counter[str]) -> list[Finding]:
    """Taxon words in key targets seen less than twice in the book: OCR misspelling?

    Auto-fix only when exactly one frequent word is reachable by OCR confusions alone
    (h/b, rn/m, ...; distance 0.5); a plain one-letter difference is reported, not fixed.
    """
    out: list[Finding] = []
    for t in tables:
        for ld in t.leads:
            for w in WORD.findall(ld.src.target.name):
                if names[w] >= 2:
                    continue
                cands = sorted({k for k, v in names.items() if v >= 3 and k != w and abs(len(k) - len(w)) <= 2
                                and k[0] == w[0] and _ocr_dist(w, k) <= 1.0}, key=lambda k: _ocr_dist(w, k))
                if not cands:
                    continue
                d = _ocr_dist(w, cands[0])
                fix = {"replace": [w, cands[0]]} if len(cands) == 1 and d <= 0.5 else None
                msg = f"{w!r} -> {cands[0]!r} (OCR distance {d})" if len(cands) == 1 else \
                    f"{w!r} unknown; candidates {cands[:5]}"
                out.append(Finding("K_NAME_SPELL", "warn", ld.page, ld.bi, msg, fix))
    return out


GRAPH_CODES = {"K_SEQ_GAP", "K_DUP_LEAD", "K_ALT_MISSING", "K_DANGLING", "K_BACKWARD", "K_UNREACHED"}


def _graph_errors(t: Table) -> int:
    return sum(f.code in GRAPH_CODES for f in check_table(t))


def check_numbering(t: Table, alt_style: str) -> list[Finding]:
    """OCR turned alternative markers (•, 1') into numbers (1,2,3,4... or 1,2,2,3,3...).

    Re-read the leads as couplets of two (lead i -> couplet i//2 + first) and keep that
    reading only if the key then checks clean while the printed numbering does not.
    """
    leads = [ld for ld in t.leads if ld.src.marker]
    if len(leads) < 4 or len(leads) % 2:
        return []
    first = min((ld.src.num for ld in leads if ld.src.num is not None), default=1)
    before = _graph_errors(t)
    if before == 0:
        return []
    trial = Table(t.title, [copy.deepcopy(ld) for ld in t.leads])
    want: dict[int, str] = {}
    k = 0
    for ld in trial.leads:
        if not ld.src.marker:
            continue
        n, alt = first + k // 2, bool(k % 2)
        ld.src.num, ld.src.alt = (None, True) if alt and alt_style == "•" else (n, alt)
        ld.src.marker = (alt_style if alt_style == "•" else f"{n}'") if alt else f"{n}."
        want[id(leads[k])] = ld.src.marker
        k += 1
    _assign_couplets(trial)
    after = _graph_errors(trial)
    if after:
        return []
    return [Finding("K_MARKER_OCR", "error", ld.page, ld.bi,
                    f"[{t.title[:40]}] marker {ld.src.marker!r} should be {want[id(ld)]!r} "
                    f"(key checks clean only with paired numbering; {before} graph errors before)",
                    {"marker": want[id(ld)]})
            for ld in leads if _norm_marker(ld.src.marker) != _norm_marker(want[id(ld)])]


def _alt_style(tables: list[Table]) -> str:
    c = Counter("prime" if ld.src.num is not None else "bullet"
                for t in tables for ld in t.leads if ld.src.alt)
    return "•" if c["bullet"] >= c["prime"] else "'"


# ---------------------------------------------------------------- fixes
STRUCTURAL = ("role", "merge", "prefix", "split_glued", "marker")


def _render_target(t: Target, cjk: bool) -> str:
    if t.goto is not None:
        return str(t.goto)
    name = t.name
    if t.page:
        name = f"{name}（第{t.page}页）" if cjk else f"{name} (p. {t.page})"
    return name.strip()


def _join_target(text: str, target: str) -> str:
    return f"{text.rstrip(' .．…⋯·')} ..... {_LEAD_DOTS.sub('', target).strip()}"


def _set_couplet_target(b: dict[str, Any], rhs: str) -> None:
    rhs = _LEAD_DOTS.sub("", rhs).strip()
    if rhs and not GOTO.match(rhs):
        rhs = _render_target(parse_target(rhs), bool(CJK.search(rhs)))
    c = b["couplet"]
    if GOTO.match(rhs):
        c["name"], c["target"] = "", rhs
    else:
        c["name"], c["target"] = rhs, ""


def _merge(lb: dict[str, Any], tb: dict[str, Any], lone: bool) -> None:
    """Read block tb into lead block lb; tb stays in the file, emptied and flagged."""
    if lone:
        lb["text"] = _join_target(lb.get("text") or "", tb.get("text") or "")
        if lb.get("role") == "couplet" and isinstance(lb.get("couplet"), dict):
            _set_couplet_target(lb, tb.get("translation") or "")
        elif lb.get("translation") is not None:
            lb["translation"] = _join_target(lb["translation"], tb.get("translation") or "")
    else:
        lb["text"] = f"{(lb.get('text') or '').rstrip()} {(tb.get('text') or '').strip()}"
        if lb.get("translation") is not None:
            lb["translation"] = f"{lb['translation'].rstrip()}{(tb.get('translation') or '').strip()}"
    tb["translation"] = ""
    tb["keycheck"] = "merged"


def _set_marker(b: dict[str, Any], new: str) -> None:
    for key in ("text", "translation"):
        v = b.get(key)
        if isinstance(v, str):
            m = MARK.match(v)
            if m and parse_line(v).marker:
                b[key] = f"{new} {v[m.end():]}"
    if isinstance(b.get("couplet"), dict):
        b["couplet"]["marker"] = new


def _apply_structural(out: dict[str, Any], findings: list[Finding], log: list[dict[str, Any]]) -> int:
    pages = {p.get("page"): p for p in out.get("pages", [])}
    n = 0
    for f in findings:
        if not f.fix or f.bi is None or not any(k in f.fix for k in STRUCTURAL):
            continue
        b = pages[f.page]["blocks"][f.bi]
        before = {k: copy.deepcopy(b.get(k)) for k in ("role", "text", "translation", "couplet")}
        if "role" in f.fix:
            b["role"] = f.fix["role"]
        elif "merge" in f.fix:
            tp, tbi = f.fix["merge"]
            tb = pages[tp]["blocks"][tbi]
            _merge(b, tb, f.code == "K_SPLIT_TARGET")
            if b.get("role") not in KEY_ROLES:
                b["role"] = "key"
            log.append({"page": tp, "block": tbi, "rule": f.code, "field": "merged_into",
                        "old": tb.get("text"), "new": f"p{f.page} b{f.bi}"})
        elif "prefix" in f.fix:
            b["text"] = f.fix["prefix"] + (b.get("text") or "").lstrip()
            tr = b.get("translation")
            if isinstance(tr, str) and not parse_line(tr).marker:
                b["translation"] = f.fix["prefix"] + tr.lstrip()
            if b.get("role") not in KEY_ROLES:
                b["role"] = "key"
        elif "split_glued" in f.fix:
            lp, lbi = f.fix["split_glued"]
            lb = pages[lp]["blocks"][lbi]
            gm = GLUED.match((b.get("text") or "").strip())
            tr = b.get("translation") or ""
            if gm is None or "•" not in tr:
                continue
            head_tr, rest_tr = tr.split("•", 1)
            _merge(lb, {"text": gm.group("t"), "translation": head_tr}, True)
            if lb.get("role") not in KEY_ROLES:
                lb["role"] = "key"
            b["text"], b["translation"], b["role"] = gm.group("rest"), "•" + rest_tr, "key"
        elif "marker" in f.fix:
            _set_marker(b, f.fix["marker"])
        after = {k: b.get(k) for k in before}
        for k in before:
            if before[k] != after[k]:
                log.append({"page": f.page, "block": f.bi, "rule": f.code, "field": k,
                            "old": before[k], "new": after[k]})
        n += 1
    return n


def apply_fixes(data: dict[str, Any], findings: list[Finding],
                tables: list[Table]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Content repairs (target copied from source, name spelling) on a copy of data."""
    out = copy.deepcopy(data)
    pages = {p.get("page"): p for p in out.get("pages", [])}
    lead_at = {(ld.page, ld.bi): ld for t in tables for ld in t.leads}
    log: list[dict[str, Any]] = []
    renames = {f.fix["replace"][0]: f.fix["replace"][1] for f in findings
               if f.fix and "replace" in f.fix and f.code == "K_NAME_SPELL"}
    done: set[tuple[Any, Any]] = set()
    for f in findings:
        if not f.fix or f.bi is None:
            continue
        if f.fix.get("target") == "from_source" and (f.page, f.bi) not in done and (f.page, f.bi) in lead_at:
            done.add((f.page, f.bi))
            _fix_target(pages[f.page]["blocks"][f.bi], lead_at[(f.page, f.bi)], renames, log, f.code)
    for t in tables:
        for ld in t.leads:
            b = pages[ld.page]["blocks"][ld.bi]
            for wrong, right in renames.items():
                pat = re.compile(rf"\b{re.escape(wrong)}\b")
                for key in ("text", "translation"):
                    v = b.get(key)
                    if isinstance(v, str) and pat.search(v):
                        b[key] = pat.sub(right, v)
                        log.append({"page": ld.page, "block": ld.bi, "rule": "K_NAME_SPELL", "field": key,
                                    "old": wrong, "new": right})
                c = b.get("couplet")
                if isinstance(c, dict) and pat.search(c.get("name") or ""):
                    c["name"] = pat.sub(right, c["name"])
                    log.append({"page": ld.page, "block": ld.bi, "rule": "K_NAME_SPELL", "field": "couplet.name",
                                "old": wrong, "new": right})
    return out, log


def _fix_target(b: dict[str, Any], ld: Lead, renames: dict[str, str],
                log: list[dict[str, Any]], rule: str) -> None:
    r = ld.tr
    if r is None:
        return
    src_t = copy.copy(ld.src.target)
    if src_t.empty:
        return
    for w, rr in renames.items():
        src_t.name = re.sub(rf"\b{re.escape(w)}\b", rr, src_t.name)
    tr = b.get("translation") or ""
    cjk = bool(CJK.search(tr))
    # keep a Chinese name the translator put before the Latin name
    if src_t.goto is None and r.target.name and CJK.search(r.target.name):
        zh = "".join(re.findall(r"[一-鿿]+", r.target.name))
        if zh and zh not in src_t.name:
            src_t.name = f"{zh} {src_t.name}".strip()
    new_rhs = _render_target(src_t, cjk)
    c = b.get("couplet")
    if ld.role == "couplet" and isinstance(c, dict):
        old = " ".join(x for x in (c.get("name"), c.get("target")) if x)
        _set_couplet_target(b, new_rhs)
        if old != new_rhs:
            log.append({"page": ld.page, "block": ld.bi, "rule": rule, "field": "couplet", "old": old, "new": new_rhs})
        return
    body = LEADER.sub(" ", r.body).strip() if r.target.empty else r.body
    if src_t.name:
        tail = re.compile(re.escape(src_t.name) + r"\s*(?:[（(][^）)]*[）)]?)?\s*$")
        body = tail.sub("", body)
    body = body.rstrip(" ,，;；.。")
    pm = MARK.match(tr)
    marker = r.marker or (pm.group(0).strip() if pm else "") or ld.src.marker
    new = f"{marker} {body} ..... {new_rhs}" if marker else f"{body} ..... {new_rhs}"
    if new != tr:
        b["translation"] = new
        log.append({"page": ld.page, "block": ld.bi, "rule": rule, "field": "translation", "old": tr, "new": new})


# ---------------------------------------------------------------- driver
def run(data: dict[str, Any], names: Iterable[str] = ()) -> tuple[list[Table], list[Finding]]:
    tables, found = read_tables(data)
    style = _alt_style(tables)
    for t in tables:
        renum = check_numbering(t, style)
        found.extend(renum)
        if not renum:
            found.extend(check_table(t))
    found.extend(check_names(tables, known_names(data, names)))
    return tables, found


def _match_couplet_style(data: dict[str, Any], log: list[dict[str, Any]]) -> None:
    """A lead restored as role=key inside a key typeset as couplets gets the couplet form too.

    The builder lays out role=key and role=couplet differently; a mixed key prints one lead
    in the wrong style (Vol. 41 p. 285).
    """
    pages = {p.get("page"): p for p in data.get("pages", [])}
    tables, _ = read_tables(data)
    for t in tables:
        if not any(ld.role == "couplet" for ld in t.leads):
            continue
        for ld in t.leads:
            b = pages[ld.page]["blocks"][ld.bi]
            if b.get("role") != "key":
                continue
            tr = b.get("translation") or ""
            s = parse_line(tr)
            if not s.marker or s.target.empty:
                continue
            rhs = _render_target(s.target, bool(CJK.search(tr)))
            b["role"] = "couplet"
            b["couplet"] = {"marker": s.marker, "name": "", "target": ""}
            _set_couplet_target(b, rhs)
            b["translation"] = s.body
            log.append({"page": ld.page, "block": ld.bi, "rule": "K_STYLE_COUPLET", "field": "role",
                        "old": tr, "new": b["couplet"]})


def repair(data: dict[str, Any], names: Iterable[str] = (),
           rounds: int = 4) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Structural repairs first (re-reading after each round), then content repairs."""
    out = copy.deepcopy(data)
    log: list[dict[str, Any]] = []
    for _ in range(rounds):
        tables, found = run(out, names)
        if not _apply_structural(out, found, log):
            break
    tables, found = run(out, names)
    out, more = apply_fixes(out, found, tables)
    _match_couplet_style(out, more)
    return out, log + more


def summary(tables: list[Table], found: list[Finding]) -> dict[str, Any]:
    return {
        "keys": len(tables),
        "leads": sum(len(t.leads) for t in tables),
        "by_level": dict(Counter(f.level for f in found)),
        "by_code": dict(sorted(Counter(f.code for f in found).items())),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m booklayout.keycheck",
                                 description="check and repair identification keys in an aligned JSON")
    ap.add_argument("aligned", type=Path)
    ap.add_argument("--names", type=Path, help="known taxon names, one per line (e.g. a WoRMS export)")
    ap.add_argument("--report", type=Path, help="write findings JSON here")
    ap.add_argument("--fix", type=Path, help="write the repaired aligned JSON here (input is never touched)")
    ap.add_argument("--fail-on", choices=("error", "warn", "never"), default="error")
    ap.add_argument("--show", type=int, default=40, help="findings to print")
    a = ap.parse_args(argv)
    if a.fix and a.fix.resolve() == a.aligned.resolve():
        ap.error("--fix must name a new file; the input is never overwritten")
    data = json.loads(a.aligned.read_text(encoding="utf-8"))
    names = a.names.read_text(encoding="utf-8").split("\n") if a.names else []
    tables, found = run(data, names)
    rep: dict[str, Any] = {"input": str(a.aligned), "summary": summary(tables, found),
                           "findings": [f.as_dict() for f in found]}
    remaining = [f.as_dict() for f in found if f.level != "info"]
    if a.fix:
        fixed, log = repair(data, names)
        a.fix.write_text(json.dumps(fixed, ensure_ascii=False, indent=1), encoding="utf-8")
        rep["fixes"] = log
        t2, after = run(fixed, names)
        rep["after_fix"] = summary(t2, after)
        remaining = [f.as_dict() for f in after if f.level != "info"]
        rep["remaining"] = remaining
    if a.report:
        a.report.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep["summary"], ensure_ascii=False))
    for f in [f for f in found if f.level != "info"][: a.show]:
        print(f"{f.level:5} {f.code:16} p{f.page} b{f.bi}  {f.msg}")
    if a.fix:
        print(f"fixes applied: {len(rep['fixes'])}; after fix: {json.dumps(rep['after_fix']['by_level'])}")
    if a.fail_on == "never":
        return 0
    levels = {"error"} if a.fail_on == "error" else {"error", "warn"}
    return 1 if any(x["level"] in levels for x in remaining) else 0


if __name__ == "__main__":
    sys.exit(main())
