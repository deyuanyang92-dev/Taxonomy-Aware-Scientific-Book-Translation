# -*- coding: utf-8 -*-
"""译文中只写了拉丁名的科级/目级/亚科名，若基准有中文名，则补中文名。

规则（用户 2026-11-09）：
  · 每章首次 → 「中文名（Latin）」；其后 → 「中文名」。
  · 中文名来源：~/.claude/skills/yzz-translate/terms/高阶元_核定.tsv（排除「—」与「推定」）。
  · 讨论名称本身的地方不动：前文含 拼作/拼写/写作/原书作/一名/名称/称作/称之为/命名为/误作/作“ 等，
    或后文紧跟「一名」。标题行不动（章名另行处理）。
用法: python3 脚本/fill_family_names.py [--dry]   报告 → 核译/fill_family_names_report.tsv
"""
import glob, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.expanduser('~/.claude/skills/yzz-translate/terms')
DRY = '--dry' in sys.argv

RANKS = {'科', '亚科', '目', '亚目', '总科', '族'}   # 门、纲、亚纲等高阶元另有译法，不动
allz, names = {}, {}
TENT = set()   # 依 WoRMS/词源暂拟的名称：首现标「暂定名」
# 基准（低→高，后者覆盖）：名录2008 → 近海1988 → 记述该类群的动物志卷 → 高阶元_核定
for fn, zc, rc in [('名录_刘瑞玉2008_环节动物.tsv', 1, 2), ('基准_近海1988.tsv', 2, 3), ('基准_动物志46.tsv', 2, 3),
                   ('基准_动物志54.tsv', 2, 3), ('基准_动物志33.tsv', 2, 3), ('基准_动物志09.tsv', 2, 3)]:
    for line in open(f'{T}/{fn}', encoding='utf-8').read().splitlines()[1:]:
        c = [x.strip() for x in line.split('\t')]
        if len(c) > rc and c[rc] in RANKS and c[zc] and not c[0].endswith('iformia'):
            names[c[0]] = c[zc]
for line in open(f'{T}/高阶元_核定.tsv', encoding='utf-8').read().splitlines()[1:]:
    c = line.split('\t')
    if len(c) < 4 or c[2] in ('', '—') or '推定' in c[3]:
        continue
    allz[c[0]] = c[2]
    if c[3].startswith('暂定'):
        TENT.add(c[0])
    if (c[1] in RANKS or c[1] == '支系') and not c[0].endswith('iformia'):
        names[c[0]] = c[2]
for line in open(f'{T}/名录_刘瑞玉2008_环节动物.tsv', encoding='utf-8').read().splitlines()[1:]:
    c = line.split('\t')
    if len(c) > 2 and c[2] == '科':
        allz.setdefault(c[0], c[1])
# 译文对这些支系另有固定译法（游走类、隐居类、囊吻动物），或只在命名讨论中出现，不补
for k in ('Errantia', 'Sedentaria', 'Scolecida', 'Longosomatidae', 'Longosomidae', 'Hermellidae', 'Amphictenidae',
          'Ariciidae', 'Thelepinae', 'Lopadorhynchidae', 'Sipunculoidea', 'Sipunculida'):
    names.pop(k, None)
# -iformia：译文惯例作「X形类」，X 取同词根科名（Terebelliformia → 蛰龙介科 → 蛰龙介形类）
for line in open(f'{T}/高阶元_核定.tsv', encoding='utf-8').read().splitlines()[1:]:
    lat = line.split('\t')[0]
    if lat.endswith('iformia'):
        fam = allz.get(lat[:-len('iformia')] + 'idae', '')
        if fam.endswith('科'):
            names[lat] = fam[:-1] + '形类'

CUE = re.compile(r'(拼作|拼写|写作|原书作|原文作|一名|名称|称作|称为|称之为|命名为|设立的|误作|作“|作"|而造|拼成)\s*$')
CJK = r'[㐀-鿿\U00020000-\U0002ffff]'
PAT = re.compile(r'(?<![A-Za-z*“"])(' + '|'.join(sorted(map(re.escape, names), key=len, reverse=True)) + r')(?![A-Za-z*”"])')

report = []
for path in sorted(glob.glob(os.path.join(BASE, '译文', '*.md'))):
    fn = os.path.basename(path)
    lines = open(path, encoding='utf-8').read().split('\n')
    seen = set()
    for i, line in enumerate(lines):
        if line.startswith('#'):
            continue
        out, pos = [], 0
        for m in PAT.finditer(line):
            lat = m.group(1); zh = names[lat]
            pre = line[max(0, m.start() - 10):m.start()]
            post = line[m.end():m.end() + 4].lstrip()
            near = line[max(0, m.start() - 15):m.end() + 15]
            if zh in pre or CUE.search(pre) or post.startswith('一名') or not re.search(CJK, near):
                report.append((fn, lat, zh, '跳过', line[max(0, m.start() - 12):m.end() + 6]))
                continue
            in_paren = line[:m.start()].endswith('（') and line[m.end():].startswith(('）', '，', '；'))
            if in_paren:      # 已在括号内：「（Alvinellidae）」→「（阿尔文虫科 Alvinellidae）」，不套括号
                rep = f'{zh} {lat}' if lat not in seen else zh
            else:
                rep = zh if lat in seen else (f'{zh}（{lat}，暂定名）' if lat in TENT else f'{zh}（{lat}）')
            seen.add(lat)
            seg = line[pos:m.start()]
            seg = re.sub(r'(?<=' + CJK + r'|[，。；：、（“])\s+$', '', seg)   # 中文后的空格去掉
            out.append(seg + rep)
            pos = m.end()
            # 中文名后紧跟的空格去掉（「弗毛虫科 与」→「弗毛虫科与」）
            if re.match(r'\s+' + CJK, line[pos:]) or re.match(r'\s+[，。；：、）]', line[pos:]):
                pos += len(line[pos:]) - len(line[pos:].lstrip(' '))
            report.append((fn, lat, zh, '改', line[max(0, m.start() - 12):m.end() + 6]))
        if out:
            lines[i] = ''.join(out) + line[pos:]
    if not DRY:
        open(path, 'w', encoding='utf-8').write('\n'.join(lines))

with open(os.path.join(BASE, '核译', 'fill_family_names_report.tsv'), 'w', encoding='utf-8') as f:
    f.write('文件\t拉丁名\t中文名\t处理\t上下文\n')
    for r in report:
        f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
print(('DRY ' if DRY else '') + f"改 {sum(r[3]=='改' for r in report)}，跳过 {sum(r[3]=='跳过' for r in report)}")
