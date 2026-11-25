"""中文译文的「翻译腔」度量与确定性检查（目标语 = 中文时的 QA 插件）。

依据（2026-11-15 实测，每千汉字频次；语料见 docs/zh_style_evidence.md）：
本土动物学教科书（杨德渐 2006，22 万字）、本土论述文（洪德元 2016，1.7 万字）、名家中译本（Mayr《生物学思想发展史》，54 万字）
与本项目机器译稿（Handbook 93 万字、Rouse 23 万字）对比，我方译稿的问题**不是「的」多**（34/千字，与本土教科书相同，
「的」≥2 的句子只占 20%，本土 33–56%），而是：
- 句子被切得过碎：句长中位 21–23 字（本土 29–37），>60 字的句子 1–2%（本土 13–21%）；
- 虚词/代词欧化：「该」1.8（本土 0.3–0.5，约 7 倍）、「以及」1.4–1.5（本土 0.2–0.5）、「然而」0.6–0.9（本土 0.02–0.2）、
  「被」2.4–3.2（本土 1.2–1.8）、「关于」最高 1.3（本土 0.04–0.3）、「其」5.3–6.0（本土 3.4–4.1）。
所以：不按「的」机械删改；按下表的本土区间找超标的段落，只把这些段落交给模型润色。
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

HAN = r'[一-鿿]'

# 每千汉字频次。native = 本土动物学/论述文的观测区间上限（取两种本土语料的较大值，留 20% 余量）；
# ours = 本项目机器译稿观测值（Handbook / Rouse）。超过 native 上限 2 倍判为超标。
MARKERS: dict[str, tuple[str, float]] = {
    '该': ('该', 0.55),
    '以及': ('以及', 0.62),
    '然而': ('然而', 0.28),
    '被': ('被', 2.1),
    '关于': ('关于', 0.35),
    '其': ('其', 4.9),
    '一个': ('一个', 3.5),
    '它们': ('它们', 2.0),
    '作为': ('作为', 0.76),
    '对…的': ('对[^，。；：]{1,12}的', 1.8),
    '进行': ('进行', 1.1),
}
SENT_MEDIAN_NATIVE = (29, 37)   # 本土句长中位（字）
LONG_SENT_NATIVE = (13.5, 21.4)  # 本土 >60 字句子占比（%）


def han_count(t: str) -> int:
    return len(re.findall(HAN, t))


def _plain(t: str) -> str:
    return re.sub(r'<!--.*?-->|\[TN:[^\]]*\]|\*[^*\n]*\*|`[^`]*`', '', t, flags=re.S)


def sentences(t: str) -> list[str]:
    return [s for s in re.split(r'(?<=[。！？；])', _plain(t)) if han_count(s) >= 8]


@dataclass
class StyleReport:
    chars: int
    rates: dict[str, float]
    over: dict[str, float]                 # 超标的标记：倍数（相对本土上限）
    sent_median: float
    long_share: float
    short_flag: bool                       # 句子过碎
    notes: list[str] = field(default_factory=list)


def measure(text: str) -> StyleReport:
    t = _plain(text)
    n = max(1, han_count(t))
    rates = {k: round(len(re.findall(rx, t)) / n * 1000, 2) for k, (rx, _) in MARKERS.items()}
    over = {k: round(rates[k] / lim, 1) for k, (_, lim) in MARKERS.items() if rates[k] > 2 * lim}
    ln = [han_count(s) for s in sentences(t)]
    med = float(statistics.median(ln)) if ln else 0.0
    long_share = round(100 * sum(x > 60 for x in ln) / max(1, len(ln)), 1)
    short = bool(ln) and med < 0.8 * SENT_MEDIAN_NATIVE[0] and long_share < 0.5 * LONG_SENT_NATIVE[0]
    return StyleReport(n, rates, over, med, long_share, short)


def paragraph_score(p: str) -> float:
    """段落翻译腔得分：各标记「超出本土期望次数 + 1」的部分之和（短段里偶尔一个「该」不算），
    加上句子过碎罚分。阈值 PARA_THRESHOLD 按本土教科书校准（见 docs/zh_style_evidence.md）。"""
    t = _plain(p)
    n = han_count(t)
    if n < 40:
        return 0.0
    score = 0.0
    for rx, lim in MARKERS.values():
        excess = len(re.findall(rx, t)) - (lim * n / 1000 + 1)
        if excess > 0:
            score += excess
    ln = [han_count(s) for s in sentences(t)]
    if len(ln) >= 4 and statistics.median(ln) < 18:
        score += 1.0
    return round(score, 2)


PARA_THRESHOLD = 2.0


# ---- 确定性检查（与内容无关、对中文普遍成立）
@dataclass
class ZhIssue:
    line: int
    code: str
    severity: str
    message: str


CHECKS: list[tuple[str, str, str, str]] = [
    # code, severity, 正则（逐行）, 说明
    ('dup_char', 'major', r'(具具|的的|了了|是是|在在|和和)', '衍字'),
    ('dun_clause', 'minor', r'、(?:但|却|而|然而)', '顿号接转折分句，应为逗号'),
    ('kana', 'major', r'[぀-ヿ]', '残留日文假名'),
    ('half_quote', 'minor', r'(?<=[一-鿿])"|"(?=[一-鿿])', '中文里用了半角引号'),
    ('filler', 'minor', r'值得注意的是|值得一提的是|众所周知', '译者常加的套语：原文无对应时删去'),
]


def check_lines(text: str) -> list[ZhIssue]:
    out: list[ZhIssue] = []
    for i, ln in enumerate(text.split('\n'), 1):
        s = re.sub(r'\*[^*\n]*\*|`[^`]*`', '', ln)        # 斜体（学名）与代码不查
        if re.match(r'\s*#+\s', ln) and re.search(r'。\s*$', ln):
            out.append(ZhIssue(i, 'title_period', 'minor', '标题末尾不加句号'))
        for code, sev, rx, msg in CHECKS:
            if re.search(rx, s):
                out.append(ZhIssue(i, code, sev, f'{msg}：{re.search(rx, s).group(0)}'))  # type: ignore[union-attr]
    return out


def is_description(p: str) -> bool:
    """条目体描述（志书、检索表式短句：「体长 2–3 mm。口前叶圆锥形。」）：≥60% 的分句短于 15 字，且少有叙述虚词
    （是/被/在/了/这/它/该/此/由于/因为/但/而/也/都/关于/然而）——切碎的叙述段也句短，但满是这些虚词。不送润色。"""
    parts = [s for s in re.split(r'[。；]', _plain(p)) if han_count(s) >= 2]
    if len(parts) < 3 or sum(han_count(s) < 15 for s in parts) < 0.6 * len(parts):
        return False
    narrative = sum(bool(re.search(r'是|被|在|了|这|它|该|此|由于|因为|但|而|也|都|关于|然而', s)) for s in parts)
    return narrative < 0.4 * len(parts)
