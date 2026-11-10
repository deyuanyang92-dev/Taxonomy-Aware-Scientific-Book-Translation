#!/usr/bin/env python3
"""按科（按章）术语表：每章一个类群，汇总 科/亚科名、本章出现的有中文名的属、分科形态术语、
本章出现的通用形态术语、学位论文用法（仅参考）。输出 xlsx（宋体）。
用法: python3 build_family_table.py <书目录> <输出.xlsx>
需要: <书>/src_en/chNN.txt；<书>/术语库/统一/{高阶元_核定,名录_刘瑞玉2008_环节动物,形态术语_分科_候选,形态术语_核定}.tsv；
可选: <书>/术语库/论文术语/*.tsv（English/适用类群/论文中文/论文页 列）"""
import sys, re, csv, glob, pathlib, collections
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

B = pathlib.Path(sys.argv[1]); OUT = sys.argv[2]; U = B / '术语库' / '统一'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig'), delimiter='\t'))

# 章 → 上级类群（用于匹配「适用类群」里写目/亚目的条目）
GROUP = {}
for n in range(5, 27): GROUP[n] = ['Phyllodocida', 'Errantia', 'Aciculata']
for n in range(27, 34): GROUP[n] = ['Eunicida', 'Errantia', 'Aciculata']
for n in range(38, 42): GROUP[n] = ['Sabellida', 'Sedentaria']
for n in range(52, 58): GROUP[n] = ['Terebellida', 'Terebelliformia', 'Sedentaria']
for n in range(59, 65): GROUP[n] = ['Terebellida', 'Cirratuliformia', 'Sedentaria']
for n in (42, 58, 74, 78): GROUP.setdefault(n, []).extend(['Spionida', 'Sedentaria'])
for n in (46, 47, 48, 49, 50, 51, 65, 66, 67, 68): GROUP.setdefault(n, []).append('Sedentaria')

taxa = {}
for r in rd(U / '名录_刘瑞玉2008_环节动物.tsv'): taxa[r['拉丁名']] = (r['中文名'], r['阶元'], r.get('来源', ''))
for r in rd(U / '高阶元_核定.tsv'):
    taxa[r['拉丁名']] = ((r.get('核定中文名') or '').strip(), r.get('阶元', ''), (r.get('依据(书名+页码或URL)') or ''))
fam_morph = rd(U / '形态术语_分科_候选.tsv')
gen_morph = rd(U / '形态术语_核定.tsv')
thesis = []
for p in glob.glob(str(B / '术语库' / '论文术语' / '*.tsv')):
    src = pathlib.Path(p).stem
    for r in rd(p):
        r['_src'] = src; thesis.append(r)

def en_pat(eng):
    alts = [a.strip() for a in re.split(r'[;/]', re.sub(r'\(.*?\)', '', eng)) if len(a.strip()) > 2]
    if not alts: return None
    return re.compile(r'\b(' + '|'.join(re.escape(a) + r'(?:s|es|e|ae|i|a)?' for a in alts) + r')\b', re.I)

def scope_hit(scope, names):
    s = scope or ''
    return any(n and re.search(r'\b' + re.escape(n) + r'\b', s) for n in names)

wb = Workbook(); ws = wb.active; ws.title = '按科总表'
HEAD = ['章', '类群（原书章名）', '类群中文', '类别', '拉丁名/English', '中文', '依据', '状态/备注', '本章次数']
ws.append(HEAD)
F = Font(name='宋体', size=10); FB = Font(name='宋体', size=10, bold=True)
fill = PatternFill('solid', fgColor='DDEBF7')
idx = []
for f in sorted((B / 'src_en').glob('ch*.txt')):
    n = int(re.sub(r'\D', '', f.stem)); t = f.read_text(encoding='utf8')
    if n < 3: continue
    head = next((l for l in t.split('\n')[1:6] if re.search(r'[A-Z]{4,}', l)), f.stem).split()[0].strip(',')
    lat = head.capitalize(); zh = taxa.get(lat, ('',))[0] or '—'
    names = [lat] + GROUP.get(n, [])
    rows = []
    # 1 类群名 + 本章出现的科/亚科/总科
    seen = set()
    for m in re.findall(r'\b([A-Z][a-z]+(?:idae|inae|oidea|ida|iformia|morpha))\b', t):
        if m in seen: continue
        seen.add(m); z, rank, src = taxa.get(m, ('', '', ''))
        if m == lat or t.count(m) >= 2:
            rows.append(('1 类群名', m, z or '—（只用拉丁名）', src[:120], rank, t.count(m)))
    # 2 属名（仅权威名录有中文者）
    for g, (z, rank, src) in taxa.items():
        if rank == '属' and z and re.search(r'\b' + g + r'\b', t):
            rows.append(('2 属名', g, z, src[:60], '', len(re.findall(r'\b' + g + r'\b', t))))
    # 3 分科形态术语
    for r in fam_morph:
        if scope_hit(r['适用类群'], names):
            p = en_pat(r['English']); c = len(p.findall(t)) if p else 0
            rows.append(('3 形态（分科）', r['English'], r['中文'], r['依据'][:200], f"{r['状态']} {r.get('备注','')}".strip(), c))
    # 4 本章出现的通用形态术语
    for r in gen_morph:
        if (r.get('依据(书名+页/URL)') or '').strip() in ('通行', '') or r['English'].lower() in ('clade', 'taxon', 'species', 'genus'): continue
        p = en_pat(r['English'])
        if not p: continue
        c = len(p.findall(t))
        if c >= 2:
            rows.append(('4 形态（通用）', r['English'], r['核定中文'], r['依据(书名+页/URL)'][:120], r.get('说明', '')[:80], c))
    # 5 学位论文用法（仅参考）
    for r in thesis:
        if scope_hit(r.get('适用类群', ''), names):
            rows.append(('5 学位论文（仅参考）', r.get('English', ''), r.get('论文中文', ''), f"{r['_src']} {r.get('论文页','')}",
                         f"{r.get('一致性','')} {r.get('动物志/近海用词','')}".strip()[:120], ''))
    ws.append([f'ch{n:02d}', lat, zh, '', '', '', '', '', ''])
    for c in ws[ws.max_row]: c.font = FB; c.fill = fill
    for k, e, z, src, st, c in sorted(rows, key=lambda x: (x[0], -(x[5] or 0) if isinstance(x[5], int) else 0, x[1].lower())):
        ws.append([f'ch{n:02d}', lat, zh, k, e, z, src, st, c])
    idx.append((f'ch{n:02d}', lat, zh, len(rows)))
for row in ws.iter_rows():
    for c in row:
        if c.font != FB: c.font = F
        c.alignment = Alignment(wrap_text=True, vertical='top')
for col, w in zip('ABCDEFGHI', [6, 18, 14, 14, 26, 22, 50, 30, 7]): ws.column_dimensions[col].width = w
ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
for c in ws[1]: c.font = FB
wi = wb.create_sheet('目录', 0); wi.append(['章', '类群', '中文', '条目数'])
for r in idx: wi.append(list(r))
wi.append([]); wi.append(['说明：类别 1 类群名、2 属名（仅刘瑞玉2008/动物志有中文者，其余属只用拉丁名）、3 分科形态术语、4 本章出现≥2次的通用形态术语、5 学位论文用法（仅供参考，不作依据）。'])
wi.append(['依据优先级：中国动物志 > 杨德渐、孙瑞平1988《中国近海多毛环节动物》 > 刘瑞玉2008名录 > 名词委/图谱 > 学位论文（参考）> 百度百科（线索）。'])
for row in wi.iter_rows():
    for c in row: c.font = F
for col, w in zip('ABCD', [6, 20, 16, 8]): wi.column_dimensions[col].width = w
wb.save(OUT); print('saved', OUT, sum(r[3] for r in idx), 'rows')
