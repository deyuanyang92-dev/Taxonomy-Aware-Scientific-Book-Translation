#!/usr/bin/env python3
"""与模型无关的批次调度，两种模式。闸口都是 apply_issues.py --dry，与用哪个模型无关。

一、智能体模式（--engine codex|claude，默认 codex）：按 核译/batches.json 渲染 PROMPTS.md 模板 B（核译）或
   A（初译），交给 codex 或 claude 的非交互模式并发执行，模型自己读写文件。
  python3 run_batches.py <书> --mode review [--engine codex|claude] [-j 3] [--only b00,b03] [--dry]
  python3 run_batches.py <书> --mode translate --chapters ch05,ch06 [--engine codex]
  产物: 核译/prompts/<id>.txt（实际下发的提示词）  核译/logs/<id>.md（模型最后一条消息）

二、直调模式（--engine deepseek-flash|deepseek-v4-pro|claude-sonnet|claude-opus）：原文切块（约 9000 字符），
   每块注入 yiku 术语表，经 llm_engines 直接调模型，产物按块写盘、已有则跳过。详见 direct_mode.py。
  python3 run_batches.py <书> --mode translate --chapters ch05 --engine claude-sonnet [--scope Nereididae]
  python3 run_batches.py <书> --mode review    --chapters ch05 --engine deepseek-flash
  python3 run_batches.py <书> --mode final     --chapters body,captions --engine deepseek-flash   # 闸口改完后核合并终稿
  推荐分配：初译 claude-sonnet，核译 deepseek-flash（初译与核译必须是不同模型）。
  每次合并后自动对合并译文跑 yiku check（正文和图注各一章，都跑），报告在 核译/direct/<章>/yiku_check.txt。
  python3 run_batches.py <书> --mode species   --chapters body,captions [--names 种名.tsv] [--dry]   # 种名格式，闸口之后跑
  流程：translate -> review -> apply_issues.py（闸口）-> species -> final -> apply_issues.py。
  python3 run_batches.py <书> --mode split    --chapters body,captions   # 草稿前：src_en 的正文/图注切分检查（不调模型）
  python3 run_batches.py <书> --mode cite     --chapters body,captions   # 终稿后：英文原文 vs 合并译文的引文/图号对照（不调模型）
  split 对 src_en/<正文章>.txt 与 src_en/<图注章>.txt（--chapters 依次给正文章、图注章）跑 split_check.py，报告写 核译/split_check.txt，有可疑段退出码 1。
  cite 对每个 --chapters 章的 src_en/<章>.txt 与 译文/<章>_直译初译.md 合并后跑 cite_diff.py，报告写 核译/cite_diff.tsv
  （已确认噪声放 核译/cite_noise.tsv，可选别名 核译/cite_alias.tsv），有真差异退出码 1。
  species 不调模型：对合并译文 译文/<章>_直译初译.md 按原书页规范有中文名的种（首现「中文（*拉丁*）」，同页再现只写中文；
  页码来自译文里的 <!-- p.N --> 标记；图注类章节每条图注算一个单元），先备份 *.bak-species 再写回，--dry 只报告。

--dry 只写提示词不执行，可人工检查后再跑。先试点 1 批，主线程抽查合格再铺开。"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

SK = pathlib.Path(__file__).resolve().parent.parent
S = SK / 'scripts'
SKD = SK if (SK / 'RULES.md').exists() else SK / 'skill'   # 技能目录副本里 md 在根，仓库里在 skill/

DOMAIN = '分类学'
DIRECT_ENGINES = ('deepseek-flash', 'deepseek-v4-pro', 'claude-sonnet', 'claude-opus')


FALLBACK = None   # yiku --fallback；None = yiku 默认（分类学书回退到进化生物学）


def term_table(src):
    """术语表来自 yiku 术语库；类群取原文前 5 行的 -idae/-ida 名（与旧 term_table.py 相同）。"""
    head = ' '.join(pathlib.Path(src).read_text(encoding='utf8').splitlines()[:5])
    scope = ';'.join(sorted({w.capitalize() for w in re.findall(r'\b([A-Za-z]+(?:idae|ida))\b', head)}))
    cmd = (['yiku', 'table', str(src), '--domain', DOMAIN] + (['--scope', scope] if scope else [])
           + (['--fallback', FALLBACK] if FALLBACK else []))
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else f'（yiku table 失败：{r.stderr.strip()[:200]}）'


def src_path(B, name):
    p = B / 'src_en' / name
    return p if p.suffix == '.txt' else p.with_suffix('.txt')


def review_prompt(B, bid, batch, notes):
    chs = [pathlib.Path(x['src']).stem for x in batch]
    tables = '\n\n'.join(f'### {c}\n' + term_table(src_path(B, c)) for c in chs)
    return f"""工作目录 {B}。不要再派生子代理/子任务。
先读 {SKD}/RULES.md、{SKD}/domains/{DOMAIN}.md、{SKD}/STYLE.md，以及 {SKD}/PROMPTS.md 的「核译输出要求」，严格执行。
本批范围：{'、'.join(chs)}。英文 src_en/<章>.txt；中译 译文/<章>*.md（用 ls 确认文件名）。临时脚本放 核译/tmp/{bid}/。
各章术语表（分 HARD 必用 / SOFT 先判义项再取舍，用法见表头；术语按「英文 + 义项」核，见 RULES.md 第 2 节；SOFT 术语若译文取舍与术语表不符，核对是否有出处、义项是否吻合；义项不同或不明的登记 核译/tmp/{bid}/uncertain_terms.tsv）：
{tables}
{notes}
输出：核译/issues/{bid}.jsonl（每核完一节就追加写入）。
结束前运行 python3 {S}/apply_issues.py {B} 核译/issues/{bid}.jsonl --dry，修好所有拒绝行。不要去掉 --dry，不要改译文。
结束前另跑 yiku check src_en/<章>.txt 译文/<章>*.md --domain {DOMAIN}（若存在 核译/term_decisions.jsonl，加 --decisions 核译/term_decisions.jsonl），把术语不一致处（「提示」不算错误，核对后再定）并入 JSONL。
最后回复 ≤150 字：各类条数 + 最严重 2–3 处。"""


def translate_prompt(B, ch, notes):
    return f"""工作目录 {B}。不要再派生子代理/子任务。
先读 {SKD}/RULES.md、{SKD}/domains/{DOMAIN}.md 与 {SKD}/STYLE.md，并严格执行。
第一步 术语预扫：通读原文，列出本章术语（含术语表没有的），写入 核译/tmp/{ch}/terms_scan.tsv，列为 English\t义项\t译法\t依据（表中已核/经典译本/暂定）。
第二步 翻译：把 src_en/{ch}.txt 译成中文，写入 译文/{ch}_<中文章名>.md（Markdown：# 章标题，## / ### 小节，图注用 **图 N.N** …）。术语按 terms_scan.tsv。
本章术语表（HARD 必用；SOFT 先读「定义/出处语境」判断本章义项再取舍，用法见表头；义项不同或不明的登记到 核译/tmp/{ch}/uncertain_terms.tsv）：
{term_table(src_path(B, ch))}
SOFT 术语的每个取舍，都追加登记到 核译/tmp/{ch}/term_decisions.jsonl，一行一个 JSON：{{"en":…,"zh":…,"sense":义项简述,"reason":理由,"source":依据的术语表来源及页码（没有就写空串，不编造）,"chunk":"{ch}"}}。HARD 术语不用写。
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
    if out:
        out.close()
    return pid, rc


def run_direct(a, B, notes):
    """直调模式：每章切块 -> 术语表 -> llm_engines.call -> 按块写盘 -> 合并。返回进程退出码。"""
    import direct_mode as dm
    import llm_engines
    chapters = [c for c in a.chapters.split(',') if c]
    if not chapters:
        sys.exit('直调模式必须给 --chapters ch05,ch06')
    usage = B / '核译' / 'usage.tsv'
    system = dm.build_system(a.mode, a.domain, a.book_desc, notes)
    code = 0
    for chn in chapters:
        ch = dm.Chapter(B, chn, a.chunk_chars)
        ids = ch.prepare(a.domain, a.scope, fallback=getattr(a, 'fallback', None))
        (ch.dir / f'system_{a.mode}.md').write_text(system, encoding='utf8')
        print(f'{chn}：{len(ids)} 块，系统提示词 {len(system)} 字符 -> {ch.dir}')
        if a.dry:
            continue
        engines_f = ch.dir / 'engines.json'
        used = json.loads(engines_f.read_text()) if engines_f.exists() else {}
        others = [used.get('review'), used.get('final')] if a.mode == 'translate' else [used.get('translate')]
        if a.engine in others and not a.same_engine_ok:
            sys.exit(f'{chn}：初译和核译不能用同一个模型（{a.engine}）；确需如此加 --same-engine-ok')
        used[a.mode] = a.engine
        engines_f.write_text(json.dumps(used, ensure_ascii=False))
        fn = {'translate': dm.run_translate, 'review': dm.run_review, 'final': dm.run_final_review}[a.mode]
        try:
            n, skipped, fails = fn(ch, ids, a.engine, system, llm_engines.call, a.j, usage, a.force)
        except dm.StaleOutputError as exc:
            sys.exit(str(exc))
        print(f'{chn}：完成 {n} 块，跳过 {skipped} 块（已有产物），失败 {len(fails)} 块')
        for f in fails:
            print('  ', f)
        if fails:
            code = 1
        if a.mode == 'translate':
            print(f'{chn}：', dm.merge_translation(ch, ids))
        elif a.mode == 'final':
            ok, bad = dm.merge_final(ch, ids)
            print(f'{chn}：终稿问题单 {ok} 条 -> {ch.final_issues}；拒绝 {bad} 条（见 {ch.dir}/rejected_final.jsonl）')
            print(f'  下一步：python3 {S}/apply_issues.py {B} 核译/issues/{ch.final_issues.name} --dry')
        else:
            ok, bad = dm.merge_review(ch, ids)
            print(f'{chn}：问题单 {ok} 条 -> {ch.issues}；拒绝 {bad} 条（见 {ch.dir}/rejected.jsonl）')
            print(f'  下一步：python3 {S}/apply_issues.py {B} 核译/issues/{ch.issues.name} --dry')
        try:   # 单个核译模型会漏 HARD 术语：每次合并后对合并译文自动跑 yiku check，正文和图注都跑
            print(dm.run_term_check(ch, a.domain, a.scope, getattr(a, 'fallback', None)))
        except RuntimeError as exc:
            print(f'{chn}：术语检查没能运行：{exc}')
            code = 1
    return code


def run_split(a, B):
    """--mode split：草稿前对 src_en 的正文章、图注章跑 split_check（不调模型）。有可疑段退出码 1。"""
    import direct_mode as dm
    import split_check as sc
    chapters = [c for c in a.chapters.split(',') if c]
    if len(chapters) != 2:
        sys.exit('split 模式必须给 --chapters <正文章>,<图注章>（如 body,captions）')
    body, caps = (dm.Chapter(B, c).source for c in chapters)
    for p in (body, caps):
        if not p.exists():
            print(f'找不到原文 {p}')
            return 2
    found = sc.check_text(body.read_text(encoding='utf8'), caps.read_text(encoding='utf8'))
    paths = {'body': body, 'captions': caps}
    lines = [s.line_str(str(paths[s.file])) for s in found]
    (B / '核译').mkdir(parents=True, exist_ok=True)
    (B / '核译' / 'split_check.txt').write_text(''.join(ln + '\n' for ln in lines), encoding='utf8')
    print('\n'.join(lines))
    print(f'切分检查：可疑段 {len(found)} 处 -> 核译/split_check.txt' + ('；请人工核对，必要时把图注残段移入图注后再开始草稿' if found else ''))
    return 1 if found else 0


def run_cite(a, B):
    """--mode cite：终稿后对英文原文与合并译文跑 cite_diff（不调模型）。有真差异退出码 1。"""
    import cite_diff as cd
    import direct_mode as dm
    chapters = [c for c in a.chapters.split(',') if c]
    if not chapters:
        sys.exit('cite 模式必须给 --chapters body,captions')
    en, zh = [], []
    for chn in chapters:
        ch = dm.Chapter(B, chn)
        if not ch.source.exists() or not ch.merged.exists():
            print(f'{chn}：缺 {ch.source if not ch.source.exists() else ch.merged}')
            return 2
        en.append(ch.source.read_text(encoding='utf8'))
        zh.append(ch.merged.read_text(encoding='utf8'))
    d = B / '核译'
    d.mkdir(parents=True, exist_ok=True)
    noise = cd.parse_noise((d / 'cite_noise.tsv').read_text(encoding='utf8')) if (d / 'cite_noise.tsv').exists() else None
    alias = cd.parse_alias((d / 'cite_alias.tsv').read_text(encoding='utf8')) if (d / 'cite_alias.tsv').exists() else None
    rep = cd.compare(en, zh, noise=noise, alias=alias)
    (d / 'cite_diff.tsv').write_text(rep.tsv(), encoding='utf8')
    print(rep.summary())
    for r in rep.rows:
        if r.status == 'real':
            print(f'  [{r.kind}] {r.obj}  英{r.en}/中{r.zh}  {r.verdict}')
    print('报告 核译/cite_diff.tsv')
    return 1 if rep.real else 0


def run_species(a, B):
    """--mode species：对每章合并译文跑 species_format（不调模型）。返回退出码：没有页码标记或取不到名单为 1。"""
    import direct_mode as dm
    import species_format as sf
    chapters = [c for c in a.chapters.split(',') if c]
    if not chapters:
        sys.exit('species 模式必须给 --chapters ch05,captions')
    code = 0
    for chn in chapters:
        ch = dm.Chapter(B, chn)
        if not ch.merged.exists():
            print(f'{chn}：没有合并译文 {ch.merged.name}，跳过')
            code = 1
            continue
        text = ch.merged.read_text(encoding='utf8')
        unit = sf.auto_unit(ch.merged) if getattr(a, 'unit', 'auto') == 'auto' else a.unit
        try:
            names = sf.collect_names(text, a.names, None if a.no_yiku else a.domain)
            known, generic = (set(), set()) if a.no_yiku else sf.yiku_context(names, a.domain)
            src = ch.source.read_text(encoding='utf8') if ch.source.exists() else None   # 核对拉丁名是否在对应原书页出现
            if src is None:
                print(f'{chn}：没有原文 {ch.source}，拉丁名未核对原文')
            new, changes = sf.fix_text(text, names, unit, src=src, known=known, generic=generic)
        except sf.NoPageMarkers:
            print(f'{chn}：译文里没有页码标记 <!-- p.N -->，无法按原书页处理；请用带页码标记的原文重译（见 direct_mode.with_page_markers），'
                  '或确认整篇只算一页后单独跑 species_format.py --unit whole')
            code = 1
            continue
        except (FileNotFoundError, ImportError) as exc:
            print(f'{chn}：取不到 yiku 种名（{exc}）；用 --names 给名单或 --no-yiku')
            code = 1
            continue
        print(f"{chn}：名单 {len(names)} 个种，按{ {'page': '页', 'paragraph': '段（每条图注一个单元）', 'whole': '整篇'}[unit] }，"
              f"待改 {len(changes)} 处")
        for c in changes:
            print('  ' + c.line())
        ch.dir.mkdir(parents=True, exist_ok=True)
        (ch.dir / 'species_format.txt').write_text(''.join(c.line() + '\n' for c in changes), encoding='utf8')
        if changes and not a.dry:
            bak = ch.merged.with_name(ch.merged.name + sf.BACKUP_SUFFIX)
            if not bak.exists():
                bak.write_text(text, encoding='utf8')
            ch.merged.write_text(new, encoding='utf8')
            print(f'  已写回 {ch.merged}（原件备份 {bak.name}）')
    return code


def main():
    ap = argparse.ArgumentParser(description='批次调度：智能体模式（codex/claude）或直调模式（deepseek-*/claude-*），见文件头说明')
    ap.add_argument('book')
    ap.add_argument('--mode', choices=['review', 'translate', 'final', 'species', 'split', 'cite'], required=True,
                    help='translate=初译；review=核译初译原稿；final=核闸口改完后的合并终稿（仅直调模式）；'
                         'species=按原书页规范种名拉丁名（闸口之后跑，不调模型）；'
                         'split=草稿前检查正文/图注切分（--chapters 正文章,图注章）；cite=终稿后对照英文原文与译文的引文和图号（均不调模型）')
    ap.add_argument('--engine', choices=['codex', 'claude', *DIRECT_ENGINES], default='codex',
                    help='codex/claude=智能体模式；deepseek-flash|deepseek-v4-pro|claude-sonnet|claude-opus=直调模式。'
                         '默认分配：初译 claude-sonnet，核译 deepseek-flash（初译与核译必须是不同模型）')
    ap.add_argument('-j', type=int, default=3)
    ap.add_argument('--only', default='')
    ap.add_argument('--chapters', default='')
    ap.add_argument('--notes', default='', help='附加说明文件（本批已知系统性问题等），内容原样插入提示词')
    ap.add_argument('--domain', default='分类学', help='yiku 领域')
    ap.add_argument('--fallback', default=None, help='yiku --fallback 回退领域（逗号/分号分隔，none=不回退）；缺省用 yiku 默认：分类学回退到进化生物学')
    ap.add_argument('--scope', default=None, help='直调模式：yiku --scope 类群（科名，分号分隔）；缺省从原文前 5 行自动取 -idae/-ida')
    ap.add_argument('--chunk-chars', type=int, default=9000, help='直调模式：每块约多少字符')
    ap.add_argument('--book-desc', default='', help='直调模式：写进系统提示词的书目说明，如「（Handbook of Zoology 第4卷 沙蚕科 一章的一部分）」')
    ap.add_argument('--force', action='store_true',
                    help='直调模式：已有产物与当前引擎/系统提示词/术语表不一致时，删掉不一致的块重做（默认报错停下）')
    ap.add_argument('--same-engine-ok', action='store_true', help='直调模式：允许初译与核译用同一模型（默认拒绝）')
    ap.add_argument('--names', default=None, help='species 模式：种名 TSV（拉丁名<TAB>中文名）；与 yiku 的 HARD 种名叠加，TSV 优先')
    ap.add_argument('--no-yiku', action='store_true', help='species 模式：不去 yiku 查 HARD 种名，只用 --names')
    ap.add_argument('--unit', choices=['auto', 'page', 'paragraph', 'whole'], default='auto',
                    help='species 模式：单元＝页（页码标记）/段（每条图注）/整篇；auto＝章名含 caption 或 图注 按段，否则按页')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    B = pathlib.Path(a.book).resolve()
    global DOMAIN, FALLBACK
    DOMAIN = a.domain
    FALLBACK = a.fallback
    notes = pathlib.Path(a.notes).read_text() if a.notes else ''
    if a.mode == 'species':
        sys.exit(run_species(a, B))
    if a.mode == 'split':
        sys.exit(run_split(a, B))
    if a.mode == 'cite':
        sys.exit(run_cite(a, B))
    if a.engine in DIRECT_ENGINES:
        sys.exit(run_direct(a, B, notes))
    if a.mode == 'final':
        sys.exit('--mode final 只支持直调模式（--engine deepseek-flash|deepseek-v4-pro|claude-sonnet|claude-opus）')
    P, L = B / '核译' / 'prompts', B / '核译' / 'logs'
    P.mkdir(parents=True, exist_ok=True)
    L.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.mode == 'review':
        batches = json.loads((B / '核译' / 'batches.json').read_text())
        only = set(filter(None, a.only.split(',')))
        for i, b in enumerate(batches):
            bid = f'b{i:02d}'
            if not only or bid in only:
                jobs.append((bid, review_prompt(B, bid, b, notes)))
    else:
        for ch in filter(None, a.chapters.split(',')):
            jobs.append((ch, translate_prompt(B, ch, notes)))
    if not jobs:
        sys.exit('没有任务（检查 --only / --chapters）')
    for pid, txt in jobs:
        (P / f'{pid}.txt').write_text(txt)
    print('提示词已写入', P, '：', ' '.join(p for p, _ in jobs))
    if a.dry:
        return
    with ThreadPoolExecutor(a.j) as ex:
        futs = [ex.submit(run, a.engine, B, pid, P / f'{pid}.txt', L / f'{pid}.md') for pid, _ in jobs]
        for f in futs:
            pid, rc = f.result()
            print(pid, 'OK' if rc == 0 else f'退出码 {rc}', '日志', L / f'{pid}.md')


if __name__ == '__main__':
    main()
