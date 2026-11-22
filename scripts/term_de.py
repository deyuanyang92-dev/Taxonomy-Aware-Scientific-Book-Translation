"""德文基础形态术语前置替换（零模型）：德文词送机翻前占位，回来按目标语言写入已核定名。

依据：2026-11-22 零模型实测，谷歌把 Borstensegmente 译成「刷毛段」。定名取自术语库 yiku 已核条目
（zh：yzz_核定 / 动物志33 / 杨德渐2006；检索键见各行 en）；tests/test_term_de.py 会对照 ~/.yiku/yiku.db，
库里定名变了测试就报错。只收德文词形明确、中文定名已核的词；没有已核定名的（Kiefer、Rüssel…）不收，交 QA 报警。
"""
from __future__ import annotations

import re

# (德文单数形, 德文复数形, zh, 英文单数, 英文复数, yiku 检索键)
TERMS: list[tuple[str, str, str, str, str, str]] = [
    ("Borstensegment", "Borstensegmente[n]?", "刚节", "chaetiger", "chaetigers", "chaetiger"),
    ("Parapodium", "Parapodien", "疣足", "parapodium", "parapodia", "parapodium"),
    ("Prostomium", "Prostomien", "口前叶", "prostomium", "prostomia", "prostomium"),
    ("Peristomium", "Peristomien", "围口节", "peristomium", "peristomia", "peristomium"),
    ("Elytre", "Elytren", "鳞片", "elytron", "elytra", "elytra"),
    ("Analcirrus", "Analcirren", "肛须", "anal cirrus", "anal cirri", "anal cirrus"),
    ("Tentakelcirrus", "Tentakelcirren", "触须", "tentacular cirrus", "tentacular cirri", "tentacular cirri"),
    ("Rückencirrus", "Rückencirren", "背须", "dorsal cirrus", "dorsal cirri", "dorsal cirrus"),
    ("Aciculum", "Acicula[e]?", "足刺", "aciculum", "acicula", "aciculum"),
    ("Pygidium", "Pygidien", "尾部", "pygidium", "pygidia", "pygidium"),
    ("Nuchalorgan", "Nuchalorgane", "项器", "nuchal organ", "nuchal organs", "nuchal organ"),
    ("Pharynx", "Pharynx", "咽", "pharynx", "pharynges", "pharynx"),
    ("Antenne", "Antennen", "触手", "antenna", "antennae", "antenna"),
    ("Palpe", "Palpen", "触角", "palp", "palps", "palp"),
]
# Borstensegment 单数形写成 Borstensegment；复数含 e/en；单复数正则合并为一条，复数分支用 Plural 判定
_PLUR_ENDINGS = ("n", "e", "en")


def _forms(sing: str, plur: str) -> str:
    return f"(?:{plur}|{sing})"


PATTERN = re.compile(
    r"(?<![\w])(?:" + "|".join(_forms(s, p) for s, p, *_ in TERMS) + r")(?![\w])")


def lookup(word: str) -> tuple[str, str, str, bool] | None:
    """德文词形 → (zh, en, 英文复数, 是否复数)；未收录返回 None。"""
    for s, p, zh, en_s, en_p, _ in TERMS:
        if re.fullmatch(p, word) and word != s:
            return zh, en_s, en_p, True
        if word == s:
            return zh, en_s, en_p, False
    return None


def render(word: str, tl: str) -> str | None:
    """按目标语言给出定名；非 zh/en 目标或未收录返回 None（原词保留）。"""
    hit = lookup(word)
    if not hit:
        return None
    zh, en_s, en_p, plural = hit
    lang = tl.split("-")[0].lower()
    if lang == "zh":
        return zh
    if lang == "en":
        return en_p if plural else en_s
    return None
