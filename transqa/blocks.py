"""块类型判定与确定性处理（0 token）。

分类专著里异名录、参考文献、索引行基本由学名、人名、年份、页码组成，不需要机器翻译也不需要大模型：
脚本按转写表、缩写表处理；处理后仍有原文文字残留的，才退回模型。
Marinov 1977 实测（保加利亚文）：异名录 7.0%、文献与索引 6.5%、标题 3.2%、检索表 8.2%、图注 3.7%、自由叙述 71.3%（按字符）。
检索表与图注含描述性文字，照常翻译。
"""
from __future__ import annotations

import collections
import re

from . import languages as L

YEAR = r'(?:1[5-9]\d\d|20\d\d)'
PROTECTED = frozenset({'synonymy', 'reference', 'index'})
KINDS = ('heading', 'key', 'caption', 'synonymy', 'reference', 'index', 'free')

# 各语种常见引文缩写（原文 → 英文）；可由 --abbr 表补充或覆盖
ABBR = {
    'bg': {'стр.': 'p.', 'табл.': 'pl.', 'фиг.': 'fig.', 'сем.': 'fam.', 'и др.': 'et al.'},
    'ru': {'стр.': 'p.', 'с.': 'p.', 'табл.': 'pl.', 'рис.': 'fig.', 'сем.': 'fam.', 'и др.': 'et al.'},
    'uk': {'стор.': 'p.', 'с.': 'p.', 'табл.': 'pl.', 'рис.': 'fig.'},
    'de': {'S.': 'p.', 'Taf.': 'pl.', 'Abb.': 'fig.', 'u.': 'and'},
    'fr': {'pl.': 'pl.', 'fig.': 'fig.'},
    'ja': {'頁': 'p.', '図版': 'pl.', '図': 'fig.'},
}
AND_WORD = {'bg': 'и', 'ru': 'и', 'uk': 'і', 'de': 'und', 'fr': 'et', 'es': 'y', 'it': 'e', 'pt': 'e', 'nl': 'en'}


def _own_ratio(t: str, sl: str) -> float:
    """源语言专属文字在「引文骨架以外」的字母中的占比：先去掉斜体、「作者, 年份」、引文缩写、作者间连词。"""
    i = L.info(sl) if sl else None
    t = re.sub(r'\*[^*\n]+\*', '', t)
    t = re.sub(rf"[^\W\d_][\w'’\-]*(?:\s+(?:и|і|und|et|and|y|e|en)\s+[^\W\d_][\w'’\-]*)?,?\s*{YEAR}", '', t)
    for a in ABBR.get(L.base(sl), {}):
        t = t.replace(a, '')
    letters = re.findall(r'[^\W\d_]', t)
    if not i or not i['own'] or not letters:
        return 0.0
    return sum(1 for ch in letters if re.match(f"[{i['own']}]", ch)) / len(letters)


def classify(text: str, sl: str = '') -> str:
    """块类型。sl 给出时，异名录还要求源语言专属文字占比 < 60%（异名录以拉丁学名、人名为主）。"""
    t = text.strip()
    lines = [x for x in t.split('\n') if x.strip()]
    if len(lines) > 1:   # 连排的文献条目/索引行：≥80% 行是同一受保护类型（其余多为折行）。残留原文的仍会退回模型
        kinds = collections.Counter(classify(x, sl) for x in lines)
        k, n = kinds.most_common(1)[0]
        if k in ('reference', 'index') and n >= 0.8 * len(lines):
            return k
    if t.startswith('#'):
        return 'heading'
    if re.match(r'\**\d+\s*\(\d+\)', t):
        return 'key'
    years = len(re.findall(YEAR, t))
    words = re.findall(r'[^\W\d_]{3,}', re.sub(r'\*[^*\n]+\*', '', t))
    # 文献条目：「姓, 首字母. 年.」开头
    if '\n' not in t and re.match(rf'^[^\W\d_][\w\'\- ]{{1,40}},\s+(?:[^\W\d_]{{1,3}}\.\s*){{1,3}}.*?{YEAR}', t):
        return 'reference'   # 单行「姓, 首字母. 年.」；多行段可能夹叙述，不判文献
    # 异名录：多个年份、分号分隔、普通词很少（以学名、人名、页码为主）
    cites = len(re.findall(rf',\s*{YEAR}', t))                     # 「作者, 年份」
    evidence = '*' in t or re.search(r'(?:\bp|стр|с|S|pp)\.\s*\d', t)  # 斜体学名或页码引注
    if cites >= 2 and t.count(';') >= 1 and evidence and len(words) <= 4 * years and _own_ratio(t, sl) < 0.6:
        return 'synonymy'
    # 索引行：短、以页码数字收尾
    if (len(t) < 80 and re.fullmatch(r"[^\s,]+(?:,\s*[^\s,]+)?,\s*\d+\*?(?:,\s*\d+\*?)*", t)
            and not re.search(rf'{YEAR}\s*$', t)):
        return 'index'   # 「词, [属,] 页码, 页码…」
    if re.search(r'\d[a-zа-я]\s*[—–-]', t):
        return 'caption'
    return 'free'


def deterministic(text: str, sl: str, names: list[tuple[str, str]] | None = None,
                  abbr: dict[str, str] | None = None) -> str:
    """转写表（长的优先，整词）+ 缩写表 + 作者之间的连词。只做确定性替换，不改学名、数字、标点。"""
    out = text
    pairs = sorted(names or [], key=lambda x: -len(x[0]))
    for src, tgt in pairs:
        for variant in re.split(r'\s*/\s*', src):
            v = re.sub(r'（.*?）|\(.*?\)', '', variant).strip()
            if v:
                out = re.sub(rf'(?<![^\W\d_]){re.escape(v)}(?![^\W\d_])', tgt, out)
    table = {**ABBR.get(L.base(sl), {}), **(abbr or {})}
    for a in sorted(table, key=len, reverse=True):
        if table[a] in ('et al.', 'and'):        # 短语：整词替换
            out = re.sub(rf'(?<![^\W\d_]){re.escape(a)}(?![^\W\d_])', table[a], out)
        else:                                    # 引注缩写：只在后跟数字或罗马数字时替换（S. 12 → p. 12；S. latifolia 不动）
            out = re.sub(rf'(?<![^\W\d_]){re.escape(a)}(?=\s*[\dIVXLC])', table[a], out)
    w = AND_WORD.get(L.base(sl))
    if w:
        out = re.sub(rf'(?<=[A-Za-z.]) {w} (?=[A-Z])', ' and ', out)
    return out


def residue_left(text: str, sl: str) -> bool:
    """确定性处理后是否仍有源语言专属文字（≥2 连写；斜体内与 1а 式图注字母不算）。"""
    i = L.info(sl)
    if not i or not i['own']:
        return False
    own = i['own']
    b = re.sub(r'\*[^*\n]+\*|\[TN:[^\]]*\]', '', text)
    b = re.sub(rf'(?<=\d)[{own}](?![{own}])', '', b)
    return bool(re.search(f'[{own}]{{2,}}', b))
