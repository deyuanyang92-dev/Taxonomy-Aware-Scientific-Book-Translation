#!/usr/bin/env python3
"""学名排版：属名、种加词、亚种加词斜体；科/亚科/族等阶元名、命名人、sp./cf. 正体。

Why: OCR 只保留字形，不保留斜体；Google/DeepSeek 也不会替原文补排版。于是译文里
*Opisthodonta morena* 全成了正体。本脚本按分类学通行的排版规则做确定性补斜体，
不调用模型，可重复运行。

规则（Zootaxa / ICZN 惯例）：
  *斜体*：属名、种加词、亚种加词，含缩写 *O. morena*；检索表、图注、标题内同样适用。
  正体：科（-idae）、亚科（-inae）、族（-ini）、总科（-oidea）等科级以上阶元；
        命名人与年份（Langerhans, 1879）；sp./spp./sp. n./cf./aff./var./gen. n. 等符号词。

用法：
  python3 taxoformat.py a.md b.md                 # 只报告，有待改处退出码 1
  python3 taxoformat.py a.md b.md --fix           # 备份 *.bak-taxo 后写回
  python3 taxoformat.py a.md --report out.tsv     # 另存报告
  python3 taxoformat.py a.md --genera genera.txt  # 追加已知属名（每行一个）

属名/双名优先取本机 WoRMS Annelida 缓存；文本中新描述的种（sp. n.）、带命名人年份的
标题、genus X 标签、重复出现的双名补进词表。WoRMS 未收录的异名按“属名 + 小写非停用词”
补斜体，但 *Leanira* it、*Onuphis* cannot 这类英语词只斜体属名。已知属名可再用
--genera 补。局限：只处理拉丁学名的常见书写形式；不判断同名异义（如属名恰好是人名）。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BACKUP_SUFFIX = ".bak-taxo"

# 本机 WoRMS 缓存（oworms / specimen inventory 共用）；有则用其中的 Annelida 属名作权威表。
DEFAULT_GENERA_DB = Path("/root/.specimen_inventory/worms_cache.sqlite")

# hunspell 英语词典：判断未收录类群里紧跟斜体属名的词是不是普通英语词。
ENGLISH_DICT = Path("/usr/share/hunspell/en_US.dic")

# 科级及以上阶元：这些后缀的词一律正体（属名极少以这些后缀结尾）。
FAMILY_SUFFIX = re.compile(r"(?:idae|inae|ini|oidea|acea|iformes|phyta|mycota)$", re.IGNORECASE)

# 阶元符号词：正体，不当作种加词。
RANK_WORDS = {
    "sp", "spp", "sp.", "spp.", "cf", "cf.", "aff", "aff.", "var", "var.",
    "f", "f.", "forma", "gen", "gen.", "nov", "nov.", "n", "n.", "comb", "comb.",
    "stat", "stat.", "incertae", "sedis", "subsp", "subsp.", "ssp", "ssp.",
}

# 大写词后接小写词时，这些不是属名/种加词（英语功能词、描述词、常见标题词）。
STOP = {
    # function words
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "as", "at", "by", "for",
    "from", "in", "into", "of", "on", "onto", "to", "with", "without", "within", "between",
    "among", "during", "after", "before", "under", "over", "above", "below", "near", "along",
    "across", "through", "about", "approximately", "around", "per", "via", "versus", "vs",
    # 法/德/荷人名与地名里的介词、冠词：Richer de Forges / van der Land
    "de", "del", "della", "der", "den", "des", "du", "et", "al", "la", "le", "les",
    "van", "von", "und", "mit", "fur", "für", "auf", "aus", "bei", "nach", "zu", "zum",
    "zur", "sur", "sous", "dans", "pour", "par", "aux", "am", "im", "zum",
    "this", "these", "those", "that", "which", "where", "when", "while", "who", "whose",
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "does", "do",
    "did", "can", "could", "may", "might", "must", "shall", "should", "will", "would",
    "not", "no", "only", "also", "both", "all", "some", "each", "other", "another", "such",
    "more", "most", "less", "least", "very", "well", "poorly", "known", "described",
    "recorded", "reported", "found", "collected", "examined", "illustrated", "characterized",
    "similar", "closely", "differs", "differ", "resembles", "compared", "belongs", "occurs",
    "ranges", "extends", "reaches", "lacks", "shows", "bearing", "including", "includes",
    "comprises", "consists", "contains", "forms", "occurs", "lives", "inhabits", "appears",
    "seems", "remains", "becomes", "grows", "measures", "varies", "divided", "provided",
    # common sentence starts / headings
    "the", "this", "these", "those", "three", "four", "five", "six", "two", "one", "new",
    "simple", "median", "lateral", "dorsal", "ventral", "anterior", "posterior", "body",
    "prostomium", "peristomium", "pharynx", "stomach", "parapodia", "parapodium", "setae",
    "chaetae", "antenna", "antennae", "cirri", "cirrus", "palps", "eyes", "types", "type",
    "holotype", "paratype", "paratypes", "syntype", "syntypes", "lectotype", "material",
    "etymology", "habitat", "biology", "synonymy", "reproduction", "development",
    "variation", "affinities", "comparison", "differential", "systematic", "taxonomic",
    "zoological", "university", "museum", "institute", "department", "republic", "north",
    "south", "east", "west", "red", "black", "white", "mediterranean", "atlantic", "pacific",
    "indian", "arctic", "antarctic", "locus", "figure", "fig", "figs", "plate", "pl",
    "table", "text", "station", "sample", "genus", "species", "family", "subfamily",
    "order", "class", "phylum", "remarks", "distribution", "ecology", "description",
    "diagnosis", "discussion", "references", "summary", "introduction", "key", "abstract",
    "according", "because", "however", "therefore", "although", "whereas", "further",
    "additional", "mainly", "mostly", "generally", "usually", "often", "sometimes",
    "particularly", "especially", "relatively", "slightly", "distinctly", "strongly",
    "widely", "narrowly", "deeply", "shallowly", "smoothly", "finely", "coarsely",
}

# 这些词即使小写也不当种加词（常见英语词，防止 Genus from / Genus with 被整体斜体）。
EPITHET_STOP = STOP | {
    "type", "types", "specimens", "specimen", "material", "record", "records", "species",
    "form", "forms", "group", "groups", "complex", "sense", "lato", "strict", "sensu",
    "part", "parts", "side", "sides", "end", "ends", "base", "bases", "tip", "tips",
    "edge", "edges", "margin", "margins", "surface", "surfaces", "shape", "size", "sizes",
    "length", "width", "height", "depth", "range", "ranges", "number", "numbers",
    # 常见代词/助动词/动词/普通名词：避免把 "*Leanira* it"、"*Onuphis* cannot"、
    # "*Nerinides* possess"、"*Phragmatopoma* tubes" 当成双名。
    "it", "its", "they", "them", "their", "this", "these", "those", "there", "which",
    "that", "who", "whose", "we", "our", "you", "i", "he", "she", "his", "her",
    "cannot", "can", "could", "may", "might", "must", "shall", "should", "will",
    "would", "do", "does", "did", "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "possess", "possesses", "show", "shows", "occur", "occurs",
    "contain", "contains", "lack", "lacks", "bear", "bears", "reach", "reaches",
    "measure", "measures", "differ", "differs", "resemble", "resembles",
    "tubes", "tube", "justified",
}

CAND = re.compile(r"\b([A-Z][a-z][a-z-]{1,})\s+([a-z][a-z-]{1,})\b")


@dataclass(frozen=True)
class Lexicon:
    genera: frozenset[str]
    binomials: frozenset[tuple[str, str]]
    trinomials: frozenset[tuple[str, str, str]]
    # 英语常用词（hunspell en_US），用于区分未收录类群的种加词与普通英语词：
    # *Cypris* verauxli 补斜体，*Acropora* coral 不补。词典缺失时为空集。
    english: frozenset[str] = frozenset()

    @property
    def upper_genera(self) -> frozenset[str]:
        return frozenset(g.upper() for g in self.genera)

    @property
    def upper_binomials(self) -> frozenset[tuple[str, str]]:
        return frozenset((g.upper(), e.upper()) for g, e in self.binomials)

    @property
    def abbr_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset((g[0].upper(), e) for g, e in self.binomials if g)

    @property
    def upper_abbr_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset((g[0].upper(), e.upper()) for g, e in self.binomials if g)


def _ok_pair(genus: str, epithet: str) -> bool:
    if not genus or not epithet:
        return False
    if genus.lower() in STOP or epithet.lower() in EPITHET_STOP:
        return False
    if FAMILY_SUFFIX.search(genus) or FAMILY_SUFFIX.search(epithet):
        return False
    if epithet.lower().strip(".") in RANK_WORDS:
        return False
    return True


NAME_RE = re.compile(r"^([A-Z][a-z-]+)\s+([a-z][a-z-]+)(?:\s+([a-z][a-z-]+))?$")


def load_worms_names(path: Path = DEFAULT_GENERA_DB) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str, str]]]:
    """WoRMS 缓存里的 Annelida 属名、双名、三名；库不存在时返回空集。"""
    if not path.exists():
        return set(), set(), set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = con.execute(
            "select distinct valid_name from worms_taxa "
            "where phylum='Annelida' and rank in ('Species','Subspecies')"
        ).fetchall()
    except sqlite3.Error:
        return set(), set(), set()
    genera: set[str] = set()
    binomials: set[tuple[str, str]] = set()
    trinomials: set[tuple[str, str, str]] = set()
    for (name,) in rows:
        m = NAME_RE.match((name or "").strip())
        if not m:
            continue
        g, e, s = m.groups()
        genera.add(g)
        binomials.add((g, e))
        if s:
            trinomials.add((g, e, s))
    return genera, binomials, trinomials


NEW_SPECIES = re.compile(
    r"\b([A-Z][a-z-]+)\s+([a-z][a-z-]+)\s+"
    r"(?:sp\.\s*n\.|n\.\s*sp\.|sp\.\s*nov\.|nov\.\s*sp\.)"
)
AUTHORED = re.compile(
    r"\b([A-Z][a-z-]+)\s+([a-z][a-z-]+)\s+"
    r"[A-Z][A-Za-zÀ-ÿ'’-]+(?:,\s*|\s+)(?:1[789]\d\d|20\d\d)"
)
NEW_GENUS = re.compile(r"\b([A-Z][a-z-]+)\s+gen\.\s*n\.")
GENUS_LABEL = re.compile(r"\b(?:genus|subgenus)\s+([A-Z][a-z-]+)")


def build_lexicon(texts: list[str], extra_genera: list[str] | None = None,
                  genera_db: Path | None = DEFAULT_GENERA_DB,
                  english_dict: Path | None = ENGLISH_DICT) -> Lexicon:
    """属名/双名表：WoRMS Annelida + 文本里的新种、命名人年份与重复双名。

    不用「大写词 + 任意小写词」直接当学名：参考文献标题、地名会混进来。
    """
    base, binomials, trinomials = load_worms_names(genera_db) if genera_db else (set(), set(), set())
    genera: set[str] = set(base)
    for g in extra_genera or []:
        g = g.strip()
        if g and not FAMILY_SUFFIX.search(g) and g.lower() not in STOP:
            genera.add(g)

    pair_counts: Counter[tuple[str, str]] = Counter()
    triple_counts: Counter[tuple[str, str, str]] = Counter()
    for text in texts:
        clean = _strip_italics(text)
        for m in NEW_GENUS.finditer(clean):
            g = m.group(1)
            if _ok_pair(g, "x"):
                genera.add(g)
        for m in GENUS_LABEL.finditer(clean):
            g = m.group(1)
            if _ok_pair(g, "x"):
                genera.add(g)
        for m in NEW_SPECIES.finditer(clean):
            g, e = m.group(1), m.group(2)
            if _ok_pair(g, e):
                genera.add(g)
                binomials.add((g, e))
        for m in AUTHORED.finditer(clean):
            g, e = m.group(1), m.group(2)
            if _ok_pair(g, e):
                genera.add(g)
                binomials.add((g, e))
        for m in CAND.finditer(clean):
            g, e = m.group(1), m.group(2)
            if _ok_pair(g, e):
                pair_counts[(g, e)] += 1
        for m in re.finditer(r"\b([A-Z][a-z-]+)\s+([a-z][a-z-]+)\s+([a-z][a-z-]+)\b", clean):
            g, e, s = m.groups()
            if _ok_pair(g, e) and _ok_pair(g, s):
                triple_counts[(g, e, s)] += 1

    for (g, e), n in pair_counts.items():
        if n >= 2 and g in genera:
            binomials.add((g, e))
    for (g, e, s), n in triple_counts.items():
        if n >= 2 and (g, e) in binomials:
            trinomials.add((g, e, s))
    return Lexicon(frozenset(genera), frozenset(binomials), frozenset(trinomials),
                   load_english_words(english_dict))


def _strip_italics(text: str) -> str:
    # 用占位符而不是空格：否则 "genus *Opisthodonta* Langerhans" 会被
    # GENUS_LABEL 误读成 "genus Langerhans"，把命名人当属名。
    return re.sub(r"\*[^*\n]+\*", " \x00 ", text)


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """不改：HTML 注释、行内代码、已有斜体/粗体、链接、URL。"""
    patterns = [
        r"<!--.*?-->",
        r"`[^`\n]*`",
        # (?<!\\) 排除已转义的星号：否则 \*B. 被当成斜体开头，与跨行的
        # clavata\* 配对，输出拆坏的 \**B. ... clavata*\*。
        r"(?<!\\)\*\*(?!\s)[^*\n]*?(?<!\s)(?<!\\)\*\*",
        # 行首脚注星号（"* ABSTRACT: ..."）后面是空格，不能当斜体开头；
        # 否则会把后面的真斜体 *Genus species* 拆开，套成 **Genus species**。
        r"(?<!\\)\*(?!\s)[^*\n]*?(?<!\s)(?<!\\)\*",
        r"\[[^\]\n]*\]\([^)\n]*\)",
        r"https?://\S+",
    ]
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        spans.extend((m.start(), m.end()) for m in re.finditer(pat, text, re.DOTALL))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _escape_genera(genera: frozenset[str]) -> str:
    return "|".join(sorted((re.escape(g) for g in genera), key=len, reverse=True))


# 学名各词之间只允许段内空白，最多一个换行：不能跨空行，否则缩写属名
# B. 会和下一段的种加词拼成 B. clavata（1979 稿 \*B.\n\nclavata\* 的根因）。
_SEP = r"(?:[ \t]+|\n[ \t]*)"
_SEP0 = r"(?:[ \t]+|\n[ \t]*)?"


def _name_regex(lex: Lexicon) -> re.Pattern[str]:
    if not lex.genera:
        return re.compile(r"(?!x)x")  # 永不匹配
    g = _escape_genera(lex.genera)
    ug = _escape_genera(lex.upper_genera)
    parts = [
        # 全大写双名 / 三名
        rf"(?P<ubin>\b(?:{ug}){_SEP}[A-Z][A-Z-]+(?:{_SEP}[A-Z][A-Z-]+)?\b)",
        # 属名 + cf./aff. + 种加词：cf./aff. 正体
        rf"(?P<cf>\b(?:{g}){_SEP}(?:cf\.|aff\.){_SEP}[a-z][a-z-]+\b)",
        # 属名 + 种加词 + var./f./subsp. + 变种/亚种加词：rank 词正体，加词斜体
        rf"(?P<var>\b(?:{g}){_SEP}[a-z][a-z-]+{_SEP}(?:var\.|f\.|subsp\.|ssp\.|forma){_SEP}[a-z][a-z-]+\b)",
        # 属名 + sp./spp./sp. n.：属名斜体，符号词正体
        rf"(?P<sp>\b(?:{g}){_SEP}(?:sp\.|spp\.|sp\.{_SEP0}n\.|n\.{_SEP0}sp\.)\b)",
        # 属名（亚属）种加词
        rf"(?P<subgen>\b(?:{g}){_SEP}\([A-Z][a-z-]+\){_SEP}[a-z][a-z-]+\b)",
        # 属名 + 种加词 [+ 亚种加词]
        rf"(?P<bin>\b(?:{g}){_SEP}[a-z][a-z-]+(?:{_SEP}[a-z][a-z-]+)?\b)",
        # 缩写属名 + n. sp. / n. gen.：属名斜体，符号词正体
        rf"(?P<abbrnsp>\b[A-Z]\.{_SEP}(?:n\.{_SEP0}sp\.|n\.{_SEP0}gen\.|sp\.{_SEP0}n\.|gen\.{_SEP0}n\.))",
        # 缩写属名 + cf./aff. + 种加词：O. cf. morena
        rf"(?P<abbrcf>\b[A-Z]\.{_SEP}(?:cf\.|aff\.){_SEP}[a-z][a-z-]+\b)",
        # 缩写属名 + 种加词 + var./subsp. + 加词
        rf"(?P<abbrvar>\b[A-Z]\.{_SEP}[a-z][a-z-]+{_SEP}(?:var\.|f\.|subsp\.|ssp\.|forma){_SEP}[a-z][a-z-]+\b)",
        # 缩写属名 + 种加词：O. morena
        rf"(?P<abbr>\b[A-Z]\.{_SEP}[a-z][a-z-]+\b)",
        # 全大写缩写 + 全大写种加词：O. MORENA
        rf"(?P<uabbr>\b[A-Z]\.{_SEP}[A-Z][A-Z-]+\b)",
        # 全大写属名（标题）
        rf"(?P<ugen>\b(?:{ug})\b)",
        # 属名单词
        rf"(?P<gen>\b(?:{g})\b)",
    ]
    return re.compile("|".join(parts))


def load_english_words(path: Path | None = ENGLISH_DICT) -> frozenset[str]:
    """hunspell .dic 的词干表（去掉 /FLAGS），小写；文件缺失返回空集。"""
    if path is None or not path.exists():
        return frozenset()
    words: set[str] = set()
    try:
        with path.open(encoding="latin-1") as f:
            next(f, None)  # 首行是词条数
            for line in f:
                w = line.split("/", 1)[0].strip().lower()
                if w and w.isalpha():
                    words.add(w)
    except OSError:
        return frozenset()
    return frozenset(words)


_EN_SUFFIXES = (("s", ""), ("es", ""), ("ed", ""), ("ed", "e"), ("d", ""),
                ("ing", ""), ("ing", "e"), ("ly", ""))


def _is_english_word(word: str, english: frozenset[str]) -> bool:
    """word 或其规则屈折形式的词干在英语词表里。"""
    if not english:
        return False
    if word in english:
        return True
    for suffix, add in _EN_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            if word[:-len(suffix)] + add in english:
                return True
    # 双写辅音 + ed/ing：occurred -> occur
    if word.endswith(("ed", "ing")) and len(word) > 4 and word[-3] == word[-4]:
        stem = word[:-3] if word.endswith("ed") else word[:-4]
        if stem in english:
            return True
    return False


def _epithet_like(word: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z-]+", word)) \
        and word not in EPITHET_STOP and word not in RANK_WORDS


def _italic_binomial(m: re.Match[str], lex: Lexicon) -> str:
    text = m.group(0)
    worlds = text.split()
    genus = worlds[0]
    if genus not in lex.genera:
        return text
    if len(worlds) == 1:
        return f"*{text}*"
    epithet = worlds[1]
    if (genus, epithet) not in lex.binomials:
        # 词表没收录的异名/新组合：第二个词像种加词（不是英语词/阶元符号）时，
        # 仍按 属名+种加词 斜体；否则只斜体属名，避免 *Leanira* it。
        if _epithet_like(epithet):
            return f"*{genus} {epithet}*" + text[len(genus) + 1 + len(epithet):]
        return f"*{genus}*" + text[len(genus):]
    if len(worlds) == 3:
        if (genus, epithet, worlds[2]) in lex.trinomials or worlds[2] == epithet:
            return f"*{text}*"
        # 第三个词不是已知亚种：只斜体双名，第三个原样留在斜体外。
        return f"*{genus} {epithet}*" + text[len(genus) + 1 + len(epithet):]
    return f"*{genus} {epithet}*"


def _replace_match(m: re.Match[str], lex: Lexicon) -> str:
    kind = m.lastgroup
    text = m.group(0)
    if kind == "ubin":
        worlds = text.split()
        if worlds[0] not in lex.upper_genera:
            return text
        if len(worlds) >= 2 and (worlds[0], worlds[1]) in lex.upper_binomials:
            if len(worlds) == 3 and (worlds[0], worlds[1], worlds[2]) not in lex.trinomials \
                    and worlds[2] != worlds[1]:
                return f"*{worlds[0]} {worlds[1]}*" + text[len(worlds[0]) + 1 + len(worlds[1]):]
            return f"*{text}*"
        return f"*{worlds[0]}*" + text[len(worlds[0]):]
    if kind == "var":
        mm = re.match(r"(.+?)\s+(var\.|f\.|subsp\.|ssp\.|forma)\s+([a-z][a-z-]+)$", text)
        if not mm:
            return text
        genus, epithet = mm.group(1).split()
        rank, variety = mm.group(2), mm.group(3)
        if (genus, epithet) not in lex.binomials:
            return text
        if variety in RANK_WORDS:
            return f"*{genus} {epithet}* {rank} {variety}"
        return f"*{genus} {epithet}* {rank} *{variety}*"
    if kind == "cf":
        g, rest = text.split(None, 1)
        words = rest.split()
        if len(words) < 2:
            return text
        if (g, words[1]) in lex.binomials:
            return f"*{g}* {words[0]} *{words[1]}*"
        return f"*{g}* {words[0]} {words[1]}"
    if kind == "sp":
        g = text.split(None, 1)[0]
        return f"*{g}*" + text[len(g):]
    if kind == "subgen":
        g, rest = text.split(None, 1)
        sub, sp = rest.split(None, 1)
        if (g, sp) not in lex.binomials:
            return f"*{g}*" + text[len(g):]
        return f"*{g}* (*{sub.strip('()')}*) *{sp}*"
    if kind == "bin":
        return _italic_binomial(m, lex)
    if kind == "abbrnsp":
        initial = text.split(".", 1)[0]
        return f"*{initial}.*" + text[len(initial) + 1:]
    if kind == "abbrcf":
        initial, rest = text.split(".", 1)
        rank, epithet = rest.split()
        return f"*{initial}.* {rank} *{epithet}*"
    if kind == "abbrvar":
        initial, rest = text.split(".", 1)
        epithet, rank, variety = rest.split()
        if variety in RANK_WORDS:
            return f"*{initial}. {epithet}* {rank} {variety}"
        return f"*{initial}. {epithet}* {rank} *{variety}*"
    if kind == "abbr":
        initial = text.split(".", 1)[0].upper()
        rest = text.split(".", 1)[1].strip()
        # 单字母属名缩写 + 小写种加词；排除罗马数字编号 I./V./X. 和作者缩写（后接大写姓氏）。
        if initial in {"I", "V", "X"}:
            return text
        if rest in RANK_WORDS:
            return f"*{initial}.* {rest}"
        return f"*{text}*"
    if kind == "uabbr":
        initial, epithet = text.split(".", 1)[0].upper(), text.split()[-1].upper()
        if (initial, epithet) in lex.upper_abbr_pairs:
            return f"*{text}*"
        return text
    if kind == "ugen":
        return f"*{text}*"
    if kind == "gen":
        return f"*{text}*"
    return text


def _complete_existing_binomials(text: str, lex: Lexicon) -> tuple[str, int]:
    """已带斜体的属名后面跟正体种加词时补斜体：*Syllis* longifilis -> *Syllis longifilis*。"""
    pat = re.compile(r"\*([A-Z][a-z-]+)\* ([a-z][a-z-]+)\b")
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        genus, epithet = m.groups()
        # 属名已在文本里斜体，说明模型认定它是学名；WoRMS 只收 Annelida，
        # 其他类群（如 1962 篇的介形虫）靠英语词表排除 *Acropora* coral 这类。
        if not _epithet_like(epithet):
            return m.group(0)
        if (genus, epithet) not in lex.binomials and _is_english_word(epithet, lex.english):
            return m.group(0)
        n += 1
        return f"*{genus} {epithet}*"

    return pat.sub(repl, text), n


def _complete_existing_varieties(text: str, lex: Lexicon) -> tuple[str, int]:
    """已带斜体的双名后面跟 var./subsp. 时，补斜体加词；保护现有 *...* 不影响跨边界规则。"""
    pat = re.compile(r"\*([A-Z][a-z-]+) ([a-z][a-z-]+)\* (var\.|f\.|subsp\.|ssp\.|forma) ([a-z][a-z-]+)\b")
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        genus, epithet, rank, variety = m.groups()
        if (genus, epithet) not in lex.binomials or variety in RANK_WORDS:
            return m.group(0)
        n += 1
        return f"*{genus} {epithet}* {rank} *{variety}*"

    return pat.sub(repl, text), n


def _escape_stray_asterisks(text: str) -> str:
    """把不成对的 *（OCR 脚注星号）转成 \\*，避免 Markdown 把它当强调开头。"""
    spans = _protected_spans(text)
    out: list[str] = []
    pos = 0
    si = 0
    for i, ch in enumerate(text):
        if ch != "*":
            continue
        while si < len(spans) and spans[si][1] <= i:
            si += 1
        if si < len(spans) and spans[si][0] <= i < spans[si][1]:
            continue
        if i > 0 and text[i - 1] == "\\":
            continue
        out.append(text[pos:i])
        out.append("\\*")
        pos = i + 1
    out.append(text[pos:])
    return "".join(out)


_ESCAPED_CLOSER = re.compile(r"(?<!\\)\*([A-Z][a-z-]+)\\+\*")
# 索引里的页码星号（"192*, 606"）：数字后紧跟的 * 是字面星号，不是斜体定界符。
_PAGE_STAR = re.compile(r"(?<=\d)\*(?=[\s,;)])")


def _normalize_stars(text: str) -> tuple[str, int]:
    """修正两类 OCR/模型星号：*Genus\\* -> *Genus*；页码星号 192* -> 192\\*。"""
    text, n1 = _ESCAPED_CLOSER.subn(r"*\1*", text)
    text, n2 = _PAGE_STAR.subn(r"\\*", text)
    return text, n1 + n2


def format_text(text: str, lex: Lexicon) -> tuple[str, int]:
    """返回 (排版后文本, 新增斜体处数)。"""
    text, n_star = _normalize_stars(text)
    text, n_bin = _complete_existing_binomials(text, lex)
    text, n_existing = _complete_existing_varieties(text, lex)
    regex = _name_regex(lex)
    spans = _protected_spans(text)
    out: list[str] = []
    pos = 0
    changes = n_bin + n_existing + n_star
    for a, b in spans:
        if a < pos:
            continue
        chunk = text[pos:a]
        new, n = _format_chunk(chunk, regex, lex)
        out.append(text[pos:a] if n == 0 else new)
        changes += n
        out.append(text[a:b])
        pos = b
    chunk = text[pos:]
    new, n = _format_chunk(chunk, regex, lex)
    out.append(text[pos:] if n == 0 else new)
    changes += n
    return _escape_stray_asterisks("".join(out)), changes


def _format_chunk(chunk: str, regex: re.Pattern[str], lex: Lexicon) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        new = _replace_match(m, lex)
        if new != m.group(0):
            count += 1
        return new

    return regex.sub(repl, chunk), count


def process(paths: list[Path], fix: bool, extra_genera: list[str],
            genera_db: Path | None = DEFAULT_GENERA_DB) -> tuple[list[dict[str, object]], int]:
    texts = [p.read_text(encoding="utf-8") for p in paths]
    lex = build_lexicon(texts, extra_genera, genera_db=genera_db)
    rows: list[dict[str, object]] = []
    total = 0
    for p, text in zip(paths, texts):
        new, n = format_text(text, lex)
        total += n
        if fix and n:
            shutil.copyfile(p, p.with_name(p.name + BACKUP_SUFFIX))
            p.write_text(new, encoding="utf-8")
        rows.append({"path": str(p), "changes": n, "genera": len(lex.genera),
                     "binomials": len(lex.binomials)})
    return rows, total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--fix", action="store_true", help="写回文件（先备份 .bak-taxo）")
    ap.add_argument("--report", type=Path, help="写 TSV 报告")
    ap.add_argument("--genera", type=Path, help="追加已知属名，每行一个")
    ap.add_argument("--genera-db", type=Path, default=DEFAULT_GENERA_DB,
                    help=f"WoRMS 缓存库（默认 {DEFAULT_GENERA_DB}）")
    ap.add_argument("--no-worms", action="store_true", help="不用 WoRMS 库，只从文本抽属名")
    args = ap.parse_args(argv)
    extra = []
    if args.genera:
        extra = [ln.strip() for ln in args.genera.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    rows, total = process(args.files, args.fix, extra,
                          genera_db=None if args.no_worms else args.genera_db)
    if args.report:
        with args.report.open("w", encoding="utf-8") as fh:
            fh.write("path\tchanges\tgenera\tbinomials\n")
            for r in rows:
                fh.write(f"{r['path']}\t{r['changes']}\t{r['genera']}\t{r['binomials']}\n")
    for r in rows:
        print(f"{r['path']}\t{r['changes']}")
    print(f"total changes: {total}", file=sys.stderr)
    return 0 if (args.fix or total == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
