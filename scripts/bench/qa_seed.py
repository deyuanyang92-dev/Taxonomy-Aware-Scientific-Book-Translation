#!/usr/bin/env python3
"""植入基准：在译文里植入已知错误，用来量 qa_run 的检出率（只用于方案比较和回归，不用于真实书稿）。

用法：
  python3 scripts/bench/qa_seed.py <src.md> <tgt.md> -o <tgt_seeded.md> --seeds <seeds.json> [--n-per-kind 6] [--rng-seed N]

五种错误（每种最多 n_per_kind 处，每个段落至多植入一处）：
  number    译文里与原文一致的数字（后接 mm/cm/pairs/segments/chaetigers/m）加 3、5 或 9
  flip      含义翻转：absent↔present、anterior↔posterior、dorsal↔ventral、longer↔shorter 等
  species   学名改拼：只改「原文里原样出现」的二名法的种加名（普通英文短语不会被当成学名）
  addition  段末凭空添加一句原文没有的话
  omission  删去一整句；被删的句子 ≥ 20 个字符、≥ 3 个词（不会只删掉「.」「Annelida.」）
无效候选跳过并换下一个；凑不满时返回实际数量，清单每项带 valid: true。
只用两边段数相等的页（段落序号才能和 qa_align / 抽样共用）。同一输入和 rng_seed 得到同一结果。

清单每项：kind, page, para（transqa.aligner.split_paras 的段序号）, old_para, new_para, orig, mut,
span（被改处在 new_para 里的 [起, 止)；omission 为删除点，起=止）, valid。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))   # 仓库根：transqa
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # scripts/：taxoformat
from transqa import aligner  # noqa: E402
import taxoformat  # noqa: E402

MARK = re.compile(r'(?m)^[ \t]*<!-- PDF p\.(\d+)\b[^\n]*$')
FW = str.maketrans('０１２３４５６７８９', '0123456789')
KINDS = ('number', 'flip', 'species', 'addition', 'omission')
FLIPS = [('absent', 'present'), ('present', 'absent'), ('larger', 'smaller'), ('smaller', 'larger'),
         ('longer', 'shorter'), ('shorter', 'longer'), ('anterior', 'posterior'), ('posterior', 'anterior'),
         ('dorsal', 'ventral'), ('ventral', 'dorsal'), ('upper', 'lower'), ('lower', 'upper')]
NUMBER = re.compile(r'(?<![\w.\-])(\d{1,3})(?= ?(?:mm|cm|pairs|segments|chaetigers|m\b))')
BINOMIAL = re.compile(r'\b([A-Z][a-z]{3,}) ([a-z]{5,})\b')
ADDITIONS = ['This species is common in muddy sediments of the intertidal zone.',
             'The type material has been lost.',
             'Specimens are often found in association with sponges.']


def _regions(md: str) -> dict[int, tuple[int, int]]:
    """{页号: (起, 止)}：从该页标记行开始到下一个标记行之前。"""
    ms = list(MARK.finditer(md))
    out: dict[int, tuple[int, int]] = {}
    for i, m in enumerate(ms):
        out[int(m.group(1))] = (m.start(), ms[i + 1].start() if i + 1 < len(ms) else len(md))
    return out


def _paras(md: str, page: int) -> list[tuple[int, int, str]]:
    """该页各段在 md 里的 (起, 止, 文字)，段序号同 aligner.split_paras。"""
    lo, hi = _regions(md)[page]
    text = md[lo:hi]
    out, cur = [], 0
    for p in aligner.split_paras(text):
        i = text.find(p, cur)
        out.append((lo + i, lo + i + len(p), p))
        cur = i + len(p)
    return out


def _page_paras(md: str) -> dict[int, list[str]]:
    return {p: [t for _, _, t in _paras(md, p)] for p in _regions(md)}


def _number(t: str, s: str, rng: random.Random, genera: frozenset[str]) -> dict[str, Any] | None:
    s2 = s.translate(FW)
    ms = [m for m in NUMBER.finditer(t) if m.group(1) in s2]
    if not ms:
        return None
    m = rng.choice(ms)
    n2 = str(int(m.group(1)) + rng.choice([3, 5, 9]))
    return {'new': t[:m.start(1)] + n2 + t[m.end(1):], 'orig': m.group(1), 'mut': n2,
            'span': [m.start(1), m.start(1) + len(n2)]}


def _flip(t: str, s: str, rng: random.Random, genera: frozenset[str]) -> dict[str, Any] | None:
    pairs = FLIPS[:]
    rng.shuffle(pairs)
    for a, b in pairs:
        m = re.search(rf'\b{a}\b', t)
        if m:
            return {'new': t[:m.start()] + b + t[m.end():], 'orig': a, 'mut': b,
                    'span': [m.start(), m.start() + len(b)]}
    return None


def _species(t: str, s: str, rng: random.Random, genera: frozenset[str]) -> dict[str, Any] | None:
    # 原文里原样出现，且属名是已知属（WoRMS Annelida + 文本里的新种/命名人年份推出的属）才算学名：
    # 参考文献标题里的 'Polychaetous annelids' 会原样出现在原文，只靠「原样出现」挡不住它
    ms = [m for m in BINOMIAL.finditer(t) if m.group(0) in s and m.group(1) in genera]
    if not ms:
        return None
    m = rng.choice(ms)
    ep = m.group(2)
    ep2 = ep[:-2] + ('is' if not ep.endswith('is') else 'us')
    return {'new': t[:m.start(2)] + ep2 + t[m.end(2):], 'orig': m.group(0), 'mut': f'{m.group(1)} {ep2}',
            'span': [m.start(), m.start() + len(m.group(1)) + 1 + len(ep2)]}


def _addition(t: str, s: str, rng: random.Random, genera: frozenset[str]) -> dict[str, Any] | None:
    cands = [a for a in ADDITIONS if a not in t]
    if not cands:
        return None
    a = rng.choice(cands)
    return {'new': t + ' ' + a, 'orig': '', 'mut': a, 'span': [len(t) + 1, len(t) + 1 + len(a)]}


def _good_omission(sent: str) -> bool:
    return len(sent) >= 20 and len(sent.split()) >= 3 and len(re.findall(r'[A-Za-z]', sent)) >= 8


ABBREV = {'fig', 'figs', 'sp', 'spp', 'cf', 'no', 'nos', 'pl', 'var', 'ssp', 'st', 'vs', 'al', 'etc', 'p', 'pp'}


def _sentences(t: str) -> list[str]:
    """按「. 」切句，但不在 Fig. / sp. / cf. 等缩写后切（否则 '(Fig.' 会被当成一句）。"""
    out, cur = [], 0
    for m in re.finditer(r'\. ', t):
        word = re.search(r'([A-Za-z]+)$', t[cur:m.start()])
        if word and word.group(1).lower() in ABBREV:
            continue
        out.append(t[cur:m.start() + 1])
        cur = m.end()
    out.append(t[cur:])
    return out


def _omission(t: str, s: str, rng: random.Random, genera: frozenset[str]) -> dict[str, Any] | None:
    ss = _sentences(t)
    if len(ss) < 3:
        return None
    ks = [k for k in range(1, len(ss) - 1) if _good_omission(ss[k])]
    if not ks:
        return None
    k = rng.choice(ks)
    head = ' '.join(ss[:k])
    return {'new': ' '.join(ss[:k] + ss[k + 1:]), 'orig': ss[k], 'mut': '', 'span': [len(head), len(head)]}


MUTATORS = {'number': _number, 'flip': _flip, 'species': _species, 'addition': _addition, 'omission': _omission}


def seed(src_md: str, tgt_md: str, *, n_per_kind: int = 6,
         rng_seed: int = 20261120) -> tuple[str, list[dict[str, Any]]]:
    """返回（植入后的译文, 植入清单）。无效候选跳过，凑不满返回实际数量。"""
    rng = random.Random(rng_seed)
    genera = taxoformat.build_lexicon([src_md, tgt_md]).genera
    src_pp, tgt_pp = _page_paras(src_md), _page_paras(tgt_md)
    ok = sorted(p for p in tgt_pp if p in src_pp and len(src_pp[p]) == len(tgt_pp[p]))
    used: set[tuple[int, int]] = set()
    seeds: list[dict[str, Any]] = []
    out = tgt_md
    for kind in KINDS:
        cands = [(p, i) for p in ok for i, t in enumerate(tgt_pp[p]) if len(t) > 150 and (p, i) not in used]
        rng.shuffle(cands)
        got = 0
        for p, i in cands:
            if got >= n_per_kind:
                break
            old = tgt_pp[p][i]
            r = MUTATORS[kind](old, src_pp[p][i], rng, genera)
            if r is None or r['new'] == old:
                continue
            lo, hi, text = _paras(out, p)[i]
            assert text == old                      # 前面的植入只改段内，不改段数和顺序
            out = out[:lo] + r['new'] + out[hi:]
            used.add((p, i))
            got += 1
            seeds.append({'kind': kind, 'page': p, 'para': i, 'old_para': old, 'new_para': r['new'],
                          'orig': r['orig'], 'mut': r['mut'], 'span': r['span'], 'valid': True})
    return out, seeds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('tgt')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--seeds', required=True)
    ap.add_argument('--n-per-kind', type=int, default=6)
    ap.add_argument('--rng-seed', type=int, default=20261120)
    a = ap.parse_args(argv)
    seeded, seeds = seed(Path(a.src).read_text(encoding='utf-8'), Path(a.tgt).read_text(encoding='utf-8'),
                         n_per_kind=a.n_per_kind, rng_seed=a.rng_seed)
    Path(a.out).write_text(seeded, encoding='utf-8')
    Path(a.seeds).write_text(json.dumps(seeds, ensure_ascii=False, indent=1), encoding='utf-8')
    counts = {k: sum(1 for s in seeds if s['kind'] == k) for k in KINDS}
    print(f'seeded {len(seeds)} {counts} → {a.out}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
