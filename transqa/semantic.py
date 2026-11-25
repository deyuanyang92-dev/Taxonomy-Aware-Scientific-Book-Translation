"""语义偏离检测与校准分流（GitHub #25）。只分流、不自动改：发现进问题单，由人或 apply_issues 闸口处理。

Tier 1（全书、零模型调用）：段对齐后用确定性特征比较原文与译文——否定极性、有无、频度/情态/界限/限定词、方位对、
  比较关系、数值范围、学名顺序、引用（作者+年）、图号，以及长度比（漏译/增译的粗筛）。语言对表在本文件 TABLES，
  未收录的语言对报 capability_missing，不得当作通过。
Tier 2（候选 + 固定对照抽样）：与译者不同的审校模型按 MQM 评分表逐对复核，输出 JSONL 问题单；必须给出 NO_ISSUES 或
  问题行，解析失败记为 failed 而非干净；按 (提示词版本, 原文, 译文, 术语) 的 digest 缓存，重跑幂等；预算有上限，
  DeepSeek 忙时回避与用量记录（usage.tsv）由 scripts/llm_engines.call 负责。
Tier 3：回译只作佐证（attach_back_translation），永远不单独成为问题。
校准：calibrate() 把 8 类已知错误注入真实译文对并报每类召回与精度、选定阈值；approved 默认 False，
  gate_allowed() 在人工批准且达标前恒为 False，此前 check_all 的语义发现只作为非阻断分流。
覆盖诚实：Coverage 报告已查/未查对数及原因、未触发的规则、Tier 2 覆盖比例；「没发现」与「没查」可区分。

命令行：
    python3 -m transqa.semantic tier1 原文.md 译文.md --sl en --tl zh [--out 分流.jsonl]
    python3 -m transqa.semantic calibrate 原文.md 译文.md --sl en --tl zh --out calibration.json
    python3 -m transqa.semantic tier2 原文.md 译文.md --translator codex-sol --reviewer deepseek-flash \\
        --cache work/semcache [--budget 40 --control 6 --out issues.jsonl]（候选取 Tier 1 的发现）
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import random
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .issue import Issue
from .segments import Segment
from .taxonomy import latin_names

MIN_WORDS = 8
PROMPT_VERSION = 'sem-v1'
TYPES_ALL = [
    'presence.flip', 'negation.drop', 'negation.add', 'frequency.shift', 'frequency.drop', 'modality.drop',
    'bound.shift', 'bound.drop', 'restrictive.drop', 'quantifier.shift', 'direction.swap', 'comparative.flip',
    'range.shift', 'taxon.swap', 'citation.year', 'citation.swap', 'figure.ref', 'length.low', 'length.high',
    'addition',
]


@dataclass
class Pair:
    id: str
    page: int
    src: str
    tgt: str
    kind: str          # 1-1 | n-m（页内段数不等，合并比较）| src_only | tgt_only


@dataclass
class Flag:
    segment: str
    page: int
    type: str
    severity: str      # major | minor（分流用，非 MQM 严重度）
    reason: str
    src_quote: str
    tgt_quote: str
    confidence: str = 'needs_verification'
    tier: int = 1
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Thresholds:
    ratio_lo: float = 0.6     # 汉字数/英文词数低于此值：疑漏译
    ratio_hi: float = 3.4     # 高于此值：疑增译
    ratio_add: float = 2.4    # 译文句数多于原文且比值高于此值：疑增译


@dataclass
class Coverage:
    sl: str = ''
    tl: str = ''
    pairs_total: int = 0
    checked: int = 0
    unchecked: dict[str, int] = field(default_factory=dict)
    rules_fired: dict[str, int] = field(default_factory=dict)
    rules_not_fired: list[str] = field(default_factory=list)
    capability_missing: bool = False
    tier2_reviewed: int = 0

    @property
    def tier2_fraction(self) -> float:
        return self.tier2_reviewed / self.checked if self.checked else 0.0


# ---------------------------------------------------------------- 段对齐
def build_pairs(src: list[Segment], tgt: list[Segment]) -> list[Pair]:
    """按页配对：页内段数相等 → 逐段 1-1；不等 → 整页合并为一对（n-m），不静默绕过；只在一侧的页 → src_only/tgt_only。"""
    sp: dict[int, list[Segment]] = collections.defaultdict(list)
    tp: dict[int, list[Segment]] = collections.defaultdict(list)
    for s in src:
        sp[s.page].append(s)
    for t in tgt:
        tp[t.page].append(t)
    out: list[Pair] = []
    for page in sorted(set(sp) | set(tp)):
        a, b = sp.get(page, []), tp.get(page, [])
        if a and not b:
            out += [Pair(s.id, page, s.text, '', 'src_only') for s in a]
        elif b and not a:
            out += [Pair(t.id, page, '', t.text, 'tgt_only') for t in b]
        elif len(a) == len(b):
            out += [Pair(s.id, page, s.text, t.text, '1-1') for s, t in zip(a, b, strict=True)]
        else:
            out.append(Pair(a[0].id, page, '\n'.join(s.text for s in a), '\n'.join(t.text for t in b), 'n-m'))
    return out


# ---------------------------------------------------------------- 语言对表（en → zh）
def _rx(*pats: str) -> re.Pattern[str]:
    return re.compile('|'.join(f'(?:{p})' for p in pats), re.I)


# 组 → 概念 → (英文正则, 中文正则)。同组概念互斥；概念内部用「出现与否」比较。
GROUPS_EN_ZH: dict[str, dict[str, tuple[re.Pattern[str], re.Pattern[str]]]] = {
    'presence': {
        'present': (_rx(r'\b(?:present|presence)\b'),
                    _rx(r'(?<![没不未无缺所])(?:具有|具|有|存在|出现)(?!无)')),
        'absent': (_rx(r'\b(?:absent|absence|lacking|lacks?|devoid|missing)\b'),
                   _rx(r'缺失|缺如|缺少|缺乏|不具|没有|无(?!脊)|未见')),
    },
    'frequency': {
        'always': (_rx(r'\b(?:always|invariably)\b'), _rx(r'总是|始终|一律|永远|恒定')),
        'usually': (_rx(r'\b(?:usually|typically|generally|normally)\b'), _rx(r'通常|一般|往往|(?<![经])常(?![常见])')),
        'often': (_rx(r'\b(?:often|frequently|commonly)\b'), _rx(r'经常|常常|常见|多见')),
        'sometimes': (_rx(r'\b(?:sometimes|occasionally)\b'), _rx(r'有时|偶尔|偶见')),
        'rarely': (_rx(r'\b(?:rarely|seldom)\b'), _rx(r'很少|罕见|少见|鲜见')),
    },
    'quantifier': {
        'all': (_rx(r'\b(?:all|every|each)\b'), _rx(r'所有|全部|每|各|均|皆')),
        'some': (_rx(r'\b(?:some|certain)\b'), _rx(r'一些|部分|有些|某些')),
        'most': (_rx(r'\b(?:most|majority)\b'), _rx(r'大多|多数|大部分')),
        'few': (_rx(r'\b(?:few|several)\b'), _rx(r'少数|少量|个别|数个')),
    },
    'bound': {
        'at_least': (_rx(r'\bat least\b', r'\bno fewer than\b'), _rx(r'至少|不少于|不低于|最少')),
        'up_to': (_rx(r'\bup to\b', r'\bat most\b', r'\bno more than\b', r'\bmaximum\b'),
                  _rx(r'至多|最多|多达|可达|不超过|最大')),
        'about': (_rx(r'\b(?:about|approximately|roughly|nearly)\b'), _rx(r'约|大约|近|左右|大致')),
    },
    'direction_dv': {
        'dorsal': (_rx(r'\bdors\w*'), _rx(r'背(?!景|后|离|叛)')),
        'ventral': (_rx(r'\bventr\w*'), _rx(r'腹')),
    },
    'direction_ap': {
        'anterior': (_rx(r'\banterior\w*'), _rx(r'前(?:端|部|侧|方|缘|面|节|叶)')),
        'posterior': (_rx(r'\bposterior\w*'), _rx(r'后(?:端|部|侧|方|缘|面|节|叶)')),
    },
    'direction_pd': {
        'proximal': (_rx(r'\bproximal\w*'), _rx(r'近(?:端|侧|部)')),
        'distal': (_rx(r'\bdistal\w*'), _rx(r'远(?:端|侧|部)')),
    },
    'direction_lr': {
        'left': (_rx(r'\bleft\b', r'\bsinistral\w*'), _rx(r'左')),
        'right': (_rx(r'\bright\b', r'\bdextral\w*'), _rx(r'右')),
    },
    'comparative': {
        'gt': (_rx(r'\b(?:longer|wider|larger|greater|broader|thicker|more than)\b'),
               _rx(r'[长宽大多高粗厚]于', r'比[^，。；]{1,12}?[长宽大多高粗厚]')),
        'lt': (_rx(r'\b(?:shorter|narrower|smaller|lesser|fewer|thinner|less than)\b'),
               _rx(r'[短窄小少低细薄]于', r'比[^，。；]{1,12}?[短窄小少低细薄]', r'不足')),
        'eq': (_rx(r'\b(?:subequal|equal|equally)\b'), _rx(r'近等|约等|几乎等|相等|等长|大致相等')),
    },
}
MODALITY = (_rx(r'\b(?:may|might|could|possibly|perhaps|probably|likely|apparently|presumably)\b'),
            _rx(r'可能|或许|也许|大概|多半|似乎|看似|显然'))
RESTRICT = (_rx(r'\b(?:only|solely|exclusively)\b'), _rx(r'仅|只|唯一|仅仅|只有'))
NEG = (_rx(r'\b(?:no|not|never|without|none|nor|neither|absent|absence|lack\w*|devoid|missing)\b', r'\bnon-'),
       _rx(r'没有|并未|不(?!同|少|论|仅|久|断|一定|足)|未(?!来)|无(?!脊|数|论)|非(?!洲)|缺'))
FIG = (re.compile(r'\b(?:Figs?|Plates?|Pl)\.?\s*(\d+)', re.I), re.compile(r'(?:图版|图)\s*(\d+)'))
RANGE_RX = re.compile(r'(\d+(?:\.\d+)?)\s*(?:[–—-]|至|～|~)\s*(\d+(?:\.\d+)?)')
CITE_RX = re.compile(r"([A-Z][A-Za-zÀ-ÿ'\-]+)(?:\s+et al\.?|\s*(?:&|and)\s+[A-Z][A-Za-zÀ-ÿ'\-]+)?[,，]?\s*"
                     r"[(（]?\s*((?:1[5-9]|20)\d\d)[a-z]?")
TABLES: dict[tuple[str, str], str] = {('en', 'zh'): 'GROUPS_EN_ZH'}
_ABBR = re.compile(r'\b(?:sp|spp|Fig|Figs|fig|Pl|cf|vs|al|nov|gen|comb|var|subsp|ca|approx|Nos?|St|Dr)\.|\b[A-Z]\.')
_HAN = re.compile('[一-鿿]')
_WORD = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*|\d+(?:\.\d+)?")
_MASK = re.compile(r'\*[^*\n]+\*|[(（][^()（）]*(?:1[5-9]|20)\d\d[^()（）]*[)）]')


def capability(sl: str, tl: str) -> bool:
    return (sl.lower()[:2], tl.lower()[:2]) in TABLES


def _find(rx: re.Pattern[str], text: str) -> list[re.Match[str]]:
    return list(rx.finditer(text))


def _concepts(group: dict[str, tuple[re.Pattern[str], re.Pattern[str]]], text: str, side: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, rxs in group.items():
        m = rxs[side].search(text)
        if m:
            out[name] = m.group(0) if side == 0 else _ctx(text, m)
    return out


def _ctx(text: str, m: re.Match[str], w: int = 6) -> str:
    return text[max(0, m.start() - w):m.end() + w].strip()


def _quote(text: str, m: re.Match[str]) -> str:
    return m.group(0).strip()


def _sentences_en(t: str) -> list[str]:
    t = _ABBR.sub(lambda m: m.group(0).replace('.', '\x01'), t)
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z(*“"\[])', t.strip())
    return [p.replace('\x01', '.') for p in parts if p.strip()]


def _sentences_zh(t: str) -> list[str]:
    return [p for p in re.split(r'(?<=[。！？])', t.strip()) if p.strip()]


def _n_words(t: str) -> int:
    return len(_WORD.findall(_MASK.sub(' ', t)))


def _n_han(t: str) -> int:
    return len(_HAN.findall(_MASK.sub(' ', t)))


def _both_diff(a: set[str], b: set[str]) -> bool:
    return bool(a - b) and bool(b - a)


def _pair_flags(p: Pair, th: Thresholds) -> list[Flag]:
    s, t = p.src, p.tgt
    fl: list[Flag] = []

    def add(typ: str, sev: str, reason: str, sq: str, tq: str) -> None:
        fl.append(Flag(p.id, p.page, typ, sev, reason, sq, tq))

    # 有无 / 频度 / 数量词 / 界限 / 方位 / 比较
    for gname, g in GROUPS_EN_ZH.items():
        a, b = _concepts(g, s, 0), _concepts(g, t, 1)
        if not a:
            continue
        sa, sb = set(a), set(b)
        q1, q2 = ' / '.join(a.values()), ' / '.join(b.values())
        if gname == 'presence' and _both_diff(sa, sb):
            add('presence.flip', 'major', f'原文 {sorted(sa)}，译文 {sorted(sb)}：有/无相反', q1, q2)
        elif gname == 'frequency':
            if _both_diff(sa, sb):
                add('frequency.shift', 'major', f'频度词不一致：原文 {sorted(sa)}，译文 {sorted(sb)}', q1, q2)
            elif not sb:
                add('frequency.drop', 'minor', f'频度词 {sorted(sa)} 在译文中缺失', q1, '')
        elif gname == 'quantifier' and _both_diff(sa, sb):
            add('quantifier.shift', 'major', f'数量词不一致：原文 {sorted(sa)}，译文 {sorted(sb)}', q1, q2)
        elif gname == 'bound':
            if _both_diff(sa, sb):
                add('bound.shift', 'major', f'界限词不一致：原文 {sorted(sa)}，译文 {sorted(sb)}', q1, q2)
            elif not sb:
                add('bound.drop', 'minor', f'界限词 {sorted(sa)} 在译文中缺失', q1, '')
        elif gname.startswith('direction') and _both_diff(sa, sb):
            add('direction.swap', 'major', f'方位词相反：原文 {sorted(sa)}，译文 {sorted(sb)}', q1, q2)
        elif gname == 'comparative' and _both_diff(sa, sb):
            add('comparative.flip', 'major', f'比较关系不一致：原文 {sorted(sa)}，译文 {sorted(sb)}', q1, q2)
    # 情态 / 限定词丢失
    m_s, m_t = MODALITY[0].search(s), MODALITY[1].search(t)
    if m_s and not m_t:
        add('modality.drop', 'minor', '原文情态/推测词在译文中缺失', _quote(s, m_s), '')
    r_s, r_t = RESTRICT[0].search(s), RESTRICT[1].search(t)
    if r_s and not r_t:
        add('restrictive.drop', 'minor', '原文限定词（only 类）在译文中缺失', _quote(s, r_s), '')
    # 否定极性（有无翻转时由 presence.flip 报告，不重复）
    if not any(f.type == 'presence.flip' for f in fl):
        ns, nt = len(_find(NEG[0], s)), len(_find(NEG[1], t))
        if ns and not nt:
            add('negation.drop', 'major', f'原文有否定（{ns} 处）而译文无', _quote(s, NEG[0].search(s)), '')  # type: ignore[arg-type]
        elif nt and not ns:
            add('negation.add', 'major', f'译文有否定（{nt} 处）而原文无', '', _quote(t, NEG[1].search(t)))  # type: ignore[arg-type]
    # 数值范围
    rs = {(float(x), float(y)): m.group(0) for m in RANGE_RX.finditer(s) for x, y in [m.groups()]}
    rt = {(float(x), float(y)): m.group(0) for m in RANGE_RX.finditer(t) for x, y in [m.groups()]}
    if rs and rt and (set(rs) - set(rt)) and (set(rt) - set(rs)):
        add('range.shift', 'major', f'数值范围不一致：原文 {sorted(rs)}，译文 {sorted(rt)}',
            rs[sorted(set(rs) - set(rt))[0]], rt[sorted(set(rt) - set(rs))[0]])
    # 学名顺序
    ns_, nt_ = latin_names(s), latin_names(t)
    if len(ns_) >= 2 and sorted(ns_) == sorted(nt_) and ns_ != nt_ and len(set(ns_)) == len(ns_):
        add('taxon.swap', 'major', '学名集合相同但出现顺序不同（可能互换了种名；语序合法改写需人判）',
            ' → '.join(ns_), ' → '.join(nt_))
    # 引用（作者, 年）
    cs = collections.Counter((a, y) for a, y in CITE_RX.findall(s))
    ct = collections.Counter((a, y) for a, y in CITE_RX.findall(t))
    if cs and cs != ct:
        sa_, ta_ = collections.Counter(a for a, _ in cs.elements()), collections.Counter(a for a, _ in ct.elements())
        sy_, ty_ = collections.Counter(y for _, y in cs.elements()), collections.Counter(y for _, y in ct.elements())
        if sy_ == ty_ and sa_ == ta_:
            add('citation.swap', 'major', '引用的作者与年份配对改变', str(sorted(cs)), str(sorted(ct)))
        elif sa_ == ta_ and sy_ != ty_:
            add('citation.year', 'major', f'引用年份不一致：原文 {sorted(sy_)}，译文 {sorted(ty_)}',
                str(sorted(cs)), str(sorted(ct)))
        elif ct:
            add('citation.year', 'major', '引用作者/年份不一致', str(sorted(cs)), str(sorted(ct)))
    # 图号
    fs_, ft_ = collections.Counter(FIG[0].findall(s)), collections.Counter(FIG[1].findall(t))
    if fs_ and ft_ and fs_ != ft_ and _both_diff(set(fs_), set(ft_)):
        add('figure.ref', 'major', f'图号不一致：原文 {sorted(fs_)}，译文 {sorted(ft_)}', str(sorted(fs_)), str(sorted(ft_)))
    # 长度比（漏译/增译粗筛；句数相等时逐句比较，避免合并段里的漏句被平均掉）
    ss, ts = _sentences_en(s), _sentences_zh(t)
    units = list(zip(ss, ts, strict=True)) if len(ss) == len(ts) and len(ss) > 1 else [(s, t)]
    for es, zs in units:
        w = _n_words(es)
        if w < MIN_WORDS:
            continue
        ratio = _n_han(zs) / w
        if ratio < th.ratio_lo:
            add('length.low', 'minor', f'译文偏短（汉字/词 = {ratio:.2f} < {th.ratio_lo}）：疑漏译，含从句漏译',
                es[:60], zs[:60])
        elif ratio > th.ratio_hi:
            add('length.high', 'minor', f'译文偏长（汉字/词 = {ratio:.2f} > {th.ratio_hi}）：疑增译', es[:60], zs[:60])
    if len(ts) > len(ss) and (w := _n_words(s)) >= MIN_WORDS and _n_han(t) / w > th.ratio_add \
            and not any(f.type.startswith('length.high') for f in fl):
        add('addition', 'major', f'译文句数多于原文（{len(ts)} > {len(ss)}）且偏长：疑增译（原文未有的断言）',
            s[:60], ts[-1][:60])
    return fl


def tier1(pairs: list[Pair], sl: str, tl: str, th: Thresholds | None = None) -> tuple[list[Flag], Coverage]:
    th = th or Thresholds()
    cov = Coverage(sl=sl, tl=tl, pairs_total=len(pairs))
    flags: list[Flag] = []
    fired: collections.Counter[str] = collections.Counter()
    unchecked: collections.Counter[str] = collections.Counter()
    if not capability(sl, tl):
        cov.capability_missing = True
        cov.unchecked = {'capability_missing': len(pairs)}
        cov.rules_not_fired = list(TYPES_ALL)
        return [], cov
    for p in pairs:
        if p.kind in ('src_only', 'tgt_only'):
            unchecked['unmatched'] += 1
        elif _n_words(p.src) < MIN_WORDS:
            unchecked['too_short'] += 1
        else:
            cov.checked += 1
            for f in _pair_flags(p, th):
                flags.append(f)
                fired[f.type] += 1
    cov.unchecked = dict(unchecked)
    cov.rules_fired = dict(fired)
    cov.rules_not_fired = [t for t in TYPES_ALL if t not in fired]
    return flags, cov


def attach_back_translation(flag: Flag | None, bt: str) -> Flag | None:
    """回译只作佐证：给已有发现附上回译文本，绝不凭回译新建发现。"""
    if flag is None:
        return None
    return dataclasses.replace(flag, evidence={**flag.evidence, 'back_translation': bt})


# ---------------------------------------------------------------- Tier 2
RUBRIC = """你是双语审校（原文英文，译文中文）。只找语义偏离，不评文风。按 MQM 分类：accuracy（误译/漏译/增译）与分类学专项
（数量、位置、性状状态、比较关系、学名、检索表、异名、分布、图号）。每个问题输出一行 JSON：
{"page":int,"segment":str,"src_quote":原文原句片段,"tgt_quote":译文原句片段,"type":..,"reason":..,
 "severity":"Critical|Major|Minor","confidence":"confirmed|needs_verification","fix":可选的建议改法}
引文必须逐字取自给定原文和译文；没有逐字引文的问题无效。没有任何问题时只输出一行 NO_ISSUES。不要输出其他内容。"""
_SEV = {'Critical', 'Major', 'Minor'}
_CONF = {'confirmed', 'needs_verification'}
_KEYS = ('page', 'segment', 'src_quote', 'tgt_quote', 'type', 'reason', 'severity', 'confidence')


@dataclass
class Tier2Result:
    issues: list[dict[str, Any]] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    reviewed: int = 0
    failed: int = 0
    reused: int = 0
    rejected: int = 0
    controls: int = 0
    candidates_over_budget: int = 0


def digest(pair: Pair, terms: str = '', version: str = PROMPT_VERSION) -> str:
    return hashlib.sha256('\0'.join((version, pair.src, pair.tgt, terms)).encode()).hexdigest()


def _norm(s: str) -> str:
    return re.sub(r'\s+', '', s)


def parse_verdict(raw: str, pair: Pair) -> tuple[list[dict[str, Any]], int] | None:
    """返回 (有效问题, 被拒条数)；格式不合（既无 NO_ISSUES 也无合法 JSON 行，或二者混杂）返回 None（= failed）。"""
    text = re.sub(r'^```\w*|```$', '', raw.strip(), flags=re.M).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    if lines == ['NO_ISSUES']:
        return [], 0
    issues: list[dict[str, Any]] = []
    rejected = 0
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            return None
        if not isinstance(d, dict) or any(k not in d for k in _KEYS) or d['severity'] not in _SEV \
                or d['confidence'] not in _CONF:
            return None
        if not d['src_quote'] or not d['tgt_quote'] or _norm(str(d['src_quote'])) not in _norm(pair.src) \
                or _norm(str(d['tgt_quote'])) not in _norm(pair.tgt):
            rejected += 1   # 无逐字引文的问题不收
            continue
        d = {**d, 'segment': pair.id, 'page': pair.page, 'tier': 2}
        issues.append(d)
    return issues, rejected


def _default_judge(engine: str) -> Callable[[str, str], str]:
    def judge(system: str, user: str) -> str:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
        import llm_engines  # type: ignore[import-not-found]
        return str(llm_engines.call(engine, system, user, tag='semantic')[0])
    return judge


def tier2(pairs: list[Pair], candidates: list[Pair], *, translator_engine: str, reviewer_engine: str,
          cache_dir: str | Path, judge: Callable[[str, str], str] | None = None, budget: int = 40, control: int = 6,
          seed: int = 0, terms: str = '', version: str = PROMPT_VERSION) -> Tier2Result:
    """候选（Tier 1 发现所在对）优先，余额抽固定种子的对照样本；总调用数 ≤ budget。审校模型必须不同于译者。"""
    if reviewer_engine == translator_engine:
        raise ValueError('审校模型必须不同于译者模型')
    judge = judge or _default_judge(reviewer_engine)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    res = Tier2Result()
    cand_ids: list[str] = []
    for p in candidates:
        if p.id not in cand_ids:
            cand_ids.append(p.id)
    chosen = cand_ids[:budget]
    res.candidates_over_budget = max(0, len(cand_ids) - budget)
    pool = sorted((p for p in pairs if p.id not in cand_ids and p.kind not in ('src_only', 'tgt_only')
                   and _n_words(p.src) >= MIN_WORDS), key=lambda p: p.id)
    k = min(control, max(0, budget - len(chosen)), len(pool))
    ctrl = [p.id for p in random.Random(seed).sample(pool, k)]
    res.controls = len(ctrl)
    by_id = {p.id: p for p in pairs}
    for pid in chosen + ctrl:
        got = by_id.get(pid)
        if got is None:
            continue
        p = got
        res.selected.append(pid)
        f = cache / f'{digest(p, terms, version)}.json'
        parsed: tuple[list[dict[str, Any]], int] | None
        if f.exists():
            d = json.loads(f.read_text(encoding='utf-8'))
            parsed = parse_verdict(d['raw'], p)
            if parsed is not None:
                res.reused += 1
        else:
            user = f'terms:\n{terms}\n\n[page {p.page} segment {p.id}]\nSOURCE:\n{p.src}\n\nTARGET:\n{p.tgt}\n'
            raw = judge(RUBRIC, user)
            parsed = parse_verdict(raw, p)
            if parsed is not None:
                f.write_text(json.dumps({'raw': raw, 'version': version}, ensure_ascii=False), encoding='utf-8')
        if parsed is None:
            res.failed += 1
            continue
        res.reviewed += 1
        res.issues += parsed[0]
        res.rejected += parsed[1]
    return res


def issue_rows(issues: list[dict[str, Any]], file: str) -> list[dict[str, Any]]:
    """Tier 2 问题 → apply_issues 行。只有带逐字引文且审校给了 fix 的才生成；语义发现永不自动改，行仅供人审后并入。"""
    kind = {'omission': '漏译', 'addition': '增译', 'terminology': '术语'}
    rows = []
    for i in issues:
        if i.get('fix') and i.get('src_quote') and i.get('tgt_quote'):
            rows.append({'file': file, 'old': i['tgt_quote'], 'new': i['fix'],
                         'type': kind.get(str(i['type']).lower(), '误译'), 'reason': i['reason'],
                         'en': i['src_quote'], 'confidence': i['confidence'], 'severity': i['severity']})
    return rows


# ---------------------------------------------------------------- 校准
INJECTION_TYPES = ('negation_flip', 'clause_omission', 'hedge_removal', 'range_shift', 'taxon_swap', 'citation_swap',
                   'direction_swap', 'added_claim')
EXPECTED: dict[str, set[str]] = {
    'negation_flip': {'negation.drop', 'negation.add', 'presence.flip'},
    'clause_omission': {'length.low'},
    'hedge_removal': {'modality.drop', 'bound.drop', 'frequency.drop', 'restrictive.drop'},
    'range_shift': {'range.shift'},
    'taxon_swap': {'taxon.swap'},
    'citation_swap': {'citation.year', 'citation.swap'},
    'direction_swap': {'direction.swap'},
    'added_claim': {'addition', 'length.high'},
}
_ADDED = '该种在深海热液喷口亦有分布，且为该区域的优势类群，这一点已被多次证实。'
_HEDGES = ('通常', '一般', '可能', '大约', '至少', '似乎', '最多', '至多', '约', '仅')
_DIR_SWAP = [('背', '腹'), ('腹', '背'), ('前端', '后端'), ('后端', '前端'), ('近端', '远端'), ('远端', '近端'),
             ('左', '右'), ('右', '左')]
_NEG_SWAP = [('没有', '有'), ('缺失', '具有'), ('不具', '具'), ('无', '有'), ('具', '不具')]


def inject(kind: str, p: Pair, rng: random.Random) -> Pair | None:
    """向译文注入一类已知错误；不可注入（缺少相应特征）返回 None。"""
    t = p.tgt
    new: str | None = None
    if kind == 'negation_flip':
        for a, b in _NEG_SWAP:
            if a in t:
                new = t.replace(a, b, 1)
                break
    elif kind == 'clause_omission':
        clauses = re.split(r'(?<=[，；])', t)
        if len(clauses) >= 3:
            j = max(range(len(clauses) - 1), key=lambda i: len(clauses[i]))
            if len(clauses[j]) >= 0.25 * len(t):
                new = ''.join(clauses[:j] + clauses[j + 1:])
    elif kind == 'hedge_removal':
        for h in _HEDGES:
            if h in t and MODALITY[0].search(p.src) or h in t and any(
                    r[0].search(p.src) for g in ('frequency', 'bound') for r in GROUPS_EN_ZH[g].values()):
                new = t.replace(h, '', 1)
                break
    elif kind == 'range_shift':
        m = RANGE_RX.search(t)
        if m:
            hi = m.group(2)
            nhi = str(int(float(hi)) + 1) if float(hi).is_integer() else str(float(hi) + 1)
            new = t[:m.start(2)] + nhi + t[m.end(2):]
    elif kind == 'taxon_swap':
        spans = list(re.finditer(r'\*([^*\n]+)\*', t))
        names = [m.group(1) for m in spans]
        if len(names) >= 2 and names[0] != names[1]:
            m1, m2 = spans[0], spans[1]
            new = t[:m1.start(1)] + m2.group(1) + t[m1.end(1):m2.start(1)] + m1.group(1) + t[m2.end(1):]
    elif kind == 'citation_swap':
        m = CITE_RX.search(t)
        if m:
            y = m.group(2)
            new = t[:m.start(2)] + str(int(y) + 1) + t[m.start(2) + 4:]
    elif kind == 'direction_swap':
        for a, b in _DIR_SWAP:
            if a in t:
                new = t.replace(a, b, 1)
                break
    elif kind == 'added_claim':
        new = t + _ADDED
    if new is None or new == t:
        return None
    return Pair(p.id, p.page, p.src, new, p.kind)


def calibrate(base: list[Pair], sl: str, tl: str, *, seed: int = 0) -> dict[str, Any]:
    """用真实（或合成）对生成标注集：每类注入 + 未改动对照。报每类召回、每发现类型精度、选定阈值。
    approved 恒为 False：阈值需人工确认后才能让语义检查阻断发布。"""
    rng = random.Random(seed)
    base = [p for p in base if p.kind == '1-1' and _n_words(p.src) >= MIN_WORDS]
    labelled: list[tuple[str | None, Pair]] = [(None, p) for p in base]
    for kind in INJECTION_TYPES:
        for p in base:
            q = inject(kind, p, rng)
            if q is not None:
                labelled.append((kind, q))

    def run(th: Thresholds) -> dict[str, Any]:
        per = {k: {'n': 0, 'hit': 0} for k in INJECTION_TYPES}
        flagged: collections.Counter[str] = collections.Counter()
        tp: collections.Counter[str] = collections.Counter()
        ctrl_fp = 0
        for kind, p in labelled:
            fl, _ = tier1([p], sl, tl, th)
            types = {f.type for f in fl}
            if kind is None:
                ctrl_fp += bool(types)
                for t in types:
                    flagged[t] += 1
                continue
            per[kind]['n'] += 1
            per[kind]['hit'] += bool(types & EXPECTED[kind])
            for t in types:
                flagged[t] += 1
                tp[t] += t in EXPECTED[kind]
        return {'per': per, 'flagged': flagged, 'tp': tp, 'ctrl_fp': ctrl_fp}

    best, best_score = Thresholds(), -1e9
    for lo in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        for add in (1.8, 2.0, 2.4, 2.8):
            th = Thresholds(ratio_lo=lo, ratio_add=add)
            r = run(th)
            score = r['per']['clause_omission']['hit'] + r['per']['added_claim']['hit'] - 3 * r['ctrl_fp']
            if score > best_score:
                best, best_score = th, score
    r = run(best)
    n_ctrl = len(base)
    return {
        'sl': sl, 'tl': tl, 'controls': n_ctrl, 'injected': sum(v['n'] for v in r['per'].values()),
        'per_type': {k: {'n': v['n'], 'recall': (v['hit'] / v['n']) if v['n'] else None} for k, v in r['per'].items()},
        'precision_by_flag': {t: r['tp'][t] / n for t, n in sorted(r['flagged'].items())},
        'control_fp_rate': (r['ctrl_fp'] / n_ctrl) if n_ctrl else None,
        'thresholds': dataclasses.asdict(best), 'approved': False,
        'note': '合成注入集的结果；approved=False 前语义检查只作分流。批准需人工在真实稿上复核后手动改为 true。',
    }


def gate_allowed(cal: dict[str, Any] | None, *, min_recall: float = 0.8, min_precision: float = 0.5,
                 max_control_fp: float = 0.1) -> bool:
    """只有人工批准（approved=True）且每类召回、精度、对照误报率均达标，语义发现才可阻断发布。"""
    if not cal or cal.get('approved') is not True:
        return False
    rec = [v['recall'] for v in cal.get('per_type', {}).values() if v['n']]
    prec = list(cal.get('precision_by_flag', {}).values())
    return bool(rec) and min(rec) >= min_recall and (not prec or min(prec) >= min_precision) \
        and (cal.get('control_fp_rate') or 0) <= max_control_fp


def save_calibration(cal: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(cal, ensure_ascii=False, indent=2), encoding='utf-8')


# ---------------------------------------------------------------- transqa 接口
def check(src: list[Segment], tgt: list[Segment], cfg: dict[str, Any]) -> list[Issue]:
    sl, tl = str(cfg.get('sl', '')), str(cfg.get('tl', ''))
    cal = cfg.get('semantic_calibration')
    th = Thresholds(**cal['thresholds']) if cal and cal.get('thresholds') else Thresholds()
    flags, cov = tier1(build_pairs(src, tgt), sl, tl, th)
    if cov.capability_missing:
        return [Issue('semantic.capability_missing', 'minor',
                      f'语义检查未支持语言对 {sl}→{tl}：未检查（不是通过）', evidence=dataclasses.asdict(cov))]
    block = gate_allowed(cal)
    out = [Issue(f'semantic.{f.type}', 'major' if block and f.severity == 'major' else 'minor', f.reason,
                 page=f.page, segment=f.segment,
                 evidence={'src_quote': f.src_quote, 'tgt_quote': f.tgt_quote, 'confidence': f.confidence, 'tier': 1})
           for f in flags]
    d = dataclasses.asdict(cov)
    d['tier2_fraction'] = cov.tier2_fraction
    out.append(Issue('semantic.coverage', 'info',
                     f'语义 Tier1：已查 {cov.checked}/{cov.pairs_total} 对，未查 {cov.unchecked or 0}，发现 {len(flags)}；'
                     f'Tier2 覆盖 {cov.tier2_fraction:.0%}（分流，未经批准的校准不阻断）', evidence=d))
    return out


# ---------------------------------------------------------------- CLI
def _load(path: str) -> list[Segment]:
    from .segments import segments_from_pages
    return segments_from_pages(Path(path).read_text(encoding='utf-8'))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='语义偏离检测（只分流，不自动改）')
    ap.add_argument('cmd', choices=['tier1', 'calibrate', 'tier2'])
    ap.add_argument('src')
    ap.add_argument('tgt')
    ap.add_argument('--sl', default='en')
    ap.add_argument('--tl', default='zh')
    ap.add_argument('--out')
    ap.add_argument('--translator')
    ap.add_argument('--reviewer')
    ap.add_argument('--cache', default='semcache')
    ap.add_argument('--budget', type=int, default=40)
    ap.add_argument('--control', type=int, default=6)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args(argv)
    pairs = build_pairs(_load(a.src), _load(a.tgt))
    if a.cmd == 'calibrate':
        cal = calibrate(pairs, a.sl, a.tl, seed=a.seed)
        if a.out:
            save_calibration(cal, a.out)
        print(json.dumps(cal, ensure_ascii=False, indent=2))
        return 0
    flags, cov = tier1(pairs, a.sl, a.tl)
    if a.cmd == 'tier1':
        rows = [dataclasses.asdict(f) for f in flags]
        if a.out:
            Path(a.out).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        print(json.dumps({**dataclasses.asdict(cov), 'flags': len(flags)}, ensure_ascii=False))
        return 0
    if not (a.translator and a.reviewer):
        ap.error('tier2 需要 --translator 和 --reviewer')
    ids = {f.segment for f in flags}
    res = tier2(pairs, [p for p in pairs if p.id in ids], translator_engine=a.translator, reviewer_engine=a.reviewer,
                cache_dir=a.cache, budget=a.budget, control=a.control, seed=a.seed)
    cov.tier2_reviewed = res.reviewed
    if a.out:
        Path(a.out).write_text(''.join(json.dumps(i, ensure_ascii=False) + '\n' for i in res.issues), encoding='utf-8')
    print(json.dumps({'reviewed': res.reviewed, 'failed': res.failed, 'reused': res.reused, 'rejected': res.rejected,
                      'issues': len(res.issues), 'tier2_fraction': round(cov.tier2_fraction, 3),
                      'candidates_over_budget': res.candidates_over_budget}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
