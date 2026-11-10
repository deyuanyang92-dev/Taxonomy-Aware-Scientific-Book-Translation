#!/usr/bin/env python3
"""扫描本 PDF 逐页 RapidOCR，每页一个 txt（已存在则跳过），最后合并 all.txt（含 ==== pNNNN 页标）。
用法: python3 ocr_rapid.py <pdf> <outdir>"""
import sys, os, fitz, tempfile, warnings
warnings.filterwarnings('ignore')
from rapidocr_onnxruntime import RapidOCR
pdf, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
d = fitz.open(pdf); eng = RapidOCR()
tmp = os.path.join(out, '_t.png')
for i in range(d.page_count):
    dst = os.path.join(out, f'p{i+1:04d}.txt')
    if os.path.exists(dst): continue
    d[i].get_pixmap(dpi=200).save(tmp)
    r, _ = eng(tmp)
    open(dst, 'w').write('\n'.join(x[1] for x in (r or [])))
with open(os.path.join(out, 'all.txt'), 'w') as w:
    for i in range(d.page_count):
        w.write(f'\n==== p{i+1:04d}\n' + open(os.path.join(out, f'p{i+1:04d}.txt')).read())
print('done', out, d.page_count)
