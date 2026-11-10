#!/usr/bin/env python3
"""全书统一已定论术语（规则 TSV：正则\t替换\t依据），结果追加到核译对照报告。
用法: python3 unify.py <书目录> <规则.tsv> [--dry]   —— 全部核译批次结束后再跑。"""
import sys, re, csv, pathlib, collections
B = pathlib.Path(sys.argv[1]); rules = list(csv.DictReader(open(sys.argv[2], encoding='utf8'), delimiter='\t'))
dry = '--dry' in sys.argv; cnt = collections.Counter(); samp = {}
for f in sorted((B / '译文').glob('*.md')):
    t = f.read_text(encoding='utf8'); o = t
    for r in rules:
        for m in list(re.finditer(r['正则'], t))[:1]:
            samp.setdefault(r['正则'], t[max(0, m.start()-12): m.end()+12].replace('\n', ' '))
        t, n = re.subn(r['正则'], r['替换'], t); cnt[r['正则']] += n
    if t != o and not dry: f.write_text(t, encoding='utf8')
if not dry:
    with (B / '核译' / '核译对照报告.md').open('a', encoding='utf8') as w:
        w.write('\n## 全书统一替换\n\n| 规则 | 处数 | 依据 |\n|---|---|---|\n')
        for r in rules: w.write(f"| `{r['正则']}` → `{r['替换']}` | {cnt[r['正则']]} | {r['依据']} |\n")
for r in rules: print(cnt[r['正则']], r['正则'], '｜样例:', samp.get(r['正则'], '-'))
