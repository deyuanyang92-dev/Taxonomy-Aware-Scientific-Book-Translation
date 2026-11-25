#!/usr/bin/env python3
"""段落对齐检测阶段：逐页让模型比对原文与译文，找遗漏/凭空添加，引文经脚本核对后才算数。

用法：python3 scripts/qa_align.py <原文.md> <译文.md> -o <工作目录> --sl ja --tl en [--engine deepseek-flash] [--workers 3]
产物（都在工作目录）：
  align/pNNN.json        每页缓存（摘要含引擎、提示词摘要、两边页文字；模型原始输出，闸口每次重算）
  qa_align.json          通过引文闸口的条目（只进人工队列，本阶段不修改译文）
  qa_align_dropped.json  被闸口丢弃的条目及原因
  qa_align_failed.json   未能检测的页：{"page", "reason"}（missing_in_tgt / empty_in_tgt / empty_in_src /
                         parse_failed / 引擎报错文字 / budget_exceeded）
每页至多一次模型调用。预算超限（BudgetExceeded）停下并向上抛，已完成页的产物照常写盘。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根：transqa

import auto_translate as at  # noqa: E402
from token_economy import BudgetExceeded  # noqa: E402
from transqa import aligner  # noqa: E402

DEFAULT_ENGINE = 'deepseek-flash'


def _blank(t: str | None) -> bool:
    return not aligner.split_paras(t or '')


def stage_align(src_pg: dict[int, str], tgt_pg: dict[int, str], work: Path,
                a: argparse.Namespace) -> list[dict[str, Any]]:
    """返回通过闸口的条目（dict 列表）。不修改 src_pg / tgt_pg。"""
    engine = getattr(a, 'engine', DEFAULT_ENGINE)
    if engine in ('auto', '', None):
        engine = DEFAULT_ENGINE
    sl, tl = a.sl, a.tl
    system = aligner.system_prompt(sl, tl)
    failed: list[dict[str, Any]] = []
    todo: list[int] = []
    for p in sorted(src_pg):
        if p not in tgt_pg:
            failed.append({'page': p, 'reason': 'missing_in_tgt'})
        elif _blank(src_pg[p]) and _blank(tgt_pg[p]):
            continue
        elif _blank(tgt_pg[p]):
            failed.append({'page': p, 'reason': 'empty_in_tgt'})
        elif _blank(src_pg[p]):
            failed.append({'page': p, 'reason': 'empty_in_src'})
        else:
            todo.append(p)
    stop = threading.Event()   # 预算超限后，排队中的页不再调用

    def one(p: int) -> tuple[int, dict[str, Any] | None]:
        if stop.is_set():
            return p, None
        src, tgt = src_pg[p], tgt_pg[p]
        dg = at._digest(engine, aligner.PROMPT_DIGEST, sl, tl, src, tgt)
        cpath = work / f'align/p{p:03d}.json'
        rec = at._cached(cpath, dg)
        if rec is None:
            user = aligner.build_user(aligner.split_paras(src), aligner.split_paras(tgt))
            try:
                found, why = at._ask_json_ex(engine, system, user, f'auto/align/p{p:03d}', work)
            except BudgetExceeded:
                stop.set()
                raise
            rec = {'digest': dg, 'engine': engine, 'prompt_digest': aligner.PROMPT_DIGEST, 'page': p,
                   'status': 'ok' if found is not None else 'parse_failed', 'reason': why, 'items': found or []}
            at._write(cpath, json.dumps(rec, ensure_ascii=False, indent=1))
        return p, rec

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    done: set[int] = set()
    budget_err: BudgetExceeded | None = None
    with ThreadPoolExecutor(max_workers=max(1, getattr(a, 'workers', 3))) as ex:
        futs = [ex.submit(one, p) for p in todo]
        for f in futs:
            try:
                p, rec = f.result()
            except BudgetExceeded as exc:
                budget_err = budget_err or exc
                continue
            if rec is None:
                continue
            done.add(p)
            if rec['status'] != 'ok':
                failed.append({'page': p, 'reason': rec.get('reason') or 'parse_failed'})
                continue
            k, d = aligner.gate_items(rec['items'], p, src_pg[p], tgt_pg[p])
            kept += [asdict(x) for x in k]
            dropped += d
    failed += [{'page': p, 'reason': 'budget_exceeded'} for p in todo if p not in done and budget_err]
    failed.sort(key=lambda x: x['page'])
    at._write(work / 'qa_align.json', json.dumps(kept, ensure_ascii=False, indent=1))
    at._write(work / 'qa_align_dropped.json', json.dumps(dropped, ensure_ascii=False, indent=1))
    at._write(work / 'qa_align_failed.json', json.dumps(failed, ensure_ascii=False, indent=1))
    print(f'align pages={len(todo)} kept={len(kept)} dropped={len(dropped)} failed={len(failed)}', flush=True)
    if budget_err:
        raise budget_err
    return kept


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('tgt')
    ap.add_argument('-o', '--work', required=True)
    ap.add_argument('--sl', default='ja')
    ap.add_argument('--tl', default='en')
    ap.add_argument('--engine', default=DEFAULT_ENGINE)
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    stage_align(at.pages(Path(a.src).read_text(encoding='utf-8')), at.pages(Path(a.tgt).read_text(encoding='utf-8')),
                work, a)


if __name__ == '__main__':
    main()
