#!/usr/bin/env python3
"""科名漂移检查：逐章比较英文中拉丁科名次数与译文中对应中文名次数，中文显著多于英文即可疑
（旧脚本连锁替换常见：Orbiniidae↔梯额虫科、Fabriciidae→丝鳃虫科、Glyceridae↔角吻沙蚕科）。
用法: python3 drift_check.py <书目录>"""
import sys, pathlib, re
from _terms import taxa
B = pathlib.Path(sys.argv[1])
pairs = {la: zh for la, (zh, rank, _) in taxa().items() if zh and zh != '—' and zh.endswith('科')}
names = sorted(set(pairs.values()), key=len, reverse=True)
def count_zh(t, z):
    longer = [n for n in names if z in n and n != z]
    return t.count(z) - sum(t.count(n) for n in longer)
for p in sorted((B / 'src_en').glob('*.txt')):
    en = p.read_text(encoding='utf8').replace('-\n', '')
    zh = ''.join(f.read_text(encoding='utf8') for f in (B / '译文').glob(p.stem + '*.md'))
    if not zh: continue
    out = []
    for z in names:
        ne = sum(en.count(la) for la, v in pairs.items() if v == z)
        nz = count_zh(zh, z)
        if nz >= 2 and nz > ne + 1: out.append(f'{z}{nz}>英{ne}')
    if out: print(p.stem, ' '.join(out))
