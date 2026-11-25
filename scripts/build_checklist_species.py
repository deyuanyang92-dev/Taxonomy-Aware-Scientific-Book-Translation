#!/usr/bin/env python3
"""从刘瑞玉2008《中国海洋生物名录》（有文本层 PDF）抽取环节动物（含星虫、螠虫）种级名录。

用法: python3 build_checklist_species.py <名录.pdf> <起页> <止页> <输出.tsv>
  默认页码: 426 477（PDF 页，「中国物种名录上半册.pdf」）
输出列: 名录拉丁名 | 命名人 | 中文名 | 不确定种(*) | 名录所列异名【】 | 属 | 科 | 科中文 | 目 | 来源
规则（用户 2026-11-09）: 名录写法原样保留，不订正拼写、不换现行名；异名匹配另做，见 match 步骤。
"""
import re
import subprocess
import sys

pdf, p0, p1, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]

SP = re.compile(r'^\s*(\d+)\.\s+(\*?)\s*([^\x00-\x7f][^A-Za-z]*?)\s*([A-Z][a-zà-ÿ]+(?:\s+\((?:[A-Z][a-z]+|sensu stricto)\))?\s+(?:cf\.\s+|aff\.\s+)?(?:sp\.|[a-zà-ÿ][a-zà-ÿ\-/]+)(?:\s+(?:var\.|subsp\.|f\.)?\s*(?!group\b)[a-zà-ÿ][a-zà-ÿ\-]+)?(?:\s+group)?)\s+(.*)$')
FAM = re.compile(r'^\s*\(\d+\)\s*(\S+)\s+Family\s+([A-Z][a-z]+)')
GEN = re.compile(r'^\s*\d+\)\s*(\S+)\s+Genus\s+([A-Z][a-z]+)')
ORD = re.compile(r'^\s*(\S+)\s+Order\s+([A-Z]+)')
YEAR = re.compile(r'^(.*?\b1[789]\d\d\)?|.*?\b20[01]\d\)?)')

rows, cur = [], None
fam = famzh = gen = order = ''
started = False
for page in range(p0, p1 + 1):
    txt = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), '-layout', pdf, '-'],
                         capture_output=True, text=True).stdout
    for line in txt.splitlines():
        if 'Phylum ANNELIDA' in line:
            started = True
        if 'Phylum MOLLUSCA' in line:
            started = False
        if not started or not line.strip():
            continue
        if m := ORD.match(line):
            order = m.group(2).capitalize()
            cur = None
            continue
        if m := FAM.match(line):
            famzh, fam = m.group(1), m.group(2)
            cur = None
            continue
        if m := GEN.match(line):
            gen = m.group(2)
            cur = None
            continue
        if m := SP.match(line):
            _, star, zh, latin, rest = m.groups()
            cur = {'latin': re.sub(r'\s+', ' ', latin), 'zh': zh.strip(), 'star': '*' if star else '',
                   'rest': rest, 'gen': gen, 'fam': fam, 'famzh': famzh, 'order': order, 'page': page}
            rows.append(cur)
            continue
        # 续行：只在异名括号未闭合时并入（分布续行不需要）
        if cur and cur['rest'].count('【') > cur['rest'].count('】'):
            cur['rest'] += ' ' + line.strip()

with open(out, 'w', encoding='utf-8') as f:
    f.write('名录拉丁名\t命名人\t中文名\t不确定种(*)\t名录所列异名\t属\t科\t科中文\t目\t来源\n')
    for r in rows:
        rest = r['rest']
        syn = '; '.join(s.strip() for s in re.findall(r'【(.*?)】', rest))
        rest = re.sub(r'【.*?】', '', rest).strip()
        m = YEAR.match(rest)
        author = m.group(1).strip() if m else ''
        f.write('\t'.join([r['latin'], author, r['zh'], r['star'], syn, r['gen'], r['fam'], r['famzh'],
                           r['order'], f'刘瑞玉2008《中国海洋生物名录》PDF第{r["page"]}页']) + '\n')
print(len(rows), 'species ->', out, file=sys.stderr)
