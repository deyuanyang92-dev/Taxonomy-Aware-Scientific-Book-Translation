#!/usr/bin/env python3
"""qa_run 的报告：把各阶段写在工作目录里的产物汇成 qa_report.md。

只读工作目录里已有的文件，缺哪个就写「未运行/无」，不编数字。报告不替人工下「无错」的结论：
覆盖率、各阶段条数、自动落实清单、转人工数、费用对照和已知盲区都是为了让人知道没看到什么。

用法：python3 qa_report.py <工作目录> [状态 ok|budget_exceeded|failed_pages]
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import token_economy as te  # noqa: E402
from auto_translate import DS_PRICE  # noqa: E402

STATUS_TEXT = {
    'ok': '全部阶段完成，无失败页。',
    'budget_exceeded': '预算超限，已停机；下面只含已完成部分。加大 --budget-multiple / --budget-tokens 后在同一工作目录重跑即可续做。',
    'failed_pages': '有失败页或缺页：这些页没有被检测完整，须重跑或人工看。',
}


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def _jsonl(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def _cell(x: Any, limit: int = 200) -> str:
    s = ' '.join(str(x).split()).replace('|', '\\|')
    return s if len(s) <= limit else s[:limit] + '…'


def _pages(v: Any) -> str:
    return ','.join(str(p) for p in v) if isinstance(v, list) else str(v)


def _usage(work: Path) -> dict[str, float] | None:
    """usage.tsv 汇总：调用数、billable（与 token_economy.billable 同口径）、deepseek 估算美元。"""
    uf = work / 'usage.tsv'
    if not uf.exists():
        return None
    calls = billable = 0
    usd = 0.0
    for ln in uf.read_text(encoding='utf-8').splitlines()[1:]:
        f = ln.split('\t')
        if len(f) < 7:
            continue

        def n(i: int, f: list[str] = f) -> int:
            try:
                return int(float(f[i]))
            except ValueError:
                return 0

        calls += 1
        billable += te.billable({'input_tokens': n(3), 'output_tokens': n(4), 'cache_read_tokens': n(5)})
        if f[1].startswith('deepseek'):
            usd += (n(3) * DS_PRICE['in'] + n(5) * DS_PRICE['cache'] + n(4) * DS_PRICE['out']) / 1e6
    return {'calls': calls, 'billable': billable, 'usd': usd}


def _coverage(work: Path, est: dict[str, Any], state: dict[str, Any]) -> list[str]:
    total = est.get('pages')
    failed = _json(work / 'check_failed.json', [])
    a_failed = _json(work / 'qa_align_failed.json', [])
    unconfirmed = _json(work / 'check_unconfirmed.json', [])
    bad_check = {int(p) for x in failed if isinstance(x, dict) for p in x.get('pages', [])}
    bad_align = {int(x['page']) for x in a_failed if isinstance(x, dict) and 'page' in x}
    no_receipt = {int(p) for x in unconfirmed if isinstance(x, dict) for p in x.get('pages', [])} - bad_check
    # 阶段没跑完（预算停机、崩溃）就不会写 check_failed.json / qa_align_failed.json：文件不存在不是「没有失败」，是「没跑」
    check_ran = (work / 'check_failed.json').exists()
    align_ran = (work / 'qa_align_failed.json').exists()
    out = ['## 1 覆盖率', '']
    if isinstance(total, int):
        ran_c = total - len(bad_check) if check_ran else 0
        ran_a = total - len(bad_align) if align_ran else 0
        confirmed = total - len(bad_check) - len(no_receipt) if check_ran else 0
        out.append(f'- 参与页（原文、译文都有且非空）：{total}')
        out.append(f'- 找错与复核已运行：{ran_c} / {total}；段落对齐已覆盖：{ran_a} / {total}')
        if not check_ran or not align_ran:
            out.append('- 注意：' + '、'.join(n for n, ran in (('找错与复核', check_ran), ('段落对齐', align_ran)) if not ran)
                       + '没有跑完（预算停机或中断），上面按 0 页计；重跑续做。')
        out.append(f'- 其中模型给了回执、覆盖已确认：{confirmed} / {total}；'
                   f'回执未确认：{len(no_receipt)} 页（检查已运行，但模型没有逐页回执，覆盖未确证）')
    else:
        out.append('- 页数：未知（没有 qa_estimate.json）')
    if no_receipt:
        out += ['', '**回执未确认的块**', '']
        for x in unconfirmed:
            if isinstance(x, dict):
                out.append(f"- {x.get('chunk', '?')}（p.{_pages(x.get('pages', []))}）：{_cell(x.get('reason', ''))}")
    out += ['', '**失败页（须重跑或人工看）**', '']
    if not failed and not a_failed:
        out.append('- 无')
    for x in failed:
        if isinstance(x, dict):
            out.append(f"- 找错/复核 {x.get('chunk', '?')}（p.{_pages(x.get('pages', []))}）第{x.get('pass', 1)}遍："
                       f"{_cell(x.get('reason', ''))}")
        else:
            out.append(f'- 找错/复核 {_cell(x)}')
    for x in a_failed:
        out.append(f"- 段落对齐 p.{x.get('page', '?')}：{_cell(x.get('reason', ''))}")
    miss_t, miss_s = state.get('missing_in_tgt', []), state.get('missing_in_src', [])
    out += ['', '**缺页（只在一边出现，没有被核对）**', '']
    if not miss_t and not miss_s:
        out.append('- 无')
    if miss_t:
        out.append(f'- 译文缺页：{_pages(miss_t)}')
    if miss_s:
        out.append(f'- 原文缺页（译文多出）：{_pages(miss_s)}')
    return out + ['']


def _stages(work: Path) -> list[str]:
    gate = _json(work / 'qa_issues_input.json', None)
    logs = _jsonl(work / 'check_log.jsonl')
    align = _json(work / 'qa_align.json', None)
    dropped = _json(work / 'qa_align_dropped.json', None)
    post = _json(work / 'qa_postgate.json', None)
    rows: list[tuple[str, str]] = []
    if gate is None:
        rows.append(('确定性闸口（输入译文）', '未运行'))
    else:
        sev = {k: sum(1 for x in gate if x.get('severity') == k) for k in ('critical', 'major', 'minor', 'info')}
        rows.append(('确定性闸口（输入译文）', f"critical {sev['critical']}，major {sev['major']}，minor {sev['minor']}，"
                                         f"info {sev['info']}（qa_issues_input.json）"))
    if logs is None:
        rows.append(('找错与复核', '未运行'))
    else:
        def n(*keys: str) -> int:
            return sum(all(k in str(x.get('result', '')) for k in keys) for x in logs)
        pre, veto, unsure, guard = n('预过滤'), n('第二模型未认可'), n('queued', '没把握'), n('queued', 'GUARDRAIL')
        crit, only, app = n('queued', 'critical'), n('仅第二模型'), n('applied')
        apply_rej = n('rejected') - pre - veto
        rows += [
            ('找错模型提出（两遍合并去重）', str(len(logs) - only)),
            ('预过滤剔除（old 不在页内、无变化等）', str(pre)),
            ('复核 ACCEPT', str(app + crit + guard + apply_rej)),
            ('复核否决（REJECT）', str(veto)),
            ('复核 UNSURE（转人工）', str(unsure)),
            ('落实前护栏拒绝（GUARDRAIL，转人工）', str(guard)),
            ('critical 转人工', str(crit)),
            ('落实时拒绝（apply_edits 闸口）', str(apply_rej)),
            ('自动落实', str(app)),
            ('复核模型另报（转人工）', str(only)),
        ]
    if align is None:
        rows.append(('段落对齐检测', '未运行'))
    else:
        rows.append(('段落对齐检测通过闸口（转人工，不自动改）', str(len(align))))
        rows.append(('段落对齐引文不实被丢弃', str(len(dropped or []))))
    if post is None:
        rows.append(('落实后复检', '未运行'))
    else:
        rolled = sum(1 for x in post if x.get('result') == 'rolled_back')
        rows.append(('落实后复检回滚（POST_GATE，转人工）', str(rolled)))
        failed_rb = sum(1 for x in post if x.get('result') == 'rollback_failed')
        if failed_rb:
            rows.append(('落实后回滚失败（须人工处理）', str(failed_rb)))
    out = ['## 2 各阶段条目数', '', '| 阶段 | 条数 |', '|---|---|']
    out += [f'| {a} | {b} |' for a, b in rows]
    return out + ['']


def _applied(work: Path) -> list[str]:
    rows = _jsonl(work / 'qa_applied.jsonl')
    out = ['## 3 自动落实改动清单', '']
    if rows is None:
        return out + ['未运行到落实阶段（没有 qa_applied.jsonl）。', '']
    if not rows:
        return out + ['无自动落实改动。', '']
    out += ['| 页 | old | new | reason |', '|---|---|---|---|']
    out += [f"| {r.get('pdf_page', '')} | {_cell(r.get('old', ''))} | {_cell(r.get('new', ''))} | "
            f"{_cell(r.get('reason', ''))} |" for r in rows]
    out += ['', '回滚方法：每条把 new 换回 old（交换 old/new 后经 `auto_translate.apply_edits` 或 `apply_issues.py`'
            ' 应用，old 须在该页恰好出现一次）；全部回滚即得到输入译文。', '']
    return out


def _human(work: Path) -> list[str]:
    out = ['## 4 转人工与小样', '']
    path = work / 'qa_sample.csv'
    if not path.exists():
        return out + ['未运行到小样阶段（没有 qa_sample.csv）。', '']
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    q = sum(1 for r in rows if r.get('source') == 'queue')
    s = sum(1 for r in rows if r.get('source') == 'sample')
    out += [f'- 转人工条目：{q}（qa_sample.csv 中 source=queue）',
            f'- 分层随机抽样段：{s}（source=sample）',
            '- 小样按层等量抽取，**不按段数加权**；人工判定后 `python3 scripts/qa_sample.py score qa_sample.csv` '
            '给出的区间估计的是「未进转人工队列的段落」里的残余错误率，不能当作全书的错误率。', '']
    return out


def _cost(work: Path, est: dict[str, Any], state: dict[str, Any]) -> list[str]:
    out = ['## 5 费用：估算与实际', '']
    if est:
        out.append(f"- 估算：{est.get('calls', '?')} 次调用，约 {est.get('billable_tokens', '?')} billable token，"
                   f"约 ${est.get('usd', '?')}；预算上限 {state.get('budget_tokens', est.get('budget_tokens', '?'))} token"
                   f"（估算的 {est.get('multiple', '?')} 倍）")
    else:
        out.append('- 估算：未运行')
    u = _usage(work)
    if u is None:
        out.append('- 实际：没有 usage.tsv（未调用模型，或只用了缓存）')
    else:
        out.append(f"- 实际（usage.tsv）：{u['calls']:.0f} 次调用，{u['billable']:.0f} billable token，"
                   f"约 ${u['usd']:.4f}（deepseek 按闲时价 DS_PRICE 估算）")
    if 'spent_tokens' in state:
        out.append(f"- 本次进程累计 billable：{state['spent_tokens']}")
    return out + ['']


BLIND_SPOTS = [
    '**图版说明里的方位词翻转**（如 `a: anterior dorsal view` 译成 posterior）：40 页植入实验里所有变体都漏掉，'
    '检测模型与对齐检测都不可靠。小样须专门覆盖图版说明。',
    '**长检索表句漏译**（一个偶句很长，中间一段被省略）：同样全部变体漏掉。检索表按偶句人工对照原文。',
    '检出有运行间噪声（同配置两次检出相差约 ±3/28），一次运行没报错不等于没有错；本报告不保证译文无错，只说明哪些被检查过、哪些没有。',
]


def build_report(work: Path, status: str) -> str:
    """生成并写入 work/qa_report.md；返回正文。status ∈ ok / budget_exceeded / failed_pages。"""
    work = Path(work)
    est = _json(work / 'qa_estimate.json', {})
    state = _json(work / 'qa_state.json', {})
    out = ['# 译文质检报告（qa_run）', '', f'状态：{status} —— {STATUS_TEXT.get(status, "")}', '']
    out += _coverage(work, est, state)
    out += _stages(work)
    out += _applied(work)
    out += _human(work)
    out += _cost(work, est, state)
    out += ['## 6 已知盲区', ''] + [f'- {x}' for x in BLIND_SPOTS] + ['']
    text = '\n'.join(out)
    (work / 'qa_report.md').write_text(text, encoding='utf-8')
    return text


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or len(args) > 2:
        sys.exit(__doc__)
    print(build_report(Path(args[0]), args[1] if len(args) > 1 else 'ok'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
