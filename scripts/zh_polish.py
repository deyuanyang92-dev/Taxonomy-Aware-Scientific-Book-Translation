#!/usr/bin/env python3
"""中文译文润色（专业书籍）：只把「翻译腔」超标的叙述段送模型，按本土中文习惯改写；事实一律不动。

    python3 zh_polish.py 译文.md -o WORK [--engine auto|codex-sol|deepseek-flash] [--verify-engine auto|cursor-composer|codex-sol]
                         [--threshold 1.0] [--dry]
默认润色 codex-sol、核对 cursor-composer（试点依据见 docs/zh_style_evidence.md §6–7）。

依据：transqa/zh_style.py 文首与 docs/zh_style_evidence.md（本土教科书、本土论述文、名家中译本与我方译稿的逐项计数）。
我方译稿的问题是句子切得太碎、「该/以及/然而/被/关于/其」欧化，而不是「的」多——所以不删「的」，改的是这些。

流程
1 切段（transqa 段 ID，页标记与图版行原样保留）；只取叙述段（检索表、标题、异名录、图注不润色：
  志书与检索表的电报体是规范写法）。
2 段落翻译腔得分 ≥ 阈值的才送模型（省 token）；system = 润色规则 + 本土范文（整本书不变，前缀缓存）。
3 模型按段 ID 返回改写；脚本闸口与第二模型（意思等价核对）都通过才替换，否则保留原文：
  - ASCII 串（学名、人名、年份、数字、图号、引文）与斜体内容逐项相同；
  - 否定词（不/无/未/非/没）、限定语（可能/或许/似/约/通常/一般/多/少数/仅/偶）数量不减少；
  - 引号数量、范围词（任何/所有/均…）、时间词（此后/最初/仍…）不减少；
  - 汉字数在原文 80%–125% 之间；翻译腔得分不升高；
  - 第二模型（默认 codex-sol，与润色模型不同）逐段判定意思等价；有疑问即不替换。
  依据：2026-11-15 盲评 7 段，润色稿 7/7 更自然，但 3 段有细微意思漂移（指代、「此后」、「任何」→「甚少」）脚本没拦住。
4 产出 WORK/polished.md、WORK/polish_report.md（全书指标前后对比、逐段前后对照、被拒段及原因）。
不许做的：增删信息、改数字学名引文图号、改已核术语、删限定语。润色稿须再过 transqa（若有原文）。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transqa import zh_style as Z  # noqa: E402
from transqa.blocks import classify  # noqa: E402
from transqa.segments import render, split_template  # noqa: E402

PROMPT_VERSION = '2026-11-15p4'
VERIFY_SYS = """你核对中文润色是否改变了意思。每组给出同一段落的「原」与「改」（改只应是表达调整）。
逐组判断两者信息是否完全等价：指代对象、程度与范围（任何/所有/甚少）、时间先后、因果与转折、引号含义、限定语与否定、数字与学名。
只输出 JSON 数组：[{"id": "段ID", "same": true|false, "why": "不等价时写出差异"}]，覆盖每个 id。有任何疑问就判 false。"""
BATCH_CHARS = 3500

POLISH_SYS = """你是资深的中文科学编辑，正在润色一部外文动物学专著的中译稿。译稿意思已经核对过，你只改中文表达，让它读起来像中国学者直接用中文写的。
忠实指意思等价而非字面对应：语序、句子切分、词性、主动被动都可以按中文习惯重组，但信息、逻辑关系、论证方向、强调、断言强度、指代对象不能变。
输入是若干段，每段以 ⟦段ID⟧ 开头一行；按同样格式逐段输出改写后的段落（每个 ID 都要返回、顺序不变、段内不许出现 ⟦ ⟧），不要任何说明。

要改的（据本土教科书与我方译稿的计数，这些是我方译稿与本土写法差得最多的地方）：
1. 句子不要切得太碎。本土动物学行文的句长中位约 30 字；把前后紧密相关的短句用逗号、分号或关联词并成自然的长句，但一句只讲一件事，不超过约 70 字。
2. 「该」用得太多（本土约为我方的 1/7）：指代清楚时省去，或改「此」「这」「这些」，或直接重复名词；「该种」「该属」在分类描述中可保留。
3. 「以及」「然而」「此外」「关于」不要逐个对译英文 and / however / moreover / on：并列用「和」「与」或顿号；转折语气已清楚时省去「然而」，需要时用「但」「不过」；「关于……的研究」改成「……研究」或「研究了……」。
4. 「被」字句改主动或无标记被动：「被认为是」→「一般认为」「学者认为」；「被用于」→「用于」；「被发现于」→「见于」。
5. 名词化改动词：「对……的理解/认识/研究」→「理解/认识/研究……」；「进行……」能省则省。
6. 「一个」「它」「它们」：不需要数量或指代时省去。
6b. 英文括注要克制：日常词、人名、已有通行译名的概念后面的英文括注删去（地方博物学家（naturalists）→地方博物学家）；
    专业术语只在本段第一次出现时保留括注。人名不写成「雷·兰克斯特（Ray Lankester）」式双写：通行中文名的用中文，其余保留原文。
    经典著作用通行全称（《起源》→《物种起源》）。括号里含年份的文献引注一律保留。
7. 先说条件、背景，后说结论，符合中文语序；时间、地点状语前置。

不许做的：
- 增删任何信息；改动数字、单位、拉丁学名（含 *斜体*）、命名人、年份、图号、表号、文献引注、括注的英文术语。
- 删掉否定词或限定语（不、无、未、非、可能、或许、似、约、通常、一般、多、少数、仅）；改变论证方向。
- 改已统一的术语译名；把描述性的条目体（「体长 2–3 mm。口前叶圆锥形。」）改成口语。
- 生造四字格、加感情色彩、加译者评论。

本土范文（体会句长与衔接，不要照抄内容）：
{examples}"""

NEG = r'不|无|未|非|没|否'
QUANT = r'任何|所有|全部|一切|均|皆|每|各|凡'          # 量词范围：改掉会改变强度（盲评：「缺乏任何……」→「所知甚少」）
TIME = r'此后|此前|随后|之后|之前|最初|起初|最终|后来|曾|已|仍|尚'   # 时间先后（盲评：润色删了「此后」）
QUAL = r'可能|或许|也许|似|约|大约|大致|通常|一般|多数|多半|少数|仅|只|偶尔|偶见|往往|常'
ASCII = r'[A-Za-z][A-Za-z.\'\-]*|\d+(?:[.,]\d+)?'
# 可删的英文括注：（naturalists）（morphological species concept）（Ray Lankester）——纯字母、≤5 词、不含数字。
# STYLE.md §6 要求删日常词、人名与已译概念后的括注；引文（含年份数字）与斜体学名不在此列，仍受保护。
GLOSS = re.compile(r'[（(]\s*[A-Za-z][A-Za-z\'\- ]{1,60}[）)]')


def _ascii_tokens(s: str) -> collections.Counter[str]:
    return collections.Counter(re.findall(ASCII, s))


def _gloss_tokens(s: str) -> collections.Counter[str]:
    out: collections.Counter[str] = collections.Counter()
    for m in GLOSS.finditer(s):
        if len(m.group(0).split()) <= 5 and not re.search(r'\*', m.group(0)):
            out.update(re.findall(ASCII, m.group(0)))
    return out


def guard(old: str, new: str) -> list[str]:
    """改写后的段落能否替换原段。返回拒绝理由；空 = 通过。"""
    why = []
    a, b = _ascii_tokens(old), _ascii_tokens(new)
    lost, added = a - b, b - a
    lost = lost - _gloss_tokens(old)            # 删掉的英文括注不算丢失
    if lost or added:
        why.append(f'ASCII 串（学名/数字/引文）变化：少 {dict(lost)} 多 {dict(added)}')
    if collections.Counter(re.findall(r'\*[^*\n]+\*', old)) != collections.Counter(re.findall(r'\*[^*\n]+\*', new)):
        why.append('斜体内容变化')
    if (old.count('“'), old.count('”'), old.count('「')) != (new.count('“'), new.count('”'), new.count('「')):
        why.append('引号数量变化（引号可能表示存疑或术语）')
    for name, rx in (('否定词', NEG), ('限定语', QUAL), ('范围词', QUANT), ('时间词', TIME)):
        if len(re.findall(rx, new)) < len(re.findall(rx, old)):
            why.append(f'{name}减少（{len(re.findall(rx, old))}→{len(re.findall(rx, new))}）')
    import difflib
    keep = difflib.SequenceMatcher(None, old, new, autojunk=False).ratio()
    if keep < 0.5:   # 改动率上限（借 shuorenhua 留存率、im-not-ai 改动率闸口；阈值按中文自校前先取 0.5）
        why.append(f'改动过大（字符相似度 {keep:.2f} < 0.5，疑似重写而非润色）')
    na, nb = Z.han_count(old), Z.han_count(new)
    if na and not 0.8 <= nb / na <= 1.25:
        why.append(f'篇幅变化过大（{na}→{nb} 字）')
    if Z.paragraph_score(new) > Z.paragraph_score(old):
        why.append('翻译腔得分升高')
    return why


def examples(n: int = 3) -> str:
    """本土范文：优先取 classics.sqlite 里杨德渐《海洋无脊椎动物学》的叙述段；不可用时返回空。"""
    db = Path('/mnt/p/翻译-译作/经典译作_本地化/classics.sqlite')
    if not db.exists():
        return '（无）'
    import sqlite3
    rows = sqlite3.connect(str(db)).execute(
        "select text from pages where key='杨德渐2006' and page in (40, 120, 260) order by page").fetchall()
    out = []
    for (t,) in rows[:n]:
        paras = [p for p in (t or '').split('\n') if Z.han_count(p) > 120]
        if paras:
            out.append(paras[0][:400])
    return '\n\n'.join(out) or '（无）'


ID_RE = re.compile(r'⟦(p\d+_s\d+)⟧')


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    parts = ID_RE.split(text)
    got: dict[str, str] = {}
    dups: list[str] = []
    for k in range(1, len(parts) - 1, 2):
        if parts[k] in got:
            dups.append(parts[k])
        else:
            got[parts[k]] = parts[k + 1].strip()
    return got, dups


def llm(engine: str, system: str, user: str, tag: str, usage: Path) -> str:
    import auto_translate as at
    return at.llm(engine, system, user, tag, usage)[0]


def pick(engine: str) -> str:
    """默认润色模型 codex-sol（2026-11-15 试点：codex-luna 10 段只过 2 段且有漂移；codex-sol 过 7 段、盲评无实质差异）。
    deepseek-flash 润色尚未比测，需要时显式 --engine deepseek-flash（仅夜间）。"""
    return 'codex-sol' if engine == 'auto' else engine


def verify(pairs: list[tuple[Any, str]], engine: str, work: Path, k: int) -> dict[str, dict[str, Any]]:
    """第二模型逐段核对润色前后意思等价（只输出 JSON 判定，便宜）。缓存按内容摘要。"""
    user = '\n\n'.join(f'## {s.id}\n原：{s.text}\n改：{new}' for s, new in pairs)
    dg = hashlib.sha1('\x00'.join([VERIFY_SYS, user, engine, PROMPT_VERSION]).encode()).hexdigest()
    cache = work / f'polish/v{k:04d}.json'
    if cache.exists():
        rec = json.loads(cache.read_text(encoding='utf-8'))
        if rec.get('digest') == dg:
            return {x['id']: x for x in rec['verdicts']}
    import auto_translate as at
    os_env = __import__('os').environ
    os_env.setdefault('YZZ_CODEX_EFFORT', 'medium')
    v = at._ask_json(engine, VERIFY_SYS, user, f'polish/verify/v{k:04d}', work) or []   # 失败返回 [] → 全部判未核对
    cache.write_text(json.dumps({'digest': dg, 'verdicts': v}, ensure_ascii=False, indent=1), encoding='utf-8')
    return {str(x.get('id')): x for x in v}


def polish(md: str, work: Path, engine: str = 'auto', threshold: float = Z.PARA_THRESHOLD,
           dry: bool = False, verify_engine: str = 'auto') -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    segs, tpl = split_template(md)
    texts = {s.id: s.text for s in segs}
    cand = [s for s in segs if classify(s.text) == 'free' and not s.text.lstrip().startswith(('#', '|', '!['))
            and not Z.is_description(s.text) and Z.paragraph_score(s.text) >= threshold]
    batches: list[list[Any]] = []
    cur: list[Any] = []
    size = 0
    for s in cand:
        if cur and size + len(s.text) > BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s.text)
    if cur:
        batches.append(cur)
    stats = {'segments': len(segs), 'candidates': len(cand), 'batches': len(batches)}
    if dry:
        return stats
    system = POLISH_SYS.format(examples=examples())
    eng = pick(engine)
    if verify_engine == 'auto':     # 核对模型必须不同于润色模型（且最好不同厂商）
        verify_engine = 'cursor-composer' if eng.startswith('codex') else 'codex-sol'
    if verify_engine == eng:
        raise ValueError(f'润色与核对用了同一模型 {eng}')
    log: list[dict[str, Any]] = []
    for k, b in enumerate(batches):
        todo = list(b)
        feedback: dict[str, list[str]] = {}
        rejected: dict[str, tuple[list[str], str | None]] = {}
        for attempt in range(2):                     # 第二轮只重做第一轮被拒的段，附上拒绝理由
            user = '\n\n'.join(f'⟦{s.id}⟧\n{s.text}' + (
                '\n（上次改写被拒：' + '；'.join(feedback[s.id]) + '。这次只改表达，保留这些内容。）'
                if s.id in feedback else '') for s in todo)
            tag = f'b{k:04d}' + (f'r{attempt}' if attempt else '')
            dg = hashlib.sha1('\x00'.join([system, user, eng, PROMPT_VERSION]).encode()).hexdigest()
            cache = work / f'polish/{tag}.json'
            rec = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else None
            if not rec or rec.get('digest') != dg:
                try:
                    out = llm(eng, system, user, f'polish/{tag}', work / 'usage.tsv')
                except Exception as exc:  # noqa: BLE001 - 引擎网络/额度错误：本批保留原文，记入报告，继续下一批
                    print(f'[zh_polish] {eng} 调用失败：{str(exc)[-160:]}', flush=True)
                    rejected = {s.id: ([f'润色模型调用失败（{type(exc).__name__}），保留原文'], None) for s in todo}
                    break
                got, dups = parse(out)
                rec = {'digest': dg, 'engine': eng, 'got': got, 'dups': dups}
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
            passed: list[tuple[Any, str]] = []
            rejected = {}
            for s in todo:
                new = rec['got'].get(s.id)
                if new is None or s.id in rec.get('dups', []):
                    rejected[s.id] = (['模型未返回或重复返回该段'], None)
                    continue
                why = guard(s.text, new)
                if why:
                    rejected[s.id] = (why, new)
                else:
                    passed.append((s, new))
            verdicts = (verify(passed, verify_engine, work, k * 10 + attempt)
                        if passed and verify_engine != 'none' else {})
            for s, new in passed:
                v = verdicts.get(s.id)
                if verify_engine != 'none' and not (v and v.get('same') is True):
                    rejected[s.id] = (['第二模型判意思有变：' + str((v or {}).get('why', '无判定'))], new)
                    continue
                texts[s.id] = new
                log.append({'id': s.id, 'result': 'applied', 'attempt': attempt + 1, 'old': s.text, 'new': new,
                            'score': [Z.paragraph_score(s.text), Z.paragraph_score(new)]})
            feedback = {sid: why for sid, (why, _) in rejected.items()}
            todo = [s for s in todo if s.id in rejected]
            if not todo:
                break
        for s in todo:
            why, new = rejected[s.id]
            log.append({'id': s.id, 'result': 'rejected', 'why': why, 'old': s.text, 'new': new})
        print(f'polish b{k:04d} {eng} paras={len(b)} applied={len(b) - len(todo)}', flush=True)
    out_md = render(tpl, texts)
    (work / 'polished.md').write_text(out_md, encoding='utf-8')
    (work / 'polish_log.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in log),
                                           encoding='utf-8')
    stats.update(applied=sum(x['result'] == 'applied' for x in log), rejected=sum(x['result'] == 'rejected' for x in log))
    (work / 'polish_report.md').write_text(report(md, out_md, log, stats), encoding='utf-8')
    return stats


def report(before: str, after: str, log: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    a, b = Z.measure(before), Z.measure(after)
    rows = ['# 中文润色报告', '', f"段 {stats['segments']}，候选 {stats['candidates']}，落实 {stats.get('applied', 0)}，"
            f"拒绝 {stats.get('rejected', 0)}（提示词 {PROMPT_VERSION}）", '',
            '| 指标（每千汉字） | 润色前 | 润色后 | 本土上限 |', '|---|---|---|---|']
    for k, (_, lim) in Z.MARKERS.items():
        rows.append(f'| {k} | {a.rates[k]} | {b.rates[k]} | {lim} |')
    rows.append(f'| 句长中位（字） | {a.sent_median} | {b.sent_median} | {Z.SENT_MEDIAN_NATIVE[0]}–{Z.SENT_MEDIAN_NATIVE[1]} |')
    rows.append(f'| >60 字句占比（%） | {a.long_share} | {b.long_share} | {Z.LONG_SENT_NATIVE[0]}–{Z.LONG_SENT_NATIVE[1]} |')
    rows += ['', '## 逐段对照（落实的）', '']
    for x in [x for x in log if x['result'] == 'applied'][:200]:
        rows += [f"### {x['id']}（得分 {x['score'][0]}→{x['score'][1]}）", '', f"原：{x['old']}", '', f"改：{x['new']}", '']
    rej = [x for x in log if x['result'] == 'rejected']
    if rej:
        rows += ['## 被闸口拒绝（保留原文）', '']
        rows += [f"- {x['id']}：{'；'.join(x['why'])}" for x in rej]
    return '\n'.join(rows) + '\n'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tgt')
    ap.add_argument('-o', '--work', default='zh_polish_work')
    ap.add_argument('--engine', default='auto')
    ap.add_argument('--threshold', type=float, default=Z.PARA_THRESHOLD)
    ap.add_argument('--dry', action='store_true', help='只统计候选段数与批数，不调用模型')
    ap.add_argument('--verify-engine', default='auto',
                    help='第二模型核对意思等价（默认：润色用 Codex 时 cursor-composer，否则 codex-sol；none 不核对，不推荐）')
    a = ap.parse_args(argv)
    stats = polish(Path(a.tgt).read_text(encoding='utf-8'), Path(a.work), a.engine, a.threshold, a.dry, a.verify_engine)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
