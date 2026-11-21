#!/usr/bin/env python3
"""全书译文质检（模拟三审三校）：一条命令把译文过一遍，人工只看转人工条目和小样。

用法：
  python3 scripts/qa_run.py <src.md> <tgt.md> -o <工作目录> --sl ja --tl en            # 全流程
  python3 scripts/qa_run.py <src.md> <tgt.md> -o <工作目录> --sl ja --tl en --dry      # 只估算，不调模型

阶段（每阶段完成写 qa_state.json；重跑时已完成的阶段跳过，模型调用另有缓存，中断后不重复花钱）：
  0 估算并启用预算上限（默认估算的 2 倍；--budget-tokens 可直接指定）
  1 确定性闸口 transqa.check_all → qa_issues_input.json（免费）
  2 找错两遍 + judge 复核 + 护栏（auto_translate.stage_check）
  3 段落对齐检测漏译/凭空添加（qa_align.stage_align；只转人工，不自动改）
  4 落实后复检：把已落实改动重放到输入译文得 qa_final.md；新增阻断问题的页整页回滚（POST_GATE）
  5 人工小样包 qa_sample.csv（转人工条目 + 分层随机抽样段）
  6 报告 qa_report.md

只有「复核通过、非 critical、过护栏、过 apply_edits 闸口、过落实后复检」的改动写进 qa_final.md，
逐条列在 qa_applied.jsonl，可交换 old/new 回滚。输入 tgt 从不被覆盖。
退出码：0 全部完成；1 有失败页或缺页；2 预算超限（已完成部分的报告照常生成）。
模型只用 --engine（默认 deepseek-flash，非思考）；DeepSeek 忙时由 llm_engines 自动等待。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根：transqa

import auto_translate as at  # noqa: E402
import qa_align  # noqa: E402
import qa_estimate  # noqa: E402
import qa_report  # noqa: E402
import qa_sample  # noqa: E402
import token_economy as te  # noqa: E402
from transqa import aligner, check_all, guardrails, postgate, sampling  # noqa: E402

STAGES = ('gate', 'check', 'align', 'postgate', 'sample')
# 本流水线自己写的产物：输入或设置变了就移进 stale_<旧摘要前 8 位>/，不删（块缓存 check/ verify/ align/ 自带摘要，保留）
PRODUCTS = ('checked.md', 'human_review_queue.csv', 'check_failed.json', 'check_log.jsonl', 'check_unconfirmed.json',
            'qa_align.json', 'qa_align_dropped.json', 'qa_align_failed.json', 'qa_applied.jsonl', 'qa_final.md',
            'qa_issues.json', 'qa_issues_input.json', 'qa_postgate.json', 'qa_report.md', 'qa_sample.csv')
PASSES = 2


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def _w(path: Path, obj: Any) -> None:
    at._write(path, json.dumps(obj, ensure_ascii=False, indent=1))


def _page_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _para_of(pg: dict[int, str], page: int, needle: str) -> int | None:
    """译文该页里第一个含 needle 的段下标（按 aligner.split_paras 切段，空白不计）。找不到返回 None。"""
    n = ''.join(needle.split())
    if not n:
        return None
    for i, para in enumerate(aligner.split_paras(pg.get(page, ''))):
        if n in ''.join(para.split()):
            return i
    return None


def _failures(work: Path, state: dict[str, Any]) -> bool:
    return bool(_json(work / 'check_failed.json', []) or _json(work / 'qa_align_failed.json', [])
                or state.get('missing_in_tgt') or state.get('missing_in_src'))


# ---------------------------------------------------------------- 阶段
def stage_gate(src_text: str, tgt_text: str, a: argparse.Namespace, work: Path) -> bool:
    issues = check_all(src_text, tgt_text, a.sl, a.tl)
    _w(work / 'qa_issues_input.json', [vars(x) for x in issues])
    return True


def stage_check(src_pg: dict[int, str], tgt_pg: dict[int, str], a: argparse.Namespace, work: Path) -> bool:
    at.stage_check(src_pg, tgt_pg, work, a)
    return not _json(work / 'check_failed.json', [])


def stage_align(src_pg: dict[int, str], tgt_pg: dict[int, str], a: argparse.Namespace, work: Path) -> bool:
    qa_align.stage_align(src_pg, tgt_pg, work, a)
    return not _json(work / 'qa_align_failed.json', [])


def stage_postgate(src_text: str, tgt_text: str, tgt_name: str, a: argparse.Namespace, work: Path) -> bool:
    """把 check_log 里已落实的改动重放到输入译文（只改列出的地方，其余逐字节不变），再复检、必要时回滚。"""
    logged = [x for x in _jsonl(work / 'check_log.jsonl') if x.get('result') == 'applied']
    final, log = at.apply_edits(src_text, tgt_text, logged)
    applied = [x for x in log if x['result'] == 'applied']
    results: list[dict[str, Any]] = []
    for x in log:
        if x['result'] != 'applied':   # 重放被拒：不该发生（check 阶段刚落实过）；不静默，转人工
            results.append(dict(x, result='rollback_failed', gate_reason=f"REAPPLY_FAILED: {x['result']}"))
    if applied:
        changed = {_page_int(e.get('pdf_page')) for e in applied}
        bad = postgate.new_blocking(src_text, tgt_text, final, a.sl, a.tl, changed)
        if bad:
            final, rb = postgate.rollback(final, applied, set(bad))
            for r in rb:
                why = '; '.join(f'{i.code}: {i.message}' for i in bad.get(_page_int(r.get('pdf_page')), []))
                if r['result'] in ('rolled_back', 'rollback_failed'):
                    results.append(dict(r, gate_reason=f'POST_GATE: {why}'))
            applied = [r for r in rb if r['result'] != 'rolled_back']
    at._write(work / 'qa_final.md', final)
    rows = [{'file': tgt_name, 'old': e['old'], 'new': e['new'], 'type': 'auto', 'reason': e.get('reason', ''),
             'pdf_page': e.get('pdf_page'), 'chunk': e.get('chunk', ''), 'severity': e.get('severity', '')}
            for e in applied]
    at._write(work / 'qa_applied.jsonl', ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    _w(work / 'qa_postgate.json', results)
    print(f'postgate applied={len(rows)} rolled_back={sum(r["result"] == "rolled_back" for r in results)}', flush=True)
    return True


def _queue_rows(work: Path, final_pg: dict[int, str]) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    """转人工条目（找错队列 + 对齐 + 落实后回滚），以及它们所在的段（抽样时排除）。"""
    rows: list[dict[str, Any]] = []
    qpath = work / 'human_review_queue.csv'
    if qpath.exists():
        with open(qpath, encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                page = _page_int(r.get('pdf_page'))
                para = _para_of(final_pg, page, r.get('old') or '')
                rows.append({'page': page, 'para': '' if para is None else para,
                             'reason': f"{r.get('severity') or ''} {r.get('old') or ''} → {r.get('new') or ''}; "
                                       f"{r.get('reason') or ''} {r.get('second_model_why') or ''}".strip()})
    for x in _json(work / 'qa_align.json', []):
        rows.append({'page': _page_int(x.get('page')), 'para': x.get('para', ''),
                     'reason': f"ALIGN {x.get('type')}: {x.get('quote')}; {x.get('reason')}"})
    for x in _json(work / 'qa_postgate.json', []):
        page = _page_int(x.get('pdf_page'))
        para = _para_of(final_pg, page, str(x.get('old', '')))
        rows.append({'page': page, 'para': '' if para is None else para,
                     'reason': f"{x.get('gate_reason', 'POST_GATE')}; {x.get('old')} → {x.get('new')}; "
                               f"{x.get('reason', '')}".strip()})
    taken = {(r['page'], r['para']) for r in rows if isinstance(r['para'], int) and r['para'] >= 0}
    return rows, taken


def stage_sample(src_pg: dict[int, str], a: argparse.Namespace, work: Path, per_stratum: int, seed: int) -> bool:
    final_pg = at.pages((work / 'qa_final.md').read_text(encoding='utf-8'))
    queue, taken = _queue_rows(work, final_pg)
    drawn = sampling.draw(sampling.paragraphs(final_pg, a.tl), per_stratum, seed, taken)
    path = qa_sample.write_package(work, queue, drawn, src_pg, final_pg)
    print(f'sample queue={len(queue)} sample={len(drawn)} → {path}', flush=True)
    return True


# ---------------------------------------------------------------- 编排
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('tgt')
    ap.add_argument('-o', '--work', required=True)
    ap.add_argument('--sl', default='ja')
    ap.add_argument('--tl', default='en')
    ap.add_argument('--glossary')
    ap.add_argument('--engine', default='deepseek-flash')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--budget-multiple', type=float, default=qa_estimate.DEFAULT_MULTIPLE,
                    help='预算上限 = 估算 billable token × 此倍数（默认 2.0）')
    ap.add_argument('--budget-tokens', type=int, default=None, help='直接指定预算上限（token），覆盖倍数')
    ap.add_argument('--per-stratum', type=int, default=10, help='小样每层抽样段数')
    ap.add_argument('--seed', type=int, default=1119)
    ap.add_argument('--dry', action='store_true', help='只估算并写 qa_estimate.json，不调用模型')
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    work = Path(args.work)
    tgt_path = Path(args.tgt)
    if tgt_path.resolve() == (work / 'qa_final.md').resolve():
        raise ValueError(f'输入译文就是 {work / "qa_final.md"}：会被覆盖。换一个工作目录再跑。')
    work.mkdir(parents=True, exist_ok=True)
    src_text = Path(args.src).read_text(encoding='utf-8')
    tgt_text = tgt_path.read_text(encoding='utf-8')
    src_all, tgt_all = at.pages(src_text), at.pages(tgt_text)
    common = sorted(set(src_all) & set(tgt_all))
    src_pg, tgt_pg = {p: src_all[p] for p in common}, {p: tgt_all[p] for p in common}

    est = qa_estimate.estimate(src_all, tgt_all, passes=PASSES, align=True, multiple=args.budget_multiple)
    qa_estimate.write_estimate(work, est)
    limit = args.budget_tokens if args.budget_tokens is not None else int(est['billable_tokens'] * args.budget_multiple)
    print(f"estimate pages={est['pages']} calls={est['calls']} billable≈{est['billable_tokens']} "
          f"usd≈{est['usd']} budget_limit={limit}", flush=True)
    if args.dry:
        return 0

    a = argparse.Namespace(sl=args.sl, tl=args.tl, glossary=args.glossary, engine=args.engine, day_engine=None,
                           verify_engine=args.engine, allow_same_verify=True, verify_mode='judge', passes=PASSES,
                           workers=args.workers, no_taxoformat=True, risky_only=False, pitfalls=None,
                           receipt_required=False)
    gl = Path(args.glossary) if args.glossary else None
    gl_hash = hashlib.sha1(gl.read_bytes()).hexdigest() if gl is not None and gl.is_file() else str(args.glossary)
    digest = hashlib.sha1('\x00'.join([
        src_text, tgt_text, args.sl, args.tl, args.engine, gl_hash,      # 术语表看内容，不只看路径
        str(PASSES), at.PROMPT_VERSION, aligner.PROMPT_DIGEST,           # 提示词/遍数/极性词表一变，阶段结果就过期
        repr(guardrails.load_polarity(args.sl, args.tl)),
        str(args.per_stratum), str(args.seed)]).encode()).hexdigest()    # 抽样参数也算：改了要重抽
    state = _json(work / 'qa_state.json', {})
    if state.get('input_digest') != digest:      # 输入或设置变了：旧阶段结果作废，不静默沿用
        _retire_products(work, str(state.get('input_digest') or 'unknown'))
        state = {'input_digest': digest, 'stages': {}}
    state.pop('status', None)                     # 上一轮的结论不得挂在这一轮的（可能中途崩溃的）状态上
    stages: dict[str, bool] = {s: bool(state['stages'].get(s)) for s in STAGES}
    first = next((i for i, s in enumerate(STAGES) if not stages[s]), len(STAGES))
    for s in STAGES[first:]:
        stages[s] = False
    state.update(stages=stages, missing_in_tgt=est['pages_missing_in_tgt'], missing_in_src=est['pages_missing_in_src'])

    _save(work, state, stages)
    te.reset_spent()
    state['budget_tokens'] = qa_estimate.arm_budget(est, multiple=args.budget_multiple,
                                                    override_tokens=args.budget_tokens)
    runners = {
        'gate': lambda: stage_gate(src_text, tgt_text, a, work),
        'check': lambda: stage_check(src_pg, tgt_pg, a, work),
        'align': lambda: stage_align(src_pg, tgt_pg, a, work),
        'postgate': lambda: stage_postgate(src_text, tgt_text, tgt_path.name, a, work),
        'sample': lambda: stage_sample(src_pg, a, work, args.per_stratum, args.seed),
    }
    budget_hit = False
    clean = True      # 前面的阶段都干净完成才记「已完成」：有失败页的阶段下次重跑要重试
    try:
        for s in STAGES[first:]:
            ok = runners[s]()
            stages[s] = bool(ok and clean)
            clean = clean and bool(ok)
            _save(work, state, stages)
    except te.BudgetExceeded as exc:
        budget_hit = True
        print(f'[qa_run] 预算超限，停机：{exc}', flush=True)
    finally:
        state['spent_tokens'] = te.spent()
        te.set_budget(None)
    status = 'budget_exceeded' if budget_hit else ('failed_pages' if _failures(work, state) else 'ok')
    state['status'] = status
    _save(work, state, stages)
    qa_report.build_report(work, status)
    print(f'[qa_run] {status}；报告 {work / "qa_report.md"}', flush=True)
    return {'ok': 0, 'failed_pages': 1, 'budget_exceeded': 2}[status]


def _retire_products(work: Path, old_digest: str) -> None:
    """把上一输入/设置留下的产物移进 stale_<摘要前 8 位>/（不删）。"""
    old = [work / n for n in PRODUCTS if (work / n).exists()]
    if not old:
        return
    dest = work / f'stale_{old_digest[:8]}'
    dest.mkdir(exist_ok=True)
    for p in old:
        p.replace(dest / p.name)


def _save(work: Path, state: dict[str, Any], stages: dict[str, bool]) -> None:
    state['stages'] = dict(stages)
    state['spent_tokens'] = te.spent()
    _w(work / 'qa_state.json', state)


if __name__ == '__main__':
    raise SystemExit(main())
