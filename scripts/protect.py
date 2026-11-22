"""送机翻前保护不可改写的记号（学名+命名人年份、n. sp. 等命名标记、两位年份的日期），回来后原样还原。

依据：2026-11-22 零模型实测（docs/research/2026-11-21-zero-model-run.md）：谷歌把 `n. sp.` 改成 `n。 sp。`，
把「29. 12. 59」译成「2059 年 12 月 29 日」。占位符 [[n]] 经实测在 de/ja→zh 里原样保留；
还原时容忍占位符内外多出的空格。注意：谷歌自己丢字母（anoculata→anculata）发生在学名内部，被占位符整体挡住。
"""
from __future__ import annotations

import re

import term_de

_AUTH = r"(?:\(?[A-Z][\w'’.\-]*(?:[\s,&]+(?:and |et |und )?[A-Z][\w'’.\-]*)*,?\s?\d{4}(?:\s?[a-z](?![a-z]))?\)?)"
_TAG = r"(?:n\.\s?g\.(?:\s?n\.\s?sp\.)?|n\.\s?(?:sp|gen|comb|subsp|var)\.|(?:sp|gen|comb)\.\s?n\.|nom\.\s?nov\.|comb\.\s?nov\.)"
_BINOM = r"[A-Z][a-z]{2,}(?:\s\([A-Z][a-z]{2,}\))?\s[a-z]{3,}(?:\s(?:var|subsp|f)\.\s[a-z]{3,})?"
# 先匹配最长的：学名+命名人年份 / 学名+命名标记；再匹配单独命名标记、日期
PATTERNS = [
    re.compile(rf"{_BINOM}\s{_AUTH}"),
    re.compile(rf"{_BINOM}\s{_TAG}"),
    re.compile(rf"(?<![\w])[A-Z]\.\s[a-z]{{4,}}\s{_TAG}"),   # 缩写属名：T. anoculata n. sp.
    re.compile(rf"(?<![\w]){_TAG}"),
    # 日文「数字+量词」（15対、2列）：谷歌在长句里会把数字吞掉或并错，数字单独占位
    re.compile(r"(?<![\d.,])\d{1,3}(?:対|列|剛毛束)|(?<![\d.,])\d{1,3}(?=[枚個本節])"),
    # 数字+单位（谷歌会把「ca. 10 mm」写成「100 厘米。10毫米」）：整体占位，还原原样
    re.compile(r"(?<![\w.,])(?:ca\.\s?)?\d+(?:[.,]\d+)?(?:\s?(?:[-–]|bis)\s?\d+(?:[.,]\d+)?)?\s?(?:mm|cm|µm|μm)\b"),
    # 德文「N bis M」「N Paar」：谷歌会丢数字（「2 bis 2½」「10 Paar」实测）
    re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)? bis \d+(?:[.,]\d+)?[%½]?(?![\d.,])|(?<![\d.,])\d+ Paar\b"),
    # OCR 常把第一个点识成逗号（10, 3. 60），也算日期
    re.compile(r"(?<!\d)\d{1,2}[.,]\s?\d{1,2}\.\s?\d{2}(?!\d)"),
    # 括号内单独的命名人+年份（异名/分布引证），谷歌会把人名音译
    re.compile(r"\((?!(?:Abb|Fig|Taf|Tab|Pl|Tafel)\b)[^\W\d_a-z][\w'’.\-]*(?:[\s,&]+(?:and |et |und )?[^\W\d_a-z][\w'’.\-]*)*,?\s?\d{4}(?:\s?[a-z](?![a-z]))?\)"),
    # 德文志书把人名排成大写：「O. HARTMAN (1959)」「AUGENER (1922)」
    re.compile(r"(?<![\w])(?:[A-Z]\.\s?)?[^\W\d_a-z]{3,}(?:-[^\W\d_a-z]{3,})?\s\(\d{4}(?:\s?[a-z](?![a-z]))?\)"),
]


def clean_ocr(text: str) -> str:
    """翻译前套用 docstore/rules/ocr_fix.toml 的正则规则（不含编辑距离词表纠错，免得慢和误改）。"""
    import tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "docstore" / "rules" / "ocr_fix.toml").read_text("utf-8"))
    for r in cfg.get("regex_rules", []):
        text = re.sub(r["pattern"], r["replace"], text)
    return text


def mask(text: str, sl: str = "") -> tuple[str, list[str]]:
    """返回 (带占位符的文本, 原片段表)；同一输入输出确定，可作缓存键。sl=de 时德文基础形态术语也占位。"""
    saved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return f"[[{len(saved)}]]"

    for pat in PATTERNS:
        text = pat.sub(sub, text)
    if sl.split("-")[0].lower() == "de":
        text = term_de.PATTERN.sub(sub, text)
    return text, saved


_COUNTERS = {"対": ("对", "pair"), "列": ("列", "row"), "剛毛束": ("刚毛束", "seta bundle")}


def _counter(orig: str, tl: str) -> str:
    """日文「N対」占位时连量词一起藏起来，按目标语言还原（谷歌会把「2対の眼」译成「2那双眼睛」）。"""
    if tl and (t := term_de.render(orig, tl)):
        return t
    lang0 = tl.split("-")[0].lower()
    if lang0 in ("zh", "en"):
        if " bis " in orig:   # 2 bis 2% → 2–2½（OCR 把 ½ 识成 %）；1,5 bis 3 mm → 1,5–3 mm
            return re.sub(r"%$", "½", orig).replace(" bis ", "–")
        if orig.endswith(" Paar"):
            n = orig[:-5]
            return f"{n}对" if lang0 == "zh" else f"{n} pair" + ("" if n == "1" else "s")
    for ja, (zh, en) in _COUNTERS.items():
        if orig.endswith(ja):
            n = orig[: -len(ja)]
            lang = tl.split("-")[0].lower()
            if lang == "zh":
                return n + zh
            if lang == "en":
                return f"{n} {en}" + ("" if n == "1" else "s")
    return orig


def restore(text: str, saved: list[str], tl: str = "") -> str:
    """占位符换回原文。占位符被机翻吞掉时不补（用 lost() 先查）。"""
    for i, orig in enumerate(saved, 1):
        orig = _counter(orig, tl)
        text = re.sub(rf"\[\[\s*{i}\s*\]\]", orig.replace("\\", "\\\\"), text)
    return text


def lost(text: str, saved: list[str]) -> list[int]:
    """还原前检查：返回译文里已丢失的占位符编号。"""
    return [i for i in range(1, len(saved) + 1) if not re.search(rf"\[\[\s*{i}\s*\]\]", text)]
