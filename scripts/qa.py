#!/usr/bin/env python3
"""译文确定性检查：残留英文段、星号/中文引号不配对、中文间空格、U+3000、推测语气被译成断言（显然）、recovered→恢复。
用法: python3 qa.py <书目录>"""
import sys, pathlib, re
B = pathlib.Path(sys.argv[1])
for f in sorted((B / '译文').glob('*.md')):
    t = f.read_text(encoding='utf8'); iss = []
    for i, l in enumerate(t.splitlines(), 1):
        if len(re.findall(r'[A-Za-z]', l)) > 150 and len(re.findall(r'[一-鿿]', l)) < 20 and '参考文献' not in l:
            iss.append(f'L{i} 疑似残留英文段')
        if l.count('*') % 2: iss.append(f'L{i} 星号不成对')
        if l.count('“') != l.count('”'): iss.append(f'L{i} 中文引号不配对')
    n = len(re.findall(r'(?<=[一-鿿]) +(?=[一-鿿])', t))
    if n: iss.append(f'中文间空格 {n}')
    if '　' in t: iss.append(f'U+3000 全角空格 {t.count(chr(0x3000))}')
    src = B / 'src_en' / (f.name.split('_')[0] + '.txt')
    if src.exists():
        en = src.read_text(encoding='utf8').lower()
        ap = len(re.findall(r'\bapparent(ly)?\b|\bappears?\b', en)); xr = t.count('显然')
        if xr > 0 and ap >= xr: iss.append(f'「显然」{xr} 处，原文 apparent/appear {ap} 处——逐处核')
        if re.search(r'\brecover', en) and '恢复' in t: iss.append(f'「恢复」{t.count("恢复")} 处，原文有 recovered——系统发育语境应「解析为/得到」')
    if iss: print(f.name, '｜', '；'.join(iss[:8]))
