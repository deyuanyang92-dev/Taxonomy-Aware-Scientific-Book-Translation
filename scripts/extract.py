#!/usr/bin/env python3
"""PDF 页段 → 纯文本（双栏按「栏→纵坐标」重排，去页眉页脚/水印/孤立页码）。
用法: python3 extract.py <pdf> <起页> <止页> [--head 0.075] [--foot 0.945]
页码为 PDF 物理页（1 起）。输出到 stdout。"""
import re, sys, argparse, fitz
ap = argparse.ArgumentParser()
ap.add_argument('pdf'); ap.add_argument('start', type=int); ap.add_argument('end', type=int)
ap.add_argument('--head', type=float, default=0.075); ap.add_argument('--foot', type=float, default=0.945)
a = ap.parse_args()
NOISE = ('Downloaded from', 'Authenticated', 'Download Date', 'https://doi.org')
def page_text(p):
    W, H = p.rect.width, p.rect.height
    keep = []
    for x0, y0, x1, y1, txt, *_ in p.get_text('blocks'):
        txt = txt.strip()
        if not txt or y0 < H * a.head or y1 > H * a.foot: continue
        if re.fullmatch(r'\d{1,4}', txt) or any(k in txt for k in NOISE): continue
        col = 0 if ((x1 - x0) > W * 0.62 or x0 < W * 0.48) else 1
        keep.append((col, y0, x0, txt))
    keep.sort()
    return '\n'.join(t[3] for t in keep)
d = fitz.open(a.pdf)
out = '\n'.join(page_text(d[i]) for i in range(a.start - 1, a.end))
print(re.sub(r'\n{3,}', '\n\n', out).strip())
