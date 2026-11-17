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


# 文件名「作者, 年份-题名」（文献管理软件常见导出格式）
_AUTHOR_YEAR = re.compile(r"^(?P<a>[^,]{2,80}?),\s*(?P<y>1[5-9]\d\d|20\d\d)(?P<s>[a-z]?)(?:\s*[-–—_.,]\s*(?P<t>.+))?\s*$")

# 题名语言初判：各语言高频功能词（命中数最多者胜；全不命中按英文）。新语言加一行即可。
_LANG_WORDS = {
    "de": {"der", "die", "das", "des", "den", "dem", "und", "zur", "zum", "aus", "von", "mit", "unter", "nach",
           "über", "ueber", "einer", "eines", "neue", "neuer", "gattung", "kenntnis", "beitrag", "beiträge", "insel"},
    "fr": {"les", "des", "du", "de", "la", "le", "et", "sur", "aux", "une", "nouvelle", "nouveau", "côtes"},
    "es": {"los", "las", "del", "el", "y", "sobre", "una", "nueva", "nuevo"},
    "it": {"gli", "della", "delle", "dei", "il", "e", "sulla", "nuova", "nuovo"},
    "en": {"the", "of", "and", "on", "with", "from", "new", "associated", "description", "remarks", "revision"},
}
_LANG_CHARS = {"de": re.compile(r"[äöüßÄÖÜ]"), "fr": re.compile(r"[éèêàçœ]"), "es": re.compile(r"[ñ¿¡]")}


def guess_lang(text: str) -> str:
    """拉丁字母题名的语言初判：功能词计数 + 特征字母（各记 1 分）。只是初判。"""
    if _CJK.search(text):
        return "zh"
    words = [w.lower() for w in re.findall(r"[^\W\d_]+", text)]
    score = {lang: sum(w in vocab for w in words) for lang, vocab in _LANG_WORDS.items()}
    for lang, rx in _LANG_CHARS.items():
        if rx.search(text):
            score[lang] += 1
    best = max(score, key=lambda k: score[k])
    return best if score[best] > score["en"] else "en"


def _ascii(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s.replace("ß", "ss")).encode("ascii", "ignore").decode()


def guess(path: Path) -> dict:
    stem = path.stem
    m = _AUTHOR_YEAR.match(_ZLIB.sub("", stem).strip())
    if m and not _CJK.search(stem):
        return _guess_author_year(path, m)
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
    lang = "zh" if has_cjk else guess_lang(title)
    if kind == "英文原著" and lang != "en":
        kind = "外文原著"
    low = (title + " " + str(path.parent.name)).lower()
    domain = ""
    for words, dom in DOMAIN_RULES:
        if any(w.lower() in low for w in words):
            domain = dom
            break
    return {"key": make_key(title, authors, has_cjk), "title": title, "authors": authors, "kind": kind,
            "lang": lang, "domain": domain, "note": NOTE}


_STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "to"} | set().union(*_LANG_WORDS.values()) - {
    "gattung", "kenntnis", "revision", "description", "remarks", "associated", "insel", "neue", "new"}


def _domain(text: str) -> str:
    low = text.lower()
    for words, dom in DOMAIN_RULES:
        if any(w.lower() in low for w in words):
            return dom
    return ""


def _guess_author_year(path: Path, m: re.Match) -> dict:
    """「Hartmann-Schröder, 1965- Die Polychaeten des sublitorals」→ key HartmannSchroder1965_Polychaeten_Sublitorals。
    多作者取第一作者；题名取前两个实词。括号不当作者（常是「Teil 14」之类）。"""
    authors, year, title = m.group("a").strip(), m.group("y"), (m.group("t") or "").strip()
    first = re.split(r"\s*(?:&|\bund\b|\band\b|\bet\b|;)\s*", authors)[0]
    sur = "".join(p[:1].upper() + p[1:] for p in re.findall(r"[A-Za-z]+", _ascii(first)))
    words = [w for w in re.findall(r"[A-Za-z]+", _ascii(title)) if w.lower() not in _STOP and len(w) > 1][:2]
    key = f"{sur}{year}{m.group('s') or ''}" + "".join("_" + w[:1].upper() + w[1:] for w in words)
    lang = guess_lang(title)
    return {"key": key, "title": title, "authors": authors, "year": year,
            "kind": "英文原著" if lang == "en" else "外文原著", "lang": lang,
            "domain": _domain(title + " " + path.parent.name), "note": NOTE}


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
