# -*- coding: utf-8 -*-
"""术语变更影响清单：某个英文术语的译名要改时，列出受影响的章与位置，只重核这些地方
（借鉴 translate-book 的 run_state：术语一变，只重译受影响的分块，不做全书盲目替换）。

对每章：原文出现次数、原文所在行；译文中旧译名出现次数与上下文（看是否与原文次数对得上、有没有同形异义）。
用法: python3 term_impact.py <书目录> "<英文术语>" "<旧译名>" [新译名]
输出: <书>/核译/术语变更/<英文术语>.tsv
"""
import glob, os, re, sys

book, en, old = sys.argv[1], sys.argv[2], sys.argv[3]
new = sys.argv[4] if len(sys.argv) > 4 else ''
pat_en = re.compile(r'\b' + re.escape(en).replace(r'\ ', r'[\s\-]+') + r'(?:s|es|ae|i)?\b', re.I)
out_dir = os.path.join(book, '核译', '术语变更')
os.makedirs(out_dir, exist_ok=True)
rows, tot_en, tot_zh = [], 0, 0
for src in sorted(glob.glob(os.path.join(book, 'src_en', '*.txt'))):
    key = os.path.basename(src)[:-4]
    text = open(src, encoding='utf-8').read().replace('-\n', '')
    n_en = len(pat_en.findall(text))
    zh_files = glob.glob(os.path.join(book, '译文', key + '_*.md')) + glob.glob(os.path.join(book, '译文', key + '[ab]_*.md'))
    if key == 'glossary':
        zh_files = glob.glob(os.path.join(book, '译文', '附录A*.md'))
    zh = '\n'.join(open(f, encoding='utf-8').read() for f in zh_files)
    n_zh = zh.count(old)
    if not n_en and not n_zh:
        continue
    tot_en += n_en
    tot_zh += n_zh
    ctx = [zh[max(0, m.start() - 15):m.end() + 15].replace('\n', ' ') for m in re.finditer(re.escape(old), zh)][:5]
    en_lines = [i for i, l in enumerate(text.split('\n'), 1) if pat_en.search(l)][:10]
    flag = '' if n_en == n_zh else '次数不等，逐条看'
    rows.append((key, n_en, n_zh, flag, ' '.join(map(str, en_lines)), ' ｜ '.join(ctx)))
f = os.path.join(out_dir, re.sub(r'\W+', '_', en) + '.tsv')
with open(f, 'w', encoding='utf-8') as fo:
    fo.write(f'# {en}: {old} → {new or "(未定)"}\n章\t原文次数\t译文旧译名次数\t提示\t原文行号\t译文上下文\n')
    for r in rows:
        fo.write('\t'.join(map(str, r)) + '\n')
print(f'{en}：原文 {tot_en} 次，旧译名「{old}」{tot_zh} 次，涉及 {len(rows)} 章 → {f}')
