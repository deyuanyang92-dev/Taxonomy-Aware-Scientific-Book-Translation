#!/usr/bin/env python3
"""OCR 评分器（唯一评分口径，供 test-ocr 全部引擎共用）。

用法：
  python3 scripts/bench/ocr_score.py selftest
  python3 scripts/bench/ocr_score.py page <gold.txt> <hyp.txt>

口径：
  raw   : 只统一换行，保留空白与标点（能看出空格类参数的效果）。
  norm  : 全角数字/标点折叠，去空白、点线引导符、孤立页码；不做 Unicode 降级，旧字形保留。
  CER = Levenshtein(gold, hyp) / len(gold)（真编辑距离，rapidfuzz 缺失时退回纯 Python）。
  bag_err = 1 - 字符袋 F1（不受读序影响）；order_gap = cer_norm - bag_err_norm（>0 说明读序错）。
  len_ratio = len(hyp)/len(gold)（<0.85 疑漏行，>1.2 疑幻觉）。
  分类召回：假名 / 汉字 / 数字 / 拉丁（金标中该类字符被 hyp 袋覆盖的比例）。
"""
from __future__ import annotations

import collections
import re
import sys
from typing import Any

try:
    from rapidfuzz.distance import Levenshtein as _Lev
except ImportError:  # pragma: no cover
    _Lev = None  # type: ignore[assignment]

_FOLD = str.maketrans('０１２３４５６７８９（）；，：~’”．。、―─', '0123456789();,:～\'"..,——')
_PUNCT = re.compile(r'[.,;:()\'"\-—～~·◆、。，．；：（）]')


def norm_raw(s: str) -> str:
    return s.replace('\r\n', '\n').replace('\r', '\n').strip('\n')


def norm(s: str) -> str:
    s = norm_raw(s).translate(_FOLD)
    s = re.sub(r'[.。…・]{2,}|…', '', s)
    s = re.sub(r'^\d{1,3}$', '', s, flags=re.M)  # 孤立页码行
    return re.sub(r'\s', '', s)


def norm_nopunct(s: str) -> str:
    return _PUNCT.sub('', norm(s))


def _lev(a: str, b: str) -> int:
    if _Lev is not None:
        return int(_Lev.distance(a, b))
    prev = list(range(len(b) + 1))  # pragma: no cover
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(gold: str, hyp: str) -> float:
    if not gold:
        return 0.0 if not hyp else 1.0
    return _lev(gold, hyp) / len(gold)


def bag_f1(gold: str, hyp: str) -> float:
    a, b = collections.Counter(gold), collections.Counter(hyp)
    ov = sum((a & b).values())
    if not ov:
        return 0.0
    p, r = ov / sum(b.values()), ov / sum(a.values())
    return 2 * p * r / (p + r)


_CLASSES = {
    'kana': re.compile(r'[぀-ヿㇰ-ㇿ]'),
    'kanji': re.compile(r'[一-鿿㐀-䶿豈-﫿]'),
    'digit': re.compile(r'[0-9]'),
    'latin': re.compile(r'[A-Za-z]'),
}


def class_recall(gold: str, hyp: str) -> dict[str, float | None]:
    hb = collections.Counter(hyp)
    out: dict[str, float | None] = {}
    for k, rx in _CLASSES.items():
        g = collections.Counter(rx.findall(gold))
        n = sum(g.values())
        out[k] = sum((g & hb).values()) / n if n else None
    return out


def score_page(gold: str, hyp: str) -> dict[str, Any]:
    gn, hn = norm(gold), norm(hyp)
    gp, hp = norm_nopunct(gold), norm_nopunct(hyp)
    gr, hr = norm_raw(gold), norm_raw(hyp)
    c_norm = cer(gn, hn)
    bag = 1 - bag_f1(gn, hn)
    return {
        'cer_raw': cer(gr, hr),
        'cer_norm': c_norm,
        'cer_nopunct': cer(gp, hp),
        'bag_err': bag,
        'order_gap': c_norm - bag,
        'len_ratio': (len(hn) / len(gn)) if gn else float('nan'),
        'n_gold': len(gn),
        'recall': class_recall(gn, hn),
    }


# ---- 自检闸口：固定样例，输出变了就整批作废 ----
_SELFTEST: list[tuple[str, str, str, float]] = [
    # (说明, gold, hyp, 期望 cer_norm)
    ('完全相同', '多毛類の分類', '多毛類の分類', 0.0),
    ('1 替换/6 字', '多毛類の分類', '多毛類の分頬', 1 / 6),
    ('空白不计 norm', '多毛 類', '多毛類', 0.0),
    ('全角数字折叠', '１２３', '123', 0.0),
    ('1 漏字/4 字', 'ゴカイ科', 'ゴカイ', 1 / 4),
    ('孤立页码行不计', '本文\n61\n', '本文', 0.0),
    ('点线引导符不计', '科名.......12', '科名12', 0.0),
]


def selftest() -> bool:
    ok = True
    for name, g, h, exp in _SELFTEST:
        got = score_page(g, h)['cer_norm']
        if abs(got - exp) > 1e-9:
            print(f'FAIL {name}: got {got:.6f} expect {exp:.6f}')
            ok = False
    raw = score_page('多毛 類', '多毛類')['cer_raw']
    if abs(raw - 1 / 4) > 1e-9:
        print(f'FAIL raw 保留空白: got {raw}')
        ok = False
    s = score_page('ABCあ', 'あCBA')
    if not (s['order_gap'] > 0 and abs(s['bag_err']) < 1e-9):
        print(f'FAIL 读序差: {s}')
        ok = False
    print('selftest', 'OK' if ok else 'FAILED')
    return ok


def main(argv: list[str]) -> int:
    if argv[:1] == ['selftest']:
        return 0 if selftest() else 1
    if argv[:1] == ['page'] and len(argv) == 3:
        from pathlib import Path
        r = score_page(Path(argv[1]).read_text(), Path(argv[2]).read_text())
        for k, v in r.items():
            print(k, v)
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
