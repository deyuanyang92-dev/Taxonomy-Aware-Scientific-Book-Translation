"""把带页标记的 Markdown 切成段：页按 `<!-- PDF p.N ... -->`，段按空行；段 ID = p{页}_s{序号}（从 1 起）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

PAGE_RE = re.compile(r'^\s*<!-- PDF p\.(\d+)\b')
PLACEHOLDER_RE = re.compile(r'^\s*\[\[?(?:PLATE|Plate|图版|Table|Fig)[^\]]*\]\]?\s*$')


@dataclass(frozen=True)
class Segment:
    id: str
    page: int
    text: str


def page_order(md: str) -> list[int]:
    """页标记按出现顺序（含重复）。"""
    return [int(m.group(1)) for ln in md.split('\n') if (m := PAGE_RE.match(ln))]


def segments_from_pages(md: str) -> list[Segment]:
    out: list[Segment] = []
    page, n = 0, 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal n
        text = '\n'.join(buf).strip()
        if text:
            n += 1
            out.append(Segment(f'p{page}_s{n}', page, text))
        buf.clear()

    for ln in md.split('\n'):
        m = PAGE_RE.match(ln)
        if m:
            flush()
            page, n = int(m.group(1)), 0
            continue
        if not ln.strip():
            flush()
            continue
        if ln.lstrip().startswith('<!--') and ln.rstrip().endswith('-->'):
            continue
        if PLACEHOLDER_RE.match(ln):          # 图版占位行（[[PLATE IV]]、[图版：Таблица IV]）不是正文
            continue
        buf.append(ln)
    flush()
    return out


def by_page(segs: list[Segment]) -> dict[int, list[Segment]]:
    d: dict[int, list[Segment]] = {}
    for s in segs:
        d.setdefault(s.page, []).append(s)
    return d
