"""transqa：译文质量检查的共用层（architecture.md §5）。通用检查 core + 领域插件（taxonomy）。

    from transqa import check_all
    issues = check_all(src_md, tgt_md, 'bg', 'en')      # list[Issue]，blocking = critical/major
"""
from __future__ import annotations

from . import core, taxonomy
from .issue import BLOCKING, Issue
from .segments import Segment, page_order, segments_from_pages

PLUGINS = {'taxonomy': taxonomy.check}


def check_all(src_md: str, tgt_md: str, sl: str, tl: str, domain: str | None = 'taxonomy',
              bad_terms: list[str] | None = None) -> list[Issue]:
    src, tgt = segments_from_pages(src_md), segments_from_pages(tgt_md)
    cfg = {'sl': sl, 'tl': tl, 'bad_terms': bad_terms or [], 'src_order': page_order(src_md),
           'tgt_order': page_order(tgt_md)}
    out = core.check(src, tgt, cfg)
    if domain:
        out += PLUGINS[domain](src, tgt, cfg)
    return out


__all__ = ['BLOCKING', 'Issue', 'Segment', 'check_all', 'page_order', 'segments_from_pages']
