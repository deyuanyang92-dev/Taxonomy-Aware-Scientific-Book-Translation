#!/usr/bin/env python3
"""给 qa_run 的结果按植入清单打分（配合 qa_seed.py）。

用法：python3 scripts/bench/qa_score.py <seeds.json> <qa_run 工作目录> [--json]

匹配规则（严格，按页内位置，不用「±N 字符窗口」）：
  - check_log.jsonl 的条目：页号相同，且 old 在被植入的段落里能找到，位置与植入处（span）有重叠
    （omission 的 span 是删除点：old 须覆盖该点，或从紧接删除点的下一句开头起）→ level=span。
  - qa_align.json 的条目：页号与段序号都相同 → level=para（对齐检测只到段落）；added 且引文能在该段
    找到时按 span 重叠判定。
  - 落实后复检会回滚部分已落实改动：qa_applied.jsonl（若存在）里没有的「applied」条目按转人工计。
状态取最强的一条：applied > queued > rejected。
  detected_any = 任何条目命中（与 spec §4.1 的口径可比，含被复核否决的）；
  surfaced     = applied + queued（真正落到输出里的：自动改了、或到了人工面前）。
落在被植入段落之外的条目是「干净段上」的条目：clean 报自动落实 / 转人工 / 被否决各多少条。
落在被植入段落里、但不在植入处的条目单独记 in_seeded_para_not_span（性质不明，不算命中也不算干净）。
applied_restores：自动落实的改动是否把该段还原成未植入的样子（number/flip/species 对比原段，addition 看
添加的句子是否消失；omission 靠脚本无法判定，记 None，须人读）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

RANK = {'applied': 3, 'queued': 2, 'rejected': 1}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def _norm(t: str) -> str:
    return re.sub(r'\s+', ' ', t or '').strip()


def _status(result: str) -> str:
    r = result or ''
    return 'applied' if r == 'applied' else ('queued' if r.startswith('queued') else 'rejected')


def _overlap(a: int, b: int, lo: int, hi: int) -> bool:
    """[a,b) 与植入处 [lo,hi) 重叠。植入处是点（lo==hi，omission 的删除点）时，点落在句间空格上，
    下一句从 lo+1 开始：补回漏句的改动常从下一句开头起，所以要求 a ≤ lo+1 且 lo ≤ b。"""
    return (a <= lo + 1 and lo <= b) if lo == hi else (a < hi and lo < b)


def _locate(para: str, old: str, span: list[int]) -> str:
    """old 在 para 里的位置与 span 的关系：'span'（重叠）/ 'other'（在段内别处）/ ''（不在该段）。"""
    if not old:
        return ''
    found, start = False, 0
    while (i := para.find(old, start)) >= 0:
        found = True
        if _overlap(i, i + len(old), span[0], span[1]):
            return 'span'
        start = i + 1
    return 'other' if found else ''


def _restores(seed: dict[str, Any], edit: dict[str, Any]) -> bool | None:
    para, kind = seed['new_para'], seed['kind']
    if kind == 'omission':
        return None
    i = para.find(edit.get('old', ''))
    fixed = para[:i] + str(edit.get('new', '')) + para[i + len(edit.get('old', '')):]
    if kind == 'addition':
        return _norm(seed['mut']) not in _norm(fixed)
    return _norm(fixed) == _norm(seed['old_para'])


def score(seeds: list[dict[str, Any]], work: Path) -> dict[str, Any]:
    work = Path(work)
    log = [e for e in _jsonl(work / 'check_log.jsonl') if e.get('old') is not None]
    align = _json(work / 'qa_align.json', [])
    applied_file = work / 'qa_applied.jsonl'
    final_applied = {(str(e.get('pdf_page')), e.get('old'), e.get('new')) for e in _jsonl(applied_file)} \
        if applied_file.exists() else None
    for e in log:
        st = _status(str(e.get('result', '')))
        if st == 'applied' and final_applied is not None \
                and (str(e.get('pdf_page')), e.get('old'), e.get('new')) not in final_applied:
            st = 'queued'                   # 已落实后被落实后复检回滚：最终是转人工
        e['_st'] = st
    by_pp: dict[tuple[int, int], dict[str, Any]] = {(int(s['page']), int(s['para'])): s for s in seeds}
    by_page: dict[int, list[dict[str, Any]]] = {}
    for s in seeds:
        by_page.setdefault(int(s['page']), []).append(s)

    best: dict[int, dict[str, Any]] = {}      # id(seed) → 最强命中
    clean = {'applied': 0, 'queued': 0, 'rejected': 0}
    offspan = {'applied': 0, 'queued': 0, 'rejected': 0}

    def hit(seed: dict[str, Any], st: str, source: str, level: str, edit: dict[str, Any] | None) -> None:
        cur = best.get(id(seed))
        if cur is None or RANK[st] > RANK[cur['status']]:
            best[id(seed)] = {'status': st, 'level': level, 'sources': [source], 'edit': edit}
        elif RANK[st] == RANK[cur['status']] and source not in cur['sources']:
            cur['sources'].append(source)

    for e in log:
        page, st = int(e['pdf_page']) if str(e.get('pdf_page', '')).isdigit() else -1, e['_st']
        rels = [(s, _locate(s['new_para'], str(e.get('old', '')), s['span'])) for s in by_page.get(page, [])]
        spans = [s for s, r in rels if r == 'span']
        if spans:
            for s in spans:
                hit(s, st, 'check', 'span', e)
        elif any(r == 'other' for _, r in rels):
            offspan[st] += 1
        else:
            clean[st] += 1
    for x in align:
        page, para = int(x.get('page', -1)), x.get('para')
        target = by_pp.get((page, para)) if isinstance(para, int) else None
        if target is None:
            clean['queued'] += 1
            continue
        level = 'para'
        if x.get('type') == 'added' and x.get('quote'):
            loc = _locate(target['new_para'], str(x['quote']), target['span'])
            if loc == 'other':
                offspan['queued'] += 1
                continue
            level = 'span' if loc == 'span' else 'para'
        hit(target, 'queued', 'align', level, None)

    kinds = sorted({s['kind'] for s in seeds}, key=lambda k: ['number', 'flip', 'species', 'addition', 'omission'].index(k)
                   if k in ('number', 'flip', 'species', 'addition', 'omission') else 99)
    by_kind: dict[str, dict[str, Any]] = {}
    rows = []
    for s in seeds:
        b = best.get(id(s))
        row = {'kind': s['kind'], 'page': s['page'], 'para': s['para'],
               'status': b['status'] if b else 'missed', 'level': b['level'] if b else '',
               'sources': b['sources'] if b else []}
        if b and b['status'] == 'applied' and b['edit']:
            row['restores'] = _restores(s, b['edit'])
        rows.append(row)
    for k in kinds:
        rs = [r for r in rows if r['kind'] == k]
        c = lambda st: sum(1 for r in rs if r['status'] == st)  # noqa: E731
        by_kind[k] = {'n': len(rs), 'detected_any': len(rs) - c('missed'), 'surfaced': c('applied') + c('queued'),
                      'applied': c('applied'), 'queued': c('queued'), 'rejected_only': c('rejected'),
                      'missed': c('missed'),
                      'applied_restores': (None if k == 'omission'
                                           else sum(1 for r in rs if r['status'] == 'applied' and r.get('restores')))}
    totals = {f: sum(v[f] for v in by_kind.values()) for f in ('n', 'detected_any', 'surfaced', 'applied', 'queued',
                                                              'rejected_only', 'missed')}
    return {'n_seeds': len(seeds), 'by_kind': by_kind, 'totals': totals, 'clean': clean,
            'in_seeded_para_not_span': offspan, 'seeds': rows}


def format_report(r: dict[str, Any]) -> str:
    out = ['kind       n  检出(任何)  落到输出(自动+人工)  自动落实(还原)  转人工  仅被否决  漏']
    for k, v in r['by_kind'].items():
        out.append(f"{k:9} {v['n']:2}  {v['detected_any']:8}  {v['surfaced']:16}  {v['applied']:6}"
                   f"({v['applied_restores'] if v['applied_restores'] is not None else '须人读'})"
                   f"  {v['queued']:5}  {v['rejected_only']:6}  {v['missed']:2}")
    t = r['totals']
    out.append(f"合计      {t['n']:2}  {t['detected_any']:8}  {t['surfaced']:16}  {t['applied']:6}        "
               f"{t['queued']:5}  {t['rejected_only']:6}  {t['missed']:2}")
    c, o = r['clean'], r['in_seeded_para_not_span']
    out.append(f"干净段上的条目：自动落实 {c['applied']}，转人工 {c['queued']}，被否决 {c['rejected']}")
    out.append(f"植入段内但不在植入处：自动落实 {o['applied']}，转人工 {o['queued']}，被否决 {o['rejected']}")
    return '\n'.join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('seeds')
    ap.add_argument('work')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    r = score(json.loads(Path(a.seeds).read_text(encoding='utf-8')), Path(a.work))
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else format_report(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
