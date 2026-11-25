"""文本粘连检测（GitHub #17）：OCR 词粘连、标点粘连、跨页断词残片、跨页重复连接词。

只检测、不修复：规则是确定性的，但词边界的修复不可靠（任意插空格会破坏学名、人名），所以一律出问题单，
由人或带闸口的 apply_issues 处理。只检查译文（目标语言），斜体（学名）、URL、邮箱、DOI 先屏蔽。

代码：
- text.word_join          major  小写词粘连/机构名粘连（`UniversityOxford`、`inthe`）
- text.punct_join         minor  逗号/分号/冒号/句点后缺空格（`Rouse,Pleijel`、`sample.Another`）
- text.page_hyphen        minor  页末词以连字符结尾，下页接续（跨页断词未合并）
- text.orphan_fragment    minor  页首是孤立的词尾碎片（`mium is short`），全文无此独立词
- text.duplicate_connective minor 上页末与下页首重复同一连接词（`and | and`）
"""
from __future__ import annotations

import collections
import re
from typing import Any

from . import languages as L
from .core import _page_text, clean, strip_furniture
from .issue import Issue
from .segments import Segment, by_page

_MASK_RE = re.compile(
    r'(?<![\w*])\*(?=[^\s*\d])[^*\n]{1,120}?(?<![\s*])\*(?!\w)'      # 斜体（学名）
    r'|https?://\S+|www\.\S+|\S+@\S+\.\S+|\bdoi:\s*\S+|\b10\.\d{4,}/\S+'
    r'|\[\[?[^\]\n]*\]\]?', re.I)
_CAMEL_RE = re.compile(r'\b[A-ZÀ-Ý]?[a-zà-ÿ]{3,}[A-ZÀ-Ý][a-zà-ÿ]{2,}\b')
_CAMEL_OK = {'DeepSeek', 'YouTube', 'PowerPoint', 'JavaScript', 'LibreOffice', 'ResearchGate', 'GitHub', 'MacBook',
             'WoRMS', 'iNaturalist', 'ChatGPT', 'OpenAI', 'PhyloCode', 'BioScience', 'ZooKeys', 'ZooBank', 'MycoBank',
             'GenBank', 'PubMed', 'McDonald', 'MacDonald', 'McKay', 'McIntosh'}
_STOP_JOIN = {
    'en': re.compile(r'\b(?:of|in|and|to|on|for|with|from|by|at)(?:the)\b'),
    'es': re.compile(r'\b(?:de|en|y|con|por|para)(?:la|las|los|el)\b'),
}
_COMMA_JOIN_RE = re.compile(r'\b[^\W\d_]{3,}[,;:][^\W\d_]{2,}')
_PERIOD_JOIN_RE = re.compile(r'\b([a-zà-ÿ]{3,})\.[A-ZÀ-Ý][a-zà-ÿ]{2,}')
_ABBR = {'spp', 'nov', 'var', 'vol', 'fig', 'figs', 'etc', 'sensu', 'comb', 'gen', 'subsp', 'aff', 'cfr', 'eds', 'tab',
         'pers', 'comm', 'ibid', 'cit', 'stat', 'syn', 'non', 'auct', 'emend', 'nec', 'pro', 'part'}
_STOP = {
    'en': 'the a an of in on at to for with from by and or but that which is are was were be as it its this these those '
          'not no also than then when where while into onto over under per via'.split(),
    'es': 'el la los las un una unos unas de del en y o u a al con por para que se su sus es son fue no sin sobre entre '
          'como más pero también lo le les ya'.split(),
    'de': 'der die das den dem des ein eine und oder mit von zu im in am auf für nicht ist sind'.split(),
    'fr': 'le la les un une des de du et ou en dans sur pour avec par que qui est sont pas'.split(),
}
_CONNECTIVES = set('the a an of in on at to for with from by and or but that as de la el los las en y o con por para que'.split())
_END_PUNCT = tuple('.!?:;)]"\'”’»')


def _mask(t: str) -> str:
    return _MASK_RE.sub(lambda m: ' ' * len(m.group(0)), clean(t))


def _lines(text: str) -> list[str]:
    return [x for x in text.split('\n') if x.strip()]


def _words(s: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", s)


def check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    tl = L.base(cfg.get('tl', ''))
    if tl in ('zh', 'ja', 'ko'):       # 无词间空格的文字系统
        return []
    out: list[Issue] = []
    tp = by_page(tgt)
    pages = sorted(tp)
    texts = strip_furniture({p: _page_text(tp[p]) for p in pages})
    vocab = collections.Counter(w.lower() for p in pages for w in _words(_mask(texts[p])))
    stop = set(_STOP.get(tl, [])) | set(_STOP['en'])
    for p in pages:
        t = _mask(texts[p])
        joins: list[str] = []
        for m in _CAMEL_RE.finditer(t):
            if m.group(0) not in _CAMEL_OK:
                joins.append(m.group(0))
        if (pat := _STOP_JOIN.get(tl)) is not None:
            joins += [m.group(0) for m in pat.finditer(t)]
        if joins:
            out.append(Issue('text.word_join', 'major',
                             f'p.{p} 疑似词粘连 {sorted(set(joins))}（OCR 缺空格；须对照原文页核对，不得任意插空格）', p,
                             evidence={'tokens': sorted(set(joins))}))
        puncts = [m.group(0) for m in _COMMA_JOIN_RE.finditer(t)]
        puncts += [m.group(0) for m in _PERIOD_JOIN_RE.finditer(t) if m.group(1).lower() not in _ABBR]
        if puncts:
            out.append(Issue('text.punct_join', 'minor', f'p.{p} 标点后缺空格 {sorted(set(puncts))}', p,
                             evidence={'tokens': sorted(set(puncts))}))
    for p, q in zip(pages, pages[1:]):
        if q != p + 1:
            continue
        a, b = _lines(texts[p]), _lines(texts[q])
        if not a or not b:
            continue
        last, first = a[-1].rstrip(), b[0].lstrip()
        if re.search(r'[^\W\d_]-$', last):
            out.append(Issue('text.page_hyphen', 'minor',
                             f'p.{p} 末尾「…{last[-12:]}」连字符断词，p.{q} 接续未合并（核对原文是否为复合词）', p,
                             evidence={'tail': last[-20:], 'head': first[:20]}))
            continue
        fw = re.match(r"([a-zà-ÿ]+)\b", first)
        last_words = _words(last)
        tail_complete = bool(last_words) and last_words[-1].lower() in (stop | _CONNECTIVES)
        if (fw and len(fw.group(1)) <= 5 and fw.group(1) not in stop and vocab[fw.group(1)] <= 1
                and not last.endswith(_END_PUNCT) and not tail_complete):
            out.append(Issue('text.orphan_fragment', 'minor',
                             f'p.{q} 页首「{fw.group(1)}」疑为 p.{p} 末词的词尾残片（全文无此独立词）', q,
                             evidence={'fragment': fw.group(1), 'tail': last[-20:]}))
            continue
        lw, fwords = [w.lower() for w in _words(last)], [w.lower() for w in _words(first)]
        for k in (2, 1):
            if len(lw) >= k and len(fwords) >= k and lw[-k:] == fwords[:k] and all(w in _CONNECTIVES for w in lw[-k:]):
                out.append(Issue('text.duplicate_connective', 'minor',
                                 f'p.{p} 末与 p.{q} 首重复连接词「{" ".join(lw[-k:])}」（跨页重复）', q,
                                 evidence={'words': lw[-k:]}))
                break
    return out
