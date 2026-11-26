#!/usr/bin/env python3
"""Ophelia：矩阵 -> judge（数据+文献证据）-> 建表 -> 审计；对照『不判断、全性状』基线。"""
import json, sys
from pathlib import Path
D = Path(__file__).parent
sys.path.insert(0, str(D.parent))
from keykit.audit import audit_pairs
from keykit.build import build, leaves
from keykit.judge import apply, judge, load_evidence, report_md
from keykit.tabkey import encode, load_table, render_key
rows = load_table(D/'ophelia_lit_matrix.csv')
res = encode(rows)
m = res.matrix
js = judge(m, load_evidence(D/'ophelia_evidence.csv'))
use = apply(m, js)
(D/'ophelia_judge_report.md').write_text(report_md(js), encoding='utf-8')
def tiers(chars):
    a = audit_pairs(m, chars)
    return {k: sum(1 for x in a if x.tier == k) for k in ('separated', 'evidence_gap', 'matrix_silent')}, len(a)
from keykit.matrix import UNKNOWN, INAPPLICABLE, Matrix
poor = [i for i, t in enumerate(m.taxa) if sum(1 for c in use if m.value(i, c) not in (UNKNOWN, INAPPLICABLE)) <= 1]
print('资料不足、不进检索表（可用性状已知值 <=1）:', [m.taxa[i].name for i in poor])
keep = [i for i in range(len(m.taxa)) if i not in poor]
m = Matrix(m.characters, [m.taxa[i] for i in keep])
tree = build(m, chars=use, unknown_all=True)
lv = leaves(tree)
from keykit.tabkey import publish
rc = publish(m, tree, D/'ophelia_judged', 'Key to species of *Ophelia* (taxa listed together could not be separated with the available data)')
print('publish exit code:', rc)  # 写 ophelia_judged.key.txt/.docx/.pdf/.report.json
base = build(m, unknown_all=True)
print('excluded by encode:', res.excluded)
for j in js: print(f'{j.name:34s} {j.verdict:8s} r={j.reliability:<5} cov={j.coverage:.0%} sep={j.sep_pairs} uniq={j.unique_pairs}')
print('judge use:', [m.characters[c].name for c in use])
print('judged   tiers', tiers(use), 'unresolved', sum(1 for t, _ in lv if len(t) > 1))
print('baseline tiers', tiers(None), 'unresolved', sum(1 for t, _ in leaves(base) if len(t) > 1))
print('baseline chars used:', sorted({m.characters[c].name for _, p in leaves(base) for c, _s in p}))
