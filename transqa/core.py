"""通用检查（与语言、领域无关；语言差异全部来自 languages.LANG）。

接口（architecture.md §5）：check(src_segments, tgt_segments, config) -> list[Issue]
config: {'sl': 'bg', 'tl': 'en', 'bad_terms': [...], 'src_order': [页序], 'tgt_order': [页序]}
"""
from __future__ import annotations

import collections
import re
from typing import Any

from . import languages as L
from .issue import Issue, Severity
from .segments import Segment, by_page

FOREIGN = 'ऀ-ॿ؀-ۿ฀-๿֐-׿'   # 天城文、阿拉伯、泰、希伯来：分类学书里不该出现


def clean(t: str) -> str:
    """去掉注释、译注 [TN: ...]、图注子图字母（1а、2б）。"""
    t = re.sub(r'<!--.*?-->|\[TN:[^\]]*\]', '', t, flags=re.S)
    return t


def numbers(t: str) -> collections.Counter[str]:
    """数字。千分位（136 000、136,000、136.000、136 000）先并成 136000；小数逗号与小数点视为同一（33,6 = 33.6）。"""
    t = re.sub(r'(?<![\d.,])(\d{1,3})((?:[ \u00a0\u202f,.]\d{3})+)(?![\d.,]\d)',
               lambda m: m.group(1) + re.sub(r'\D', '', m.group(2)), clean(t))
    return collections.Counter(x.replace(',', '.') for x in re.findall(r'\d+(?:[.,]\d+)?', t))


def _page_text(segs: list[Segment]) -> str:
    return '\n\n'.join(s.text for s in segs)


def coverage(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    sp, tp = by_page(src), by_page(tgt)
    for p in sorted(set(sp) - set(tp)):
        out.append(Issue('coverage.page_missing', 'critical', f'缺页 p.{p}（页标记不一致）', p))
    for p in sorted(set(tp) - set(sp)):
        out.append(Issue('coverage.page_extra', 'major', f'多出页 p.{p}（页标记不一致）', p))
    so, to = cfg.get('src_order'), cfg.get('tgt_order')
    if so and to:
        dup = [p for p, c in collections.Counter(to).items() if c > 1]
        if dup:
            out.append(Issue('coverage.page_duplicate', 'critical', f'页标记重复 {dup}'))
        common = [p for p in to if p in set(so)]
        if common != [p for p in so if p in set(to)]:
            out.append(Issue('coverage.page_order', 'critical', '页序与原文不同（页被调换）',
                             evidence={'src': so[:50], 'tgt': to[:50]}))
    for p in sorted(set(sp) & set(tp)):
        ns, nt = len(sp[p]), len(tp[p])
        if nt < ns:
            lines = sum(len([x for x in s.text.split('\n') if x.strip()]) for s in tp[p])
            if lines >= ns:   # 段数少但行数够：只是空行丢了（合段），文字还在
                out.append(Issue('coverage.segment_merged', 'minor', f'p.{p} 段数少于原文（{nt}/{ns}），行数相当，疑为合段',
                                 p, evidence={'src': ns, 'tgt': nt, 'tgt_lines': lines}))
            else:
                out.append(Issue('coverage.segment_missing', 'major', f'p.{p} 段数少于原文（{nt}/{ns}），疑似漏段', p,
                                 evidence={'src': ns, 'tgt': nt, 'tgt_lines': lines}))
        empty = [s.id for s in tp[p] if not re.search(r'\w', clean(s.text))]
        if empty:
            out.append(Issue('coverage.segment_empty', 'major', f'p.{p} 空译段 {empty}', p))
    return out


def number_check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    sl = cfg.get('sl', '')
    sp, tp = by_page(src), by_page(tgt)
    words_ok = bool(L.numerals(sl))
    for p in sorted(set(sp) & set(tp)):
        s, t = _page_text(sp[p]), _page_text(tp[p])
        ns, nt = numbers(s), numbers(t)
        miss = ns - nt
        if miss:
            out.append(Issue('number.missing', 'critical', f'p.{p} 缺数字 {dict(miss)}', p, evidence=dict(miss)))
        extra = nt - ns
        allow = collections.Counter(str(v) for v in L.numeral_values(clean(s), sl))
        extra = extra - allow
        if extra:
            sev: Severity = 'major' if words_ok else 'info'
            msg = f'p.{p} 多出原文没有的数字 {dict(extra)}' + ('' if words_ok else f'（{sl} 无数词表，未能排除数词→数字）')
            out.append(Issue('number.added', sev, msg, p, evidence=dict(extra)))
    return out


def script_check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    sl, tl = cfg.get('sl', ''), cfg.get('tl', '')
    si, ti = L.info(sl), L.info(tl)
    tp = by_page(tgt)
    for p, segs in sorted(tp.items()):
        body = clean(_page_text(segs))
        f = re.findall(f'[{FOREIGN}]', body)
        if f:
            out.append(Issue('script.foreign', 'major', f'p.{p} 出现异常文字 {"".join(f)[:20]}', p))
        if si is None or ti is None:
            continue
        own = si['own']
        if not own or _overlap(own, ti['script']):   # 源语言没有专属文字（拉丁字母语言），或与目标共用（ja→zh 的汉字）
            continue
        b2 = re.sub(r'\*[^*\n]+\*', '', body)                       # 斜体（学名、原文引语）不算
        # 1а 式图注字母；前后都不是文字的单个字母（а, б — original）
        b2 = re.sub(rf'(?<=\d)[{own}](?![{own}])|(?<![^\W\d_])[{own}](?![^\W\d_])', '', b2)
        run = 1 if L.base(sl) in ('ja', 'ko') else 2       # 假名、谚文单字也算残留
        left = re.findall(f'[{own}]{{{run},}}', b2)
        if left:
            out.append(Issue('script.residue', 'major', f'p.{p} 残留未译原文 {len(left)} 处：{" ".join(left[:5])}', p))
    if si is None or ti is None:
        out.append(Issue('capability_missing', 'info', f'语言表缺 {sl if si is None else tl}，残留原文检查未做'))
    return out


def _overlap(a: str, b: str) -> bool:
    """两个字符类范围是否有交集（如 ja 的汉字与 zh）。只比较 'X-Y' 形式的区段。"""
    def ranges(s: str) -> list[tuple[int, int]]:
        return [(ord(x), ord(y)) for x, y in re.findall(r'(.)-(.)', s)]
    return any(x1 <= y2 and x2 <= y1 for x1, y1 in ranges(a) for x2, y2 in ranges(b))


def negation_check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    sl, tl = cfg.get('sl', ''), cfg.get('tl', '')
    if L.info(sl) is None or L.info(tl) is None:
        return [Issue('capability_missing', 'info', f'语言表缺 {sl if L.info(sl) is None else tl}，否定词风险未查')]
    out: list[Issue] = []
    sp, tp = by_page(src), by_page(tgt)
    for p in sorted(set(sp) & set(tp)):
        a, b = L.count_neg(_page_text(sp[p]), sl) or 0, L.count_neg(_page_text(tp[p]), tl) or 0
        if a > b:
            out.append(Issue('meaning.negation_risk', 'info', f'p.{p} 原文否定/缺失词 {a} 处、译文 {b} 处，核对有/无', p,
                             evidence={'src': a, 'tgt': b}))
    return out


def bad_terms(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    out = []
    for w in cfg.get('bad_terms') or []:
        hits = [s for s in tgt if re.search(rf'\b{re.escape(w)}\b', s.text)]
        if hits:
            out.append(Issue('term.forbidden', 'major', f'禁用词 {w}（{len(hits)} 段）', hits[0].page, hits[0].id))
    return out


def check(src: list[Segment], tgt: list[Segment], config: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    for f in (coverage, number_check, script_check, negation_check, bad_terms):
        out += f(src, tgt, config)
    return out
