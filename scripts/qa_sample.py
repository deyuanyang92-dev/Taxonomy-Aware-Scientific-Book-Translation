#!/usr/bin/env python3
"""人工小样包：把转人工队列和分层抽样段写成一张 CSV，人工填 verdict 后读回算残余错误率。

用法（算分）：python3 scripts/qa_sample.py score <工作目录>/qa_sample.csv
CSV 列：source(queue|sample) page para stratum reason text_src text_tgt verdict note
verdict 由人工填 ok / error / unsure（大小写不论）；unsure 不计入 n；填了别的值会报错，不静默跳过。
只有 source == sample 的行计入残余错误率；queue 行是流程已经点名的疑点，不是估计对象。
编码 utf-8-sig（带 BOM，Excel 直接打开中日文不乱码）。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根：transqa

from transqa import sampling  # noqa: E402
from transqa.aligner import split_paras  # noqa: E402

COLUMNS = ['source', 'page', 'para', 'stratum', 'reason', 'text_src', 'text_tgt', 'verdict', 'note']
VERDICTS = ('ok', 'error', 'unsure')


def _src_text(src_pg: dict[int, str], tgt_pg: dict[int, str], page: int, para: Any) -> str:
    """段数相等时取同下标原文段，否则整页原文（段数不等时下标不可靠）。"""
    sp = split_paras(src_pg.get(page, ''))
    tp = split_paras(tgt_pg.get(page, ''))
    if isinstance(para, int) and len(sp) == len(tp) and 0 <= para < len(sp):
        return sp[para]
    return '\n\n'.join(sp)


def _row(source: str, r: dict[str, Any], src_pg: dict[int, str], tgt_pg: dict[int, str]) -> dict[str, Any]:
    page = int(r.get('page', r.get('pdf_page', 0)) or 0)
    para = r.get('para', '')
    tp = split_paras(tgt_pg.get(page, ''))
    text_tgt = r.get('text') or r.get('text_tgt')
    if not text_tgt:
        text_tgt = tp[para] if isinstance(para, int) and 0 <= para < len(tp) else '\n\n'.join(tp)
    return {'source': source, 'page': page, 'para': para, 'stratum': r.get('stratum', ''),
            'reason': r.get('reason', ''), 'text_src': r.get('text_src') or _src_text(src_pg, tgt_pg, page, para),
            'text_tgt': text_tgt, 'verdict': '', 'note': ''}


def write_package(work: Path, queue_rows: list[dict[str, Any]], sample: list[dict[str, Any]],
                  src_pg: dict[int, str], tgt_pg: dict[int, str]) -> Path:
    """写 work/qa_sample.csv：先转人工队列行，再抽样行。返回路径。"""
    path = Path(work) / 'qa_sample.csv'
    rows = [_row('queue', r, src_pg, tgt_pg) for r in queue_rows] + [_row('sample', r, src_pg, tgt_pg) for r in sample]
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def score_package(path: Path) -> dict[str, Any]:
    """读回 source == sample 且 verdict 已填的行。返回 {n, k_error, rate, wilson, by_stratum, unsure}。"""
    n = k = unsure = 0
    by: dict[str, dict[str, int]] = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for ln, row in enumerate(csv.DictReader(f), start=2):
            if row.get('source') != 'sample':
                continue
            v = (row.get('verdict') or '').strip().lower()
            if not v:
                continue
            if v not in VERDICTS:
                raise ValueError(f'{path} 第 {ln} 行 verdict={row.get("verdict")!r} 不是 ok/error/unsure')
            if v == 'unsure':
                unsure += 1
                continue
            n += 1
            k += v == 'error'
            b = by.setdefault(row.get('stratum') or '', {'n': 0, 'k_error': 0})
            b['n'] += 1
            b['k_error'] += v == 'error'
    return {'n': n, 'k_error': k, 'rate': k / n if n else None, 'wilson': sampling.wilson(k, n),
            'by_stratum': by, 'unsure': unsure}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != 'score':
        sys.exit(__doc__)
    print(json.dumps(score_package(Path(sys.argv[2])), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
