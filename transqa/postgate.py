"""落实后复检与回滚：自动落实改动之后，对被改的页重跑确定性闸口；改动引入阻断问题的页整页撤回。

new_blocking：只返回「落实后出现、落实前没有」的阻断问题（落实前就有的不算这次改动的账）。
rollback：把被点名页里每条已落实改动的 new 换回 old，只动这些页，其余页逐字节不变。
"""
from __future__ import annotations

import re
from typing import Any

from . import check_all
from .issue import Issue

_PAGE = re.compile(r'^\s*<!-- PDF p\.(\d+)\b')


def new_blocking(src_md: str, before_md: str, after_md: str, sl: str, tl: str,
                 pages: set[int]) -> dict[int, list[Issue]]:
    """落实后新增的阻断问题，按页分组，只看 pages 内的页。键为 (code, 页, message)。"""
    old = {(i.code, i.page, i.message) for i in check_all(src_md, before_md, sl, tl)}
    out: dict[int, list[Issue]] = {}
    for i in check_all(src_md, after_md, sl, tl):
        if i.blocking and i.page in pages and (i.code, i.page, i.message) not in old:
            out.setdefault(i.page, []).append(i)
    return out


def _split(md: str) -> list[tuple[int | None, str]]:
    """切成 (页号, 该页原样文字) 的块；首个页标记之前的内容页号为 None。各块用换行连起来即原文。"""
    blocks: list[tuple[int | None, list[str]]] = [(None, [])]
    for ln in md.split('\n'):
        m = _PAGE.match(ln)
        if m:
            blocks.append((int(m.group(1)), []))
        blocks[-1][1].append(ln)
    return [(p, '\n'.join(lines)) for p, lines in blocks if lines]   # 译文以页标记开头时，没有「首页之前」的块


def _join(blocks: list[tuple[int | None, str]]) -> str:
    return '\n'.join(t for _, t in blocks)


def rollback(after_md: str, applied: list[dict[str, Any]], pages: set[int]) -> tuple[str, list[dict[str, Any]]]:
    """撤回 pages 内每条已落实改动（按落实的逆序，把 new 换回 old）。
    new 须在该页恰好出现一次，否则该条保持原样并标 rollback_failed。返回（新译文, 每条结果：
    rolled_back / rollback_failed / kept——页不在 pages 内）。"""
    blocks = _split(after_md)
    results: list[dict[str, Any]] = [dict(e, result='kept') for e in applied]
    for idx in range(len(applied) - 1, -1, -1):
        e = applied[idx]
        try:
            pn = int(e.get('pdf_page', -1))
        except (TypeError, ValueError):
            pn = -1
        if pn not in pages:
            continue
        old, new = str(e.get('old', '')), str(e.get('new', ''))
        for j, (p, text) in enumerate(blocks):
            if p != pn:
                continue
            if new and text.count(new) == 1:
                blocks[j] = (p, text.replace(new, old, 1))
                results[idx] = dict(e, result='rolled_back')
            else:
                results[idx] = dict(e, result='rollback_failed',
                                    reason_failed=f'new 在该页出现 {text.count(new) if new else 0} 次（须恰好 1 次）')
            break
        else:
            results[idx] = dict(e, result='rollback_failed', reason_failed='译文没有该页')
    return _join(blocks), results
