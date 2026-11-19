"""分类文献的块类型（0 token）：按段首标签词、标题格式、引文格式、动词密度分流。

用途：auto_translate 的 --rewrite-kinds。实测（Hartmann-Schröder 德文 25 万词，2026-11-15）字符占比：
描述 57%、叙述 16%、产地 8%、生态 4%、分布 3%、标题 3%、讨论 3%、图注 2%、OCR 垃圾 2%、引文/文献 1%。
1971 Opisthodonta 试点：描述段 Google 初稿经术语表与学到的替换规则后，与 DeepSeek 改写稿相似度 0.85，
与「DeepSeek 稿 vs Codex 稿」的 0.86 相当 → 描述、标签段可只做意义核对，不整段改写；叙述、讨论段才交模型改写。

kind() 返回：junk heading caption locality ecology distribution remarks label citation reference key narrative description
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .core import numbers

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

RULES = Path(__file__).with_name("rules") / "taxo_labels.toml"
YEAR = r"1[789]\d\d|20[012]\d"
KINDS = ("junk", "heading", "caption", "locality", "ecology", "distribution", "remarks", "label", "citation",
         "reference", "key", "narrative", "description")


@lru_cache(maxsize=None)
def _lang(sl: str) -> dict[str, list[str]]:
    data = tomllib.loads(RULES.read_text(encoding="utf-8"))
    return data.get(sl) or data["en"]


def _junk(t: str) -> bool:
    """插图区被 OCR 成的乱码行（bt If) 7 bad m CO LIU SA）：短、几乎没有正常词。"""
    words = re.findall(r"[^\W\d_]+", t)
    if not words:
        return not re.search(r"\d{3,}", t)  # 纯标点/零散数字
    normal = sum(1 for w in words if len(w) >= 3 and (w.islower() or w.istitle() or w.isupper()))
    if len(t) < 60 and normal <= 1 and not re.search(YEAR, t):
        return True
    return len(words) >= 4 and normal / len(words) < 0.5


def kind(text: str, sl: str = "de") -> str:
    t = text.strip()
    lab = _lang(sl)
    if _junk(t):
        return "junk"
    if re.match(r"(?:%s)\.?\s*\d" % "|".join(map(re.escape, lab["caption"])), t):
        return "caption"
    if re.match(r"(?:%s)\b" % "|".join(lab["rank"]), t) and len(t) < 300:
        return "heading"
    if len(t) < 200 and re.match(r"[A-Z][a-z]+ (?:\([A-Z][a-z]+\) )?[a-z]+(?: [a-z]+)? (?:n\. ?sp\.|sp\. ?n\.|[A-Z(])", t) \
            and re.search(YEAR, t):
        return "heading"
    for k in ("locality", "ecology", "distribution", "remarks", "other"):
        words = sorted(lab[k], key=len, reverse=True)
        if re.match(r"(?:%s)\s*[:.—–-]" % "|".join(map(re.escape, words)), t):
            return "label" if k == "other" else k
    # 文献表条目：「FAUVEL, P., 1923.」「——, 1970.」（OCR 常把年份读坏：10966），整段原样保留不译
    if re.match(r"^(?:——|—|--)\s*,\s*\S", t) or re.match(r"^[A-ZÄÖÜ][A-Za-zÄÖÜäöü'\-]+,\s+(?:[A-Z]\.\s*){1,3}(?:[A-Z]\.|,|&)", t):
        return "reference"
    if re.match(r"^[A-ZÄÖÜ][A-ZÄÖÜ'\- ]{2,}(?:,| &| und| and)", t) and re.search(YEAR, t) and len(t) < 600:
        if re.search(rf"[A-Z]\.\s*(?:\([^)]*\))?,?\s*(?:{YEAR})[a-z]?\.", t[:90]) and len(t) > 60:
            return "reference"
        return "citation"
    if re.match(r"^\d+\s*\(\d+\)", t) or re.match(r"^\d+[a-z]?\s.{5,}?(?:\.{2,}|…|—)\s*\d+\s*$", t):
        return "key"
    verbs = len(re.findall(r"\b(?:%s)\b" % "|".join(lab["narrative_words"]), t, flags=re.I))
    sent = max(1, len(re.findall(r"[.!?](?:\s|$)", t)))
    return "narrative" if verbs / sent >= 0.8 else "description"


# ---- 风险段（只核对这些，省 token）----
_EPITHET = re.compile(r"\b([A-Z][a-z]{3,})\s+(?:\([A-Z][a-z]+\)\s+)?([a-z]{4,}(?:a|us|um|is|ae|ii|i|ensis|oides|ata|ina|ella|ica|osa|ensis))\b")
# 数字比较用 core.numbers：小数逗号 = 小数点（1,5 = 1.5），千分位（1.200 / 1,200 / 136 000）先并成整数。
# 旧版直接比原始写法，德→英的 1,5 / 1.5、1.200 / 1,200 全部误报 number（2026-11-19 复现）。
_NEG = {"de": r"\b(?:nicht|kein\w*|ohne|fehl\w*|nie)\b", "en": r"\b(?:no|not|without|absent|lacking|lacks?|none|never|nor|devoid)\b|\bnon-"}
_RESIDUE = {"de": r"\b(?:der|und|mit|von|aus|bei|ist|sind|nicht|oder|auf|vom|zum|zur|des|dem|den|einer|eines)\b"}
_STOP_EPI = {"mittleren", "hinteren", "vorderen", "kleinen", "großen", "grossen", "dorsal", "ventral", "lateral"}
# 句首的方位/形态形容词不是属名：「Dorsal cirrus」「Ventral cirri」会被 _EPITHET 当成「属 + 种加词」（2026-11-19 复现）。
_STOP_GENUS = frozenset({
    "dorsal", "ventral", "lateral", "anterior", "posterior", "distal", "proximal", "medial", "median", "apical",
    "basal", "oral", "aboral", "external", "internal", "frontal", "caudal", "cephalic",
    "dorsale", "ventrale", "laterale", "vordere", "hintere", "mittlere",
})

# 长度比：中日韩字符信息密度高，EN→ZH 字数约为英文的一半。
# 依据：Rouse 2022 ch05–ch09 整章实测 0.44–0.50（含保留的拉丁名/引文，偏高）；纯叙述句约 0.22–0.25（逐句估，未系统测）。
# 页级分布未测（未确证），所以用宽带：只挡整段缺失、重复、未翻译（英文原样留下 → 比值≈1），不抓细小漏译
# （那是 term/number/negation 的工作）。同文字体系仍用原来的 0.6–1.6。
_CJK_LANGS = frozenset({"zh", "ja", "ko"})
_LATIN_TO_CJK = (0.15, 0.90)
_SAME_SCRIPT = (0.6, 1.6)
_SHORT = 30  # 源文和译文都短于此（标签、图序）时不按比例判；空译文仍报


def _is_cjk(lang: str) -> bool:
    return lang.replace("_", "-").split("-")[0].lower() in _CJK_LANGS


def _length_band(sl: str, tl: str) -> tuple[float, float]:
    s, t = _is_cjk(sl), _is_cjk(tl)
    if t and not s:
        return _LATIN_TO_CJK
    if s and not t:
        return 1 / _LATIN_TO_CJK[1], 1 / _LATIN_TO_CJK[0]
    return _SAME_SCRIPT


def _stem(w: str) -> str:
    w = w.lower()
    return w[:max(4, len(w) - 2)] if len(w) > 5 else w


def risk(src: str, tgt: str, sl: str = "de", tl: str = "en", rewritten: bool = False,
         terms: list[tuple[str, str]] | None = None) -> list[str]:
    """一段译文的风险信号（脚本，0 token）。空列表 = 低风险，可不送模型核对。
    rewritten：该段由模型整段改写过（会编造），一律视为风险。
    terms：术语表 (源, 定名)；原文出现源术语（词干匹配）而译文没有定名（词干匹配）→ term。"""
    why = []
    low_s, low_t = src.lower(), tgt.lower()

    def has(text: str, phrase: str) -> bool:
        # 整词、词首匹配，只容 ≤3 字母屈折词尾：Borsten 不匹配 Borstensegmenten，hinten 不匹配 hinteren
        pat = r"\s+".join(re.escape(_stem(x)) + r"\w{0,%d}" % (len(x) - len(_stem(x)) + 3) for x in phrase.split())
        return re.search(r"(?<!\w)" + pat + r"(?!\w)", text) is not None

    for a, b in terms or []:
        if a and b and has(low_s, a.lower()) and not has(low_t, b.lower()):
            why.append("term")
            break
    if rewritten:
        why.append("rewritten")
    if numbers(src) != numbers(tgt):
        why.append("number")
    if sl in _NEG and tl in _NEG and len(re.findall(_NEG[sl], src, re.I)) > len(re.findall(_NEG[tl], tgt, re.I)):
        why.append("negation")
    if src.strip() and not tgt.strip():
        why.append("length")
    elif max(len(src), len(tgt)) >= _SHORT:
        lo, hi = _length_band(sl, tl)
        r = len(tgt) / max(1, len(src))
        if r < lo or r > hi:
            why.append("length")
    if sl in _RESIDUE and re.search(_RESIDUE[sl], tgt):
        why.append("residue")
    for g, e in _EPITHET.findall(src):
        if g.lower() in _STOP_GENUS:
            continue
        if e.lower() not in _STOP_EPI and (g not in tgt or e not in tgt):
            why.append("name")
            break
    return why
