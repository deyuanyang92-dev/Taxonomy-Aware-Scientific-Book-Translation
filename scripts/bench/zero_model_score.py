#!/usr/bin/env python3
"""零模型实测评分（确定性，不调模型）：对比源文与各路径译文。
用法：python3 scripts/bench/zero_model_score.py bench/zero_model  [--json]
指标（全文，n=页数）：学名保留（源中拉丁双名在译文出现）、年份缺失、数字缺失/多出（多重集）、
残留假名、transqa.check_all 按 严重度:code 计数。
"""
import json, re, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from transqa import check_all  # noqa: E402

# 学名 = 双名 + 紧跟 (作者, 年份) 或 n. sp.；纯双词匹配会把德文普通词算进来
BIN = re.compile(r"\b[A-Z][a-z]{2,} (?:\([A-Z][a-z]+\) )?[a-z]{3,}(?= \(?(?:[A-Z][\w.&' -]{1,40}?,? ?\d{4}|n\. ?sp))")
YEAR = re.compile(r"\b1[5-9]\d\d[a-z]?\b|\b20[0-2]\d\b")
NUM = re.compile(r"\d+")
KANA = re.compile(r"[ぁ-ヿ]")


def clean(s):
    s = re.sub(r"<!--.*?-->", "", s)
    return re.sub(r"[*_]", "", s)


def score(src, tgt, sl, tl):
    s, t = clean(src), clean(tgt)
    sb = {m.group(0).lower() for m in BIN.finditer(s)}
    tb = {m.group(0).lower() for m in BIN.finditer(t)}
    sy, ty = Counter(YEAR.findall(s)), Counter(YEAR.findall(t))
    sn, tn = Counter(NUM.findall(s)), Counter(NUM.findall(t))
    iss = check_all(src, tgt, sl, tl, 'taxonomy')
    codes = Counter(f"{i.severity}:{i.code}" for i in iss)
    return {
        'binomials_src': len(sb), 'binomials_kept': len(sb & tb), 'binomials_lost': sorted(sb - tb)[:8],
        'years_src': sum(sy.values()), 'years_missing': sum((sy - ty).values()),
        'num_src': sum(sn.values()), 'num_missing': sum((sn - tn).values()), 'num_extra': sum((tn - sn).values()),
        'kana_residue': len(KANA.findall(t)),
        'transqa': dict(codes),
    }


def main():
    d = Path(sys.argv[1])
    paths = [
        ('ja>en (repo copy, no junk fix)', 'ja_src.md', 'ja_en', 'ja', 'en'),
        ('ja>en', 'ja_src.md', 'ja_en_fix', 'ja', 'en'),
        ('ja>en>zh pivot', 'ja_src.md', 'ja_pivot_zh', 'ja', 'zh-CN'),
        ('ja>zh direct', 'ja_src.md', 'ja_zh_direct_fix', 'ja', 'zh-CN'),
        ('de>en', 'de_src.md', 'de_en', 'de', 'en'),
        ('de>en>zh pivot', 'de_src.md', 'de_pivot_zh', 'de', 'zh-CN'),
        ('de>zh direct', 'de_src.md', 'de_zh_direct', 'de', 'zh-CN'),
    ]
    out = {}
    for name, sf, wd, sl, tl in paths:
        f = d / wd / 'checked.md'
        if f.exists():
            out[name] = score((d / sf).read_text(encoding='utf-8'), f.read_text(encoding='utf-8'), sl, tl)
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for k, v in out.items():
            print(k, json.dumps(v, ensure_ascii=False))


if __name__ == '__main__':
    main()
