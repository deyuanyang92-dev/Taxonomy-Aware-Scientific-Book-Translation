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


Template = list[tuple[str, str]]   # ('raw', 一行原样) 或 ('seg', 段 ID)


def split_template(md: str) -> tuple[list[Segment], Template]:
    """切段并记录模板：页标记、注释、图版占位、空行原样保留，段的位置记为 ('seg', id)。render() 可原样拼回。
    图版占位行、注释行在段中间出现时也断段，保证源与译切法一致。"""
    out: list[Segment] = []
    tpl: Template = []
    page, n = 0, 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal n
        text = '\n'.join(buf).strip()
        if text:
            n += 1
            sid = f'p{page}_s{n}'
            out.append(Segment(sid, page, text))
            tpl.append(('seg', sid))
        buf.clear()

    for ln in md.split('\n'):
        m = PAGE_RE.match(ln)
        if m:
            flush()
            page, n = int(m.group(1)), 0
            tpl.append(('raw', ln))
        elif not ln.strip() or (ln.lstrip().startswith('<!--') and ln.rstrip().endswith('-->')) or PLACEHOLDER_RE.match(ln):
            flush()
            tpl.append(('raw', ln))
        else:
            buf.append(ln)
    flush()
    return out, tpl


def segments_from_pages(md: str) -> list[Segment]:
    return split_template(md)[0]


def render(tpl: Template, texts: dict[str, str]) -> str:
    """按模板拼回；缺少的段 ID 抛 KeyError（不静默丢段）。"""
    return '\n'.join(texts[x] if kind == 'seg' else x for kind, x in tpl)


def by_page(segs: list[Segment]) -> dict[int, list[Segment]]:
    d: dict[int, list[Segment]] = {}
    for s in segs:
        d.setdefault(s.page, []).append(s)
    return d
