"""拉丁字母语种（德文为主）OCR 后处理：纯脚本、零 token，每处改动留痕。

依据（2026-11-15，Hartmann-Schröder 德文 6 页金标准，Tesseract deu 300 dpi 的剩余错误）：
1. 性别符号：♂ 读成 & / c& / &”，♀ 读成 9 / @（D1985p6 共 13 处，全部错）。
2. 老印刷（1960）变音点丢失、c/e 混淆：Zahne、tragt、stcht、dreicckig。
3. 小型大写人名大小写混乱：KoTT、GIsLEN、WıLSON、PERKINs。
4. µm 读成 um。

做法：
- 规则 1、3、4 按上下文正则。
- 规则 2 用「全库词频」纠错：同一语种的已 OCR 页构成词表（各书互相印证），某词罕见（≤ rare 次）而只差
  一个易混字符（a→ä、o→ö、u→ü、c→e、e→c、ı→i、l→i、ii→ü、rn→m）的候选词常见（≥ common 次且 ≥ ratio 倍）时替换。
  不引外部词典：术语和学名在本库里出现得最多，外部词典反而会把学名「纠正」坏。
模型兜底产出的修正应回流成本模块的规则或词频（见 docs/ocr_tool_survey.md）。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# 易混字符（错 → 对）。每个候选只替换一处。
CONFUSIONS: list[tuple[str, str]] = [
    ("a", "ä"), ("o", "ö"), ("u", "ü"), ("A", "Ä"), ("O", "Ö"), ("U", "Ü"),
    ("c", "e"), ("e", "c"), ("ı", "i"), ("l", "i"), ("i", "l"), ("ii", "ü"), ("rn", "m"), ("m", "rn"),
    ("n", "u"), ("u", "n"), ("cl", "d"), ("t", "l"), ("f", "t"), ("K", "F"), ("N", "fl"), ("ız", "g"),
]

# ---- 1. 性别符号 ----
_CTX = r"(?:beim|bei|vom|von|dem|den|der|des|das|ein|eine|einem|einen|einer|und|oder|atokem|atoken|atokes|" \
       r"epitokem|epitoken|epitokes|reifem|reifen|reifes|großem|kleinem|\d+)"
# ♂：上下文词 + & / c& / o&（Day & Hutchings 之类人名间的 & 不在上下文词之后，不动）
_MALE = re.compile(rf"\b({_CTX}) (?:c&|o&|&)[”\"']?(?=[\s.,;:)]|$)", re.M)
_MALE_PAREN = re.compile(r"\((?:c&|&)\)")
# ♀：上下文词 + 9 / @，后面不是数字、单位或计数名词
_FEMALE = re.compile(rf"\b({_CTX}) (?:9|@)(?=[\s,;:)]|$)"  # 「beim 9.」可能是序数（9. Segment），不改
                     r"(?!\s*(?:mm|cm|µm|m\b|%|‰|°|Segment|Borsten|Parapod|Exemplar|Expl))", re.M)


_AT = re.compile(r"(?<=[\s(])@(?=[\s,;:.)])")


def fix_sex(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def sub(rx: re.Pattern, sym: str, t: str) -> str:
        def rep(m: re.Match) -> str:
            new = (m.group(1) + " " + sym) if m.groups() else sym
            changes.append((m.group(0), new))
            return new
        return rx.sub(rep, t)

    text = sub(_MALE, "♂", text)
    text = sub(_MALE_PAREN, "(♂)", text)
    text = sub(_FEMALE, "♀", text)
    text = sub(_AT, "♀", text)
    return text, changes


# ---- 3. 小型大写人名 ----
_SMALLCAPS = re.compile(r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüıß]{3,}\b")


def fix_smallcaps(text: str) -> tuple[str, list[tuple[str, str]]]:
    """KoTT → KOTT、GIsLEN → GISLEN、PERKINs → PERKINS：大写字母占 ≥60% 且至少 3 个大写时整体大写。
    glauCopsis（大写只 1 个）、McIntosh 不动。"""
    changes = []

    def rep(m: re.Match) -> str:
        w = m.group(0)
        letters = [c for c in w if c.isalpha()]
        up = sum(c.isupper() for c in letters)
        if up == len(letters) or up < 3 or up / len(letters) < 0.6:
            return w
        new = w.replace("ı", "I").upper()
        changes.append((w, new))
        return new

    return _SMALLCAPS.sub(rep, text), changes


# ---- 4. 单位 ----
_UM = re.compile(r"(?<=\d) ?um\b(?=\s*(?:[.,;:)]|lang|breit|dick|hoch|groß|gross|Durchmesser|$))", re.M)


def fix_units(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes = []

    def rep(m: re.Match) -> str:
        new = m.group(0).replace("um", "µm")
        changes.append((m.group(0), new))
        return new

    return _UM.sub(rep, text), changes


# ---- 5. 字形混淆（1971 Opisthodonta 页实例，2026-11-15）----
# 属名缩写：O0. / 0. / 00. 后接小写种加词 → O.（「0. morena」「O0. pterochaeta」）
_GENUS_ABBR = re.compile(r"(?<![\w.,])(?:O0|0O|00|0)\.(?= [a-z]{3,})")
# 无点 ı（土耳其字母，德文里不会出现）：挨着数字或作图号（Fig. ıa、Taf. ı、ı3.）→ 1，其余 → i
_DOTLESS_NUM = re.compile(r"ı(?=\d|[a-z]?(?:[\s,.;:)\-]|$))|(?<=\d)ı")
# 法文文献里 é/è 读成 &（Oc&anogr、l’&tude、corallige&ne）：两侧是字母或撇号
_AMP_E = re.compile(r"(?<=[A-Za-z’'])&(?=[a-z])")
# ‰ 读成 %o / %00 / %0
_PERMILLE = re.compile(r"%(?:oo|o0|00|0|o)(?![\w])")


def fix_glyphs(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def sub(rx: re.Pattern, new: str, t: str) -> str:
        def rep(m: re.Match) -> str:
            changes.append((m.group(0), new))
            return new
        return rx.sub(rep, t)

    text = sub(_GENUS_ABBR, "O.", text)
    text = sub(_DOTLESS_NUM, "1", text)
    text = sub(re.compile("ı"), "i", text)
    text = sub(_AMP_E, "é", text)
    text = sub(_PERMILLE, "‰", text)
    return text, changes


# ---- 0. 规范化（#22）：先于一切规则，只动 Unicode 表示，不动拼写 ----
_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
_LIGATURE = re.compile("[ﬀ-ﬆ]")
_FULLWIDTH_RUN = re.compile("[！-～]+")
_COMBINING_WORD = re.compile(r"\w*[̀-ͯ]\w*")
_CJK = re.compile("[⺀-鿿　-〿가-힯＀-￯]")
_HOMOGLYPH = {
    **dict(zip("аеорсухіјѕАВЕКМНОРСТХУ", "aeopcyxijsABEKMHOPCTXY", strict=True)),   # Cyrillic
    **dict(zip("οανιρτΑΒΕΙΚΜΝΟΡΤΧ", "oavipt" + "ABEIKMNOPTX", strict=True)),         # Greek
}
_HG_CHARS = "".join(_HOMOGLYPH)
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
_OTHER_SCRIPT = re.compile("[Ѐ-ӿͰ-Ͽ]")


def normalize(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """规范化；返回 (新文本, [(规则, 原, 新)])。规则名：norm.invisible / norm.ligature / norm.fullwidth /
    norm.nfc / norm.homoglyph。µ（U+00B5）不动；全角字符紧挨 CJK 时不动（中文语境不归本模块）。
    不用整体 NFKC：它会把 µ 变成希腊 μ、把 ² 变成 2。"""
    log: list[tuple[str, str, str]] = []

    def sub(rx: re.Pattern[str], rule: str, fn, t: str) -> str:  # type: ignore[no-untyped-def]
        def rep(m: re.Match[str]) -> str:
            new = fn(m)
            if new != m.group(0):
                log.append((rule, m.group(0), new))
            return new
        return rx.sub(rep, t)

    text = sub(_INVISIBLE, "norm.invisible", lambda m: "", text)
    text = sub(_LIGATURE, "norm.ligature", lambda m: unicodedata.normalize("NFKC", m.group(0)), text)

    def fw(m: re.Match[str]) -> str:
        b, e = m.start(), m.end()
        if (b > 0 and _CJK.match(m.string[b - 1])) or (e < len(m.string) and _CJK.match(m.string[e])):
            return m.group(0)
        return unicodedata.normalize("NFKC", m.group(0))

    text = sub(_FULLWIDTH_RUN, "norm.fullwidth", fw, text)
    text = sub(_COMBINING_WORD, "norm.nfc", lambda m: unicodedata.normalize("NFC", m.group(0)), text)

    def hg(m: re.Match[str]) -> str:
        w = m.group(0)
        if not any(c in _HOMOGLYPH for c in w) or not _LATIN_LETTER.search(w):
            return w
        if any(_OTHER_SCRIPT.match(c) and c not in _HOMOGLYPH for c in w):
            return w  # 含非同形字的西里尔/希腊字母：是真正的该文字词，不动
        return "".join(_HOMOGLYPH.get(c, c) for c in w)

    text = sub(WORD, "norm.homoglyph", hg, text)
    return text, log


# ---- 2. 全库词频纠错 ----
_RULES_PATH = Path(__file__).parent / "rules" / "latin_confusions.toml"
_TABLES: dict[str, list[tuple[str, str]]] | None = None


def confusion_table(lang: str | None) -> list[tuple[str, str]]:
    """语种混淆表：base + 该语种表；lang 为 None 时沿用旧行为（CONFUSIONS 全表）；未知语种只用 base。"""
    global _TABLES
    if lang is None:
        return CONFUSIONS
    if _TABLES is None:
        d = tomllib.loads(_RULES_PATH.read_text(encoding="utf-8"))
        _TABLES = {k: [(a, b) for a, b in v] for k, v in d.items()}
    return _TABLES["base"] + _TABLES.get(lang, [])


def build_vocab(texts: Iterable[str]) -> Counter:
    c: Counter = Counter()
    for t in texts:
        t = re.sub(r"-\n\s*", "", t)  # 断行连字符接回再计数
        c.update(WORD.findall(t))
    return c


def candidates(w: str, lang: str | None = None) -> set[str]:
    out = set()
    for a, b in confusion_table(lang):
        i = w.find(a)
        while i != -1:
            out.add(w[:i] + b + w[i + len(a):])
            i = w.find(a, i + 1)
    out.discard(w)
    return out


def learn_confusions(vocab: Counter, *, common: int = 5, rare: int = 2, min_len: int = 4) -> Counter:
    """从语料学易混字符：同长、仅一个位置不同，一个词罕见（≤rare）另一个常见（≥common）→ 计 (罕见侧字符, 常见侧字符)。
    结果可按文档的字体/OCR 引擎分层统计，用来评估或扩充语种表，不自动写回规则。"""
    index: dict[tuple[int, str, str], list[str]] = {}
    for w, n in vocab.items():
        if n >= common and len(w) >= min_len:
            for i in range(len(w)):
                index.setdefault((len(w), w[:i], w[i + 1:]), []).append(w)
    out: Counter = Counter()
    for w, n in vocab.items():
        if n > rare or len(w) < min_len:
            continue
        for i in range(len(w)):
            for c in index.get((len(w), w[:i], w[i + 1:]), ()):
                if c[i] != w[i]:
                    out[(w[i], c[i])] += 1
    return out


_ITALIC = re.compile(r"\*[^*\n]+\*|_[^_\n]+_")
_AUTHORITY = re.compile(r"\([^()\n]*\b(?:1[5-9]|20)\d\d[a-z]?\)")
_INTERNAL_CAPS = re.compile(r"[a-zäöüß][A-ZÄÖÜ]")


def protected_spans(text: str) -> list[tuple[int, int]]:
    """受保护区间：斜体/强调、命名人括注 (… 1776)。"""
    return [(m.start(), m.end()) for rx in (_ITALIC, _AUTHORITY) for m in rx.finditer(text)]


def _is_protected_token(w: str, protect: set[str] | None) -> bool:
    if protect and (w in protect or w.lower() in protect):
        return True
    letters = [c for c in w if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):  # 小型大写人名
        return True
    return bool(_INTERNAL_CAPS.search(w))  # glauCopsis、McIntosh


def fix_vocab(text: str, vocab: Counter, *, rare: int = 2, common: int = 5, ratio: float = 5.0,
              min_len: int = 4, lang: str | None = None, protect: set[str] | None = None,
              review: list[dict] | None = None, dictionary: set[str] | None = None,
              detail: list[dict] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """全库词频纠错。自动替换只限「库内有证据、唯一候选」的词；有歧义的、词典标疑的进 review 队列，不改正文。
    protect：学名/作者/地名等受保护词；斜体、命名人括注、全大写、词内大写永远受保护。
    dictionary（小写词集合）只用于标疑（reason=not_in_dictionary），绝不用来替换。"""
    changes: list[tuple[str, str]] = []
    spans = protected_spans(text)
    cache: dict[str, tuple[str, str, list[tuple[str, int]]]] = {}

    def best(w: str) -> tuple[str, str, list[tuple[str, int]]]:
        """返回 (结果词, 状态 fixed|ambiguous|ok, 候选与频次)。"""
        if w in cache:
            return cache[w]
        res, state, cands = w, "ok", []
        n = vocab.get(w, 0)
        if len(w) >= min_len and n <= rare:
            scored = [(vocab.get(c, 0), c) for c in candidates(w, lang)]
            scored = [x for x in scored if x[0] >= common and x[0] >= ratio * max(n, 1)]
            scored.sort(key=lambda x: (-x[0], x[1]))
            cands = [(c, k) for k, c in scored]
            if scored:
                # 两个候选都常见且接近（≤2 倍）时不替换：无从判断
                if len(scored) == 1 or scored[0][0] >= 2 * scored[1][0]:
                    res, state = scored[0][1], "fixed"
                else:
                    state = "ambiguous"
        cache[w] = (res, state, cands)
        return cache[w]

    def rep(m: re.Match[str]) -> str:
        w = m.group(0)
        b, e = m.start(), m.end()
        if _is_protected_token(w, protect) or any(s <= b and e <= t for s, t in spans):
            return w
        res, state, cands = best(w)
        if state == "fixed":
            changes.append((w, res))
            if detail is not None:
                detail.append({"old": w, "new": res, "n_old": vocab.get(w, 0), "n_new": vocab.get(res, 0),
                               "lang": lang})
            return res
        if review is not None and len(w) >= min_len:
            if state == "ambiguous":
                review.append({"token": w, "candidates": cands, "reason": "ambiguous", "lang": lang, "pos": b})
            elif dictionary is not None and vocab.get(w, 0) <= rare and w.lower() not in dictionary:
                review.append({"token": w, "candidates": [], "reason": "not_in_dictionary", "lang": lang, "pos": b})
        return w

    return WORD.sub(rep, text), changes


def fix_page(text: str, vocab: Counter | None = None, *, lang: str | None = None, protect: set[str] | None = None,
             review: list[dict] | None = None, dictionary: set[str] | None = None,
             detail: list[dict] | None = None) -> tuple[str, list[tuple[str, str, str]]]:
    """全部规则依次执行；返回 (新文本, [(规则, 原, 新)])。detail（可选）按同序追加每处改动的审计字典
    （含规则、原、新、语种；词频改动另含 n_old/n_new 证据频次）。review（可选）收集待复核词。"""
    log: list[tuple[str, str, str]] = []

    def add(rule: str, ch: list[tuple[str, str]]) -> None:
        log.extend((rule, a, b) for a, b in ch)
        if detail is not None:
            detail.extend({"rule": rule, "old": a, "new": b, "lang": lang} for a, b in ch)

    text, nch = normalize(text)
    log += nch
    if detail is not None:
        detail.extend({"rule": r, "old": a, "new": b, "lang": lang} for r, a, b in nch)
    for name, fn in (("sex", fix_sex), ("smallcaps", fix_smallcaps), ("units", fix_units), ("glyphs", fix_glyphs)):
        text, ch = fn(text)
        add(name, ch)
    if vocab is not None:
        vd: list[dict] = []
        text, ch = fix_vocab(text, vocab, lang=lang, protect=protect, review=review, dictionary=dictionary, detail=vd)
        log += [("vocab", a, b) for a, b in ch]
        if detail is not None:
            detail.extend({"rule": "vocab", **d} for d in vd)
    return text, log
