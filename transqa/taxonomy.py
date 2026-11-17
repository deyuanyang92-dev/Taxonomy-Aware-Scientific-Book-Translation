"""分类学插件：学名（按出现顺序与次数）、括号命名人、检索表结构图、图版/图号。接口同 core.check。"""
from __future__ import annotations

import collections
import re
from typing import Any

from .core import clean
from .issue import Issue
from .segments import Segment, by_page

ROMAN = r'[IVXLC]+'
PLATE_RE = re.compile(rf'\b(?:pl|tab|табл|taf|plate|plates|Таблица|Table|Tafel|図版)\.?\s*({ROMAN})\b', re.I)
AUTH_PAREN_RE = re.compile(r'\(([A-Z][\w.\'\- ]+?),?\s(1[5-9]\d\d|20\d\d)\)')


def latin_names(t: str) -> list[str]:
    """提取格式标记中的拉丁双名，避免把独立脚注星号配成超长斜体段。"""
    # OCR 文本常用独立 * 标脚注。只抽取符合属名 + 种加词形式的斜体片段，
    # 不能把 `Genus * 1. ... *Species epithet*` 当成一个跨整段的斜体名称。
    pattern = re.compile(
        r'\*('
        r'(?:[A-Z][a-z]{1,}|[A-Z]\.)\s+'
        r'(?:\([A-Z][a-z]+\)\s+)?'
        r'[a-z][a-z-]*'
        r'(?:\s+(?:subsp\.|var\.|f\.)\s+[a-z][a-z-]*)?'
        r')\*'
    )
    return [re.sub(r'\s+', ' ', m.strip()) for m in pattern.findall(clean(t))]


def key_edges(t: str) -> list[tuple[int, int, str]]:
    """检索表每条：(编号, 对偶编号, 跳转)。跳转 = 行末点线后的数字；以学名/类群结论结尾记为 '-'。"""
    out = []
    for ln in clean(t).split('\n'):
        m = re.match(r'\s*\**(\d+)\s*\((\d+)\)', ln)
        if not m:
            continue
        lead = re.search(r'(?:…+|(?:\.\s*){3,})\s*(\d+)\s*$', ln)
        out.append((int(m.group(1)), int(m.group(2)), lead.group(1) if lead else '-'))
    return out


def key_graph_issues(edges: list[tuple[int, int, str]], page: int, where: str) -> list[Issue]:
    """单份文本内的检索表自洽性：对偶缺失、跳转悬空、环。只报 major（原书本身可能有印刷错误，须与原文比较定性）。"""
    out: list[Issue] = []
    nums = {a for a, _, _ in edges}
    pairs = {(a, b) for a, b, _ in edges}
    for a, b, lead in edges:
        if (b, a) not in pairs:
            out.append(Issue('key.unpaired', 'major', f'p.{page} {where} 检索表 {a}({b}) 无对偶 {b}({a})', page))
        if lead != '-' and int(lead) not in nums and int(lead) > max(nums | {0}):
            pass  # 跳到本页之后的条目（跨页），不判悬空
        elif lead != '-' and int(lead) not in nums:
            out.append(Issue('key.dangling', 'major', f'p.{page} {where} 检索表 {a}({b}) 跳转 {lead} 不存在', page))
    nxt = {a: int(lead) for a, _, lead in edges if lead != '-'}
    for start in nxt:
        seen, cur = set(), start
        while cur in nxt and cur not in seen:
            seen.add(cur)
            cur = nxt[cur]
        if cur in seen:
            out.append(Issue('key.cycle', 'major', f'p.{page} {where} 检索表跳转成环（含 {cur}）', page))
            break
    return out


def check(src: list[Segment], tgt: list[Segment], config: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    sp, tp = by_page(src), by_page(tgt)
    for p in sorted(set(sp) & set(tp)):
        s = '\n\n'.join(x.text for x in sp[p])
        t = '\n\n'.join(x.text for x in tp[p])
        ls, lt = latin_names(s), latin_names(t)
        miss = collections.Counter(ls) - collections.Counter(lt)
        if miss:
            out.append(Issue('taxon.name_missing', 'critical', f'p.{p} 缺学名/斜体 {dict(miss)}', p, evidence=dict(miss)))
        elif ls and [x for x in lt if x in set(ls)] != [x for x in ls if x in set(lt)]:
            out.append(Issue('taxon.name_order', 'minor', f'p.{p} 学名出现顺序与原文不同（可能语序调整，请核）', p))
        auth_s = collections.Counter(AUTH_PAREN_RE.findall(clean(s)))
        auth_t = collections.Counter(AUTH_PAREN_RE.findall(clean(t)))
        if auth_s - auth_t:
            out.append(Issue('taxon.authority_changed', 'critical', f'p.{p} 括号命名人/年份变动 {dict(auth_s - auth_t)}', p))
        ks, kt = key_edges(s), key_edges(t)
        cs = collections.Counter(f'{a}({b})' for a, b, _ in ks)
        ct = collections.Counter(f'{a}({b})' for a, b, _ in kt)
        if cs - ct:
            out.append(Issue('key.couplet_missing', 'critical', f'p.{p} 缺检索表编号 {dict(cs - ct)}', p))
        elif collections.Counter(ks) != collections.Counter(kt):
            out.append(Issue('key.structure', 'critical',
                             f'p.{p} 检索表结构（编号/跳转）与原文不同：缺 {dict(collections.Counter(ks) - collections.Counter(kt))} '
                             f'多 {dict(collections.Counter(kt) - collections.Counter(ks))}', p))
        if kt and collections.Counter(ks) == collections.Counter(kt):
            pass  # 与原文一致：原书自身的对偶/跳转问题不归译文
        elif kt:
            out += key_graph_issues(kt, p, '译文')
        ps_, pt_ = collections.Counter(PLATE_RE.findall(s)), collections.Counter(PLATE_RE.findall(t))
        if ps_ - pt_:
            out.append(Issue('ref.plate_missing', 'major', f'p.{p} 图版号缺失/变动 {dict(ps_ - pt_)}', p))
    return out


def _printed_pages(md: str) -> dict[int, int]:
    out = {}
    for m in re.finditer(r'<!-- PDF p\.(\d+)[^>]*?(?:印刷页|printed p\.)\s*(\d+)', md):
        out[int(m.group(1))] = int(m.group(2))
    return out


def toc_crosscheck(md: str, toc_pages: range | None = None) -> list[Issue]:
    """目录 ↔ 正文标题交叉核对（2026-11-15 Marinov 目录错误后加的自动检查）：
    目录表格里每个带斜体学名的条目，正文须有含同一种加词/属名的标题；属名缩写首字母须与正文全名一致；
    目录页码与正文标题所在印刷页相差 >1 报 major。toc_pages 缺省 = 含「目录/Contents」表格的页。"""
    from .segments import PAGE_RE
    pages: dict[int, str] = {}
    cur = 0
    for ln in md.split('\n'):
        m = PAGE_RE.match(ln)
        if m:
            cur = int(m.group(1))
        pages[cur] = pages.get(cur, '') + ln + '\n'
    printed = _printed_pages(md)
    if toc_pages is None:
        toc_pages = range(0)
        hits = [p for p, t in pages.items() if re.search(r'^\|\s*(?:Contents|目录|Съдържание)\s*\|', t, re.M)]
        if hits:
            toc_pages = range(min(hits), max(hits) + 1)
    heads = [(printed.get(p), re.sub(r'[*#]', '', ln).strip()) for p, t in pages.items() if p not in toc_pages
             for ln in t.split('\n') if ln.startswith('#')]
    out: list[Issue] = []
    for p in toc_pages:
        for ln in pages.get(p, '').split('\n'):
            cells = [c.strip() for c in ln.strip().strip('|').split('|')] if ln.startswith('|') else []
            if len(cells) < 2 or not re.match(r'\d+', cells[-1]):
                continue
            noted = '[TN:' in cells[0]      # 已用译注说明的原书印刷问题：降为 info，不再当错误
            ital = re.findall(r'\*([^*]+)\*', re.sub(r'\[TN:[^\]]*\]', '', cells[0]))
            words = [w for x in ital for w in re.findall(r'[A-Za-z][a-z]+\.?|[A-Z]\.', x)]
            if not words:
                continue
            key = words[-1].rstrip('.')
            cand = [h for h in heads if re.search(rf'\b{re.escape(key)}\b', h[1])]
            if not cand:
                out.append(Issue('toc.no_heading', 'info' if noted else 'major', f'p.{p} 目录条目「{cells[0][:50]}」在正文找不到对应标题', p))
                continue
            page = int(re.match(r'\d+', cells[-1]).group(0))  # type: ignore[union-attr]
            hp = sorted({h[0] for h in cand if h[0]})
            if hp and all(abs(page - x) > 1 for x in hp):
                out.append(Issue('toc.page', 'info' if noted else 'major', f'p.{p} 目录「{cells[0][:40]}」页码 {page}，正文标题在 {hp[:3]}', p))
            ini = re.match(r'([A-Z])[a-z]?\.$', words[0]) if len(words) > 1 else None
            if ini:
                full = {m.group(1) for h in cand for m in re.finditer(rf'\b([A-Z][a-z]+)\s+(?:\([A-Za-z]+\)\s+)?{re.escape(key)}', h[1])}
                if full and all(not f.startswith(ini.group(1)) for f in full):
                    out.append(Issue('toc.genus_initial', 'info' if noted else 'critical',
                                     f'p.{p} 目录「{cells[0][:40]}」属名缩写 {words[0]} 与正文 {sorted(full)} 不符', p))
    return out
