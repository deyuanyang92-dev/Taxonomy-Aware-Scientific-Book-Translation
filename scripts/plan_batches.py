#!/usr/bin/env python3
"""按英文字符量把章节分批（默认 ~48k/批），写 <书>/核译/batches.json。
用法: python3 plan_batches.py <书目录> [--size 48000]"""
import json, sys, pathlib, argparse
ap = argparse.ArgumentParser(); ap.add_argument('book'); ap.add_argument('--size', type=int, default=48000)
a = ap.parse_args(); B = pathlib.Path(a.book)
items = []
for p in sorted((B / 'src_en').glob('*.txt')):
    zh = sorted(f.name for f in (B / '译文').glob(p.stem + '*.md'))
    items.append({'src': p.name, 'size': p.stat().st_size, 'zh': zh})
batches, cur, sz = [], [], 0
for it in items:
    if cur and sz + it['size'] > a.size: batches.append(cur); cur, sz = [], 0
    cur.append(it); sz += it['size']
if cur: batches.append(cur)
(B / '核译' / 'issues').mkdir(parents=True, exist_ok=True)
(B / '核译' / 'batches.json').write_text(json.dumps(batches, ensure_ascii=False, indent=1))
for i, b in enumerate(batches):
    print(f'b{i:02d}', ' '.join(x['src'] for x in b), sum(x['size'] for x in b))
