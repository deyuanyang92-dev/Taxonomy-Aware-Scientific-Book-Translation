"""落实前护栏：模型改动在写进译文之前的确定性检查（0 token）。

规则（任一命中即拒绝，改动转人工队列，不落实）：
  1. new 为空；
  2. 译入语是拉丁文字，而 new 含源语言文字（译文里不应出现原文字符）；
  3. old→new 的差异恰为某个极性词对互换（present/absent、anterior/posterior……），
     而没有给出「原样出现在原文里的引文」作依据；
  4. old→new 只是把同一批词换了顺序（整句 notopodium↔neuropodium 互换这类）：引文也不放行——
     两遍检查与复核常在同一处共同出错，且这类改动没有任何词级证据可核，一律转人工；
  5. old→new 是纯增补（只加词、不改不删），且加进去的 ≥ 4 个词的连续片段在该页译文里已原样存在
     （忽略大小写和标点）：模型把没漏的内容当成漏译又补了一遍，落实后同一句话出现两次。
极性词表按语言对放 skill/pitfalls/{sl}-{tl}.polarity.tsv；没有该文件的语言对跳过规则 3。
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

from .languages import LANG, LAT

_REPO = Path(__file__).resolve().parent.parent


def load_polarity(sl: str, tl: str, root: Path | None = None) -> list[tuple[str, str]]:
    """读 skill/pitfalls/{sl}-{tl}.polarity.tsv（安装副本为 pitfalls/）：两列（词 A、词 B），# 开头为注释；文件不存在返回 []。
    root 是含 skill/ 的仓库根（默认本仓库）。"""
    base = root or _REPO
    # 仓库布局 skill/pitfalls/；安装到技能目录后 md/tsv 在根下，pitfalls/ 直接在根
    path = next((p for p in (base / 'skill' / 'pitfalls' / f'{sl}-{tl}.polarity.tsv',
                             base / 'pitfalls' / f'{sl}-{tl}.polarity.tsv') if p.exists()), None)
    if path is None:
        return []
    pairs: list[tuple[str, str]] = []
    for ln in path.read_text(encoding='utf-8').splitlines():
        if not ln.strip() or ln.lstrip().startswith('#'):
            continue
        cols = [c.strip() for c in ln.split('\t')]
        if len(cols) >= 2 and cols[0] and cols[1]:
            pairs.append((cols[0].lower(), cols[1].lower()))
    return pairs


def _words(t: str) -> str:
    """NFKC、小写、空白折叠（比较 old/new 用）。"""
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', t)).strip().lower()


def _squash(t: str) -> str:
    """NFKC 后去掉全部空白（引文是否原样在原文里用）。"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', t))


def _is_polarity_swap(old: str, new: str, polarity: list[tuple[str, str]]) -> bool:
    """old 里的某一处词 A（或 B）换成 B（或 A）后恰好等于 new。"""
    o, n = _words(old), _words(new)
    for x, y in polarity:
        for a, b in ((x, y), (y, x)):
            start = 0
            while (i := o.find(a, start)) != -1:
                if o[:i] + b + o[i + len(a):] == n:
                    return True
                start = i + 1
    return False


def _is_permutation(old: str, new: str) -> bool:
    """old 与 new 的词（按 \\w+ 切）是同一批、顺序不同：纯互换/调序，没有增删改词。"""
    o, n = re.findall(r'\w+', _words(old)), re.findall(r'\w+', _words(new))
    return o != n and sorted(o) == sorted(n)


MIN_DUP_WORDS = 4


def _duplicated_insertion(old: str, new: str, tgt_text: str) -> str:
    """old→new 若是纯增补且增补片段（≥ MIN_DUP_WORDS 词）已在 tgt_text 里，返回该片段；否则 ''。"""
    if not tgt_text:
        return ''
    o, n = re.findall(r'\w+', _words(old)), re.findall(r'\w+', _words(new))
    ops = [op for op in difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes() if op[0] != 'equal']
    if not ops or any(op[0] != 'insert' for op in ops):
        return ''
    page = ' ' + ' '.join(re.findall(r'\w+', _words(tgt_text))) + ' '
    for _, _, _, j1, j2 in ops:
        if j2 - j1 >= MIN_DUP_WORDS and f" {' '.join(n[j1:j2])} " in page:
            return ' '.join(n[j1:j2])
    return ''


def check_edit(old: str, new: str, src_text: str, *, sl: str, tl: str,
               polarity: list[tuple[str, str]], quote: str = '', tgt_text: str = '') -> str | None:
    """返回拒绝原因；通过返回 None。src_text 是该改动所在页的原文，quote 是裁定模型给出的原文引文，
    tgt_text 是该页当前译文（给了才查规则 5）。"""
    if not new.strip():
        return 'new 为空（等于删除）'
    s_lang, t_lang = LANG.get(sl), LANG.get(tl)
    if s_lang and t_lang and t_lang['script'] == LAT and s_lang['script'] != LAT:
        m = re.search(f"[{s_lang['script']}]+", new)
        if m:
            return f'new 含源语言（{sl}）文字「{m.group(0)[:20]}」'
    if _is_permutation(old, new):
        return '改动只是把词互换位置（同一批词换顺序），没有词级证据可核，须人工'
    dup = _duplicated_insertion(old, new, tgt_text)
    if dup:
        return f'增补的内容在该页译文里已有（「{dup[:40]}」），落实后会重复'
    if polarity and _is_polarity_swap(old, new, polarity):
        q = _squash(quote)
        if not q or q not in _squash(src_text):
            return '改动是极性词互换（如 present/absent），但没有原文原样引文作依据'
    return None
