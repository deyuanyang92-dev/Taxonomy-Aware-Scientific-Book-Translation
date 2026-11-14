#!/usr/bin/env python3
"""auto 档：自动组合免费机翻与便宜模型，保质量、省 token。通用：任意源语言 → 任意目标语言
（--sl/--tl 用 Google 语言代码，如 bg、ru、de、fr、ja、la、zh-CN、en）；分类学文本的护栏（学名、数字、检索表）对所有语种都适用。

    python3 auto_translate.py run   SRC.md -o WORK --sl bg --tl en [--glossary G.md] [--names N.md] [--bad-terms setae,palpi]
    python3 auto_translate.py check SRC.md TGT.md -o WORK [--glossary ...]   # 只做意义核对（已有译文）
    python3 auto_translate.py report WORK

输入：Markdown，逐页 `<!-- PDF p.N ... -->` 标记；空行分段。原文与译文的页标记必须一一对应。

流程（依据 docs/model_bench.md「保加利亚文→英文：Google 稿改写的性价比比测」，2026-11-14）：
1 draft   Google gtx 免费初稿（逐段、4 路并发、sqlite 缓存）。页标记、无源语言字母的段（学名列表、引文）不送。
2 revise  3 页一段，对照原文改写 Google 稿。引擎自动选择：北京时间夜间（22–8 点）deepseek-flash 关思考
          （比测重大错误 0，全书约 $0.25）；白天 codex-luna（流畅但会编造，之后必须走第 3 步）。
          只把本段用到的术语表、转写表条目送进提示词（省 token）；固定的规则放 system 前部，便于 DeepSeek 前缀缓存。
          护栏：页标记数、数字、斜体学名、检索表编号、异常文字（天城文等）、禁用词。不过护栏的段把问题清单发回重做一次，
          仍不过则取护栏问题更少的一份并在报告里标出。
3 check   意义核对：deepseek-flash 关思考逐句对照原文找错，只返回 JSON 最小改动 {pdf_page, old, new, reason}；
          再由第二个模型（--verify-engine，默认 codex-sol、medium）逐条对照原文 ACCEPT/REJECT，只落实两者都认可的。
          依据：2026-11-14 Marinov 全书实测，flash 报 76 处，sol 只认可 12 处（flash 把 цифта「对」当成单个等系统性误判）。
          落实护栏：old 在该页唯一出现；改动不得丢数字、学名；new 不得比 old 长出 2 倍+80 字符（防止整段重写）。
          DeepSeek 只在夜间调用（llm_engines 内 wait_offpeak 自动等待）；白天加 --day-engine codex-luna 才用 Codex。
          check 的严重度：critical（学名、数字、编号、有/无反转、检索表跳转）两模型都认可也不自动落实，写入
          human_review_queue.csv 由人对照扫描件定；major/minor 认可后落实。否定词计数少于原文的页作为高风险页提示核对模型。
          护栏另查检索表结构（编号与跳转目标）和残留未译原文。参照 Japanese_Taxonomy_OCR_to_English_ClaudeCode_Guide §7。
4 report  每步用量（token、秒、美元估算）、护栏问题、被拒改动，写 WORK/report.md；另抽 8 页生成 audit_sample.md，
          供 Claude Sonnet 盲评抽检（脚本不调用 Claude）。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

PAGE_RE = re.compile(r'^\s*<!-- PDF p\.(\d+)\b')
FOREIGN_RE = re.compile(r'[ऀ-ॿ؀-ۿ฀-๿가-힯֐-׿一-鿿]')
# 译成中文时汉字是正常文字，只查假名、韩文等（日→中最常见的漏网是残留假名）
FOREIGN_RE_ZH = re.compile(r'[ऀ-ॿ؀-ۿ฀-๿가-힯֐-׿぀-ヿ]')
# 源语言的文字（决定哪些段送 Google、译文里查残留）。拉丁字母语言无法查残留。新语言加一项即可；未列出的用 \w。
SCRIPT_RE = {'bg': r'[\u0400-\u04FF]', 'ru': r'[\u0400-\u04FF]', 'uk': r'[\u0400-\u04FF]', 'sr': r'[\u0400-\u04FF]',
             'el': r'[\u0370-\u03FF]', 'ja': r'[\u3040-\u30ff\u4e00-\u9fff]', 'zh-CN': r'[\u4e00-\u9fff]',
             'zh': r'[\u4e00-\u9fff]', 'ko': r'[\uAC00-\uD7AF]',
             'de': r'[A-Za-zÄÖÜäöüß]', 'fr': r'[A-Za-zÀ-ÿ]', 'es': r'[A-Za-zÀ-ÿ]', 'it': r'[A-Za-zÀ-ÿ]',
             'pt': r'[A-Za-zÀ-ÿ]', 'la': r'[A-Za-z]', 'nl': r'[A-Za-z]', 'en': r'[A-Za-z]'}
PROMPT_VERSION = '2026-11-15a'  # 提示词或裁定规则改了就改这里；写进每段缓存与报告（可追溯）
# 否定/缺失词（按语言；只用于标出高风险页，不做判定）。新语言加一行即可。
NEG = {
    'bg': r'\b(?:не|без|липсва|липсват|няма|отсъства|отсъстват|нито)\b',
    'ru': r'\b(?:не|нет|без|отсутству\w*|ни)\b',
    'uk': r'\b(?:не|немає|без|відсутн\w*|ні)\b',
    'de': r'\b(?:nicht|kein\w*|ohne|fehl\w*)\b',
    'fr': r'\b(?:ne|pas|sans|aucun\w*|absent\w*|manqu\w*)\b',
    'es': r'\b(?:no|sin|ningún|ninguna|ausente\w*|carece\w*)\b',
    'it': r'\b(?:non|senza|nessun\w*|assent\w*|manca\w*)\b',
    'pt': r'\b(?:não|sem|nenhum\w*|ausente\w*)\b',
    'la': r'\b(?:non|nec|neque|sine|nullus|nulla|desunt|deest|absent)\b',
    'en': r'\b(?:no|not|without|absent|lacking|lacks?|none|never|nor|devoid)\b|\bnon-',
    'ja': r'(?:ない|無い|なし|無し|欠く|欠如|ず[、。]|ぬ)',
    'zh': r'(?:不|无|没有|缺|未|非)',
}


def neg_count(text: str, lang: str) -> int:
    r = NEG.get(lang) or NEG.get(lang.split('-')[0])
    return len(re.findall(r, text, re.I)) if r else 0


DS_PRICE = {'in': 0.15, 'cache': 0.003, 'out': 0.6}  # deepseek-flash 闲时 USD/1M（官方定价页 2026-11-14）
BJ = dt.timezone(dt.timedelta(hours=8))
CHUNK_PAGES = 3


# ---------------------------------------------------------------- 分页与分段
def pages(text: str) -> dict[int, str]:
    """{pdf_page: 该页文字（含页标记行）}；首个标记前的内容记为第 0 页。"""
    out: dict[int, str] = {}
    cur = 0
    buf: list[str] = []
    for ln in text.split('\n'):
        m = PAGE_RE.match(ln)
        if m:
            if buf and (cur or any(x.strip() for x in buf)):
                out[cur] = '\n'.join(buf)
            cur, buf = int(m.group(1)), []
            if cur in out:
                raise ValueError(f'页标记重复：PDF p.{cur}')
        buf.append(ln)
    if buf and (cur or any(x.strip() for x in buf)):
        out[cur] = '\n'.join(buf)
    return out


def chunks_of(pg: dict[int, str], n: int = CHUNK_PAGES) -> list[list[int]]:
    ps = sorted(pg)
    return [ps[i:i + n] for i in range(0, len(ps), n)]


def join(pg: dict[int, str], ps: list[int]) -> str:
    return '\n'.join(pg[p].rstrip('\n') for p in ps if p in pg) + '\n'


# ---------------------------------------------------------------- Google 初稿
class Google:
    URL = 'https://translate.googleapis.com/translate_a/single'

    def __init__(self, sl: str, tl: str, cache: Path) -> None:
        self.sl, self.tl = sl, tl
        cache.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(cache), check_same_thread=False)
        self.db.execute('create table if not exists c(k text primary key, v text)')
        self.lock = threading.Lock()
        self.requests = 0
        self.failed: list[str] = []
        self.cool_until = 0.0  # 遇 429/5xx 所有线程一起冷却（2026-11-15 实测：8 线程无间隔 320 段/分钟，拼段请求反而 429）

    def _key(self, s: str) -> str:
        return hashlib.sha1(f'{self.sl}>{self.tl}:{s}'.encode()).hexdigest()

    def one(self, s: str) -> str:
        k = self._key(s)
        with self.lock:
            r = self.db.execute('select v from c where k=?', (k,)).fetchone()
        if r:
            return str(r[0])
        url = self.URL + '?' + urllib.parse.urlencode({'client': 'gtx', 'sl': self.sl, 'tl': self.tl, 'dt': 't', 'q': s})
        for a in range(10):
            wait = self.cool_until - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                d = json.load(urllib.request.urlopen(req, timeout=30))
                v = ''.join(str(x[0]) for x in d[0] if x and x[0])
                if v.strip():
                    with self.lock:
                        self.requests += 1
                        self.db.execute('insert or replace into c values(?,?)', (k, v))
                        self.db.commit()
                    return v
            except urllib.error.HTTPError:
                with self.lock:
                    self.cool_until = max(self.cool_until, time.time() + min(60, 5 * 2 ** a))
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, IndexError, TypeError):
                pass
            time.sleep(min(60, 2 ** a) + random.random())
        with self.lock:
            self.failed.append(s[:80])
        return s  # 失败：暂留原文；stage_draft 见 failed 非空即中止，重跑时只补失败段（成功段已缓存）

    def para(self, p: str, src_re: str) -> str:
        lines = p.split('\n')
        head = [ln for ln in lines if ln.lstrip().startswith('<!--')]
        body = '\n'.join(ln for ln in lines if not ln.lstrip().startswith('<!--')).strip()
        if not body or not re.search(src_re, body):
            return p
        if len(body) <= 4500:
            res = self.one(body)
        else:
            parts, cur = [], ''
            for s in re.split(r'(?<=[.!?;])\s+|(?<=[。．！？])', body):
                if len(s) > 4400 and cur:
                    parts.append(cur)
                    cur = ''
                while len(s) > 4400:
                    parts.append(s[:4400])
                    s = s[4400:]
                if cur and len(cur) + len(s) + 1 > 4400:
                    parts.append(cur)
                    cur = ''
                cur = (cur + ' ' + s).strip()
            if cur:
                parts.append(cur)
            res = ' '.join(self.one(c) for c in parts)
        return '\n'.join(head + [res])

    def text(self, t: str, src_re: str, workers: int = 8) -> str:
        paras = [p.strip() for p in t.split('\n\n')]
        with ThreadPoolExecutor(workers) as ex:
            return '\n\n'.join(ex.map(lambda p: self.para(p, src_re), paras)) + '\n'


# ---------------------------------------------------------------- 术语表裁剪
def load_table(path: str | None) -> list[tuple[str, str]]:
    """Markdown 表格或 TSV 的前两列 → [(源, 译)]；跳过表头与分隔行。"""
    if not path:
        return []
    rows = []
    for ln in Path(path).read_text(encoding='utf-8').splitlines():
        cells = [c.strip() for c in (ln.strip().strip('|').split('|') if ln.startswith('|') else ln.split('\t'))]
        if len(cells) < 2 or not cells[0] or set(cells[0]) <= set('-: ') or cells[0].lower() in ('source', '西里尔'):
            continue
        rows.append((cells[0], cells[1]))
    return rows


def _stem(w: str) -> str:
    w = w.lower()
    return w[:max(4, len(w) - 2)] if len(w) > 5 else w


def relevant(table: list[tuple[str, str]], text: str) -> list[tuple[str, str]]:
    """只留本段原文出现过的条目：源词组的每个实词（去掉词尾 2 个字母，容忍屈折）都在原文里出现。"""
    low = text.lower()
    out = []
    for src, tgt in table:
        words = [w for w in re.split(r'[\s/(),;.]+', src) if len(w) > 2]
        if words and all(_stem(w) in low for w in words):
            out.append((src, tgt))
    return out


def table_md(rows: list[tuple[str, str]]) -> str:
    return '\n'.join(f'- {a} = {b}' for a, b in rows) or '（无）'


# ---------------------------------------------------------------- 护栏
def _clean(t: str) -> str:
    return re.sub(r'<!--.*?-->|\[TN:[^\]]*\]', '', t, flags=re.S)


def nums(t: str) -> collections.Counter[str]:
    return collections.Counter(re.findall(r'\d+(?:[.,]\d+)?', _clean(t)))


def italics(t: str) -> collections.Counter[str]:
    return collections.Counter(re.sub(r'\s+', ' ', m.strip()) for m in re.findall(r'\*([^*\n]+)\*', _clean(t))
                               if re.search(r'[A-Za-z]', m) and not re.search(r'[Ѐ-ӿ]', m))


def couplets(t: str) -> collections.Counter[str]:
    return collections.Counter(re.sub(r'\s', '', k) for k in re.findall(r'\b\d+\s*\(\d+\)', _clean(t)))


def key_structure(t: str) -> collections.Counter[str]:
    """检索表结构：每条 n(m) 及其行末跳转目标（…… 3、. . . 3）。学名结论（…… 2. *G. limbata*）不算跳转。"""
    out: collections.Counter[str] = collections.Counter()
    for ln in _clean(t).split('\n'):
        m = re.match(r'\s*(\d+)\s*\((\d+)\)', ln)
        if not m:
            continue
        lead = re.search(r'(?:…+|(?:\.\s*){3,})\s*(\d+)\s*$', ln)
        out[f'{m.group(1)}({m.group(2)})->{lead.group(1) if lead else "-"}'] += 1
    return out


def residue(tgt: str, sl: str) -> list[str]:
    """译文里残留的原文文字（[TN:]、斜体、1а 式图注子图字母除外）。"""
    r = SCRIPT_RE.get(sl)
    if not r or re.fullmatch(r'\[A-Za-z.*', r):  # 拉丁字母源语言（de/fr/es/la…）无法按字母判断残留
        return []
    body = re.sub(r'\*[^*\n]+\*', '', _clean(tgt))
    body = re.sub(r'(?<=\d)[\u0400-\u04FF](?![\u0400-\u04FF])|\b[\u0400-\u04FF]\b', '', body)
    return re.findall(rf'{r}{{2,}}', body)


def negation_risk(src: str, tgt: str, sl: str, tl: str = 'en') -> list[int]:
    """原文否定/缺失词多于译文的页（present/absent 反转的高风险页），交给意义核对重点看。"""
    if sl.split('-')[0] not in NEG or tl.split('-')[0] not in NEG:
        return []
    ps, pt = pages(src), pages(tgt)
    return [p for p in sorted(ps) if p in pt and neg_count(ps[p], sl) > neg_count(pt[p], tl)]


def guard(src: str, tgt: str, bad_terms: list[str] | None = None, tl: str = 'en', sl: str = '') -> list[str]:
    """原文 vs 译文：返回问题清单（空 = 通过）。数字只查原文有而译文缺的（数词写成数字不算错）。"""
    probs = []
    ps, pt = pages(src), pages(tgt)
    if sorted(p for p in ps if p) != sorted(p for p in pt if p):
        probs.append(f'页标记不一致：原文 {sorted(ps)} 译文 {sorted(pt)}')
    for p in sorted(ps):
        s, t = ps[p], pt.get(p, '')
        miss = nums(s) - nums(t)
        if miss:
            probs.append(f'p.{p} 缺数字 {dict(miss)}')
        mi = italics(s) - italics(t)
        if mi:
            probs.append(f'p.{p} 缺学名/斜体 {dict(mi)}')
        mc = couplets(s) - couplets(t)
        if mc:
            probs.append(f'p.{p} 缺检索表编号 {dict(mc)}')
        ks, kt = key_structure(s), key_structure(t)
        if ks != kt and not mc:
            probs.append(f'p.{p} 检索表结构（编号/跳转）与原文不同：缺 {dict(ks - kt)} 多 {dict(kt - ks)}')
    fre = FOREIGN_RE_ZH if tl.startswith('zh') else FOREIGN_RE
    if fre.search(_clean(tgt)):
        probs.append('出现异常文字（天城文/阿拉伯文/汉字/假名等）：' + ''.join(fre.findall(_clean(tgt)))[:20])
    left = residue(tgt, sl)
    if left:
        probs.append(f'残留未译原文 {len(left)} 处：' + ' '.join(left[:5]))
    for w in bad_terms or []:
        if re.search(rf'\b{re.escape(w)}\b', tgt):
            probs.append(f'禁用词 {w}')
    return probs


# ---------------------------------------------------------------- 引擎选择
def is_night(now: dt.datetime | None = None, window: tuple[int, int] = (22, 8)) -> bool:
    h = (now or dt.datetime.now(dt.timezone.utc)).astimezone(BJ).hour
    a, b = window
    return a <= h or h < b if a > b else a <= h < b


def pick_engine(task: str, now: dt.datetime | None = None, day_engine: str | None = None) -> str:
    """revise：夜间 deepseek-flash，白天 codex-luna。check：deepseek-flash（白天除非给 day_engine，否则等夜间）。"""
    if is_night(now):
        return 'deepseek-flash'
    if task == 'revise':
        return day_engine or 'codex-luna'
    return day_engine or 'deepseek-flash'


def llm(engine: str, system: str, user: str, tag: str, usage_file: Path) -> tuple[str, dict[str, Any]]:
    import llm_engines
    if engine.startswith('deepseek'):
        os.environ.pop('YZZ_DEEPSEEK_THINKING', None)  # 比测：开思考不提质，费用约 4 倍
    return llm_engines.call(engine, system, user, tag=tag, usage_file=str(usage_file))


# ---------------------------------------------------------------- 提示词
REVISE_SYS = """You revise a Google machine translation of a scientific taxonomic text from {sl} into {tl}.
Output ONLY the revised {tl} Markdown for the whole input, paragraph for paragraph, keeping every
<!-- PDF p.N --> marker line exactly and the same blank-line paragraph breaks. No commentary.
Rules:
1. Faithful: nothing omitted, nothing added. Keep every number, couplet number such as 1(2), plate/figure reference,
   Latin name, author and year exactly as in the original (also the original's own misspellings and abbreviations,
   e.g. *H. filiformis* stays abbreviated). Keep *italics* and the dotted leaders …… of keys. Keep Cyrillic
   figure sub-labels (1а, 2б) as they are.
2. Terminology: use the glossary given with each chunk; one source term = one rendering. Standard taxonomic usage.
3. Style: natural descriptive taxonomic {tl} (telegraphic descriptions as "Body short and thin.", not "The body short").
   Rewrite every paragraph against the original; the Google draft is only a draft.
4. Never write characters of any other script; translator's notes as [TN: ...] in {tl}."""

VERIFY_SYS = """You are the second reviewer of proposed corrections to a {tl} translation of a {sl} taxonomic text.
Another model proposed each fix. For every fix decide against the original: ACCEPT only if the fix makes the
translation more faithful to the original; REJECT if it is wrong, unnecessary, merely stylistic, or "corrects" the
original author's own misprint. Output ONLY a JSON array covering every id: [{{"id": N, "verdict": "ACCEPT"|"REJECT",
"why": "short"}}]."""

CHECK_SYS = """You check a {tl} translation against its {sl} original (a taxonomic text), sentence by sentence.
Report ONLY real meaning errors: wrong meaning, omission, addition, wrong number/name/couplet, reversed negation or
comparison, mistranslated technical term. Ignore style. For each error give the smallest fix and a severity:
critical = Latin name, number, specimen/plate number, present/absent reversed, key couplet or lead-to wrong;
major = body part, count, comparison, diagnostic character mistranslated; minor = term usage without change of meaning.
Do not "correct" the original author's own misprints. Output ONLY a JSON array (possibly empty): [{{"pdf_page": N,
"old": "exact substring of the translation, unique on that page, at most one sentence", "new": "corrected substring",
"severity": "critical|major|minor", "reason": "short"}}]."""


def revise_user(src: str, draft: str, gl: list[tuple[str, str]], nm: list[tuple[str, str]], probs: list[str]) -> str:
    u = f'## Glossary for this chunk\n{table_md(gl)}\n\n## Names\n{table_md(nm)}\n\n## Original\n{src}\n\n## Google draft\n{draft}'
    if probs:
        u += '\n\n## Your previous output failed these checks; fix them\n' + '\n'.join(f'- {p}' for p in probs)
    return u


# ---------------------------------------------------------------- 核对改动的落实
def parse_json_array(text: str) -> list[dict[str, Any]] | None:
    """JSON 数组 → 列表；合法空数组返回 []；找不到或解析失败返回 None（调用方须重试或记失败，不能当成「无错」）。"""
    m = re.search(r'\[.*\]', text, re.S)
    if not m:
        return [] if re.fullmatch(r'\s*(```\w*\s*)?\[\s*\](\s*```)?\s*', text) else None
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else None


def _page_no(p: Any) -> int | None:
    if isinstance(p, int):
        return p
    if isinstance(p, str) and p.strip().isdigit():
        return int(p)
    return None


def apply_edits(src: str, tgt: str, edits: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """逐条落实；返回新译文与每条的结果（applied / rejected: 原因）。

    护栏按整页比较（替换前后相对原文页）：不得新增「原文有、译文缺」的数字或学名，不得新增原文该页没有的数字；
    old 必须在该页唯一出现；new 不得比 old 长出 2 倍 + 80 字符。"""
    log = []
    src_pg = pages(src)
    for e in edits:
        old, new, pn = str(e.get('old', '')), str(e.get('new', '')), _page_no(e.get('pdf_page'))
        res = dict(e)
        pt = pages(tgt)
        seg = pt.get(pn) if pn is not None else None
        why = None
        if not old or old == new:
            why = 'old 为空或无变化'
        elif seg is None:
            why = f'无此页 {e.get("pdf_page")}'
        elif seg.count(old) != 1:
            why = f'old 在该页出现 {seg.count(old)} 次'
        elif len(new) > 2 * len(old) + 80:
            why = 'new 过长（疑似整段重写）'
        else:
            s = src_pg.get(pn or 0, '')
            seg2 = seg.replace(old, new, 1)
            lost_n = (nums(s) - nums(seg2)) - (nums(s) - nums(seg))
            lost_i = (italics(s) - italics(seg2)) - (italics(s) - italics(seg))
            add_n = (nums(seg2) - nums(s)) - (nums(seg) - nums(s))
            if lost_n:
                why = f'改动会丢数字 {dict(lost_n)}'
            elif lost_i:
                why = f'改动会丢学名 {dict(lost_i)}'
            elif add_n:
                why = f'改动引入原文该页没有的数字 {dict(add_n)}'
        if why or seg is None:
            res['result'] = 'rejected: ' + (why or '')
        else:
            tgt = tgt.replace(seg, seg.replace(old, new, 1), 1)
            res['result'] = 'applied'
        log.append(res)
    return tgt, log


# ---------------------------------------------------------------- 流水线
def _write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding='utf-8')


def _digest(*parts: str) -> str:
    return hashlib.sha1('\x00'.join(parts).encode()).hexdigest()


def _cached(path: Path, digest: str) -> dict[str, Any] | None:
    """断点续跑：只有输入摘要一致、且上次成功的记录才复用。"""
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding='utf-8'))
    return rec if rec.get('digest') == digest and rec.get('status') == 'ok' else None


def _same_pages(src: str, tgt: str, where: str) -> None:
    a, b = sorted(p for p in pages(src) if p), sorted(p for p in pages(tgt) if p)
    if a != b:
        raise ValueError(f'{where}：原文页 {a} 与译文页 {b} 不一致')


def stage_draft(src_pg: dict[int, str], work: Path, sl: str, tl: str) -> dict[int, str]:
    g = Google(sl, tl, Path.home() / '.cache/yzz-translate/auto_google.sqlite')
    src_re = SCRIPT_RE.get(sl, r'\w')
    # 全书所有段一起并发（逐页并发时每页只有几段，线程用不满）
    keys = [(p, i) for p in sorted(src_pg) for i, _ in enumerate(src_pg[p].split('\n\n'))]
    paras = [src_pg[p].split('\n\n')[i].strip() for p, i in keys]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda x: g.para(x, src_re), paras))
    by: dict[int, list[str]] = collections.defaultdict(list)
    for (p, _), r in zip(keys, res):
        by[p].append(r)
    out = {p: '\n\n'.join(by[p]) + '\n' for p in sorted(src_pg)}
    _write(work / 'draft_stats.json', json.dumps({'requests': g.requests, 'failed': g.failed}, ensure_ascii=False))
    if g.failed:
        raise SystemExit(f'Google 有 {len(g.failed)} 段失败（见 draft_stats.json）；重跑即可，成功段已缓存')
    _write(work / 'draft.md', ''.join(out[p].rstrip('\n') + '\n' for p in sorted(out)))
    return out


def stage_revise(src_pg: dict[int, str], draft_pg: dict[int, str], work: Path, a: argparse.Namespace) -> str:
    gl, nm = load_table(a.glossary), load_table(a.names)
    bad = [w for w in (a.bad_terms or '').split(',') if w]
    sysmsg = REVISE_SYS.format(sl=a.sl, tl=a.tl)
    issues, parts = {}, []
    for k, ps in enumerate(chunks_of(src_pg)):
        out = work / f'revise/c{k:03d}.md'
        src, draft = join(src_pg, ps), join(draft_pg, ps)
        _same_pages(src, draft, f'c{k:03d} 初稿')
        if out.exists():  # 续跑：已完成的段也重新过护栏，问题照样进报告
            best = out.read_text(encoding='utf-8')
            best_p = guard(src, best, bad, a.tl, a.sl)
        else:
            g2, n2 = relevant(gl, src), relevant(nm, src)
            engine = a.engine if a.engine != 'auto' else pick_engine('revise', day_engine=a.day_engine)
            best, best_p = draft, guard(src, draft, bad, a.tl, a.sl)
            probs: list[str] = []
            for attempt in range(2):
                text, _ = llm(engine, sysmsg, revise_user(src, draft, g2, n2, probs),
                              f'auto/revise/c{k:03d}/{attempt}', work / 'usage.tsv')
                text = text.strip() + '\n'
                probs = guard(src, text, bad, a.tl, a.sl)
                if best is draft or len(probs) <= len(best_p):
                    best, best_p = text, probs
                if not probs:
                    break
            _write(out, best)
            print(f'revise c{k:03d} {engine} issues={len(best_p)}', flush=True)
        if best_p:
            issues[f'c{k:03d}'] = best_p
        parts.append(best)
    _write(work / 'revise_issues.json', json.dumps(issues, ensure_ascii=False, indent=1))
    revised = ''.join(x.rstrip('\n') + '\n' for x in parts)
    _same_pages(''.join(src_pg.values()), revised, '改写合并')
    _write(work / 'revised.md', revised)
    return revised


def _ask_json(engine: str, system: str, user: str, tag: str, work: Path) -> list[dict[str, Any]] | None:
    """调用并解析 JSON 数组；格式错或引擎连接失败都重试，最终失败返回 None（该段记为失败，不中断全书）。"""
    for attempt in range(3):
        try:
            text, _ = llm(engine, system, user, f'{tag}/{attempt}', work / 'usage.tsv')
        except Exception as exc:  # noqa: BLE001 - 引擎网络/额度错误：等一会重试
            print(f'[auto] {engine} 调用失败（{type(exc).__name__}: {str(exc)[-120:]}），第 {attempt + 1}/3 次', flush=True)
            time.sleep(30 * (attempt + 1))
            continue
        v = parse_json_array(text)
        if v is not None:
            return v
    return None


def stage_check(src_pg: dict[int, str], tgt_pg: dict[int, str], work: Path, a: argparse.Namespace) -> str:
    """找错（check_engine）→ 第二模型裁定（verify_engine，须不同于找错模型）→ 护栏落实。只落实两者都认可的改动。"""
    gl = load_table(a.glossary)
    csys, vsys = CHECK_SYS.format(sl=a.sl, tl=a.tl), VERIFY_SYS.format(sl=a.sl, tl=a.tl)
    parts, logs, failed = [], [], []
    human: list[dict[str, Any]] = []
    for k, ps in enumerate(chunks_of(src_pg)):
        cid = f'c{k:03d}'
        src, tgt = join(src_pg, ps), join(tgt_pg, ps)
        _same_pages(src, tgt, f'{cid} 核对')
        gtab = table_md(relevant(gl, src))
        # 1 找错
        risk = negation_risk(src, tgt, a.sl, a.tl)
        dg = _digest(src, tgt, gtab, csys, PROMPT_VERSION)
        rec = _cached(work / f'check/{cid}.json', dg)
        if rec is None:
            engine = a.engine if a.engine != 'auto' else pick_engine('check', day_engine=a.day_engine)
            user = f'## Glossary\n{gtab}\n\n## Original\n{src}\n\n## Translation\n{tgt}'
            if risk:
                user += (f'\n\n## Check with special care\nPages {risk}: the original has more negation/absence words '
                         'than the translation (possible present/absent reversal or omitted "without").')
            edits = _ask_json(engine, csys, user, f'auto/check/{cid}', work)
            rec = {'digest': dg, 'engine': engine, 'prompt_version': PROMPT_VERSION, 'risk_pages': risk,
                   'status': 'ok' if edits is not None else 'parse_failed',
                   'edits': edits or []}
            _write(work / f'check/{cid}.json', json.dumps(rec, ensure_ascii=False, indent=1))
        if rec['status'] != 'ok':
            failed.append(f'{cid} 找错输出无法解析')
        edits = [dict(e, id=i) for i, e in enumerate(rec['edits'])]
        # 2 第二模型裁定
        verdicts: dict[int, dict[str, Any]] = {}
        if edits and a.verify_engine != 'none':
            vd = _digest(src, tgt, json.dumps(edits, ensure_ascii=False), vsys, a.verify_engine, PROMPT_VERSION)
            vrec = _cached(work / f'verify/{cid}.json', vd)
            if vrec is None:
                os.environ.setdefault('YZZ_CODEX_EFFORT', 'medium')
                user = f'## Original\n{src}\n\n## Translation\n{tgt}\n\n## Proposed fixes\n' + '\n'.join(
                    json.dumps({k2: e[k2] for k2 in ('id', 'pdf_page', 'old', 'new', 'reason') if k2 in e},
                               ensure_ascii=False) for e in edits)
                v = _ask_json(a.verify_engine, vsys, user, f'auto/verify/{cid}', work)
                vrec = {'digest': vd, 'engine': a.verify_engine, 'prompt_version': PROMPT_VERSION,
                        'status': 'ok' if v is not None else 'parse_failed',
                        'verdicts': v or []}
                _write(work / f'verify/{cid}.json', json.dumps(vrec, ensure_ascii=False, indent=1))
            if vrec['status'] != 'ok':
                failed.append(f'{cid} 裁定输出无法解析（本段改动全部不落实）')
            verdicts = {int(x['id']): x for x in vrec['verdicts'] if _page_no(x.get('id')) is not None}
        keep, log = [], []
        for e in edits:
            vd_ = verdicts.get(e["id"])
            ok = a.verify_engine == 'none' or (vd_ and str(vd_.get('verdict', '')).upper() == 'ACCEPT')
            if ok and str(e.get('severity', '')).lower() == 'critical':
                human.append(dict(e, chunk=cid, verdict='ACCEPT', why=(vd_ or {}).get('why', '')))
                log.append(dict(e, result='queued: critical，须人工对照扫描件'))
            elif ok:
                keep.append(e)
            else:
                log.append(dict(e, result='rejected: 第二模型未认可' + (f"（{vd_.get('why', '')}）" if vd_ else '（无裁定）')))
        new, alog = apply_edits(src, tgt, keep)
        parts.append(new)
        logs += [dict(x, chunk=cid) for x in log + alog]
        n_ok = sum(x['result'] == 'applied' for x in alog)
        print(f'check {cid} proposed={len(edits)} accepted={len(keep)} applied={n_ok}', flush=True)
    _write(work / 'check_log.jsonl', ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in logs))
    _write(work / 'check_failed.json', json.dumps(failed, ensure_ascii=False, indent=1))
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['chunk', 'pdf_page', 'severity', 'old', 'new', 'reason', 'second_model_why'])
    for h in human:
        w.writerow([h['chunk'], h.get('pdf_page'), h.get('severity'), h.get('old'), h.get('new'), h.get('reason', ''),
                    h.get('why', '')])
    _write(work / 'human_review_queue.csv', buf.getvalue())
    final = ''.join(p.rstrip('\n') + '\n' for p in parts)
    _same_pages(''.join(src_pg.values()), final, '核对合并')
    _write(work / 'checked.md', final)
    return final


def report(work: Path, src_pg: dict[int, str] | None = None, tgt: str | None = None) -> str:
    rows = []
    uf = work / 'usage.tsv'
    if uf.exists():
        agg: dict[tuple[str, str], list[float]] = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
        for ln in uf.read_text(encoding='utf-8').splitlines()[1:]:
            f = ln.split('\t')
            if len(f) < 7:
                continue
            stage = f[2].split('/')[1] if f[2].count('/') >= 1 else f[2]
            v = agg[(stage, f[1])]
            v[0] += 1
            for i, j in ((1, 3), (2, 4), (3, 5), (4, 6)):
                try:
                    v[i] += float(f[j] or 0)
                except ValueError:
                    pass
        rows.append('| 步骤 | 引擎 | 调用 | 输入 | 输出 | 缓存 | 秒 | 估算美元 |\n|---|---|---|---|---|---|---|---|')
        for (stage, eng), v in sorted(agg.items()):
            usd = ((v[1] * DS_PRICE['in'] + v[3] * DS_PRICE['cache'] + v[2] * DS_PRICE['out']) / 1e6
                   if eng.startswith('deepseek') else 0)
            rows.append(f'| {stage} | {eng} | {v[0]:.0f} | {v[1]:.0f} | {v[2]:.0f} | {v[3]:.0f} | {v[4]:.0f} | {usd:.3f} |')
    ds = work / 'draft_stats.json'
    if ds.exists():
        d = json.loads(ds.read_text(encoding='utf-8'))
        rows.append(f'\nGoogle：新请求 {d["requests"]}，失败 {len(d["failed"])}')
    ri = work / 'revise_issues.json'
    if ri.exists():
        iss = json.loads(ri.read_text(encoding='utf-8'))
        rows.append(f'\n改写后仍未过护栏的段：{len(iss)}')
        rows += [f'- {k}: {"; ".join(v)[:300]}' for k, v in iss.items()]
    cl = work / 'check_log.jsonl'
    if cl.exists():
        logs = [json.loads(x) for x in cl.read_text(encoding='utf-8').splitlines() if x.strip()]
        c = collections.Counter(x['result'].split(':')[0] for x in logs)
        nv = sum('第二模型' in x['result'] for x in logs)
        nq = sum(x['result'].startswith('queued') for x in logs)
        rows.append(f'\n意义核对：找错 {len(logs)} 处，第二模型否决 {nv}，落实 {c["applied"]}，'
                    f'护栏拒绝 {c["rejected"] - nv}，critical 转人工 {nq}（human_review_queue.csv）；'
                    f'提示词版本 {PROMPT_VERSION}（见 check_log.jsonl）')
    cf = work / 'check_failed.json'
    if cf.exists() and json.loads(cf.read_text(encoding='utf-8')):
        rows.append('\n**失败段（须重跑）**：' + '；'.join(json.loads(cf.read_text(encoding='utf-8'))))
    if src_pg and tgt:
        tp = pages(tgt)
        cand = [p for p in src_pg if p in tp and len(src_pg[p]) > 1200]
        sample = sorted(random.Random(1).sample(cand, k=min(8, len(cand))))
        _write(work / 'audit_sample.md', ''.join(f'# PDF p.{p}\n\n## Original\n{src_pg[p]}\n\n## Translation\n{tp[p]}\n\n'
                                                 for p in sample))
        rows.append(f'\n抽检页（交 Claude Sonnet 盲评）：{sample} → audit_sample.md')
    text = '# auto 档报告\n\n' + '\n'.join(rows) + '\n'
    _write(work / 'report.md', text)
    return text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['run', 'check', 'report'])
    ap.add_argument('src')
    ap.add_argument('tgt', nargs='?')
    ap.add_argument('-o', '--work', required=False)
    ap.add_argument('--sl', default='bg')
    ap.add_argument('--tl', default='en')
    ap.add_argument('--glossary')
    ap.add_argument('--names')
    ap.add_argument('--bad-terms', default='')
    ap.add_argument('--engine', default='auto', help='改写与找错：auto（按时段）或 llm_engines 引擎名')
    ap.add_argument('--day-engine', default=None, help='白天用的引擎（默认 revise=codex-luna；找错等到夜间）')
    ap.add_argument('--verify-engine', default='codex-sol',
                    help='第二模型裁定找错结果（须不同于找错模型；none = 不裁定，不推荐）')
    a = ap.parse_args(argv)
    if a.cmd == 'report':
        print(report(Path(a.src)))
        return
    work = Path(a.work or 'auto_work')
    src_pg = pages(Path(a.src).read_text(encoding='utf-8'))
    if a.cmd == 'run':
        dfile = work / 'draft.md'
        draft_pg = pages(dfile.read_text(encoding='utf-8')) if dfile.exists() else stage_draft(src_pg, work, a.sl, a.tl)
        revised = stage_revise(src_pg, draft_pg, work, a)
        final = stage_check(src_pg, pages(revised), work, a)
    else:
        if not a.tgt:
            ap.error('check 需要 TGT.md')
        final = stage_check(src_pg, pages(Path(a.tgt).read_text(encoding='utf-8')), work, a)
    print(report(work, src_pg, final))


if __name__ == '__main__':
    main()
