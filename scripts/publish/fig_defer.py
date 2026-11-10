# -*- coding: utf-8 -*-
"""插图「浮动」第二遍：量 Word 渲染 PDF 中每幅图之前的页底空白，
把应推迟的正文字数写入 _fig_defer.json，build_docx.py 下一遍据此把图放到后面几段之后，
让正文先填满空白、图落到下一页页首（学原书排法）。可多轮迭代，推迟量累加。

用法: python3 脚本/fig_defer.py <渲染出的.pdf>
"""
import json, os, re, sys
import pymupdf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JF = os.path.join(BASE, '_fig_defer.json')
LINE_PT = 10.5 * 1.45          # 正文行高
CHARS_PER_LINE = 40            # 15 cm 版心、10.5 pt 宋体约 40 字
MIN_GAP = 0.12                 # 页底空白超过版心 12% 才处理

d = pymupdf.open(sys.argv[1])
H = d[0].rect.height
TOP, BOT = 70, H - 75
defer = json.load(open(JF, encoding='utf-8')) if os.path.exists(JF) else {}
changed = 0
for i in range(1, len(d)):
    page = d[i]
    blocks = [b for b in page.get_text('dict')['blocks'] if TOP < b['bbox'][1] < BOT]
    if not blocks:
        continue
    first = min(blocks, key=lambda b: b['bbox'][1])
    if first['type'] != 1:          # 本页不是以图开头
        continue
    cap = page.get_text(clip=pymupdf.Rect(0, first['bbox'][3], page.rect.width, first['bbox'][3] + 40))
    m = re.search(r'图\s*(\d+\.\d+)', cap)
    if not m:
        continue
    prev = [b for b in d[i - 1].get_text('dict')['blocks'] if TOP < b['bbox'][1] < BOT]
    if not prev or re.search(r'^第 \d+ 章', page.get_text(), re.M):
        continue
    gap = BOT - max(b['bbox'][3] for b in prev)
    if gap < (BOT - TOP) * MIN_GAP:
        continue
    chars = int(gap / LINE_PT * CHARS_PER_LINE * 0.9)
    lab = m.group(1)
    defer[lab] = defer.get(lab, 0) + chars
    changed += 1
json.dump(defer, open(JF, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'本轮调整 {changed} 幅图；累计 {len(defer)} 幅有推迟量 → {os.path.basename(JF)}')
