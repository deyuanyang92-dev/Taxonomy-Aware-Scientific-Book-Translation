# -*- coding: utf-8 -*-
"""从原书 PDF 抽取参考文献（不翻译），写成 译文/附录C_参考文献.md。

原书 PDF 第 348–585 页是 OUP 网页版导出：每条文献一个文本块，夹有 Google Scholar / WorldCat /
Crossref 等链接块；跨页的条目被拆成两块。做法：
  · 逐块取 span，斜体 span 包成 *…*（种名、刊名斜体保留）；
  · 丢弃链接块与页眉块；
  · 不以「姓, 名缩写」开头的块视为上一条的续文，接到上一条后面。
用法: python3 脚本/extract_refs.py
"""
import os, re
import pymupdf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, '原书', 'Rouse2022_Annelida_专著全本.pdf')
OUT = os.path.join(BASE, '译文', '附录C_参考文献.md')
P0, P1 = 348, 585            # PDF 页码（1 起）

NOISE = re.compile(r'^(Google Scholar|WorldCat|Crossref|Search ADS|PubMed|Google Preview|'
                   r'Annelida|Greg Rouse et al\.|https?://\S+|Published:.*|Online ISBN:.*|Print ISBN:.*|'
                   r'END MATTER|Subject:.*|References\W*|Downloaded from .*|\d+)$')
START = re.compile(r"^(?:[a-z]{1,3} )?[A-ZÀ-ÞĀ-ſ][A-Za-zÀ-ÿĀ-ſ'’\- ]+,\s+[A-ZÀ-ÞĀ-ſ][a-z]?\.")


def block_text(b):
    out = []
    for line in b['lines']:
        for s in line['spans']:
            t = s['text']
            if not t.strip():
                out.append(t)
                continue
            italic = 'Italic' in s['font'] or (s['flags'] & 2)
            out.append(f'*{t.strip()}*' + (' ' if t.endswith(' ') else '') if italic else t)
        out.append(' ')
    t = ''.join(out)
    t = re.sub(r'\*\s*\*', '', t)                 # 相邻斜体合并
    t = re.sub(r'\s+', ' ', t).strip()
    return t


refs = []
d = pymupdf.open(SRC)
for pno in range(P0 - 1, P1):
    for b in d[pno].get_text('dict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE)['blocks']:
        if b['type'] != 0:
            continue
        t = block_text(b)
        t = t.replace('\ufffd', 'ff') if re.match(r'^[A-Z][a-z]+\ufffd', t) else t
        plain = t.replace('*', '').strip()
        if not plain:
            continue
        # 块内可能夹着链接行：逐个去掉
        plain_lines = [l for l in re.split(r'\s{2,}|(?<=\.)\s(?=Google Scholar|WorldCat|Crossref)', plain)]
        if all(NOISE.match(x.strip()) for x in plain_lines if x.strip()):
            continue
        t = re.sub(r'\s*(Google Scholar|WorldCat|Crossref|Search ADS|PubMed|Google Preview|COPAC)\s*', ' ', t).strip()
        if START.match(plain) or not refs:
            refs.append(t)
        else:
            refs[-1] = (refs[-1] + ' ' + t).strip()

def fix_lig(t):
    # PDF 中 ft/ff 连字被抽成 U+FFFD：按词形还原
    t = re.sub(r'(?i)(schri|scha|Ri|Lu|Lo|Dri|Ha|hea|Zei|kra|na|heu|ca|wi)\ufffd', lambda m: m.group(1) + 'ft', t)
    t = t.replace('\ufffd', 'ff')
    for a, b in [('schriff', 'schrift'), ('schaffl', 'schaftl'), ('schaffen', 'schaften'), ('soff', 'soft'),
                 ('shiff', 'shift'), (' affer ', ' after '), ('Affer ', 'After '), ('liff ', 'lift '), ('draff', 'draft')]:
        t = t.replace(a, b)
    return t


refs = [fix_lig(re.sub(r'\s+', ' ', r)) for r in refs if len(r.replace('*', '')) > 15]
with open(OUT, 'w', encoding='utf-8') as f:
    f.write('# 附录 C 参考文献\n\n')
    f.write('> 原书参考文献，照录英文原文，不作翻译。\n\n---\n\n')
    for r in refs:
        f.write(r + '\n\n')
print('条目', len(refs), '→', OUT)
