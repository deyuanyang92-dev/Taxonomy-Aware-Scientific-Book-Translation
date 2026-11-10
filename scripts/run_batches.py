#!/usr/bin/env python3
"""与模型无关的批次调度：按 核译/batches.json 渲染 PROMPTS.md 模板 B（核译）或 A（初译），
交给 codex 或 claude 的非交互模式并发执行。闸口仍是 apply_issues.py --dry，与用哪个模型无关。

用法:
  python3 run_batches.py <书> --mode review [--engine codex|claude] [-j 3] [--only b00,b03] [--dry]
  python3 run_batches.py <书> --mode translate --chapters ch05,ch06 [--engine codex]
产物: 核译/prompts/<id>.txt（实际下发的提示词）  核译/logs/<id>.md（模型最后一条消息）
--dry 只写提示词不执行，可人工检查后再跑。先试点 1 批，主线程抽查合格再铺开。"""
import argparse, json, pathlib, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

SK = pathlib.Path(__file__).resolve().parent.parent
S = SK / 'scripts'

DOMAIN = '分类学'


def term_table(src):
    """术语表来自 yiku 术语库；类群取原文前 5 行的 -idae/-ida 名（与旧 term_table.py 相同）。"""
    head = ' '.join(pathlib.Path(src).read_text(encoding='utf8').splitlines()[:5])
    scope = ';'.join(sorted({w.capitalize() for w in re.findall(r'\b([A-Za-z]+(?:idae|ida))\b', head)}))
    cmd = ['yiku', 'table', str(src), '--domain', DOMAIN] + (['--scope', scope] if scope else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else f'（yiku table 失败：{r.stderr.strip()[:200]}）'

def src_path(B, name):
    p = B / 'src_en' / name
    return p if p.suffix == '.txt' else p.with_suffix('.txt')

def review_prompt(B, bid, batch, notes):
    chs = [pathlib.Path(x['src']).stem for x in batch]
    tables = '\n\n'.join(f'### {c}\n' + term_table(src_path(B, c)) for c in chs)
    return f"""工作目录 {B}。不要再派生子代理/子任务。
先读 {SK}/RULES.md、{SK}/domains/{DOMAIN}.md、{SK}/STYLE.md，以及 {SK}/PROMPTS.md 的「核译输出要求」，严格执行。
本批范围：{'、'.join(chs)}。英文 src_en/<章>.txt；中译 译文/<章>*.md（用 ls 确认文件名）。临时脚本放 核译/tmp/{bid}/。
各章术语表（用法见表头；术语按「英文 + 义项」核，见 RULES.md 第 2 节；义项不同或不明的登记 核译/tmp/{bid}/uncertain_terms.tsv）：
{tables}
{notes}
输出：核译/issues/{bid}.jsonl（每核完一节就追加写入）。
结束前运行 python3 {S}/apply_issues.py {B} 核译/issues/{bid}.jsonl --dry，修好所有拒绝行。不要去掉 --dry，不要改译文。
结束前另跑 yiku check src_en/<章>.txt 译文/<章>*.md --domain {DOMAIN}，把术语不一致处并入 JSONL。
最后回复 ≤150 字：各类条数 + 最严重 2–3 处。"""

def translate_prompt(B, ch, notes):
    return f"""工作目录 {B}。不要再派生子代理/子任务。
先读 {SK}/RULES.md、{SK}/domains/{DOMAIN}.md 与 {SK}/STYLE.md，并严格执行。
第一步 术语预扫：通读原文，列出本章术语（含术语表没有的），写入 核译/tmp/{ch}/terms_scan.tsv，列为 English\t义项\t译法\t依据（表中已核/经典译本/暂定）。
第二步 翻译：把 src_en/{ch}.txt 译成中文，写入 译文/{ch}_<中文章名>.md（Markdown：# 章标题，## / ### 小节，图注用 **图 N.N** …）。术语按 terms_scan.tsv。
本章术语表（用法见表头；义项不同或不明的登记到 核译/tmp/{ch}/uncertain_terms.tsv）：
{term_table(src_path(B, ch))}
{notes}
每译完一节就写盘（追加）。不自造科名、属名。
最后回复 ≤150 字。"""

def run(engine, B, pid, prompt_file, log):
    if engine == 'codex':
        cmd = ['codex', 'exec', '-C', str(B), '--skip-git-repo-check', '-s', 'workspace-write',
               '--add-dir', str(SK), '-o', str(log), '-']
        out = None
    else:  # claude -p：只放行读写和 python/grep/ls
        cmd = ['claude', '-p', '--model', 'sonnet', '--allowedTools',
               'Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash(python3:*)', 'Bash(ls:*)', 'Bash(grep:*)',
               'Bash(mkdir:*)', 'Bash(wc:*)', '--add-dir', str(SK)]
        out = open(log, 'w')
    with open(prompt_file) as fin:
        rc = subprocess.run(cmd, stdin=fin, stdout=out or subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=B).returncode
    if out: out.close()
    return pid, rc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('book'); ap.add_argument('--mode', choices=['review', 'translate'], required=True)
    ap.add_argument('--engine', choices=['codex', 'claude'], default='codex')
    ap.add_argument('-j', type=int, default=3); ap.add_argument('--only', default='')
    ap.add_argument('--chapters', default=''); ap.add_argument('--notes', default='',
                    help='附加说明文件（本批已知系统性问题等），内容原样插入提示词')
    ap.add_argument('--domain', default='分类学', help='yiku 领域')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args(); B = pathlib.Path(a.book).resolve()
    global DOMAIN
    DOMAIN = a.domain
    notes = pathlib.Path(a.notes).read_text() if a.notes else ''
    P, L = B / '核译' / 'prompts', B / '核译' / 'logs'
    P.mkdir(parents=True, exist_ok=True); L.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.mode == 'review':
        batches = json.loads((B / '核译' / 'batches.json').read_text())
        only = set(filter(None, a.only.split(',')))
        for i, b in enumerate(batches):
            bid = f'b{i:02d}'
            if not only or bid in only: jobs.append((bid, review_prompt(B, bid, b, notes)))
    else:
        for ch in filter(None, a.chapters.split(',')): jobs.append((ch, translate_prompt(B, ch, notes)))
    if not jobs: sys.exit('没有任务（检查 --only / --chapters）')
    for pid, txt in jobs: (P / f'{pid}.txt').write_text(txt)
    print('提示词已写入', P, '：', ' '.join(p for p, _ in jobs))
    if a.dry: return
    with ThreadPoolExecutor(a.j) as ex:
        futs = [ex.submit(run, a.engine, B, pid, P / f'{pid}.txt', L / f'{pid}.md') for pid, _ in jobs]
        for f in futs:
            pid, rc = f.result(); print(pid, 'OK' if rc == 0 else f'退出码 {rc}', '日志', L / f'{pid}.md')

if __name__ == '__main__':
    main()
