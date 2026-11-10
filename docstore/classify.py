"""kind / lang / domain / title / key 初判。全部只是初判，note 里标「初判，待确认」。"""

from __future__ import annotations

import re
from pathlib import Path

_CJK = re.compile(r"[㐀-鿿]")
_ZLIB = re.compile(r"\s*\((z-library|Z-Library)[^)]*\)\s*$")
_PAREN = re.compile(r"\s*[（(]([^()（）]*)[)）]\s*$")
_FOREIGN = re.compile(r"\[(美|英|法|德|日|俄|苏)\]|（(美|英|法|德|日|俄|苏)）|[Ѐ-ӿ]|·|著；")

# 先匹配者优先；「植物」放在「系统发育」之前，避免植物系统学书被归到分子系统学
DOMAIN_RULES = [
    (("动物志", "多毛", "海洋无脊椎", "名录", "环节动物"), "分类学"),
    (("植物",), "植物系统学"),
    (("系统发育", "分子进化", "phylogen", "molecular evolution"), "分子系统学"),
    (("进化", "物种", "evolution", "species"), "进化生物学"),
    (("思想", "biological thought", "history of"), "科学史"),
]

NOTE = "初判，待确认"


def clean_title(stem: str) -> tuple[str, str]:
    """去掉 z-library 尾注，拆出末尾括号里的作者。返回 (题名, 作者)。"""
    s = _ZLIB.sub("", stem).strip()
    authors = ""
    m = _PAREN.search(s)
    if m and m.start() > 0:
        authors = m.group(1).strip()
        s = s[: m.start()].strip()
    return s, authors


def guess(path: Path) -> dict:
    stem = path.stem
    title, authors = clean_title(stem)
    full = str(path)
    has_cjk = bool(_CJK.search(stem))
    if "动物志" in full:
        kind = "志书"
    elif "名录" in stem:
        kind = "名录"
    elif "学位论文" in full:
        kind = "学位论文"
    elif "/专著/" in full:
        kind = "专著"
    elif not has_cjk:
        kind = "英文原著"
    elif "译" in stem or _FOREIGN.search(stem):
        kind = "译本"
    else:
        kind = "中文论著"
    lang = "zh" if has_cjk else "en"
    low = (title + " " + str(path.parent.name)).lower()
    domain = ""
    for words, dom in DOMAIN_RULES:
        if any(w.lower() in low for w in words):
            domain = dom
            break
    return {"key": make_key(title, authors, has_cjk), "title": title, "authors": authors, "kind": kind,
            "lang": lang, "domain": domain, "note": NOTE}


_STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "to"}


def make_key(title: str, authors: str, has_cjk: bool) -> str:
    if has_cjk:
        t = re.sub(r"[\s()（）\[\]【】:：,，;；·.]+", "", title)
        return t[:14] or "doc"
    words = [w for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in _STOP][:4]
    sur = ""
    if authors:
        names = re.findall(r"[A-Za-z]+", authors.split(",")[0])
        sur = names[-1] if names else ""
    return "_".join([x for x in [sur] + words if x]) or "doc"
