#!/usr/bin/env python3
"""为一章生成注入子代理提示词的术语表（Markdown）。按类群取分科译名：本章类群专条优先，否则用通用条（*）。
用法: python3 term_table.py <src_en/chNN.txt> [--scope Sabellidae;Serpulidae]
未给 --scope 时，取原文前 5 行里出现的 -idae/-ida 名作为本章类群。"""
import re, sys, argparse
from _terms import rows, taxa
ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('--scope', default='')
a = ap.parse_args()
text = open(a.src, encoding='utf8').read().replace('-\n', '')
low = text.lower()
head = ' '.join(text.splitlines()[:5])
scope = {s.strip().capitalize() for s in a.scope.split(';') if s.strip()} or \
        {w.capitalize() for w in re.findall(r'\b([A-Za-z]+(?:idae|ida))\b', head)}
def forms(t):
    t = t.lower(); f = {t, t + 's', t + 'e'}
    for a_, b_ in (('us', 'i'), ('um', 'a'), ('on', 'a'), ('a', 'ae'), ('is', 'es')):
        if t.endswith(a_): f.add(t[: -len(a_)] + b_)
    return f
best = {}
for r in rows('形态术语_分科.tsv'):
    en = r['English'].strip()
    if not any(re.search(r'\b' + re.escape(f) + r'\b', low) for f in forms(en)): continue
    sc = {s.strip() for s in r['适用类群'].split(';')}
    rank = 2 if sc & scope else (1 if '*' in sc else 0)
    if rank and rank >= best.get(en, (0,))[0]: best[en] = (rank, r)
print(f'本章类群：{"、".join(sorted(scope)) or "未识别（用通用条）"}\n')
print('| 英文 | 中文 | 适用 | 状态 |\n|---|---|---|---|')
for en, (_, r) in sorted(best.items()):
    flag = '' if r['状态'] == '已核' else '⚠待核：保持原文词并在 uncertain_terms 记录'
    print(f"| {en} | {r['中文']} | {r['适用类群']} | {r['状态']}{flag} |")
tx = taxa(); hit = []
for la in sorted(set(re.findall(r'\b([A-Z][a-z]+(?:idae|inae|ida|oidea|iformia|morpha))\b', text))):
    if la in tx: hit.append((la, tx[la][0] or '—'))
if hit:
    print('\n| 学名 | 中文名（—=用拉丁名，禁止自造） |\n|---|---|')
    for la, zh in hit: print(f'| {la} | {zh} |')
