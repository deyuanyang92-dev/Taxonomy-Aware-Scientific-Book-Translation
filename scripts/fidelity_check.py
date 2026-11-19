#!/usr/bin/env python3
"""确定性保真检查与修正：弱模型（如不开思考的 deepseek-flash）只管起草，格式规则由脚本执行。不调模型。

四项（英文块 --en 对照中文块 --zh；中文里「### 待定术语」「### 术语决策」之后的尾节原样保留，不检查）：
  1 拉丁名  英文里的属名、双名（大写词+拉丁词尾的小写种加词；斜体 *…*；yiku 已知的属名，含句首）必须在中文里出现
            （*Genus species*、*Genus*、G. species 均可）。缺的报告并附英文原句。
            --fix：中文里有 yiku 的中文属/种名而没写拉丁名时，在该中文名第一次出现之后插入「（*拉丁名*）」；
            yiku 没有的、中文里找不到的一概不补，不凭空造中文名。
  2 人名    skill/person_names.tsv（英文<TAB>中文）里的惯译人名，在中文正文里写成英文的，--fix 改成中文
            （Ray's→雷的）；人名前的名或缩写一并去掉（A. R. Wallace→华莱士）。引证（Name, 年）、Name et al. (年)、
            Name (年)、参考文献节与条目行、标题里的「中文（English）」括注、Ray Lankester 这类前后另有姓名的，一概不动。
  3 数字    英文里带单位的数字（12 mm、5–8 cm、30%）和 4 位年份必须原样出现在中文里（只报告）。
  4 术语首现  yiku 已核译名（自域，非学名）的英文出现在英文块里时，该中文名在本章第一次出现处必须跟「（English）」，
            之后只写中文；--fix 补上。不进标题、引证；单字译名、候选译名不管；落在更长已知名里的不算（longest-match）。
            --seen FILE 记录本章已引入的术语（JSON 列表），各块依次跑即共享「首现」状态。
退出码：1 = 还有没修好的问题（拉丁名缺失且补不了、数字缺失、未加 --fix 时的人名/术语），0 = 干净。

  fidelity_check.py --en chunk.txt --zh chunk.md [--fix] [-o 另存] [--domain 分类学] [--seen seen.json]
                    [--persons FILE] [--db yiku.db] [--scope 科名;科名] [--no-yiku]
--fix 原地改写时先备份 *.bak-fidelity（已有则不覆盖）。接入 run_batches 直调初译：按块序依次检查，日志 核译/direct/<章>/fidelity/cNN.txt。
局限：拉丁名靠启发式（句首词表、拉丁词尾、地名表），可能有噪声；非斜体的 OCR 原文尤其如此。"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKUP_SUFFIX = ".bak-fidelity"

_TRAILER = re.compile(r"^### (?:待定术语|术语决策)", re.M)
_MARK = re.compile(r"^[ \t]*<!--.*?-->[ \t]*\n?", re.M)
_CJK = re.compile(r"[一-鿿]")
_ZH_NAME = re.compile(r"[一-鿿]{2,}")


@dataclass
class Issue:
    kind: str            # 拉丁名 | 人名 | 数字 | 术语首现
    item: str
    detail: str = ""
    sentence: str = ""
    fixed: bool = False

    def line(self) -> str:
        s = f"[{self.kind}] {self.item}：{self.detail}（{'已修' if self.fixed else '未修'}）"
        return s + (f"\n    英文：{self.sentence}" if self.sentence else "")


@dataclass
class Result:
    zh: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def unfixed(self) -> list[Issue]:
        return [i for i in self.issues if not i.fixed]


def split_trailer(zh: str) -> tuple[str, str]:
    m = _TRAILER.search(zh)
    return (zh[:m.start()], zh[m.start():]) if m else (zh, "")


# ---------------------------------------------------------------- 句子

_ABBR = {"al", "sp", "spp", "cf", "fig", "figs", "vs", "no", "nos", "ca", "etc", "eg", "ie", "viz", "vol", "pp", "ed", "eds"}
_BOUND = re.compile(r"[.!?][\"”’')\]]*\s+(?=[\"“‘'(\[]*[A-Z0-9])|\n[ \t]*\n")


def sentence_at(text: str, pos: int) -> str:
    start, end = 0, len(text)
    for m in _BOUND.finditer(text):
        if m.group(0)[0] == ".":
            w = re.search(r"([A-Za-z]+)$", text[:m.start()])
            if w and ((len(w.group(1)) == 1 and w.group(1).isupper()) or w.group(1).lower() in _ABBR):
                continue
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start() + 1
            break
    if end - start > 300:                                     # 长句：取命中位置前后各约 150 字
        a, b = max(start, pos - 150), min(end, pos + 150)
        return ("…" if a > start else "") + re.sub(r"\s+", " ", text[a:b]).strip() + ("…" if b < end else "")
    return re.sub(r"\s+", " ", text[start:end]).strip()


# ---------------------------------------------------------------- 保护区间（引证、文献、标题、页码标记）

_YEAR = r"(?:1[5-9]\d\d|20\d\d)[a-z]?"
_REF_HEAD = re.compile(r"^#{1,6}\s*(?:References?|Literature(?: Cited)?|Bibliography|参考文献|引用文献|文献)\s*$", re.I)
_REF_LINE = re.compile(r"^[\s\-*>\d.\[\]]*[A-Z][A-Za-z'’\-]+,?\s+(?:[A-Z]\.\s*)+")
_NARRATIVE = re.compile(rf"(?<![A-Za-z])[A-Z][A-Za-z'’\-]+(?:\s+et\s+al\.?|\s*等|\s+(?:and|&|与|和)\s*[A-Z][A-Za-z'’\-]+)?"
                        rf"\s*[,，]?\s*[（(]?\s*{_YEAR}(?!\d)")
Span = tuple[int, int]


def _lines(text: str) -> list[tuple[int, str]]:
    out, pos = [], 0
    for ln in text.split("\n"):
        out.append((pos, ln))
        pos += len(ln) + 1
    return out


def citation_spans(text: str) -> list[Span]:
    """引证：含年份且不含汉字的括号组、Name (年)/Name et al. (年)/Name, 年，参考文献节与条目行。"""
    spans: list[Span] = []
    for m in re.finditer(r"[（(][^（）()]*[）)]", text):
        if re.search(rf"(?<!\d){_YEAR}(?!\d)", m.group(0)) and not _CJK.search(m.group(0)):
            spans.append(m.span())
    spans += [m.span() for m in _NARRATIVE.finditer(text)]
    in_refs = False
    for pos, ln in _lines(text):
        if ln.startswith("#"):
            in_refs = bool(_REF_HEAD.match(ln.strip()))
        if in_refs or (_REF_LINE.match(ln) and re.search(_YEAR, ln)):
            spans.append((pos, pos + len(ln)))
    return spans


def structure_spans(text: str) -> list[Span]:
    """标题行与页码标记行。"""
    return [(p, p + len(ln)) for p, ln in _lines(text) if ln.startswith("#") or re.match(r"\s*<!--.*-->\s*$", ln)]


def _hit(spans: list[Span], a: int, b: int) -> bool:
    return any(a < e and b > s for s, e in spans)


# ---------------------------------------------------------------- 人名

GIVEN_WORDS = set("William Charles Alfred Russel Russell Gregor Johann Hugo Ernst Thomas Henry Julian Georges Jean Carl "
                  "Carolus Edward John Francis Walter Frank Joseph".split())
GIVEN = "(?:" + "|".join(sorted(GIVEN_WORDS)) + r")(?:-[A-Z][a-z]+)?"
STARTERS = set(
    "The This That These Those There Their They Then Thus Therefore It Its In On At As An A And But Or Nor If When While "
    "Whenever Whereas Where Which What Who Whose How Why Although Though Because Since For From With Without By To Of "
    "Among Between Such Some Many Most All Each Every Other Another Both One Two Three Several Few More Less Often Also "
    "Even Still Yet However Moreover Furthermore Hence Here He She We You His Her Our Not No Only Either Neither Species "
    "Genus Genera Taxa Taxon After Before During Under Over Within Upon Until Unless Once Now Today Indeed Instead Rather "
    "Perhaps Usually Generally Sometimes Recently Early Late Figure Table Plate Chapter Section Appendix Index".split())


def default_persons() -> Path | None:
    for p in (ROOT / "skill" / "person_names.tsv", ROOT / "person_names.tsv"):   # 仓库里在 skill/，技能目录副本里在根
        if p.exists():
            return p
    return None


def load_persons(path: str | Path | None = None) -> dict[str, str]:
    """TSV：英文<TAB>中文，# 开头为注释，坏行忽略。"""
    p = Path(path) if path else default_persons()
    out: dict[str, str] = {}
    if p is None or not p.exists():
        return out
    for ln in p.read_text(encoding="utf8").splitlines():
        cells = [c.strip() for c in ln.split("\t")]
        if ln.lstrip().startswith("#") or len(cells) < 2 or not cells[0] or not _CJK.search(cells[1]):
            continue
        out[cells[0]] = cells[1]
    return out


def _name_alt(name: str) -> str:
    esc = re.escape(name).replace(r"\ ", r"\s+")
    return ("[Dd]" + esc[1:]) if name.startswith("De ") else esc


def fix_persons(text: str, persons: dict[str, str], fix: bool = True) -> tuple[str, dict[str, int]]:
    """把 persons 里的英文人名换成中文。返回 (新文本, {英文名: 处数})；fix=False 时文本不变，只统计。"""
    if not persons:
        return text, {}
    alt = "|".join(_name_alt(n) for n in sorted(persons, key=len, reverse=True))
    pat = re.compile(rf"(?<![A-Za-z\-])(?P<given>(?:(?:{GIVEN}|[A-Z]\.)\s*)+)?(?P<name>{alt})(?P<poss>['’]s?)?"
                     rf"(?![A-Za-z\-])(?!\s+[A-Z][a-z]{{2,}})")
    spans = citation_spans(text)
    counts: dict[str, int] = {}

    def sub(m: re.Match[str]) -> str:
        a, b = m.start(), m.end()
        key = re.sub(r"\s+", " ", m.group("name"))
        key = "De Vries" if key == "de Vries" and "De Vries" in persons else key
        zh = persons.get(key)
        if zh is None or _hit(spans, a, b):
            return m.group(0)
        before = text[:a]
        if before.endswith(("（", "(")) and before[:-1].endswith(zh):          # 达尔文（Charles Darwin）：括注不动
            return m.group(0)
        pm = re.search(r"(?<![A-Za-z])([A-Z][a-z]+)[ \t]+$", before)
        if pm and pm.group(1) not in STARTERS and pm.group(1) not in GIVEN_WORDS:   # Erasmus Darwin：前面另有姓名
            return m.group(0)
        counts[key] = counts.get(key, 0) + 1
        return zh + ("的" if m.group("poss") else "")

    new = pat.sub(sub, text)
    return (new if fix else text), counts


# ---------------------------------------------------------------- yiku

_NOT_LATIN = re.compile(r"(ism|ist|ian|ic|ous|ive|ment|tion|ness|ity|type|species|logy)$")
_RANK_ZH = re.compile(r"(?:总科|亚科|科|亚目|目|亚纲|纲|门|族|类)$")
_LATIN_ROW = re.compile(r"[A-Z][a-z]+(?: [a-z]{3,})?")


def zh_forms(zh: str) -> list[str]:
    """译名里可作正文写法的各备选名：去括注，按 ；;/／、，, 拆开，只留 ≥2 个汉字的。"""
    base = re.sub(r"[（(][^）)]*[）)]", "", zh)
    return [a.strip() for a in re.split(r"[；;/／、，,]", base) if _ZH_NAME.fullmatch(a.strip())]


class Yiku:
    """yiku 的只读视图：已知属名/种名及其中文名（拉丁名核对与补全），已核术语（首现括注）。con 须为 sqlite3.Row 行工厂。"""

    def __init__(self, con: Any, domain: str = "分类学", scope: set[str] | None = None, fallback: str | None = None):
        self.con, self.domain, self.scope = con, domain, scope or set()
        self._D = importlib.import_module("yiku.db")
        self.fb: list[str] = self._D.resolve_fallback(domain, fallback)
        doms = list(dict.fromkeys(["*", domain, *self.fb]))
        marks = ",".join("?" * len(doms))
        self.latin: dict[str, tuple[str, list[str]]] = {}
        for en, zh in con.execute(f"SELECT en, zh FROM terms WHERE status!='否决' AND domain IN ({marks}) "
                                  "ORDER BY status!='已核'", doms):
            en = en.strip()
            if not _LATIN_ROW.fullmatch(en):
                continue
            if " " not in en and (_NOT_LATIN.search(en.lower()) or _RANK_ZH.search(zh.strip())):
                continue
            forms = zh_forms(zh)
            if forms:
                cur = self.latin.setdefault(en.lower(), (en, []))[1]
                cur += [f for f in forms if f not in cur]
        self.genera = {k for k in self.latin if " " not in k}
        self.all_zh: set[str] = set()      # 已核译名（自域），longest-match 保护用
        for (zh,) in con.execute("SELECT zh FROM terms WHERE status='已核' AND domain IN (?, '*')", (domain,)):
            self.all_zh.update(zh_forms(zh))

    def is_genus(self, word: str) -> bool:
        return word.lower() in self.genera

    def knows(self, latin: str) -> bool:
        return latin.lower() in self.latin

    def zh_names(self, latin: str) -> list[str]:
        return list(self.latin.get(latin.lower(), ("", []))[1])

    def terms_in(self, en_text: str) -> list[tuple[str, list[str]]]:
        """英文块里出现的、自域有已核译名的非学名术语：[(英文, [中文备选…])]。"""
        match = importlib.import_module("yiku.match")
        classify = importlib.import_module("yiku.classify")
        out = []
        for en in sorted(match.find_terms(self.con, en_text, self.domain, self.fb)):
            own = [h for h in self._D.candidates(self.con, en, self.domain, self.scope, self.fb)
                   if h.status == "已核" and not h.fallback]
            if not own or classify.is_taxon_name(own[0].en):
                continue
            forms = list(dict.fromkeys(f for h in own for f in zh_forms(h.zh)))
            if forms:
                out.append((own[0].en, forms))
        return out


def open_yiku(domain: str = "分类学", db: str | Path | None = None, scope: set[str] | None = None) -> Yiku | None:
    """只读打开 yiku 库；没有库或没装 yiku 返回 None（只做不依赖术语库的检查）。"""
    try:
        path = Path(db) if db else importlib.import_module("yiku.db").default_path()
        if not path.exists():
            return None
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return Yiku(con, domain, scope)
    except (ImportError, sqlite3.Error):
        return None


def _first_valid(text: str, forms: list[str], spans: list[Span], longer: list[str]) -> Span | None:
    """forms 里任一中文名在 text 里最早的、不在保护区间也不落在更长已知名里的出现。"""
    best: Span | None = None
    for z in forms:
        for m in re.finditer(re.escape(z), text):
            a, b = m.span()
            if _hit(spans, a, b) or any(a - k >= 0 and text.startswith(L, a - k) for L in longer if len(L) > len(z)
                                        for k in _offsets(L, z)):
                continue
            if best is None or a < best[0]:
                best = (a, b)
            break
    return best


def _offsets(long: str, short: str) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(short), long)]


def _longer(y: Yiku | None, zh: str) -> list[str]:
    return [L for L in y.all_zh if len(L) > len(zh) and zh in L] if y else []


# ---------------------------------------------------------------- 1 拉丁名

_NOT_GENUS = STARTERS | set(
    "Africa America Asia Australia Antarctica Europe India China Canada Cuba Java Sumatra Florida Alaska Victoria Russia "
    "Panama Carolina Virginia Georgia California Pennsylvania Louisiana Atlantis Paris Alabama Nevada Montana Dakota "
    "Minnesota Indiana Tasmania Malaysia Indonesia Siberia Gondwana Laurasia Pangaea Eurasia Oceania Polynesia Micronesia "
    "Melanesia Status Bonus Focus Analysis Hypothesis Synthesis Basis Thesis Emphasis Axis Crisis Origin Handbook".split())
_EN_WORDS = set(
    "and or the an of in on at to by for from with without as is are was were be been has have had can may might will would "
    "also but that which who whose when where while not only both each other than then thus these those this such see like "
    "occurs lacks bears shows possesses lives live include includes appears found known called named spp aff nov gen sensu "
    "indet species genus group complex status focus various previous serious obvious versus plus minus virus census".split())
_EPITHET_END = re.compile(r"(?:us|um|is|ii|i|ae|a|ens|ans|ax|ix|ex|ys|or|er|on)$")
_GENUS_END = re.compile(r"(?:a|um|us|is|ys|ix|ex|ax|ides|odes)$")
_HIGHER_RANK = re.compile(r"(?:idae|inae|ini|oidea|aceae|ales|ida|iformia|idea)$")   # 科以上：不算属名
_CAP = re.compile(r"(?<![A-Za-z'’\-])([A-Z][a-z]{2,})(?![A-Za-z])")
_ITALIC = re.compile(r"\*([A-Z][a-z]+(?: [a-z]{3,})?)\*")


def _sentence_start(text: str, pos: int) -> bool:
    b = re.sub(r"[\"“‘'(\[]+$", "", text[:pos].rstrip(" \t"))
    return not b.strip() or bool(re.search(r"[.!?:]$", b)) or bool(re.search(r"\n\s*\n$", b))


def find_latin(en: str, y: Yiku | None = None, persons: dict[str, str] | None = None) -> list[tuple[str, int]]:
    """英文里的属名/双名及首现位置（已去掉 * 的文本里的位置）。双名：斜体、yiku 已知，或大写词+拉丁词尾的小写词；
    单独的属名：斜体、yiku 已知属名，或句中的大写拉丁词尾词（排除人名表、句首词、地名、科以上词尾、Name's、Name, 年）。"""
    forced = set(_ITALIC.findall(en))
    text = en.replace("*", "")
    person_words = {w for n in (persons or {}) for w in n.split() if len(w) > 2}
    found: dict[str, int] = {}
    for m in _CAP.finditer(text):
        word, a = m.group(1), m.start()
        after = text[m.end():]
        if word in person_words or after.startswith("-"):             # 人名表；行尾断词的前半（Dis-/septa）
            continue
        ep = re.match(r" ([a-z]{3,})(?![A-Za-z])", after)
        if ep:
            name, epi = f"{word} {ep.group(1)}", ep.group(1)
            if (name in forced or bool(y and y.knows(name))
                    or (word not in _NOT_GENUS and epi not in _EN_WORDS and _EPITHET_END.search(epi))):
                found.setdefault(name, a)
                continue
        known = bool(y and y.is_genus(word))
        if word in forced or known:
            found.setdefault(word, a)
            continue
        if re.match(r"['’]s?\b", after) or re.match(rf"\s*,?\s*\(?{_YEAR}", after) or re.match(r"\s+et\s+al", after):
            continue                                                    # Ray's、Linnaeus, 1758：人名
        prev = re.search(r"(?<![A-Za-z])([A-Z][a-z]+|[A-Z]\.)[ \t]+$", text[:a])
        if (not _sentence_start(text, a) and word not in _NOT_GENUS and _GENUS_END.search(word)
                and not _HIGHER_RANK.search(word) and not (prev and prev.group(1) not in _NOT_GENUS)):
            found.setdefault(word, a)
    return sorted(found.items(), key=lambda kv: kv[1])


def latin_in_zh(zh_plain: str, name: str) -> bool:
    if " " in name:
        g, s = name.split(" ", 1)
        return bool(re.search(rf"(?<![A-Za-z])(?:{g}|{g[0]}\.)\s*{s}(?![A-Za-z])", zh_plain, re.I))
    return bool(re.search(rf"(?<![A-Za-z]){name}(?![a-z])", zh_plain))


def _latin_step(en: str, body: str, y: Yiku | None, persons: dict[str, str], fix: bool, issues: list[Issue]) -> str:
    names = find_latin(en, y, persons)
    en_plain = en.replace("*", "")
    for name, pos in names:
        if latin_in_zh(body.replace("*", "").replace("_", ""), name):
            continue
        issue = Issue("拉丁名", name, "中文里没有出现", sentence_at(en_plain, pos))
        issues.append(issue)
        forms = y.zh_names(name) if (fix and y) else []
        spans = citation_spans(body) + structure_spans(body)
        hit = _first_valid(body, forms, spans, [L for z in forms for L in _longer(y, z)]) if forms else None
        if hit:
            end = hit[1]
            if " " not in name and body[end:end + 1] == "属" and not body[hit[0]:hit[1]].endswith("属"):
                end += 1
            body = body[:end] + f"（*{name}*）" + body[end:]
            issue.fixed, issue.detail = True, f"中文里没有出现；已在「{body[hit[0]:hit[1]]}」后补「（*{name}*）」"
    return body


# ---------------------------------------------------------------- 2 人名

def _person_step(body: str, persons: dict[str, str], fix: bool, issues: list[Issue]) -> str:
    new, counts = fix_persons(body, persons, fix)
    for name, n in counts.items():
        issues.append(Issue("人名", name, f"英文人名应写「{persons[name]}」×{n}", fixed=fix))
    return new


# ---------------------------------------------------------------- 3 数字

_NUM = r"\d+(?:[.,]\d+)*"
_UNITS = ("mm2|mm3|cm2|cm3|km2|mm|cm|km|µm|μm|um|nm|mg|kg|ml|mL|µl|μl|ha|bp|kb|Mb|Ma|Myr|Gyr|mya|ppm|ppt|rpm|kDa|kHz|Hz|"
          "years?|yrs?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|weeks?|months?|per ?cent|percent|meters?|metres?|"
          "centimeters?|centimetres?|millimeters?|millimetres?|kilometers?|microns?|fathoms?|feet|ft|inch(?:es)?|"
          "°C|°F|°|%|‰|µM|μM|mM|nM")
_UNIT_NUM = re.compile(rf"(?<![\w.,])({_NUM})(?:\s*[-–—]\s*({_NUM}))?\s?(?:(?:{_UNITS})(?![A-Za-z])|[mg](?![A-Za-z]))|"
                       rf"(?<![\w.,])({_NUM})(?:\s*[-–—]\s*({_NUM}))?[lhs](?![A-Za-z])")
_YEAR_RE = re.compile(r"(?<![\d,.])(1[5-9]\d\d|20\d\d)(?!\d)")


def _norm_num(n: str) -> str:
    return re.sub(",", "", n) if re.fullmatch(r"\d{1,3}(?:,\d{3})+", n) else n


def _zh_numbers_text(zh: str) -> str:
    t = zh.translate({0xFF10 + i: ord("0") + i for i in range(10)} | {0xFF0E: ord(".")})
    return re.sub(r"(?<=\d)[, ](?=\d{3}(?!\d))", "", t)


def _number_step(en: str, body: str, issues: list[Issue]) -> None:
    zh = _zh_numbers_text(body)
    done: set[str] = set()

    def present(n: str) -> bool:
        return bool(re.search(rf"(?<![\d.]){re.escape(n)}(?!\d|\.\d)", zh))

    for m in _UNIT_NUM.finditer(en):
        nums = [_norm_num(x) for x in (m.group(1), m.group(2), m.group(3), m.group(4)) if x]
        if m.group(0) not in done and any(not present(n) for n in nums):
            done.add(m.group(0))
            issues.append(Issue("数字", m.group(0), "英文里的数字（含单位）在中文里没有原样出现", sentence_at(en, m.start())))
        done.update(nums)
    for m in _YEAR_RE.finditer(en):
        if m.group(1) not in done and not present(m.group(1)):
            done.add(m.group(1))
            issues.append(Issue("数字", m.group(1), "英文里的年份在中文里没有出现", sentence_at(en, m.start())))


# ---------------------------------------------------------------- 4 术语首现

def _gloss_ok(body: str, end: int, en: str) -> bool:
    m = re.match(r"[（(]\s*\*?([^）)]*)", body[end:])
    stem = re.sub(r"[\s\-]+", " ", en.lower())
    return bool(m and re.sub(r"[\s\-*]+", " ", m.group(1).lower()).startswith(stem[:max(4, min(len(stem), 6))]))


def _term_step(en: str, body: str, y: Yiku | None, fix: bool, seen: set[str] | None, issues: list[Issue]) -> str:
    if y is None:
        return body
    seen = seen if seen is not None else set()
    for term, forms in y.terms_in(en):
        key = term.lower()
        if key in seen:
            continue
        hit = _first_valid(body, forms, citation_spans(body) + structure_spans(body),
                           [L for z in forms for L in _longer(y, z)])
        if hit is None:
            continue
        seen.add(key)
        if _gloss_ok(body, hit[1], term):
            continue
        issue = Issue("术语首现", term, f"「{body[hit[0]:hit[1]]}」首现缺英文括注", fixed=fix)
        issues.append(issue)
        if fix:
            body = body[:hit[1]] + f"（{term}）" + body[hit[1]:]
    return body


# ---------------------------------------------------------------- 总入口

def check_texts(en: str, zh: str, *, yiku: Yiku | None = None, persons: dict[str, str] | None = None,
                fix: bool = False, seen: set[str] | None = None) -> Result:
    """核对一块。persons=None 读默认 person_names.tsv；seen 是本章已引入术语（就地更新）。fix=False 时 zh 原样返回。"""
    persons = load_persons() if persons is None else persons
    en = _MARK.sub("", en)
    body, trailer = split_trailer(zh)
    issues: list[Issue] = []
    body = _latin_step(en, body, yiku, persons, fix, issues)
    body = _person_step(body, persons, fix, issues)
    _number_step(en, body, issues)
    body = _term_step(en, body, yiku, fix, seen, issues)
    return Result(body + trailer, issues)


def report(res: Result, title: str = "") -> str:
    n = len(res.issues)
    head = f"# 保真检查{title}：问题 {n}，已修 {n - len(res.unfixed)}，待处理 {len(res.unfixed)}"
    return head + "\n" + "".join(i.line() + "\n" for i in res.issues)


# ---------------------------------------------------------------- 整章（run_batches 直调初译用）

def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf8")).hexdigest()[:12]


def run_chapter(base: Path, ids: list[str], *, yiku: Yiku | None, persons: dict[str, str] | None = None,
                fix: bool = True) -> list[str]:
    """按块序检查并修正 <base>/out/cNN.md（原文 <base>/chunks/cNN.txt），共享术语首现状态。
    原稿先备份 cNN.md.bak-fidelity；日志 <base>/fidelity/cNN.txt；状态 <base>/fidelity/seen.json 记每块修正后文本的 sha1
    和该块引入的术语（输出没变的块跳过）。遇到还没有输出的块就停（其后各块待补跑后再做，保证首现顺序）。返回给人看的摘要行。"""
    persons = load_persons() if persons is None else persons
    fid = base / "fidelity"
    state_f = fid / "seen.json"
    state: dict[str, Any] = json.loads(state_f.read_text(encoding="utf8")) if state_f.exists() else {}
    seen: set[str] = set()
    lines: list[str] = []
    for cid in ids:
        out, chunk = base / "out" / f"{cid}.md", base / "chunks" / f"{cid}.txt"
        if not out.exists():
            lines.append(f"{cid}：还没有输出，其后各块待补跑后再做保真检查")
            break
        text = out.read_text(encoding="utf8")
        st = state.get(cid)
        if st and st.get("sha") == _sha(text):
            seen.update(st.get("terms", []))
            continue
        before = set(seen)
        res = check_texts(chunk.read_text(encoding="utf8"), text, yiku=yiku, persons=persons, fix=fix, seen=seen)
        fid.mkdir(parents=True, exist_ok=True)
        if res.zh != text:
            (base / "out" / f"{cid}.md{BACKUP_SUFFIX}").write_text(text, encoding="utf8")
            out.write_text(res.zh, encoding="utf8")
        (fid / f"{cid}.txt").write_text(report(res, f" {cid}"), encoding="utf8")
        state[cid] = {"sha": _sha(res.zh), "terms": sorted(seen - before)}
        state_f.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf8")
        if res.issues:
            lines.append(f"{cid}：保真检查 {len(res.issues)} 处，已修 {len(res.issues) - len(res.unfixed)}，"
                         f"待处理 {len(res.unfixed)} -> {fid / (cid + '.txt')}")
    return lines


# ---------------------------------------------------------------- 命令行

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    ap.add_argument("--en", required=True, help="英文块")
    ap.add_argument("--zh", required=True, help="中文块（.md）")
    ap.add_argument("--fix", action="store_true", help="修正：补拉丁名、改人名、补术语首现括注")
    ap.add_argument("-o", "--out", help="另存为（缺省 --fix 时原地改写并备份 .bak-fidelity）")
    ap.add_argument("--domain", default="分类学", help="yiku 领域")
    ap.add_argument("--db", help="yiku 库（缺省 $YIKU_DB 或 ~/.yiku/yiku.db）")
    ap.add_argument("--scope", default="", help="yiku 类群范围，分号分隔")
    ap.add_argument("--no-yiku", action="store_true", help="不用 yiku（只查人名、数字和启发式拉丁名）")
    ap.add_argument("--persons", help="人名表 TSV（缺省 skill/person_names.tsv）")
    ap.add_argument("--seen", help="本章已引入术语的 JSON 文件；读入并更新，各块共用以判断「首现」")
    a = ap.parse_args(argv)
    en = Path(a.en).read_text(encoding="utf8")
    zh_path = Path(a.zh)
    zh = zh_path.read_text(encoding="utf8")
    y = None if a.no_yiku else open_yiku(a.domain, a.db, {s for s in a.scope.split(";") if s})
    if y is None and not a.no_yiku:
        print("提示：取不到 yiku 库，已跳过术语库相关检查（--no-yiku 可消除此提示）", file=sys.stderr)
    seen_f = Path(a.seen) if a.seen else None
    seen = set(json.loads(seen_f.read_text(encoding="utf8"))) if seen_f and seen_f.exists() else set()
    res = check_texts(en, zh, yiku=y, persons=load_persons(a.persons), fix=a.fix, seen=seen)
    if seen_f:
        seen_f.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf8")
    print(report(res, f" {zh_path.name}"), end="")
    if a.out:
        Path(a.out).write_text(res.zh, encoding="utf8")
    elif a.fix and res.zh != zh:
        bak = zh_path.with_name(zh_path.name + BACKUP_SUFFIX)
        if not bak.exists():
            bak.write_text(zh, encoding="utf8")
        zh_path.write_text(res.zh, encoding="utf8")
    return 1 if res.unfixed else 0


if __name__ == "__main__":
    sys.exit(main())
