#!/usr/bin/env python3
"""auto 档：自动组合免费机翻与便宜模型，保质量、省 token。通用：任意源语言 → 任意目标语言
（--sl/--tl 用 Google 语言代码，如 bg、ru、de、fr、ja、la、zh-CN、en）；分类学文本的护栏（学名、数字、检索表）对所有语种都适用。

    python3 auto_translate.py run   SRC.md -o WORK --sl bg --tl en [--glossary G.md] [--names N.md] [--bad-terms setae,palpi]
    python3 auto_translate.py check SRC.md TGT.md -o WORK [--glossary ...]   # 只做意义核对（已有译文）
    python3 auto_translate.py report WORK

输入：Markdown，逐页 `<!-- PDF p.N ... -->` 标记；空行分段。原文与译文的页标记必须一一对应。

流程（依据 docs/model_bench.md「保加利亚文→英文：Google 稿改写的性价比比测」，2026-11-14）：
1 draft   Google gtx 免费初稿（逐段、4 路并发、sqlite 缓存）。页标记、无源语言字母的段（学名列表、引文）不送。
2 revise  3 页一段，对照原文改写 Google 稿。加 --lean：只改写 narrative,remarks（省 token）。引擎自动选择：北京时间夜间（22–8 点）deepseek-flash 关思考
          （比测重大错误 0，全书约 $0.25）；白天 codex-luna（流畅但会编造，之后必须走第 3 步）。
          只把本段用到的术语表、转写表条目送进提示词（省 token）；固定的规则放 system 前部，便于 DeepSeek 前缀缓存。
          护栏：页标记数、数字、斜体学名、检索表编号、异常文字（天城文等）、禁用词。不过护栏的段把问题清单发回重做一次，
          仍不过则取护栏问题更少的一份并在报告里标出。
3 check   意义核对：默认 --verify-engine none（Cursor 优化：质控至多 1 次 LLM；其余靠脚本护栏）。
          若显式开第二模型，则找错后由 --verify-engine 逐条 ACCEPT/REJECT，只落实两者都认可的
          （历史：Marinov 实测 flash 报 76、sol 认 12）。落实护栏：old 唯一、不丢数字/学名、new 不可暴涨。
          DeepSeek 夜间 wait_offpeak；白天可用 --day-engine。critical 一律进 human_review_queue.csv。
          Lean 默认开（只改写 narrative,remarks）；--engine none 为零模型档。
3b taxo   英文定稿按分类学排版补斜体（taxoformat.py，0 token）：属名/种加词/亚种/缩写/检索表/图注斜体，
          科名、命名人、sp./cf./aff. 正体；原文 OCR 不带斜体时也能补。规则见 docs/taxonomic_typography.md。
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
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根：transqa

import entities  # noqa: E402
import taxoformat  # noqa: E402
import transqa  # noqa: E402
from transqa import taxoblocks  # noqa: E402
from transqa import terms as transqa_terms  # noqa: E402
from transqa.blocks import PROTECTED, classify, deterministic, residue_left  # noqa: E402
from transqa.segments import render, segments_from_pages, split_template  # noqa: E402

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
PROMPT_VERSION = '2026-11-15d'  # 提示词或裁定规则改了就改这里；写进每段缓存与报告（可追溯）
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


def whole(pg: dict[int, str]) -> str:
    """按页序拼回整份文本（每页以换行结尾，页标记独占一行）。"""
    return ''.join(pg[p].rstrip('\n') + '\n' for p in sorted(pg))


def join(pg: dict[int, str], ps: list[int]) -> str:
    return '\n'.join(pg[p].rstrip('\n') for p in ps if p in pg) + '\n'


# ---------------------------------------------------------------- Google 初稿
class Google:
    """auto 档的 Google 初稿：底层统一用 gtrans.Google（同一缓存、并发预取、429 全体冷却、只用 urllib）。
    失败不再抛出整书中止：记入 failed，stage_draft 见 failed 非空即中止，重跑时只补失败段。"""

    def __init__(self, sl: str, tl: str, cache: Path) -> None:
        import gtrans
        self._gt = gtrans
        self.g = gtrans.Google(gtrans.Cache(cache), sl=sl, tl=tl, pause=(0.0, 0.0))
        self.failed: list[str] = []

    @property
    def requests(self) -> int:
        return int(self.g.requests)

    def one(self, s: str) -> str:
        try:
            out = str(self.g.translate(s))
        except self._gt.GoogleError:
            self.failed.append(s[:80])
            return s
        if not out.strip():          # 空译文会让 render 少一段、段 ID 错位；退回原文并记失败
            self.failed.append(s[:80])
            return s
        return out

    def body(self, p: str) -> str:
        return '\n'.join(ln for ln in p.split('\n') if not ln.lstrip().startswith('<!--')).strip()

    def para(self, p: str, src_re: str) -> str:
        lines = p.split('\n')
        head = [ln for ln in lines if ln.lstrip().startswith('<!--')]
        body = self.body(p)
        if not body or not re.search(src_re, body):
            return p
        return '\n'.join(head + [self.one(body)])

    def text(self, t: str, src_re: str, workers: int = 8) -> str:
        paras = [p.strip() for p in t.split('\n\n')]
        self.g.prefetch([self.body(p) for p in paras if re.search(src_re, self.body(p))], workers)
        return '\n\n'.join(self.para(p, src_re) for p in paras) + '\n'


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
    """数字计数：与共用 QA 同一规则（千分位并合、小数逗号=小数点），保证护栏与落实改动的判断一致。"""
    return transqa.core.numbers(t)


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
    """原文 vs 译文的阻断问题（critical/major）说明列表；空 = 通过。实现在共用 QA 层 transqa（通用 + 分类学插件）。"""
    return [i.message for i in transqa.check_all(src, tgt, sl or 'und', tl, bad_terms=bad_terms) if i.blocking]


# ---------------------------------------------------------------- 引擎选择
def is_night(now: dt.datetime | None = None) -> bool:
    """DeepSeek 可调用时段（名字沿用「夜间」）：由 deepseek_offpeak 决定（默认避开官方工作日忙时）。"""
    from deepseek_offpeak import is_peak
    return not is_peak(now)


def pick_engine(task: str, now: dt.datetime | None = None, day_engine: str | None = None) -> str:
    """revise：夜间 deepseek-flash，白天 codex-luna。check：deepseek-flash（白天除非给 day_engine，否则等夜间）。"""
    if is_night(now):
        return 'deepseek-flash'
    if task == 'revise':
        return day_engine or 'codex-luna'
    return day_engine or 'deepseek-flash'


def llm(engine: str, system: str, user: str, tag: str, usage_file: Path,
        profile: str = 'default') -> tuple[str, dict[str, Any]]:
    import llm_engines
    if engine.startswith('deepseek'):
        os.environ.pop('YZZ_DEEPSEEK_THINKING', None)  # 比测：开思考不提质，费用约 4 倍
    return llm_engines.call(engine, system, user, profile=profile, tag=tag, usage_file=str(usage_file))


# ---------------------------------------------------------------- 提示词
REVISE_SYS = """You revise a Google machine translation of a scientific taxonomic text from {sl} into {tl}.
Input: segments, each introduced by an ID line like ⟦p103_s2⟧ followed by ORIGINAL: and DRAFT: lines.
Output ONLY the revised {tl} text of every segment, each introduced by its ID on its own line:
⟦p103_s2⟧
revised text
Return every ID exactly once, in the same order. Never write ⟦ or ⟧ inside a segment's text.
No commentary, no original text, no notes about your changes.
Faithful means the SAME MEANING, not the same form: information, logical relations, argument direction, emphasis,
degree of certainty and reference must match the original; word order, sentence division, parts of speech and voice
should be rearranged freely so the result reads like a native scientific text. Word-for-word renderings are not faithful.
Proper names with established renderings (book titles, people, institutions, places, named theories) use those renderings,
never a word-by-word translation; if none exists keep the original.
Rules:
1. Nothing omitted, nothing added. Keep every number, couplet number such as 1(2), plate/figure reference,
   Latin name, author and year exactly as in the original (also the original's own misspellings and abbreviations,
   e.g. *H. filiformis* stays abbreviated). Keep *italics*, Markdown heading marks (#) and the dotted leaders …… of keys.
   Keep figure sub-labels (1а, 2б) in the original's letters.
2. Terminology: use the glossary and names table below; one source term = one rendering. Standard taxonomic usage.
3. Style: natural descriptive taxonomic {tl} (telegraphic descriptions as "Body short and thin.", not "The body short").
   Rewrite every segment against the original; the Google draft is only a draft.
4. Never write characters of any other script; translator's notes as [TN: ...] in {tl}."""

VERIFY_SYS = """You are the independent second reviewer of a {tl} translation of a {sl} taxonomic text.
1. Read the WHOLE translation against the original, sentence by sentence (not only the proposed fixes).
2. For every proposed fix (from another model) decide: ACCEPT only if it makes the translation more faithful;
   REJECT if it is wrong, unnecessary, merely stylistic, or "corrects" the original author's own misprint.
3. Report meaning errors the other model missed as new fixes (smallest fix; severity critical/major/minor).
Output ONLY a JSON array of objects: one {{"id": N, "verdict": "ACCEPT"|"REJECT", "why": "short"}} per proposed id;
{{"new_fix": true, "pdf_page": N, "old": "exact substring", "new": "...", "severity": "...", "reason": "..."}} per
missed error; and exactly one {{"receipt": true, "pages": [all pdf pages you reviewed]}}."""

CHECK_SYS = """You check a {tl} translation against its {sl} original (a taxonomic text), sentence by sentence.
Report ONLY real meaning errors: wrong meaning, omission, addition, wrong number/name/couplet, reversed negation or
comparison, mistranslated technical term, proper name translated word by word instead of its established rendering.
Faithful means same meaning, not same form: do NOT report free restructuring, changed word order or sentence division
when the meaning is preserved. Ignore style. For each error give the smallest fix and a severity:
critical = Latin name, number, specimen/plate number, present/absent reversed, key couplet or lead-to wrong;
major = body part, count, comparison, diagnostic character mistranslated; minor = term usage without change of meaning.
Do not "correct" the original author's own misprints.
Procedure (every page, in order): (a) align each original sentence with its translation; (b) compare numbers, counts
("pair(s)", "two", "half", "twice"), negation/absence, comparisons (longer/shorter, more/fewer), the body part, and which
taxon a statement is about; (c) before reporting, confirm the meaning of each original word involved - if you are not
sure what an original word means, do NOT report it. A false report is worse than a missed one: a second model reviews
every page anyway.
REAL error (report): original says "without eyes", translation says "with eyes" (negation lost).
NON-errors (never report): sentence restructured with the same meaning; a translator's note [TN: ...]; British vs
American spelling; a term rendered as the glossary prescribes.
Output ONLY a JSON array (possibly empty): [{{"pdf_page": N,
"old": "exact substring of the translation, unique on that page, at most one sentence", "new": "corrected substring",
"severity": "critical|major|minor", "reason": "short"}}] plus exactly one {{"receipt": true, "pages": [every pdf page
you checked]}}."""

JUDGE_SYS = """You check proposed corrections to a {tl} translation of a {sl} taxonomic text. You do NOT search for new
errors. For each proposed fix answer four small questions; a script derives the verdict from your answers.
1. "quote": copy the exact original ({sl}) words that the old text translates (verbatim from the Original section).
2. "key": dictionary meaning of the key original word(s), e.g. "word = meaning; word2 = meaning2".
   Judge against the ORIGINAL only - never against the rest of the translation.
3. "old_faithful": true if the OLD text says the same as the quote (free restructuring is fine), else false.
4. "new_faithful": true if the NEW text says the same as the quote, else false.
If you cannot establish the meaning of a key word, set both to null.
Output ONLY a JSON array: [{{"id": N, "quote": "...", "key": "...", "old_faithful": true|false|null,
"new_faithful": true|false|null, "why": "short"}}]."""


STABLE_LIMIT = 150_000  # 稳定前缀（规则+全书术语+转写表）超过此字符数时，术语表改为逐段只送相关条目


def stable_prefix(base: str, gl: list[tuple[str, str]], nm: list[tuple[str, str]],
                  limit: int | None = None) -> tuple[str, bool]:
    """L1 规则 + L2 全书术语表/转写表：整本书字节不变，放在 system 最前，供 DeepSeek/OpenAI 前缀缓存命中。
    返回 (system, 是否已含术语表)。术语表过大时只放规则与转写表，术语表退回逐段相关条目（L4）。
    Lean 模式用更小 limit（token_economy.LEAN_STABLE_LIMIT），逼术语表走逐段相关条目。"""
    cap = STABLE_LIMIT if limit is None else limit
    full = f'{base}\n\n## Glossary (whole book)\n{table_md(gl)}\n\n## Names / transliteration\n{table_md(nm)}'
    if len(full) <= cap:
        return full, True
    return f'{base}\n\n## Names / transliteration\n{table_md(nm)}', False


def revise_user(items: list[tuple[str, str, str]], extra_gl: list[tuple[str, str]] | None, probs: list[str],
                names: str = '') -> str:
    """L4（每段变化的部分，放在最后）：待改写段 (ID, 原文, Google 稿)；本段专名表（entities.py 解析）。"""
    u = ''
    if names and names != '（无）':
        u += f'## Proper names in this chunk (use these established renderings; never translate them word by word)\n{names}\n\n'
    if extra_gl is not None:
        u += f'## Glossary entries for this chunk\n{table_md(extra_gl)}\n\n'
    u += '## Segments\n' + '\n\n'.join(f'⟦{sid}⟧\nORIGINAL: {s}\nDRAFT: {d}' for sid, s, d in items)
    if probs:
        u += '\n\n## Your previous output failed these checks; fix them\n' + '\n'.join(f'- {p}' for p in probs)
    return u


ID_RE = re.compile(r'⟦(p\d+_s\d+)⟧')


def parse_segments(text: str) -> tuple[dict[str, str], list[str]]:
    """模型输出 → ({段ID: 译文}, 重复出现的 ID)。重复视为格式错误由调用方重试。"""
    parts = ID_RE.split(text)
    out: dict[str, str] = {}
    dups: list[str] = []
    for k in range(1, len(parts) - 1, 2):
        if parts[k] in out:
            dups.append(parts[k])
        else:
            out[parts[k]] = parts[k + 1].strip()
    return out, dups


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
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        return None  # 混入非对象（如 [1, "unexpected"]）= 格式错，不能当成「无错」
    return v


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


def risky_filter(src_pg: dict[int, str], tgt_pg: dict[int, str], sl: str, tl: str,
                 terms: list[tuple[str, str]] | None = None,
                 rewritten_pages: set[int] | None = None) -> tuple[dict[int, str], dict[int, str], dict]:
    """Select aligned risky paragraphs; counts and characters refer to source paragraphs.

    Paragraph-count mismatches retain the original whole page. Templates preserve
    page markers and other non-paragraph material on retained pages.
    """
    src_out: dict[int, str] = {}
    tgt_out: dict[int, str] = {}
    stats: dict[str, Any] = dict(pages_in=len(src_pg), pages_kept=0, paras_in=0, paras_kept=0,
                                 chars_in=0, chars_kept=0, by_reason=collections.Counter())
    for p, src in src_pg.items():
        tgt = tgt_pg[p]
        ss, st = split_template(src)
        ts, tt = split_template(tgt)
        stats['paras_in'] += len(ss)
        stats['chars_in'] += sum(len(s.text) for s in ss)
        if len(ss) != len(ts):
            src_out[p], tgt_out[p] = src, tgt
            stats['paras_kept'] += len(ss)
            stats['chars_kept'] += sum(len(s.text) for s in ss)
            continue
        sm, tm = {}, {}
        for s, t in zip(ss, ts):
            reasons = taxoblocks.risk(s.text, t.text, sl, tl, p in (rewritten_pages or ()), terms)
            stats['by_reason'].update(reasons)
            if reasons or taxoblocks.kind(s.text, sl) in {'narrative', 'remarks'}:
                sm[s.id], tm[t.id] = s.text, t.text
                stats['paras_kept'] += 1
                stats['chars_kept'] += len(s.text)
        if sm:
            src_out[p] = render([(k, v) for k, v in st if k != 'seg' or v in sm], sm)
            tgt_out[p] = render([(k, v) for k, v in tt if k != 'seg' or v in tm], tm)
    stats['pages_kept'] = len(src_out)
    return src_out, tgt_out, stats


def stage_draft(src_pg: dict[int, str], work: Path, sl: str, tl: str) -> dict[int, str]:
    """Google 初稿。按 transqa 模板逐段处理，保证初稿与原文段 ID 一一对应；
    异名录/文献/索引块不送 Google（改写阶段走确定性处理）。全书先并发预取，再顺序拼回。"""
    g = Google(sl, tl, Path.home() / '.cache/yzz-translate/gtrans_cache.sqlite')
    src_re = SCRIPT_RE.get(sl, r'\w')
    split = {p: split_template(src_pg[p]) for p in sorted(src_pg)}
    send = [s.text for segs, _ in split.values() for s in segs
            if classify(s.text, sl) not in PROTECTED and re.search(src_re, s.text)]
    g.g.prefetch(send, 8)
    out = {}
    for p, (segs, tpl) in split.items():
        texts = {s.id: (g.one(s.text) if s.text in send else s.text) for s in segs}
        out[p] = render(tpl, texts).rstrip('\n') + '\n'
    _write(work / 'draft_stats.json', json.dumps({'requests': g.requests, 'failed': g.failed,
                                                  'segments': sum(len(x[0]) for x in split.values()),
                                                  'sent_to_google': len(send)}, ensure_ascii=False))
    if g.failed:
        raise SystemExit(f'Google 有 {len(g.failed)} 段失败（见 draft_stats.json）；重跑即可，成功段已缓存')
    _write(work / 'draft.md', ''.join(out[p] for p in sorted(out)))
    return out


def chunk_entities(src: str, cid: str, work: Path, a: argparse.Namespace) -> list[dict[str, Any]]:
    """本段专名：便宜模型抽取 + yiku/Wikidata 解析（entities.py），按原文摘要缓存。
    --no-entities 关闭；--engine none（零模型档）也跳过，避免暗中烧 token / 依赖 anthropic。"""
    if not getattr(a, 'entities', True):
        return []
    if getattr(a, 'engine', '') == 'none':
        return []
    f = work / f'entities/{cid}.json'
    dg = _digest(src, a.tl, entities.EXTRACT_SYS)
    if f.exists():
        rec = json.loads(f.read_text(encoding='utf-8'))
        if rec.get('digest') == dg:
            return list(rec['entities'])
    try:
        eng = 'codex-luna' if not is_night() else 'deepseek-flash'
        res = entities.resolve(entities.extract(src, eng, work), getattr(a, 'domain', '进化生物学'))
    except Exception as exc:  # noqa: BLE001 - 专名解析失败不阻断改写，只记入报告
        print(f'[auto] {cid} 专名解析失败：{str(exc)[-120:]}', flush=True)
        return []
    _write(f, json.dumps({'digest': dg, 'entities': res}, ensure_ascii=False, indent=1))
    return res


def repair_draft_pages(src_pg: dict[int, str], draft_pg: dict[int, str], ps: list[int],
                       work: Path, a: argparse.Namespace) -> list[int]:
    """修复旧初稿里因 Google 空响应/空行而少段的页：只重译这些页，按原文模板逐段生成。
    返回被修复的页号；正常页不动，避免整书重跑。"""
    bad = [p for p in ps
           if len(segments_from_pages(draft_pg.get(p, ''))) != len(split_template(src_pg[p])[0])]
    if not bad:
        return []
    g = Google(a.sl, a.tl, Path.home() / '.cache/yzz-translate/gtrans_cache.sqlite')
    for p in bad:
        segs, tpl = split_template(src_pg[p])
        texts = {s.id: g.one(s.text) for s in segs}
        draft_pg[p] = render(tpl, texts).rstrip('\n') + '\n'
    _write(work / 'draft.md', whole(draft_pg))
    print(f'[auto] 修复初稿页 {bad}（Google 空响应/空行导致段数不一致）', flush=True)
    return bad


def _revise_one_llm(job: dict[str, Any], work: Path, a: argparse.Namespace, sysmsg: str,
                    gl_in_prefix: bool, gl: list[tuple[str, str]], bad: list[str]) -> dict[str, Any]:
    """对单块调模型改写（可并行）。job 已在串行准备阶段填好 texts/todo/digest；产物写 revise/<cid>.json。"""
    cid, src, tpl, texts, todo, dmap, engine, dg = (
        job['cid'], job['src'], job['tpl'], job['texts'], job['todo'], job['dmap'], job['engine'], job['dg'])
    rec = _cached(work / f'revise/{cid}.json', dg)
    if rec is not None:
        return rec
    extra = None if gl_in_prefix else relevant(gl, src)
    items = [(s.id, s.text, dmap[s.id]) for s in todo]
    best: dict[str, str] = {s.id: dmap[s.id] for s in todo}
    best_p = guard(src, render(tpl, {**texts, **best}), bad, a.tl, a.sl)
    best_is_draft = True
    probs: list[str] = []
    attempts = 0
    ents = chunk_entities(src, cid, work, a) if todo else []
    names = entities.table_md(ents) if ents else ''
    model_todo = [] if engine == 'none' else list(todo)
    for attempt in range(2) if model_todo else []:
        attempts += 1
        ru = revise_user(items, extra, probs, names)
        out_text, _ = llm(engine, sysmsg, ru, f'auto/revise/{cid}/{attempt}',
                          work / 'usage.tsv', profile='revise')
        got, dups = parse_segments(out_text)
        want = [s.id for s in model_todo]
        miss, extra_ids = [x for x in want if x not in got], [x for x in got if x not in want]
        cand = {sid: got.get(sid, best[sid]) for sid in want}
        probs = guard(src, render(tpl, {**texts, **cand}), bad, a.tl, a.sl)
        probs += [x['message'] for x in entities.check(src, render(tpl, {**texts, **cand}), ents)
                  if x['severity'] == 'major']
        if miss:
            probs.append(f'缺段 ID {miss[:10]}（每个 ID 都要返回）')
        if extra_ids:
            probs.append(f'多出未请求的 ID {extra_ids[:10]}')
        if dups:
            probs.append(f'ID 重复 {dups[:10]}')
        complete = not miss and not dups
        if complete and (best_is_draft or len(probs) <= len(best_p)):
            best, best_p, best_is_draft = cand, probs, False
        if not probs:
            break
    if model_todo and best_is_draft:
        best_p = best_p + ['模型两次都未返回完整的段 ID，本段保留 Google 初稿']
    rec = {'digest': dg, 'status': 'ok', 'engine': engine, 'attempts': attempts, 'texts': best,
           'issues': best_p, 'prompt_version': PROMPT_VERSION}
    _write(work / f'revise/{cid}.json', json.dumps(rec, ensure_ascii=False, indent=1))
    print(f'revise {cid} {engine} segs={job["n_segs"]} model={len(model_todo)} attempts={attempts} '
          f'issues={len(best_p)}', flush=True)
    return rec


def stage_revise(src_pg: dict[int, str], draft_pg: dict[int, str], work: Path, a: argparse.Namespace) -> str:
    """3 页一段改写。串行准备（术语规范化、块分流、修初稿）→ 并行调模型（--workers）→ 按块序合并。
    每块只写自己的 revise/<cid>.json，不共享可变状态。"""
    from concurrent.futures import ThreadPoolExecutor
    from token_economy import LEAN_STABLE_LIMIT
    gl, nm = load_table(a.glossary), load_table(a.names)
    lib = transqa_terms.load(a.glossary) if a.glossary else []
    abbr = dict(load_table(getattr(a, 'abbr', None)))
    bad = [w for w in (a.bad_terms or '').split(',') if w]
    lim = LEAN_STABLE_LIMIT if getattr(a, 'lean', False) else None
    sysmsg, gl_in_prefix = stable_prefix(REVISE_SYS.format(sl=a.sl, tl=a.tl), gl, nm, limit=lim)
    kinds = {k.strip() for k in (getattr(a, 'rewrite_kinds', '') or '').split(',') if k.strip()}
    engine = a.engine if a.engine != 'auto' else pick_engine('revise', day_engine=a.day_engine)
    stats: collections.Counter[str] = collections.Counter()
    jobs: list[dict[str, Any]] = []
    for k, ps in enumerate(chunks_of(src_pg)):
        cid = f'c{k:03d}'
        src, draft = join(src_pg, ps), join(draft_pg, ps)
        _same_pages(src, draft, f'{cid} 初稿')
        segs, tpl = split_template(src)
        dmap = {s.id: s.text for s in segments_from_pages(draft)}
        smap = {s.id: s.text for s in segs}
        for sid in list(dmap):
            if sid in smap:
                dmap[sid], tlog = transqa_terms.normalize(smap[sid], dmap[sid], lib)
                stats['term_fixes'] += sum(n for _, _, n in tlog)
        if set(dmap) != {s.id for s in segs}:
            repair_draft_pages(src_pg, draft_pg, ps, work, a)
            dmap = {s.id: s.text for s in segments_from_pages(join(draft_pg, ps))}
        if set(dmap) != {s.id for s in segs}:
            raise ValueError(f'{cid} 初稿与原文段 ID 不一致（缺 {sorted({s.id for s in segs} - set(dmap))[:5]}）')
        texts: dict[str, str] = {}
        todo = []
        for s in segs:
            if kinds:
                tk = taxoblocks.kind(s.text, a.sl)
                stats[f'kind_{tk}'] += 1
                if tk == 'junk':
                    texts[s.id] = s.text
                    stats['junk_kept'] += 1
                    continue
                if tk not in kinds and classify(s.text, a.sl) not in PROTECTED:
                    texts[s.id] = dmap[s.id]
                    stats['google_kept'] += 1
                    continue
            if classify(s.text, a.sl) in PROTECTED:
                d = deterministic(s.text, a.sl, nm, abbr)
                if not residue_left(d, a.sl):
                    texts[s.id] = d
                    stats['deterministic'] += 1
                    continue
                stats['fallback_to_model'] += 1
            todo.append(s)
        stats['segments'] += len(segs)
        # lean 候选段数；engine=none 时不会真调模型（见 llm_calls）
        stats['sent_to_model'] += len(todo) if engine != 'none' else 0
        stats['lean_candidates'] += len(todo)
        dg = _digest(src, '\n'.join(dmap.values()), sysmsg, PROMPT_VERSION, engine, ','.join(bad),
                     json.dumps(abbr, ensure_ascii=False), ','.join(sorted(kinds)),
                     '' if gl_in_prefix else table_md(relevant(gl, src)))
        jobs.append({'cid': cid, 'src': src, 'tpl': tpl, 'texts': texts, 'todo': todo, 'dmap': dmap,
                     'engine': engine, 'dg': dg, 'n_segs': len(segs)})
    workers = max(1, int(getattr(a, 'workers', 1) or 1))
    if workers == 1 or len(jobs) <= 1:
        recs = [_revise_one_llm(j, work, a, sysmsg, gl_in_prefix, gl, bad) for j in jobs]
    else:
        print(f'[auto] revise 并行 {workers} 路 × {len(jobs)} 块', flush=True)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_revise_one_llm, j, work, a, sysmsg, gl_in_prefix, gl, bad) for j in jobs]
            recs = [f.result() for f in futs]
    issues, parts = {}, []
    for job, rec in zip(jobs, recs, strict=True):
        stats['attempts'] += int(rec.get('attempts', 0))
        stats['llm_calls'] += int(rec.get('attempts', 0))
        stats['chunks_reworked'] += int(rec.get('attempts', 0) > 1)
        stats['chunks'] += 1
        chunk = render(job['tpl'], {**job['texts'], **rec['texts']}).rstrip('\n') + '\n'
        if rec['issues']:
            issues[job['cid']] = rec['issues']
        parts.append(chunk)
    if engine == 'none':
        stats['llm_calls'] = 0
        print(f'[auto] engine=none：llm_calls=0（lean 候选段 {stats["lean_candidates"]} 保留 Google+术语表）',
              flush=True)
    _write(work / 'revise_issues.json', json.dumps(issues, ensure_ascii=False, indent=1))
    _write(work / 'revise_stats.json', json.dumps(dict(stats), ensure_ascii=False, indent=1))
    revised = ''.join(parts)
    _same_pages(whole(src_pg), revised, '改写合并')
    _write(work / 'revised.md', revised)
    return revised


def _ask_json(engine: str, system: str, user: str, tag: str, work: Path) -> list[dict[str, Any]] | None:
    """调用并解析 JSON 数组；格式错或引擎连接失败都重试，最终失败返回 None（该段记为失败，不中断全书）。"""
    for attempt in range(3):
        try:
            text, _ = llm(engine, system, user, f'{tag}/{attempt}', work / 'usage.tsv', profile='json')
        except Exception as exc:  # noqa: BLE001 - 引擎网络/额度错误：等一会重试
            print(f'[auto] {engine} 调用失败（{type(exc).__name__}: {str(exc)[-120:]}），第 {attempt + 1}/3 次', flush=True)
            time.sleep(30 * (attempt + 1))
            continue
        v = parse_json_array(text)
        if v is not None:
            return v
    return None


def load_pitfalls(sl: str, tl: str, path: str | None = None) -> str:
    """语言对陷阱表（skill/pitfalls/{sl}-{tl}.md）+ 项目自定（--pitfalls）。给廉价模型的「已知会错的地方」与正反示例。

    来源：已被两模型或人工判定的真实误报 / 漏报（例：bg 的 чифт/цифт = pair，廉价模型曾把 12 处「pairs」删掉）。"""
    out = []
    default = Path(__file__).resolve().parent.parent / 'skill' / 'pitfalls' / f'{sl}-{tl}.md'
    for f in (default, Path(path) if path else None):
        if f and f.exists():
            out.append(f.read_text(encoding='utf-8').strip())
    return '\n\n'.join(out)


_QUOTES = {'"': '["“”„«»]', '“': '["“”„«»]', '”': '["“”„«»]', "'": "['‘’]", '‘': "['‘’]", '’': "['‘’]"}


def fit_old(seg: str, old: str) -> str | None:
    """模型引用的 old 与页面原文只差引号样式或空白时，找回页面上的真实子串（唯一才算）。"""
    if seg.count(old) == 1:
        return old
    pat = ''.join(_QUOTES.get(ch, r'\s+' if ch.isspace() else re.escape(ch)) for ch in old.strip())
    pat = re.sub(r'(\\s\+)+', r'\\s+', pat)
    hits = re.findall(pat, seg) if pat else []
    return hits[0] if len(hits) == 1 else None


def _norm_ws(t: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[„“”"«»‘’\'*]', '', t)).strip().lower()


def judge_verdict(v: dict[str, Any] | None, src: str) -> str:
    """judge 模式：模型只答原子问题（引原文、释词、旧/新是否忠实），裁定由脚本推出。
    引文不在原文 → UNSURE（没找对句子）；新忠实且旧不忠实 → ACCEPT；旧忠实 → REJECT（不必改）；其余 → UNSURE。"""
    if not v:
        return ''
    q = _norm_ws(str(v.get('quote', '')))
    if len(q) < 3 or q not in _norm_ws(src):
        return 'UNSURE'
    old_ok, new_ok = v.get('old_faithful'), v.get('new_faithful')
    if new_ok is True and old_ok is False:
        return 'ACCEPT'
    if old_ok is True:
        return 'REJECT'
    return 'UNSURE'


def _prefilter(tgt: str, edits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """复核前的确定性过滤（0 token）：old 必须在该页唯一出现（容忍引号样式、空白差异）、且与 new 不同；
    不合格的不送第二模型。"""
    pt = pages(tgt)
    good, bad = [], []
    for e in edits:
        pn = _page_no(e.get('pdf_page'))
        seg = pt.get(pn) if pn is not None else None
        real = fit_old(seg, str(e.get('old', ''))) if seg and e.get('old') else None
        if real:
            e = dict(e, old=real)
        old = str(e.get('old', ''))
        if not old or old == str(e.get('new', '')):
            bad.append(dict(e, result='rejected: old 为空或无变化（预过滤）'))
        elif not real:
            bad.append(dict(e, result=f'rejected: old 不在第 {pn} 页或不唯一（预过滤，未送复核）'))
        else:
            good.append(e)
    return good, bad


def _check_chunk(k: int, ps: list[int], src_pg: dict[int, str], tgt_pg: dict[int, str], work: Path,
                 a: argparse.Namespace, csys: str, vsys: str, gl: list[tuple[str, str]],
                 gl_in_prefix: bool, full_src: dict[int, str], full_tgt: dict[int, str]) -> dict[str, Any]:
    cid = f'c{k:03d}'
    src, tgt = join(src_pg, ps), join(tgt_pg, ps)
    _same_pages(src, tgt, f'{cid} 核对')
    gtab = '' if gl_in_prefix else table_md(relevant(gl, src))
    failed: list[str] = []
    human: list[dict[str, Any]] = []
    # 1 找错
    risk = negation_risk(src, tgt, a.sl, a.tl)
    engine = a.engine if a.engine != 'auto' else pick_engine('check', day_engine=a.day_engine)
    # 零模型档：不调 LLM，只保留稿 + 后面的 transqa/taxoformat（脚本）
    if engine == 'none':
        print(f'check {cid} engine=none skipped_llm risk_pages={risk}', flush=True)
        return {'new': join(full_tgt, ps), 'log': [{'chunk': cid, 'result': 'skipped: engine=none'}],
                'failed': failed, 'human': human}
    dg = _digest(src, tgt, gtab, csys, engine, PROMPT_VERSION, str(getattr(a, 'risky_only', False)))   # 换模型必须重跑，不得复用别的模型的结果
    rec = _cached(work / f'check/{cid}.json', dg)
    if rec is None:
        if (a.verify_engine not in ('none', '') and engine == a.verify_engine
                and not getattr(a, 'allow_same_verify', False)):
            raise ValueError(f'找错模型与复核模型相同（{engine}）：异模型原则不允许，改 --verify-engine'
                             f'（同模型复核须加 --allow-same-verify；默认 verify=none 不做第二轮）')
        user = (f'## Glossary entries for this chunk\n{gtab}\n\n' if gtab else '') + \
            f'## Original\n{src}\n\n## Translation\n{tgt}'
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
    raw = [e for e in rec['edits'] if isinstance(e, dict)]
    f_receipt = {int(p) for r in raw if r.get('receipt') for p in r.get('pages', []) if _page_no(p) is not None}
    edits, pre_bad = _prefilter(tgt, [dict(e, id=i) for i, e in enumerate(x for x in raw if not x.get('receipt'))])
    judge = getattr(a, 'verify_mode', 'review') == 'judge'
    if judge and rec['status'] == 'ok' and not set(ps) <= f_receipt:
        failed.append(f'{cid} 找错模型回执缺页 {sorted(set(ps) - f_receipt)}（judge 模式下视为未核对）')
    # 2 第二模型裁定
    verdicts: dict[int, dict[str, Any]] = {}
    log: list[dict[str, Any]] = list(pre_bad)
    if a.verify_engine != 'none' and not (judge and not edits):
        # review：第二模型逐段全文复核（即使第一模型没报错）并出覆盖回执；judge：只逐条裁定（窄任务，给廉价模型）
        pit_at = vsys.find('\n\n## Known pitfalls')
        vsys_ = (JUDGE_SYS.format(sl=a.sl, tl=a.tl) + (vsys[pit_at:] if pit_at >= 0 else '')) if judge else vsys
        vd = _digest(src, tgt, json.dumps(edits, ensure_ascii=False), vsys_, a.verify_engine, PROMPT_VERSION, str(getattr(a, 'risky_only', False)))
        vrec = _cached(work / f'verify/{cid}.json', vd)
        if vrec is None:
            user = f'## Original\n{src}\n\n## Translation\n{tgt}\n\n## Proposed fixes\n' + ('\n'.join(
                json.dumps({k2: e[k2] for k2 in ('id', 'pdf_page', 'old', 'new', 'reason') if k2 in e},
                           ensure_ascii=False) for e in edits) or '(none)')
            v = _ask_json(a.verify_engine, vsys_, user, f'auto/verify/{cid}', work)
            vrec = {'digest': vd, 'engine': a.verify_engine, 'prompt_version': PROMPT_VERSION,
                    'status': 'ok' if v is not None else 'parse_failed',
                    'verdicts': v or []}
            _write(work / f'verify/{cid}.json', json.dumps(vrec, ensure_ascii=False, indent=1))
        if vrec['status'] != 'ok':
            failed.append(f'{cid} 裁定输出无法解析（本段改动全部不落实）')
        verdicts = {int(x['id']): x for x in vrec['verdicts'] if _page_no(x.get('id')) is not None}
        extra = [x for x in vrec['verdicts'] if x.get('new_fix')]
        receipt = [x for x in vrec['verdicts'] if x.get('receipt')]
        seen = {int(p) for r in receipt for p in r.get('pages', []) if _page_no(p) is not None}
        # 同一模型的两遍（--allow-same-verify，用户 2026-11-17 的 DeepSeek-only 政策）不再要求
        # 「另一模型已通读全书」的回执：两遍共用同一上下文，回执不能再证明独立覆盖。
        if vrec['status'] == 'ok' and not judge and a.verify_engine != engine and not set(ps) <= seen:
            failed.append(f'{cid} 第二模型复核回执缺页 {sorted(set(ps) - seen)}（视为未复核）')
        for x in extra:   # 第二模型独有的发现：单模型意见，不自动落实，进人工队列
            human.append(dict(x, chunk=cid, verdict='SECOND_MODEL_ONLY', why=x.get('reason', '')))
            log.append(dict(x, result='queued: 仅第二模型发现，须人工裁定'))
    keep: list[dict[str, Any]] = []
    for e in edits:
        vd_ = verdicts.get(e["id"])
        verdict = judge_verdict(vd_, src) if judge else str((vd_ or {}).get('verdict', '')).upper()
        ok = a.verify_engine == 'none' or verdict == 'ACCEPT'
        if verdict == 'UNSURE':
            human.append(dict(e, chunk=cid, verdict='UNSURE', why=f"{(vd_ or {}).get('key', '')}; {(vd_ or {}).get('why', '')}"))
            log.append(dict(e, result='queued: 裁定模型没把握，须人工'))
        elif ok and str(e.get('severity', '')).lower() == 'critical':
            human.append(dict(e, chunk=cid, verdict='ACCEPT', why=(vd_ or {}).get('why', '')))
            log.append(dict(e, result='queued: critical，须人工对照扫描件'))
        elif ok:
            keep.append(e)
        else:
            log.append(dict(e, result='rejected: 第二模型未认可' + (f"（{vd_.get('why', '')}）" if vd_ else '（无裁定）')))
    new, alog = apply_edits(join(full_src, ps), join(full_tgt, ps), keep)
    n_ok = sum(x['result'] == 'applied' for x in alog)
    print(f'check {cid} proposed={len(edits) + len(pre_bad)} prefiltered_out={len(pre_bad)} '
          f'accepted={len(keep)} applied={n_ok}', flush=True)
    return {'new': new, 'log': [dict(x, chunk=cid) for x in log + alog], 'failed': failed, 'human': human}


def stage_check(src_pg: dict[int, str], tgt_pg: dict[int, str], work: Path, a: argparse.Namespace) -> str:
    """找错（check_engine）→ 确定性预过滤 → 第二模型裁定（verify_engine，须不同于找错模型）→ 护栏落实。
    只落实两者都认可的改动。各块互相独立，--workers 并行（结果按块序合并，断点续跑照旧）。"""
    from concurrent.futures import ThreadPoolExecutor
    from token_economy import LEAN_STABLE_LIMIT
    gl = load_table(a.glossary)
    base = CHECK_SYS.format(sl=a.sl, tl=a.tl)
    pit = load_pitfalls(a.sl, a.tl, getattr(a, 'pitfalls', None))
    if pit:
        base += f'\n\n## Known pitfalls for this language pair (verified; obey them)\n{pit}'
    lim = LEAN_STABLE_LIMIT if getattr(a, 'lean', False) else None
    csys, gl_in_prefix = stable_prefix(base, gl, [], limit=lim)   # 全书术语表进稳定前缀；Lean 则逐段相关条目
    vsys = VERIFY_SYS.format(sl=a.sl, tl=a.tl) + (f'\n\n## Known pitfalls for this language pair (verified)\n{pit}'
                                                  if pit else '')
    os.environ.setdefault('YZZ_CODEX_EFFORT', 'medium')
    full_src, full_tgt = src_pg, tgt_pg
    _same_pages(whole(src_pg), whole(tgt_pg), '核对输入')
    if getattr(a, 'risky_only', False):
        src_pg, tgt_pg, stats = risky_filter(src_pg, tgt_pg, a.sl, a.tl, terms=gl)
        pct = 100 * stats['chars_kept'] / max(1, stats['chars_in'])
        print(f"risky-only kept {stats['paras_kept']}/{stats['paras_in']} paragraphs ({pct:.0f}% chars)", flush=True)
    jobs = list(enumerate(chunks_of(src_pg)))
    with ThreadPoolExecutor(max_workers=max(1, getattr(a, 'workers', 1))) as ex:
        res = list(ex.map(lambda kp: _check_chunk(kp[0], kp[1], src_pg, tgt_pg, work, a, csys, vsys, gl,
                                                  gl_in_prefix, full_src, full_tgt), jobs))
    parts = [r['new'] for r in res]
    logs = [x for r in res for x in r['log']]
    failed = [x for r in res for x in r['failed']]
    human = [x for r in res for x in r['human']]
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
    final_pg = dict(full_tgt)
    for part in parts:
        final_pg.update(pages(part))
    final = whole(final_pg)
    _same_pages(whole(full_src), final, '核对合并')
    if a.tl.lower().startswith('en'):
        # OCR/机翻都不保留斜体；英文定稿按分类学排版规则确定性补斜体（科名/命名人保持正体）。
        lex = taxoformat.build_lexicon([final])
        final, n_taxo = taxoformat.format_text(final, lex)
        _write(work / 'taxoformat.tsv',
               f'changes\tgenera\tbinomials\n{n_taxo}\t{len(lex.genera)}\t{len(lex.binomials)}\n')
    _write(work / 'checked.md', final)
    issues = transqa.check_all(whole(full_src), final, a.sl, a.tl)
    _write(work / 'qa_issues.json', json.dumps([vars(x) for x in issues], ensure_ascii=False, indent=1))
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
        npages = len([p for p in (src_pg or {}) if p]) or None
        rows.append('| 步骤 | 引擎 | 调用 | 输入（未缓存） | 缓存命中 | 输出 | 缓存命中率 | 每页输入/输出 | 秒 | 估算美元 |\n'
                    '|---|---|---|---|---|---|---|---|---|---|')
        for (stage, eng), v in sorted(agg.items()):
            usd = ((v[1] * DS_PRICE['in'] + v[3] * DS_PRICE['cache'] + v[2] * DS_PRICE['out']) / 1e6
                   if eng.startswith('deepseek') else 0)
            hit = f'{v[3] / (v[1] + v[3]):.0%}' if v[1] + v[3] else '未知'
            per = f'{(v[1] + v[3]) / npages:.0f}/{v[2] / npages:.0f}' if npages else '—'
            usd_s = f'{usd:.3f}' if eng.startswith('deepseek') else '订阅额度（未计价）'
            rows.append(f'| {stage} | {eng} | {v[0]:.0f} | {v[1]:.0f} | {v[3]:.0f} | {v[2]:.0f} | {hit} | {per} | '
                        f'{v[4]:.0f} | {usd_s} |')
    ds = work / 'draft_stats.json'
    if ds.exists():
        d = json.loads(ds.read_text(encoding='utf-8'))
        rows.append(f'\nGoogle：送 {d.get("sent_to_google", "?")}/{d.get("segments", "?")} 段，新请求 {d["requests"]}，'
                    f'失败 {len(d["failed"])}')
    rs = work / 'revise_stats.json'
    if rs.exists():
        s = json.loads(rs.read_text(encoding='utf-8'))
        ch = max(1, s.get('chunks', 0))
        rows.append(f"\n改写：段 {s.get('segments', 0)}，确定性处理（0 token）{s.get('deterministic', 0)}，"
                    f"退回模型 {s.get('fallback_to_model', 0)}，送模型 {s.get('sent_to_model', 0)}；"
                    f"返工率 {s.get('chunks_reworked', 0) / ch:.0%}（{s.get('chunks_reworked', 0)}/{ch} 段需重试）")
    ri = work / 'revise_issues.json'
    if ri.exists():
        iss = json.loads(ri.read_text(encoding='utf-8'))
        rows.append(f'\n改写后仍未过护栏的段：{len(iss)}')
        rows += [f'- {k}: {"; ".join(v)[:300]}' for k, v in iss.items()]
    cl = work / 'check_log.jsonl'
    if cl.exists():
        logs = [json.loads(x) for x in cl.read_text(encoding='utf-8').splitlines() if x.strip()]
        def n(*keys: str) -> int:
            return sum(all(k in x['result'] for k in keys) for x in logs)
        n_pre, n_veto, n_crit, n_only = n('预过滤'), n('第二模型未认可'), n('queued', 'critical'), n('仅第二模型')
        n_unsure = n('queued', '没把握')
        n_app = n('applied')
        n_guard = n('rejected') - n_pre - n_veto
        rows.append(f'\n意义核对：找错模型提出 {len(logs) - n_only}（预过滤 {n_pre}，第二模型否决 {n_veto}，'
                    f'落实 {n_app}，护栏拒绝 {n_guard}，critical 转人工 {n_crit}，裁定没把握转人工 {n_unsure}）；'
                    f'第二模型另报 {n_only}（转人工）；见 human_review_queue.csv；提示词版本 {PROMPT_VERSION}')
    qa = work / 'qa_issues.json'
    if qa.exists():
        qi = json.loads(qa.read_text(encoding='utf-8'))
        c2 = collections.Counter(x['severity'] for x in qi)
        rows.append(f'\n全书 QA（transqa）：critical {c2["critical"]}，major {c2["major"]}，minor {c2["minor"]}，'
                    f'info {c2["info"]}（qa_issues.json）')
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
    ap.add_argument('--abbr', help='引文缩写表（两列：原文缩写、译文），补充 transqa.blocks.ABBR')
    ap.add_argument('--no-entities', dest='entities', action='store_false',
                    help='不做专名解析（默认：每段抽取专名，查 yiku/Wikidata 通行中文名，注入提示词并核对）')
    ap.add_argument('--domain', default='进化生物学', help='yiku 领域（专名与术语查询）')
    ap.add_argument('--engine', default='auto',
                    help='改写与找错：auto（最省合适）/ none（零模型）/ llm_engines 名；贵模型需 --force-engine')
    ap.add_argument('--day-engine', default=None, help='白天用的引擎（默认 revise=codex-luna；找错等到夜间）')
    ap.add_argument('--verify-engine', default='none',
                    help='第二模型裁定（默认 none：质控至多 1 次 LLM；脚本护栏收尾。显式开启才费第二轮）')
    ap.add_argument('--allow-same-verify', action='store_true',
                    help='允许找错与复核用同一模型（仅在显式开启 verify 时有意义）')
    ap.add_argument('--force-engine', action='store_true',
                    help='允许 claude-opus / deepseek-v4-pro / codex-astra（默认禁用，省 token）')
    ap.add_argument('--risky-only', action='store_true', help='check 只送风险段和叙述/讨论段，段数不齐则保留整页')
    ap.add_argument('--verify-mode', choices=['review', 'judge'], default='review',
                    help='review：第二模型全文复核+裁定；judge：只逐条裁定（仅 --verify-engine 非 none 时）')
    ap.add_argument('--workers', type=int, default=4,
                    help='revise/check 并行块数（各块写自己的缓存文件；DeepSeek 建议 4–8，Codex 4–6）')
    ap.add_argument('--pitfalls', help='项目陷阱表（追加在 skill/pitfalls/{sl}-{tl}.md 之后）')
    ap.add_argument('--rewrite-kinds', default='',
                    help='分类文献：只把这些块类型交模型改写（如 narrative,remarks）；空且 --lean 时用默认 kinds')
    ap.add_argument('--lean', action=argparse.BooleanOptionalAction, default=True,
                    help='省 token（默认开）：只改写 narrative,remarks；check 风险段。--no-lean=全文改写（费）')
    ap.add_argument('--no-memory', action='store_true',
                    help='不加载跨书共享异写库（默认加载 ~/.cache/yzz-translate/memory/）')
    ap.add_argument('--tier', choices=['draft', 'release'], default='draft',
                    help='draft=试译省 token；release=交付（须异模型 verify + --chaptered）')
    ap.add_argument('--chaptered', action='store_true',
                    help='声明本 run 属于分章流水线（release 档必需；fast_book chapters 会自动加）')
    ap.add_argument('--stop-after', choices=['draft', 'revise'], default=None,
                    help='只做到这一步')
    a = ap.parse_args(argv)
    from token_economy import apply_lean, guard_engine, guard_tier
    apply_lean(a)
    guard_engine(a.engine, force=a.force_engine)
    if a.verify_engine not in ('none', ''):
        guard_engine(a.verify_engine, force=a.force_engine)
    a.tier = guard_tier(a.tier, verify_engine=a.verify_engine, chaptered=bool(a.chaptered))
    if a.cmd == 'report':
        print(report(Path(a.src)))
        return
    work = Path(a.work or 'auto_work')
    work.mkdir(parents=True, exist_ok=True)
    (work / 'tier.txt').write_text(a.tier + '\n', encoding='utf-8')
    print(f'[auto] tier={a.tier} engine={a.engine!r} verify={a.verify_engine!r}；'
          f'lean 默认开、跨书 memory 默认加载（见 skill/TOKEN_ECONOMY.md）', flush=True)
    if a.engine == 'auto':
        print('[auto] 注意：--engine auto 会对 lean 候选段调模型（仍费 token）；'
              '要 0 token 请加 --engine none', flush=True)
    if not a.no_memory:
        import book_memory
        merged = book_memory.merge_glossary(
            a.glossary, a.sl, a.tl, getattr(a, 'domain', '分类学') or '分类学',
            work / '_merged_glossary.tsv')
        a.glossary = str(merged)
        print(f'[auto] 跨书 memory 已合并 → {merged}', flush=True)
    src_pg = pages(Path(a.src).read_text(encoding='utf-8'))
    if getattr(a, 'lean', False):
        print(f'[auto] Lean：rewrite_kinds={a.rewrite_kinds!r} risky_only={a.risky_only} '
              f'verify={a.verify_engine!r}', flush=True)
    if a.cmd == 'run':
        dfile = work / 'draft.md'
        draft_pg = pages(dfile.read_text(encoding='utf-8')) if dfile.exists() else stage_draft(src_pg, work, a.sl, a.tl)
        if a.stop_after == 'draft':
            return
        revised = stage_revise(src_pg, draft_pg, work, a)
        if a.stop_after == 'revise':
            print(f'改写完成：{work / "revised.md"}；之后 check {a.src} {work / "revised.md"} -o {work}')
            return
        final = stage_check(src_pg, pages(revised), work, a)
    else:
        if not a.tgt:
            ap.error('check 需要 TGT.md')
        final = stage_check(src_pg, pages(Path(a.tgt).read_text(encoding='utf-8')), work, a)
    # 书末挖异写候选 → 跨书积累（0 token）；审核后 book_memory absorb
    draft_p = work / 'draft.md'
    final_p = work / 'checked.md' if (work / 'checked.md').exists() else work / 'final.md'
    if draft_p.exists() and final_p.exists():
        try:
            import mine_corrections as mc
            rows = mc.mine(draft_p.read_text(encoding='utf-8'), final_p.read_text(encoding='utf-8'))
            cand = work / 'memory_candidates.tsv'
            with open(cand, 'w', encoding='utf-8', newline='') as fp:
                w = __import__('csv').DictWriter(
                    fp, fieldnames=['old', 'new', 'count', 'segments_with_old', 'consistency', 'approve'],
                    delimiter='\t')
                w.writeheader()
                w.writerows(rows)
            print(f'[auto] 跨书候选 {len(rows)} 条 → {cand}（approve=y 后：'
                  f'python3 scripts/book_memory.py absorb {cand} --sl {a.sl} --tl {a.tl}）', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[auto] mine_corrections 跳过：{exc}', flush=True)
    print(report(work, src_pg, final))


if __name__ == '__main__':
    main()
