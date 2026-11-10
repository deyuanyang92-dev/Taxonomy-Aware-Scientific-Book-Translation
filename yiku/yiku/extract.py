"""从资料中抽取术语候选。抽出的都是「候选」，须人工或主会话裁定后才变「已核」。

1. paren_pairs：中文论著里的「中文（English）」括注（如洪德元论文）。
2. pair_terms：中英对照书（英文原著 + 中译本）——对给定英文术语，在译本相应位置找译者实际用的中文。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

CJK = r"一-鿿\U00020000-\U0002ffff"
# 术语前常见的虚词/动词：候选中文从最后一个这类词之后开始。只收很少出现在术语内部的词
#（不收「种」「类」「为」「有」：物种、行为隔离、有性生殖）
_BOUNDARY = ("包括", "具有", "含有", "没有", "称为", "叫做", "称作", "作为", "成为", "认为", "即为", "就是",
             "的", "了", "和", "与", "及", "在", "是", "把", "将", "从", "以", "即", "或", "等", "被", "由",
             "这", "那", "其", "各", "该", "此", "也", "都", "就", "并", "但", "又", "而")
# 中文侧候选的首尾不能是这些字，内部不能含「的了在是」
_EDGE = set("的了和与及在是把将对从以即或等被由这那其各该此也都就并但又而第个一中上下")
_INNER = set("的了在是")
_PAREN = re.compile(rf"([{CJK}“”‘’\-－]{{1,20}})\s*[（(]\s*([A-Za-z][A-Za-z .,'’\-]{{1,80}}?)\s*[)）]")


@dataclass
class Cand:
    en: str
    zh: str
    page: str
    context: str
    score: float = 0.0


def _trim_zh(run: str) -> str:
    if "“" in run[:-1]:  # 引号起头的术语：从最后一个左引号之后取
        run = run[run.rfind("“") + 1:]
    run = run.strip("“”‘’\"'-－ ")
    cut = max((run.rfind(w) + len(w) for w in _BOUNDARY if w in run[:-1]), default=0)
    zh = run[cut:] if cut < len(run) else run
    return zh.strip("“”‘’\"' ")


def paren_pairs(text: str, marks=None) -> list[Cand]:
    from .ingest import page_at

    out = []
    for m in _PAREN.finditer(text):
        en = re.sub(r"(?<=[a-z])- (?=[a-z])", "", re.sub(r"\s+", " ", m.group(2))).strip(" .,")
        zh = _trim_zh(m.group(1))
        if len(zh) < 2 or len(en) < 2 or re.fullmatch(r"[A-Z]\.?|et al|[ivx]+", en, re.I):
            continue
        s = max(0, m.start() - 40)
        out.append(Cand(en, zh, page_at(marks, m.start()) if marks else "", text[s:m.end() + 20]))
    return out


# ---------- 中英对照书 ----------

_CH_EN = re.compile(r"(?m)^\s*(?:CHAPTER|Chapter)\s+([0-9IVXLC]+|[A-Z][a-z]+)\b")
_CH_ZH = re.compile(r"(?m)^\s*第([一二三四五六七八九十百零〇0-9]+)章")


def split_chapters(text: str, lang: str) -> list[tuple[int, str]]:
    """按章切分，返回 [(起始偏移, 章文本)]；找不到章标题时整本书作为一章。"""
    pat = _CH_EN if lang == "en" else _CH_ZH
    starts = [m.start() for m in pat.finditer(text)]
    if not starts:
        return [(0, text)]
    if starts[0] > 0:
        starts = [0] + starts
    return [(s, text[s:e]) for s, e in zip(starts, starts[1:] + [len(text)])]


def align_chapters(en: str, zh: str):
    """章数相等时按顺序配对，否则整书配对（按相对位置映射仍可用，只是窗口误差大一些）。"""
    ce, cz = split_chapters(en, "en"), split_chapters(zh, "zh")
    if len(ce) == len(cz) and len(ce) > 1:
        return list(zip(ce, cz)), True
    return [((0, en), (0, zh))], False


def _ngrams(s: str, lo=2, hi=8):
    for run in re.findall(f"[{CJK}]+", s):
        for n in range(lo, min(hi, len(run)) + 1):
            for i in range(len(run) - n + 1):
                yield run[i:i + n]


def pair_terms(en_text: str, zh_text: str, terms: list[str], window: int = 400, top: int = 3,
               min_hits: int = 2, zh_marks=None) -> dict[str, list[Cand]]:
    """对每个英文术语：把它在原著中的每次出现，按所在章内的相对位置映射到译本同一章的位置，
    取 ±window 个汉字的窗口；统计窗口里的汉字 n-gram，与全书背景频率比较，得分高者即译者用字。
    得分 = 命中窗口比例 × log(1/背景概率)。返回每个术语前 top 个候选及一处上下文。"""
    from .ingest import page_at
    from .match import _pattern

    pairs, _ = align_chapters(en_text, zh_text)
    L = max(len(zh_text), 1)
    bg = Counter(_ngrams(zh_text))
    out: dict[str, list[Cand]] = {}
    for term in terms:
        pat = _pattern(term)
        windows = []
        for (es, ech), (zs, zch) in pairs:
            for m in pat.finditer(ech):
                c = zs + int(m.start() / max(len(ech), 1) * len(zch))
                windows.append((c, zh_text[max(0, c - window):c + window]))
        if len(windows) < min_hits:
            continue
        df: Counter = Counter()
        for _, w in windows:
            df.update(set(_ngrams(w)))
        scored = []
        for g, k in df.items():
            if k < min_hits or g[0] in _EDGE or g[-1] in _EDGE or _INNER & set(g):
                continue
            p_bg = min(1.0, bg[g] * 2 * window / L)
            sc = k / len(windows) * math.log(1 / max(p_bg, 1e-9))
            if sc > 0:
                scored.append((sc, k, g))
        scored.sort(key=lambda x: (-x[0], -len(x[2])))  # 同分取长者
        picked: list[Cand] = []
        for sc, k, g in scored:
            # 去掉被更长候选覆盖、命中数相同的子串（如「隔离」被「生殖隔离」覆盖）
            if any(g in p.zh or p.zh in g for p in picked):
                continue
            c, w = next(((c, w) for c, w in windows if g in w), windows[0])
            i = w.find(g)
            picked.append(Cand(term, g, page_at(zh_marks, c) if zh_marks else "",
                               w[max(0, i - 30):i + len(g) + 30], round(sc, 3)))
            if len(picked) >= top:
                break
        out[term] = picked
    return out


_STOP = set("""a an the of and or in on at to for from by with as is are was were be been being this that these
those it its which who whom whose what when where why how not no than then there their they them he she his her
we our you your i me my also only such more most other some any all each both between into through during before
after above below over under again further can could may might must shall should will would do does did have has
had about against among however thus therefore whereas while if because although though so very same own just
one two three first second new many much well even still often since upon within without""".split())


def auto_terms(en_text: str, min_freq: int = 5, max_n: int = 3, limit: int = 500) -> list[str]:
    """没有术语清单时，从原著自动挑候选：1–3 词、首尾不是虚词、出现 ≥min_freq 次。宁多勿少，靠中文侧打分过滤。"""
    words = re.findall(r"[A-Za-z][A-Za-z\-]+", en_text.lower())
    cnt: Counter = Counter()
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if g[0] in _STOP or g[-1] in _STOP or any(len(w) < 3 for w in g):
                continue
            cnt[" ".join(g)] += 1
    return [g for g, k in cnt.most_common() if k >= min_freq and (" " in g or len(g) >= 6)][:limit]
