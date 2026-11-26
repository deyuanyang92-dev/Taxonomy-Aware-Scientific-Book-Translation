"""中文目标文本的错字/错符检测（GitHub #23）：术语感知，只出问题单，修正走 apply_issues 闸口。

分三层，层级决定能否自动应用：
1. 机械层（kind=auto，上下文无关、确定性）：U+3000、全角字母数字、汉字旁的半角标点、不可能的叠字（的的、，，）、
   标点前空格、康熙部首、数字间的 ○→〇。只有这一层可由 `fix_mechanical` / `queue_rows(auto_only=True)` 生成修改。
2. 术语层（kind=review / decision）：与 yiku 已定术语只差一字、且差字在文档化的形近/同音对表里、且只匹配一个术语
   → 提议（review，从不自动改）；近形词本身也是另一个有效术语/类群名（多毛类 vs 多毛纲）→ decision，只报告。
3. 语境层（kind=review）：的/地/得、做/作、象/像、其它/其他等，只给上下文和建议，永不自动改。

受保护：斜体（学名）、命名人括注 (Müller, 1776)、URL、`[TN:…]`、`[[…]]` 占位、代码；所有规则对这些区间无效。
报告：`check()` 接入 `check_all`（目标语言 zh*），按规则计数；零发现时明确输出 zh_typo.none（不代表人工校对过）。

用法：
    from transqa import zh_typo
    zh_typo.scan(text, terms={'刚毛'}, protected_names={'多毛类'})      # list[Finding]
    new, applied = zh_typo.fix_mechanical(text)                          # 只改机械层
    rows = zh_typo.queue_rows(text, file='ch1.md', terms=…)             # 问题单行，写成 JSONL 后交 scripts/apply_issues.py
    python3 -m transqa.zh_typo 译文/ch1.md [--terms 术语.txt] [--names 类群名.txt] [--queue out.jsonl]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any

from .issue import Issue
from .segments import Segment

HAN = '一-鿿㐀-䶿'
_HAN_RE = re.compile(f'[{HAN}]')
_PROTECT_RE = re.compile(
    r'\*[^*\n]+\*|`[^`\n]*`|https?://\S+|www\.\S+|\S+@\S+\.\S+|\[TN:[^\]]*\]|\[\[[^\]\n]*\]\]'
    r'|\([^()\n]*\b(?:1[5-9]|20)\d\d[a-z]?\)')


@dataclass
class Finding:
    rule: str
    kind: str                 # auto | review | decision
    start: int
    end: int
    old: str
    new: str | None
    reason: str
    confidence: float = 1.0
    context: str = ''


# ---- 文档化的形近/同音对（术语近似检测只认这些，不做任意编辑距离）----
HOMOPHONE_PAIRS: list[str] = [
    '钢刚', '钢纲', '末未', '己已', '戊戌', '辨辩', '沙砂', '须需', '洲州', '土士', '日曰', '帐账', '鳃腮', '鳞磷',
    '亚业', '体休', '刚岗', '干于', '戴带', '蜕脱',
]
_PAIRMATES: dict[str, set[str]] = collections.defaultdict(set)
for _p in HOMOPHONE_PAIRS:
    _PAIRMATES[_p[0]].add(_p[1])
    _PAIRMATES[_p[1]].add(_p[0])

_NEVER_DUP = '的了之与并及被将而且或又'
# 确凿错字串：(错, 对, kind, 说明)。「具具」可能是合法的「工具+具有」，所以只报 review；其余无歧义，可自动改。
KNOWN_TYPOS: list[tuple[str, str, str, str]] = [
    ('蛋白质质', '蛋白质', 'auto', '衍一「质」'),
    ('具具', '具', 'review', '叠字（「具」+「具X」）；若是「工具/器具/家具」+「具有」则保留'),
    *[(w * 2, w, 'review', f'相邻叠字「{w * 2}」，多为衍字；若两字分属相邻词则保留') for w in '经中叶管体质'],
]
_DUP_PUNCT = '，。、；：！？'
_NUMERALS = '一二三四五六七八九〇零'

_CTX_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r'做为'), '作为', '做/作：「作为」'),
    (re.compile(r'好象|象是|象这样|不象'), '像', '象/像：比拟义用「像」'),
    (re.compile(r'(?<=[跑走说写看长飞游爬唱吃睡])的(?=[很非太更最极特])'), '得', '的/地/得：动词后补语用「得」'),
    (re.compile(r'(?<=[很非常十分格外])地(?=[一-鿿]{1,2}的)'), '', '的/地/得：疑似「地」位置'),
    (re.compile(r'其它'), '其他', '其它/其他：全稿统一（指人用「其他」）'),
]
_OPEN_CLOSE = [('“', '”'), ('‘', '’'), ('（', '）'), ('【', '】'), ('《', '》')]
_TRAD = dict(zip('體個們來這與為並後從會當經說讀環節動類屬種個頭觸鬚體鰓', '体个们来这与为并后从会当经说读环节动类属种个头触须体鳃', strict=False))


def _ctx(text: str, s: int, e: int, w: int = 12) -> str:
    return text[max(0, s - w):e + w].replace('\n', ' ')


def _protected(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _PROTECT_RE.finditer(text)]


def _hit(spans: list[tuple[int, int]], s: int, e: int) -> bool:
    return any(a < e and s < b for a, b in spans)


def _mk(text: str, rule: str, kind: str, s: int, e: int, new: str | None, reason: str,
        conf: float = 1.0) -> Finding:
    return Finding(rule, kind, s, e, text[s:e], new, reason, conf, _ctx(text, s, e))


def _is_han(ch: str) -> bool:
    return bool(ch) and bool(_HAN_RE.match(ch))


def _mechanical(text: str, sp: list[tuple[int, int]]) -> list[Finding]:
    out: list[Finding] = []

    def add(rule: str, m: re.Match[str], new: str, reason: str) -> None:
        if not _hit(sp, m.start(), m.end()) and m.group(0) != new:
            out.append(_mk(text, rule, 'auto', m.start(), m.end(), new, reason))

    for m in re.finditer('　', text):
        prev = text[m.start() - 1:m.start()]
        nxt = text[m.end():m.end() + 1]
        new = '' if (not prev or not nxt or _is_han(prev) or _is_han(nxt) or prev in '。，、；：' or nxt in '。，、；：') \
            else ' '
        add('zh.u3000', m, new, 'U+3000 全角空格禁用（Word 编辑标记下显示 □）')
    for m in re.finditer('[！-～]+', text):
        run = m.group(0)
        if not re.fullmatch('[０-９Ａ-Ｚａ-ｚ]+', run):
            continue  # 全角标点交给标点规则；这里只管字母数字
        before, after = text[m.start() - 1:m.start()], text[m.end():m.end() + 1]
        if _is_han(before) or _is_han(after):
            add('zh.fullwidth_alnum', m, unicodedata.normalize('NFKC', run), '中文行文中的全角字母/数字')
    for m in re.finditer(r'[⼀-⿟]', text):
        add('zh.confusable', m, unicodedata.normalize('NFKC', m.group(0)), '康熙部首字符，应为常规汉字')
    for m in re.finditer(f'(?<=[{_NUMERALS}])[○◯](?=[{_NUMERALS}])', text):
        add('zh.confusable', m, '〇', '数字中的圆圈应为〇（U+3007）')
    for m in re.finditer(f'(?<=[{HAN}]) +(?=[，。；：！？、])', text):
        add('zh.space_before_punct', m, '', '标点前多余空格')
    for m in re.finditer(f'(?<=[{HAN}”’）】》])[,;:!?](?!\\d)', text):
        add('zh.punct_halfwidth', m, {',': '，', ';': '；', ':': '：', '!': '！', '?': '？'}[m.group(0)],
            '汉字后的半角标点')
    for m in re.finditer(f'(?<=[{HAN}])\\.(?=[”’）」\\s]|$|[{HAN}])', text):
        add('zh.punct_halfwidth', m, '。', '汉字后的半角句点')
    for m in re.finditer(f'\\(([^()\\n]*[{HAN}][^()\\n]*)\\)', text):
        if not _hit(sp, m.start(), m.end()):
            out.append(_mk(text, 'zh.punct_halfwidth', 'auto', m.start(), m.end(), '（' + m.group(1) + '）',
                           '含汉字的括号应为全角'))
    for m in re.finditer(f'([{_NEVER_DUP}])\\1|([{_DUP_PUNCT}])\\2+', text):
        ch = m.group(1) or m.group(2)
        add('zh.dup', m, ch, '不可能的叠字/叠标点')
    for m in re.finditer(r'、(?=但|却|然而|不过|可是|尽管)', text):
        add('zh.dun_contrast', m, '，', '顿号用于词语并列，此处连接转折分句，应为逗号')
    for bad, good, kind, why in KNOWN_TYPOS:
        for m in re.finditer(re.escape(bad), text):
            if _hit(sp, m.start(), m.end()):
                continue
            if kind == 'auto':
                add('zh.known_typo', m, good, why)
            else:
                out.append(_mk(text, 'zh.known_typo', 'review', m.start(), m.end(), good, why, 0.6))
    return out


def _unmatched_ascii(para: str, ch: str) -> int | None:
    """段内未配对的半角括号位置：ch='(' 找没有 ')' 对应的左括号，ch=')' 找没有 '(' 对应的右括号。"""
    stack: list[int] = []
    loose: list[int] = []
    for k, x in enumerate(para):
        if x == '(':
            stack.append(k)
        elif x == ')':
            if stack:
                stack.pop()
            else:
                loose.append(k)
    pool = stack if ch == '(' else loose
    return pool[0] if len(pool) == 1 else None


def _context_checks(text: str, sp: list[tuple[int, int]], terms: set[str], names: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for pat, new, why in _CTX_RULES:
        for m in pat.finditer(text):
            if _hit(sp, m.start(), m.end()):
                continue
            if m.group(0) == '做为':
                repl = '作为'
            elif m.group(0) in ('好象', '象是', '象这样', '不象'):
                repl = m.group(0).replace('象', '像')
            elif m.group(0) == '其它':
                repl = '其他'
            else:
                repl = m.group(0) if not new else new
            out.append(_mk(text, 'zh.ctx_review', 'review', m.start(), m.end(), repl, why, 0.5))
    # 括号/引号配对（按段）
    pos = 0
    for para in re.split(r'\n\s*\n', text):
        i = text.find(para, pos)
        pos = i + len(para)
        if not _HAN_RE.search(para):
            continue
        for o, c in _OPEN_CLOSE:
            no, nc = para.count(o), para.count(c)
            if o == '‘':  # ’ 也作撇号，只计不夹在 ASCII 字母之间的
                nc = len(re.findall(r'(?<![A-Za-z])’|’(?![A-Za-z])', para))
            if no != nc and (o, c) == ('（', '）'):   # 半角括号与全角括号混用（谷歌「(…）」）：补成全角，机械可改
                a_open = _unmatched_ascii(para, '(' if nc > no else ')')
                if a_open is not None and abs(nc - no) == 1 and para.count('(') != para.count(')'):
                    s = i + a_open
                    out.append(_mk(text, 'zh.paren_mixed', 'auto', s, s + 1, '（' if nc > no else '）',
                                   '半角括号与全角括号混用，补成全角', 0.9))
                    continue
            if no != nc:
                k = para.find(o if no > nc else c)
                s = i + max(k, 0)
                out.append(_mk(text, 'zh.unpaired', 'review', s, s + 1, None, f'{o}{c} 不成对（开 {no}，闭 {nc}）', 0.7))
    # 其它/其他 同时出现已由单条规则报；繁简混用
    trad = [m for m in re.finditer('[' + ''.join(k for k in _TRAD if k != _TRAD[k]) + ']', text)
            if not _hit(sp, m.start(), m.end())]
    simp = sum(1 for ch in text if ch in set(_TRAD.values()) - set(_TRAD))
    if trad and simp >= 5 * len(trad):
        for m in trad:
            out.append(_mk(text, 'zh.mixed_script', 'review', m.start(), m.end(), _TRAD[m.group(0)],
                           '简体稿中出现繁体字', 0.6))
    return out


def _near_miss(text: str, sp: list[tuple[int, int]], terms: set[str], names: set[str]) -> list[Finding]:
    out: list[Finding] = []
    valid = terms | names
    # 已定术语/有效名在文中的占位区间：这些位置上的字符不再当作错字
    covered = [(m.start(), m.end()) for v in valid if v and len(v) >= 2 for m in re.finditer(re.escape(v), text)]
    typo_index: dict[str, set[str]] = collections.defaultdict(set)
    for t in terms:
        if len(t) < 2 or not all(_is_han(c) for c in t):
            continue
        for i, ch in enumerate(t):
            for alt in _PAIRMATES.get(ch, ()):
                w = t[:i] + alt + t[i + 1:]
                if w not in valid:
                    typo_index[w].add(t)
    for w, ts in typo_index.items():
        for m in re.finditer(re.escape(w), text):
            if _hit(sp, m.start(), m.end()) or any(a <= m.start() and m.end() <= b for a, b in covered):
                continue
            if len(ts) == 1:
                (t,) = ts
                out.append(_mk(text, 'zh.term_near_miss', 'review', m.start(), m.end(), t,
                               f'与已定术语「{t}」只差一字（形近/同音对表）', 0.8))
            else:
                out.append(_mk(text, 'zh.term_near_miss', 'review', m.start(), m.end(), None,
                               f'与多个已定术语只差一字：{"、".join(sorted(ts))}，需人裁定', 0.4))
    # 近形词本身是另一个有效术语/类群名：只报决策
    masks: dict[tuple[int, str, str], set[str]] = collections.defaultdict(set)
    for t in terms:
        for i in range(len(t)):
            masks[(len(t), t[:i], t[i + 1:])].add(t)
    for n in names - terms:
        if len(n) < 2:
            continue
        for i in range(len(n)):
            for t in masks.get((len(n), n[:i], n[i + 1:]), ()):
                if t == n:
                    continue
                for m in re.finditer(re.escape(n), text):
                    if _hit(sp, m.start(), m.end()):
                        continue
                    out.append(_mk(text, 'zh.term_decision', 'decision', m.start(), m.end(), t,
                                   f'「{n}」与已定术语「{t}」只差一字，二者均为有效名称：术语定名问题，交 yiku 裁定，不改正文', 0.9))
    return out


def _variants(text: str, sp: list[tuple[int, int]], groups: list[tuple[str, ...]]) -> list[Finding]:
    """同义异写（如 储精囊/贮精囊）：同一文本内混用时，把少数写法报为 review，建议改成多数写法；票数相等不建议。"""
    out: list[Finding] = []
    for g in groups:
        pos = {w: [m for m in re.finditer(re.escape(w), text) if not _hit(sp, m.start(), m.end())] for w in g}
        used = {w: ms for w, ms in pos.items() if ms}
        if len(used) < 2:
            continue
        top = max(len(ms) for ms in used.values())
        winners = [w for w, ms in used.items() if len(ms) == top]
        for w, ms in used.items():
            if len(ms) == top and len(winners) == 1:
                continue
            for m in ms:
                new = winners[0] if len(winners) == 1 else None
                out.append(_mk(text, 'zh.variant_minority', 'review', m.start(), m.end(), new,
                               f'同义异写混用：{"/".join(g)}（本文本多数写法：{"、".join(winners)}）', 0.7))
    return out


def scan(text: str, *, terms: set[str] | None = None, protected_names: set[str] | None = None,
         variants: list[tuple[str, ...]] | None = None) -> list[Finding]:
    """检测，返回按位置排序的 Finding。terms：yiku 已定中文术语；protected_names：其他有效中文名（类群名等）；
    variants：同义异写组，如 [('储精囊', '贮精囊')]。"""
    terms, names = set(terms or ()), set(protected_names or ())
    sp = _protected(text)
    fs = _mechanical(text, sp) + _context_checks(text, sp, terms, names)
    if variants:
        fs += _variants(text, sp, variants)
    if terms:
        fs += _near_miss(text, sp, terms, names)
    return sorted(fs, key=lambda f: (f.start, f.end, f.rule))


def _non_overlapping(fs: list[Finding]) -> list[Finding]:
    out: list[Finding] = []
    last = -1
    for f in sorted(fs, key=lambda f: (f.start, f.end)):
        if f.start >= last:
            out.append(f)
            last = f.end
    return out


def fix_mechanical(text: str, *, terms: set[str] | None = None,
                   protected_names: set[str] | None = None) -> tuple[str, list[Finding]]:
    """只应用 kind=auto 的发现；review/decision 一律不动。返回 (新文本, 已应用的 Finding)。"""
    auto = _non_overlapping([f for f in scan(text, terms=terms, protected_names=protected_names)
                             if f.kind == 'auto' and f.new is not None])
    for f in reversed(auto):
        text = text[:f.start] + (f.new or '') + text[f.end:]
    return text, auto


def _unique_old(text: str, s: int, e: int) -> tuple[str, int]:
    """扩展上下文直到 old 在文件里恰好出现 1 次（apply_issues 闸口要求）。返回 (old, 相对 s 的前缀长度)。"""
    for w in (0, 4, 8, 16, 32, 64, 128, 400):
        a, b = max(0, s - w), min(len(text), e + w)
        if text.count(text[a:b]) == 1:
            return text[a:b], s - a
    return text[max(0, s - 400):e + 400], s - max(0, s - 400)


def queue_rows(text: str, *, file: str, terms: set[str] | None = None, protected_names: set[str] | None = None,
               variants: list[tuple[str, ...]] | None = None, auto_only: bool = False, en_by_ctx: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """问题单行（交 scripts/apply_issues.py）。old 为含上下文、在文件中唯一的片段。review/decision 的行带
    confidence 与 review=true；apply_issues 不读这两个字段，人审后再决定是否并入。auto_only=True 只出机械层。"""
    rows: list[dict[str, Any]] = []
    fs = _non_overlapping([f for f in scan(text, terms=terms, protected_names=protected_names, variants=variants)
                           if f.new is not None])
    for f in fs:
        if auto_only and f.kind != 'auto':
            continue
        old, pre = _unique_old(text, f.start, f.end)
        new = old[:pre] + (f.new or '') + old[pre + (f.end - f.start):]
        if new == old:
            continue
        rows.append({'file': file, 'old': old, 'new': new, 'type': '术语' if f.kind != 'auto' else '格式',
                     'reason': f'{f.rule}: {f.reason}', 'en': (en_by_ctx or {}).get(f.context, old),
                     'rule': f.rule, 'kind': f.kind, 'confidence': f.confidence, 'review': f.kind != 'auto',
                     'context': f.context})
    return rows


def summarize(fs: list[Finding]) -> dict[str, int]:
    return dict(collections.Counter(f.rule for f in fs))


def _src_unbalanced(text: str) -> bool:
    """原文段括号/引号是否本身不成对（OCR 把脚注号「¹)」识成「‘)」、断页只剩「21)」等）。"""
    return any(text.count(o) != text.count(c) for o, c in (('(', ')'), ('[', ']'), ('（', '）')))


def check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    """transqa 接口：目标语言为 zh* 时运行。cfg 可选 zh_terms / zh_names（集合）。"""
    if not str(cfg.get('tl', '')).lower().startswith('zh'):
        return []
    terms, names = set(cfg.get('zh_terms') or ()), set(cfg.get('zh_names') or ())
    variants = [tuple(g) for g in (cfg.get('zh_variants') or ())]
    out: list[Issue] = []
    n_checked = 0
    counts: collections.Counter[str] = collections.Counter()
    src_by_id = {x.id: x.text for x in src}
    for s in tgt:
        if not _HAN_RE.search(s.text):
            continue
        n_checked += 1
        for f in scan(s.text, terms=terms, protected_names=names, variants=variants):
            if f.rule == 'zh.unpaired' and _src_unbalanced(src_by_id.get(s.id, '')):
                continue   # 原文（OCR 脚注号、断页残片）本身括号不成对，不是译文引入的
            counts[f.rule] += 1
            out.append(Issue(f'zh_typo.{f.rule}', 'minor', f'{f.reason}：{f.context}', page=s.page, segment=s.id,
                             evidence={'kind': f.kind, 'old': f.old, 'new': f.new, 'confidence': f.confidence}))
    if not n_checked:
        return [Issue('zh_typo.not_checked', 'info', '目标文本中没有汉字段，未做错字检查')]
    if counts:
        out.append(Issue('zh_typo.summary', 'info', f'错字/错符规则触发 {sum(counts.values())} 处（{n_checked} 段已查）',
                         evidence={'by_rule': dict(counts), 'segments_checked': n_checked}))
    else:
        out.append(Issue('zh_typo.none', 'info',
                         f'已检查 {n_checked} 段，错字/错符规则均未触发（不代表已人工校对）',
                         evidence={'segments_checked': n_checked}))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='中文错字/错符检测（只报告；--queue 写问题单 JSONL）')
    ap.add_argument('file')
    ap.add_argument('--terms', help='yiku 中文术语文件，每行一词')
    ap.add_argument('--names', help='其他有效中文名（类群名）文件，每行一词')
    ap.add_argument('--variants', help='同义异写文件，每行一组，词之间用制表符或空格分隔')
    ap.add_argument('--queue', help='问题单 JSONL 输出（file 字段取文件名）')
    ap.add_argument('--auto-only', action='store_true', help='问题单只含机械层')
    a = ap.parse_args(argv)

    def words_raw(p: str | None) -> list[str]:
        if not p:
            return []
        with open(p, encoding='utf-8') as fh:
            return [ln.strip() for ln in fh if ln.strip()]

    def words(p: str | None) -> set[str]:
        if not p:
            return set()
        with open(p, encoding='utf-8') as fh:
            return {ln.strip() for ln in fh if ln.strip()}

    with open(a.file, encoding='utf-8') as fh:
        text = fh.read()
    terms, names = words(a.terms), words(a.names)
    variants = [tuple(ln.split()) for ln in words_raw(a.variants) if len(ln.split()) >= 2]
    fs = scan(text, terms=terms, protected_names=names, variants=variants)
    print(json.dumps({'by_rule': summarize(fs), 'total': len(fs)}, ensure_ascii=False) if fs
          else '错字/错符规则均未触发（不代表已人工校对）')
    if a.queue:
        rows = queue_rows(text, file=a.file.rsplit('/', 1)[-1], terms=terms, protected_names=names,
                          variants=variants, auto_only=a.auto_only)
        with open(a.queue, 'w', encoding='utf-8') as out:
            out.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
        print(f'问题单 {len(rows)} 行 → {a.queue}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
