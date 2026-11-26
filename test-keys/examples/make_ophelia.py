#!/usr/bin/env python3
"""Ophelia 种-性状矩阵：由本地 14_物种知识库/_index_*.tsv（原始描述/重描述摘录）规范化。
只取索引原文能确定的值；'not stated' -> ? ；无鳃种的鳃相关性状 -> -（不适用）。
排除二手/非原始描述行：cf. limacina (Yang&Sun 1988)、"yangi"(学位论文概念名)。
用法: python3 examples/make_ophelia.py"""
import csv, re
from pathlib import Path
SRC = Path('/mnt/p/粘海蛹新种-宁德合作-2026/00_学习笔记/14_物种知识库')
D = Path(__file__).parent
rows = []
for f in ('_index_a-l.tsv', '_index_m-z.tsv'):
    rows += list(csv.DictReader(open(SRC/f, encoding='utf-8'), delimiter='\t'))
rows = [r for r in rows if not re.search(r'cf\. limacina|yangi', r['species'])]
def first_int(s):
    m = re.search(r'\d+', s); return int(m.group()) if m else None
out = []
for r in rows:
    sp = r['species']; fm = r['formula'].strip(); bs = r['branchia_start'].lower(); fe = r['fenestrations'].lower()
    vg = r['ventral_groove_start'].lower(); dr = r['dorsal_ridges'].lower(); ap = r['anal_papillae'].lower()
    abr = bool(re.match(r'(none|absent)', bs)) or fm.startswith('not applicable') or '(abranchiate)' in fm
    ant = bp = tot = None
    m = re.match(r'^(\d+)a\+(\d+)b(?:\([^)]*\))?\+(\d+)a', fm)
    if m: ant, bp = int(m.group(1)), int(m.group(2)); tot = ant + bp + int(m.group(3))
    m0 = re.match(r'^(\d+)a \(0b\)', fm)
    if m0: tot = int(m0.group(1))
    if ant is None and not abr:
        m = re.match(r'chaetiger (\d+)|setiger (\d+)|segment (\d+)|foot (\d+)|somite (\d+)', bs)
        if m: ant = int([g for g in m.groups() if g][0]) - 1 if False else None
        m = re.match(r'(?:chaetiger|setiger|segment|foot|somite) (\d+)', bs)
        if m and 'inferred' not in bs: ant = int(m.group(1)) - 1
    if abr: gill, ant, bp = 'absent', '-', '-'
    else: gill = 'present' if (bp or re.match(r'(chaetiger|setiger|segment|foot|somite) \d+', bs)) else '?'
    if fe.startswith('n/a') or abr: fen = '-'
    elif fe.startswith(('present', 'yes')): fen = 'present'
    elif re.match(r'(absent|none|not seen|not observed|not certain|no[ (])', fe) and not fe.startswith('not certain'): fen = 'absent'
    else: fen = '?'
    mv = re.match(r'(?:chaetiger|setiger|segment|foot) (\d+)', vg)
    vgs = mv.group(1) if mv else '?'
    drs = 'present' if dr.startswith(('present', 'pair', '4 lateral')) else ('absent' if dr.startswith('absent') else '?')
    if re.search(r'2 (?:large|stout|long|thick|lanceolate|lancet|inferior)?[^+;]*ventral|2 large|two large|2 stout|2 thick|2 long stout|2 lanceolate|2 slightly|2 ventral|ventral: 1', ap) and not re.search(r'no enlarged', ap): av = 'paired enlarged ventral'
    elif re.search(r'no enlarged|equal|10 equal|not stated', ap): av = 'no enlarged ventral pair' if 'no enlarged' in ap or 'equal' in ap else '?'
    else: av = '?'
    if 'ventral: 1' in ap: av = 'single ventral'
    out.append(dict(taxon=sp, chaetigers_before_gills=ant if ant is not None else '?', gill_pairs=bp if bp is not None else '?',
        total_chaetigers=tot if tot is not None else '?', gills=gill, branchial_fenestrations=fen,
        ventral_groove_start_chaetiger=vgs, posterior_dorsal_ridges=drs, anal_ventral_papillae=av))
with open(D/'ophelia_lit_matrix.csv', 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print(len(out), 'taxa')
