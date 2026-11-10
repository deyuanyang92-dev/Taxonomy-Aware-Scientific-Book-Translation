#!/usr/bin/env python3
"""核译闸口：把子代理 JSONL 问题清单精确替换进译文，并追加对照报告。
用法: python3 apply_issues.py <书目录> <issues.jsonl> [--dry]
行格式: {"file","old","new","type":"误译|漏译|增译|术语|语序|格式","reason","en"}
闸口: old 在文件中恰好 1 次；old≠new；非 术语/误译/漏译/增译 类不得丢失英文词或数字。"""
import json, re, sys, pathlib, datetime
B = pathlib.Path(sys.argv[1]); path = pathlib.Path(sys.argv[2]); dry = '--dry' in sys.argv
ZH, REPORT = B / '译文', B / '核译' / '核译对照报告.md'
TOKEN = re.compile(r'[A-Za-z][A-Za-z\-]+|\d+(?:\.\d+)?')
ok, bad, rows = 0, [], []
for ln, line in enumerate(path.read_text(encoding='utf8').splitlines(), 1):
    if not line.strip(): continue
    try: it = json.loads(line)
    except Exception as e: bad.append((ln, f'JSON 错: {e}')); continue
    f = ZH / it['file']
    if not f.exists(): bad.append((ln, f'文件不存在 {it["file"]}')); continue
    t = f.read_text(encoding='utf8'); n = t.count(it['old'])
    if n != 1: bad.append((ln, f'{it["file"]} 匹配 {n} 次: {it["old"][:40]}')); continue
    if it['old'] == it['new']: bad.append((ln, '新旧相同')); continue
    lost = set(TOKEN.findall(it['old'])) - set(TOKEN.findall(it['new']))
    if lost and it.get('type') not in ('术语', '误译', '漏译', '增译'):
        bad.append((ln, f'丢失英文/数字 {sorted(lost)[:5]}（type={it.get("type")}）')); continue
    if not dry: f.write_text(t.replace(it['old'], it['new'], 1), encoding='utf8')
    ok += 1; rows.append(it)
if not dry and rows:
    esc = lambda s: s.replace('|', '｜').replace('\n', ' ')
    with REPORT.open('a', encoding='utf8') as w:
        w.write(f'\n## {path.stem}（{datetime.datetime.now():%m-%d %H:%M}，应用 {ok}，拒绝 {len(bad)}）\n\n')
        w.write('| 文件 | 类型 | 原译 | 改为 | 理由 |\n|---|---|---|---|---|\n')
        for it in rows:
            w.write(f'| {it["file"][:6]} | {it.get("type","")} | {esc(it["old"])} | {esc(it["new"])} | {esc(it.get("reason",""))} |\n')
        if bad: w.write('\n拒绝：\n' + ''.join(f'- 行{l}: {m}\n' for l, m in bad))
print(f'应用 {ok}，拒绝 {len(bad)}' + (' (dry)' if dry else ''))
for l, m in bad: print(f'  行{l}: {m}')
