"""送机翻前保护不可改写的记号（学名+命名人年份、n. sp. 等命名标记、两位年份的日期），回来后原样还原。

依据：2026-11-22 零模型实测（docs/research/2026-11-21-zero-model-run.md）：谷歌把 `n. sp.` 改成 `n。 sp。`，
把「29. 12. 59」译成「2059 年 12 月 29 日」。占位符 [[n]] 经实测在 de/ja→zh 里原样保留；
还原时容忍占位符内外多出的空格。注意：谷歌自己丢字母（anoculata→anculata）发生在学名内部，被占位符整体挡住。
"""
from __future__ import annotations

import re

_AUTH = r"(?:\(?[A-Z][\w'’.\-]*(?:[ ,&]+(?:and |et |und )?[A-Z][\w'’.\-]*)*,? ?\d{4}[a-z]?\)?)"
_TAG = r"(?:n\. ?(?:sp|gen|comb|subsp|var)\.|(?:sp|gen|comb)\. ?n\.|nom\. ?nov\.|comb\. ?nov\.)"
_BINOM = r"[A-Z][a-z]{2,}(?: \([A-Z][a-z]{2,}\))? [a-z]{3,}(?: (?:var|subsp|f)\. [a-z]{3,})?"
# 先匹配最长的：学名+命名人年份 / 学名+命名标记；再匹配单独命名标记、日期
PATTERNS = [
    re.compile(rf"{_BINOM} {_AUTH}"),
    re.compile(rf"{_BINOM} {_TAG}"),
    re.compile(rf"(?<![\w]){_TAG}"),
    # OCR 常把第一个点识成逗号（10, 3. 60），也算日期
    re.compile(r"(?<!\d)\d{1,2}[.,] ?\d{1,2}\. ?\d{2}(?!\d)"),
    # 括号内单独的命名人+年份（异名/分布引证），谷歌会把人名音译
    re.compile(r"\((?!(?:Abb|Fig|Taf|Tab|Pl|Tafel)\b)[^\W\d_a-z][\w'’.\-]*(?:[ ,&]+(?:and |et |und )?[^\W\d_a-z][\w'’.\-]*)*,? ?\d{4}[a-z]?\)"),
    # 德文志书把人名排成大写：「O. HARTMAN (1959)」「AUGENER (1922)」
    re.compile(r"(?<![\w])(?:[A-Z]\. ?)?[^\W\d_a-z]{3,}(?:-[^\W\d_a-z]{3,})? \(\d{4}[a-z]?\)"),
]


def mask(text: str) -> tuple[str, list[str]]:
    """返回 (带占位符的文本, 原片段表)；同一输入输出确定，可作缓存键。"""
    saved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return f"[[{len(saved)}]]"

    for pat in PATTERNS:
        text = pat.sub(sub, text)
    return text, saved


def restore(text: str, saved: list[str]) -> str:
    """占位符换回原文。占位符被机翻吞掉时不补（用 lost() 先查）。"""
    for i, orig in enumerate(saved, 1):
        text = re.sub(rf"\[\[\s*{i}\s*\]\]", orig.replace("\\", "\\\\"), text)
    return text


def lost(text: str, saved: list[str]) -> list[int]:
    """还原前检查：返回译文里已丢失的占位符编号。"""
    return [i for i in range(1, len(saved) + 1) if not re.search(rf"\[\[\s*{i}\s*\]\]", text)]
