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
from collections import Counter
from collections.abc import Iterable

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


# ---- 2. 全库词频纠错 ----
def build_vocab(texts: Iterable[str]) -> Counter:
    c: Counter = Counter()
    for t in texts:
        t = re.sub(r"-\n\s*", "", t)  # 断行连字符接回再计数
        c.update(WORD.findall(t))
    return c


def candidates(w: str) -> set[str]:
    out = set()
    for a, b in CONFUSIONS:
        i = w.find(a)
        while i != -1:
            out.add(w[:i] + b + w[i + len(a):])
            i = w.find(a, i + 1)
    out.discard(w)
    return out


def fix_vocab(text: str, vocab: Counter, *, rare: int = 2, common: int = 5, ratio: float = 5.0,
              min_len: int = 4) -> tuple[str, list[tuple[str, str]]]:
    changes = []
    cache: dict[str, str] = {}

    def best(w: str) -> str:
        if w in cache:
            return cache[w]
        res = w
        n = vocab.get(w, 0)
        if len(w) >= min_len and n <= rare:
            scored = [(vocab.get(c, 0), c) for c in candidates(w)]
            scored = [x for x in scored if x[0] >= common and x[0] >= ratio * max(n, 1)]
            if scored:
                scored.sort(reverse=True)
                # 两个候选都常见且接近（≤2 倍）时不替换：无从判断
                if len(scored) == 1 or scored[0][0] >= 2 * scored[1][0]:
                    res = scored[0][1]
        cache[w] = res
        return res

    def rep(m: re.Match) -> str:
        w = m.group(0)
        b = best(w)
        if b != w:
            changes.append((w, b))
        return b

    return WORD.sub(rep, text), changes


def fix_page(text: str, vocab: Counter | None = None) -> tuple[str, list[tuple[str, str, str]]]:
    """全部规则依次执行；返回 (新文本, [(规则, 原, 新)])。"""
    log: list[tuple[str, str, str]] = []
    for name, fn in (("sex", fix_sex), ("smallcaps", fix_smallcaps), ("units", fix_units), ("glyphs", fix_glyphs)):
        text, ch = fn(text)
        log += [(name, a, b) for a, b in ch]
    if vocab is not None:
        text, ch = fix_vocab(text, vocab)
        log += [("vocab", a, b) for a, b in ch]
    return text, log
