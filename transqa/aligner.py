"""段落对齐检测器（V3）：逐页让模型比对原文与译文，只报「遗漏」与「凭空添加」。

纯函数，不调用模型。模型给出的引文必须原样出现在原文（omitted）或译文（added）的整页文字里，
否则丢弃——模型引不出原话的指控不进人工队列。按整页比对是有意的：两边段落数不等时，段落下标不可靠。
提示词来自 2026-11-19 的 40 页植入测试（spec §4.1 的 V3）；日→英时与当时所用原文逐字相同。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

SYSTEM_PROMPT = """You compare a {SL} taxonomic source text with its {TL} translation, paragraph by paragraph.
Paragraph i of SOURCE corresponds to paragraph i of TARGET. Report ONLY substantive content mismatches:
- "omitted": a {SL} clause/sentence stating a fact (character, count, size, locality, habitat, comparison, remark) that has NO counterpart in the {TL} paragraph.
- "added": an {TL} sentence stating a fact that is NOT in the {SL} paragraph.
Ignore wording choices, restructuring, figure references, OCR noise, and Latin names/citations. Do not report terminology issues.
Output ONLY a JSON array (possibly empty): [{"para": <i>, "type": "omitted"|"added", "quote": "<verbatim {SL} clause for omitted / verbatim {TL} sentence for added>", "reason": "<one short sentence>"}]"""
PROMPT_DIGEST = hashlib.sha1(SYSTEM_PROMPT.encode('utf-8')).hexdigest()   # 缓存摘要用：提示词一改，缓存失效

LANG_NAMES = {'ja': 'Japanese', 'en': 'English', 'zh': 'Chinese', 'zh-CN': 'Chinese', 'ko': 'Korean',
              'bg': 'Bulgarian', 'ru': 'Russian', 'uk': 'Ukrainian', 'sr': 'Serbian', 'de': 'German',
              'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'la': 'Latin',
              'el': 'Greek'}
# 模型在 reason 里自己写明「其实没有遗漏」（clean2 实测 10 条里 4 条）：不进人工队列，进 dropped 留痕
SELF_NEGATED = re.compile(r'\bnot (?:a )?(?:true |real |actual )?(?:omitted|omission)\b|\bno omission\b'
                          r'|\bskip\b|\bis actually present\b|\balready present\b', re.I)
MIN_QUOTE = 6   # 引文（NFKC、去空白后）至少这么长才有核对价值


def system_prompt(sl: str, tl: str) -> str:
    return SYSTEM_PROMPT.replace('{SL}', LANG_NAMES.get(sl, sl)).replace('{TL}', LANG_NAMES.get(tl, tl))


@dataclass
class AlignItem:
    page: int
    para: int
    type: str
    quote: str
    reason: str


def split_paras(page_text: str) -> list[str]:
    """按空行分段；去掉只含页标记（HTML 注释）的段和空段。"""
    out = []
    for p in re.split(r'\n\s*\n', page_text):
        p = p.strip()
        if p and not re.fullmatch(r'<!--.*?-->', p, re.S):
            out.append(p)
    return out


def build_user(src_paras: list[str], tgt_paras: list[str]) -> str:
    return ('SOURCE:\n' + '\n'.join(f'[{i}] {s}' for i, s in enumerate(src_paras))
            + '\n\nTARGET:\n' + '\n'.join(f'[{i}] {t}' for i, t in enumerate(tgt_paras)))


def _squash(t: str) -> str:
    """NFKC 后去掉全部空白：全角数字/空格差异不影响「原样出现」的判断。"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', t))


def gate_items(raw: list[Any], page: int, src_page: str,
               tgt_page: str) -> tuple[list[AlignItem], list[dict[str, Any]]]:
    """返回（通过, 丢弃）。通过：type 为 omitted/added；引文规范化后 ≥ MIN_QUOTE；
    omitted 的引文在原文整页内、added 的引文在译文整页内。丢弃项附 drop_reason。"""
    kept: list[AlignItem] = []
    dropped: list[dict[str, Any]] = []
    pools = {'omitted': _squash(src_page), 'added': _squash(tgt_page)}
    for it in raw:
        if not isinstance(it, dict):
            dropped.append({'item': it, 'drop_reason': '条目不是对象'})
            continue
        ty = str(it.get('type', ''))
        q = _squash(str(it.get('quote', '')))
        if ty not in pools:
            why = f'type 不是 omitted/added：{ty!r}'
        elif len(q) < MIN_QUOTE:
            why = f'引文太短（{len(q)} < {MIN_QUOTE}）'
        elif q not in pools[ty]:
            why = '引文不在' + ('原文' if ty == 'omitted' else '译文') + '该页内（疑似模型编造）'
        elif SELF_NEGATED.search(str(it.get('reason', ''))):
            why = '模型自述并无遗漏（reason 里写明 not omitted / no omission / skip）'
        else:
            why = ''
        if why:
            dropped.append(dict(it, page=page, drop_reason=why))
            continue
        try:
            para = int(it.get('para', -1))
        except (TypeError, ValueError, OverflowError):    # "para": Infinity → float('inf') → OverflowError
            para = -1
        kept.append(AlignItem(page=page, para=para, type=ty, quote=str(it.get('quote', '')).strip(),
                              reason=str(it.get('reason', ''))))
    return kept, dropped
