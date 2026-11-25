#!/usr/bin/env python3
"""源语言术语前置替换：从已译完的书学「源术语 → 英文词」映射，下一本送 Google 前先替换。零模型。

依据（2026-11-20，Imajima 三卷日→英，映射由另两卷学得，留出一卷）：
  映射覆盖的术语在 Google 初稿里命中 27%，前置替换后 95.6%（120 段随机抽样，改写稿 90.7%）。
  日文术语词次在另两卷出现过的占 80–86%，所以每译一本都可累积。

用法：
  python3 term_presub.py learn SRC.md FINAL.md [SRC2.md FINAL2.md ...] -o map.tsv [--min-count 3] [--min-dice 0.6]
  python3 term_presub.py apply map.tsv SRC.md -o SRC.presub.md     # 送 Google 前

映射是共现统计，会学错（如 体長→width）：map.tsv 带 count/dice，上线前要审；--deny 文件里的词直接排除。
对齐用段落级动态规划（学名、数字、长度相似度），只用置信对齐的段落学习。
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

TOKEN_RE = {
    'ja': re.compile(r'[ァ-ヴー]{3,}|[一-鿿]{2,}'),
    'zh': re.compile(r'[一-鿿]{2,}'),
}
STOP = set('with that this from which have been were also than their there these those other when where into over '
           'under between each both only more most some such about after before during while without within through'.split())
STEM = 6


def paras(text: str) -> list[str]:
    return [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip() and not p.strip().startswith('<!--')]


def _sig(p: str) -> set[str]:
    return set(re.findall(r'[A-Z][a-z]{3,}|\d+(?:\.\d+)?|[a-z]{5,}ae\b', p))


def _score(s: str, e: str) -> float:
    a, b = _sig(s), _sig(e)
    j = len(a & b) / len(a | b) if a | b else 0.3
    la, lb = len(s), len(e) * 3
    ratio = min(la, lb) / max(la, lb) if max(la, lb) else 0
    return j * 2 + ratio - 0.3


def align(src: list[str], tgt: list[str], window: int = 40, confident: float = 0.5) -> list[tuple[int, int]]:
    """段落级单调对齐（允许两侧各自跳段）。返回得分 > confident 的 (源段号, 译段号)。"""
    n, m, gap, neg = len(src), len(tgt), -0.4, -1e9
    dp: list[dict[int, float]] = [{} for _ in range(n + 1)]
    bp: list[dict[int, str]] = [{} for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        c = int(i * m / max(n, 1))
        for j in range(max(0, c - window), min(m, c + window) + 1):
            if i == 0 and j == 0:
                continue
            best, arg = neg, ''
            if i and j and (j - 1) in dp[i - 1]:
                best, arg = dp[i - 1][j - 1] + _score(src[i - 1], tgt[j - 1]), 'd'
            if i and j in dp[i - 1] and dp[i - 1][j] + gap > best:
                best, arg = dp[i - 1][j] + gap, 'u'
            if j and (j - 1) in dp[i] and dp[i][j - 1] + gap > best:
                best, arg = dp[i][j - 1] + gap, 'l'
            if arg:
                dp[i][j], bp[i][j] = best, arg
    i, j, out = n, m, []
    while i or j:
        a = bp[i].get(j)
        if a == 'd':
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif a == 'u':
            i -= 1
        elif a == 'l':
            j -= 1
        else:
            break
    return [(i, j) for i, j in out[::-1] if _score(src[i], tgt[j]) > confident]


def learn(pairs: list[tuple[str, str]], lang: str = 'ja', min_count: int = 3,
          min_dice: float = 0.6, deny: set[str] | None = None) -> list[dict[str, object]]:
    """pairs: (源段, 英文段)。用 Dice 共现学「源术语 → 英文词干」，再取该词干最常见的完整词形。"""
    tok = TOKEN_RE[lang]
    tf: collections.Counter[str] = collections.Counter()
    ef: collections.Counter[str] = collections.Counter()
    co: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    full: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for s, e in pairs:
        ws = [w for w in re.findall(r'[a-z]{4,}', e.lower()) if w not in STOP]
        es = {w[:STEM] for w in ws}
        for w in ws:
            full[w[:STEM]][w] += 1
        ts = set(tok.findall(s))
        tf.update(ts)
        ef.update(es)
        for t in ts:
            co[t].update(es)
    rows: list[dict[str, object]] = []
    for t, n in tf.items():
        if n < min_count or (deny and t in deny) or not co[t]:
            continue
        stem, c = max(co[t].items(), key=lambda x: x[1] / (n + ef[x[0]] - x[1]))
        dice = c / (n + ef[stem] - c)
        if dice >= min_dice and full[stem]:
            rows.append({'src': t, 'en': full[stem].most_common(1)[0][0], 'count': n, 'dice': round(dice, 3)})
    return sorted(rows, key=lambda r: -int(r['count']))  # type: ignore[call-overload]


def load_map(path: str | Path) -> dict[str, str]:
    with open(path, encoding='utf-8', newline='') as f:
        return {r['src']: r['en'] for r in csv.DictReader(f, delimiter='\t') if r.get('src') and r.get('en')}


def presub(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """把映射里的源术语换成英文词（两侧留空格，便于机翻保留）。最长优先。返回 (新文本, 替换次数)。"""
    if not mapping:
        return text, 0
    pat = re.compile('|'.join(map(re.escape, sorted(mapping, key=len, reverse=True))))
    n = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return f' {mapping[m.group(0)]} '
    return pat.sub(sub, text), n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    lp = sub.add_parser('learn')
    lp.add_argument('files', nargs='+', help='SRC FINAL [SRC FINAL ...]')
    lp.add_argument('-o', '--out', required=True)
    lp.add_argument('--lang', default='ja', choices=sorted(TOKEN_RE))
    lp.add_argument('--min-count', type=int, default=3)
    lp.add_argument('--min-dice', type=float, default=0.6)
    lp.add_argument('--deny', help='每行一个要排除的源术语（人工审出的错配）')
    ap_ = sub.add_parser('apply')
    ap_.add_argument('map')
    ap_.add_argument('src')
    ap_.add_argument('-o', '--out', required=True)
    a = ap.parse_args(argv)
    if a.cmd == 'learn':
        if len(a.files) % 2:
            ap.error('文件要成对给出：SRC FINAL')
        pairs: list[tuple[str, str]] = []
        for k in range(0, len(a.files), 2):
            s = paras(Path(a.files[k]).read_text(encoding='utf-8'))
            e = paras(Path(a.files[k + 1]).read_text(encoding='utf-8'))
            al = align(s, e)
            print(f'{a.files[k]}: {len(s)} 段 / {len(e)} 段，置信对齐 {len(al)}', file=sys.stderr)
            pairs += [(s[i], e[j]) for i, j in al]
        deny = set(Path(a.deny).read_text(encoding='utf-8').split()) if a.deny else None
        rows = learn(pairs, a.lang, a.min_count, a.min_dice, deny)
        with open(a.out, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['src', 'en', 'count', 'dice'], delimiter='\t')
            w.writeheader()
            w.writerows(rows)
        print(f'映射 {len(rows)} 条 → {a.out}（共现统计，上线前请审；错配写进 --deny）', file=sys.stderr)
    else:
        out, n = presub(Path(a.src).read_text(encoding='utf-8'), load_map(a.map))
        Path(a.out).write_text(out, encoding='utf-8')
        print(f'替换 {n} 处 → {a.out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
