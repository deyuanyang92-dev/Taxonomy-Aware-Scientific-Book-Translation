"""人工小样：按段落类型分层的确定性随机抽样，和抽样结果的残余错误率区间（Wilson）。

纯函数，不调用模型，不读写文件。抽样对象是「没被自动流程拦下的」译文段（exclude 排除已在转人工队列里的段），
所以抽样错误率估的是「流程漏过去、人工终审会遇到的」残余错误率。各层每层抽同样多段（不按层大小加权），
合并的 Wilson 区间因此不是全书加权估计，by_stratum 才是分层结果；报告里要这样写。
"""
from __future__ import annotations

import random
import re
from math import sqrt
from typing import Any

from . import taxoblocks
from .aligner import split_paras   # 与对齐检测器同一种切法：para 下标两边通用
from .core import numbers

STRATA = ('numeric', 'key', 'caption', 'description')
NUMERIC_MIN = 5   # 一段里数字串 ≥ 这么多算数字密集段
_SKIP = ('heading', 'reference', 'citation', 'junk')
# taxoblocks 的英文图注词表只有 Fig/Figs/Plate/Pl，不认 "Figure 2."（英文书常见）；这里补，不改词表（词表改了会改变翻译流水线的分流）
_FIGURE = re.compile(r'\s*(?:Figs?|Figures?|Plates?|Pls?)\.?\s*\d', re.I)


def _stratum(text: str, lang: str) -> str | None:
    if sum(numbers(text).values()) >= NUMERIC_MIN:
        return 'numeric'
    k = taxoblocks.kind(text, lang)
    if k == 'key':
        return 'key'
    if k == 'caption' or (k not in _SKIP and _FIGURE.match(text)):
        return 'caption'
    if k in ('description', 'narrative'):
        return 'description'
    return None


def paragraphs(tgt_pg: dict[int, str], lang: str) -> list[dict[str, Any]]:
    """译文每个可抽样的段：{page, para, text, stratum}。para 是该页按空行切出的全部段中的下标
    （含被跳过的标题、文献等段）。lang 是被分类文字的语言（传译文语言），决定图注词表。"""
    out: list[dict[str, Any]] = []
    for page in sorted(tgt_pg):
        for i, text in enumerate(split_paras(tgt_pg[page])):
            st = _stratum(text, lang)
            if st is not None:
                out.append({'page': page, 'para': i, 'text': text, 'stratum': st})
    return out


def draw(paras: list[dict[str, Any]], per_stratum: int, seed: int,
         exclude: set[tuple[int, int]]) -> list[dict[str, Any]]:
    """每层不放回随机抽 min(per_stratum, 可用数) 段。同 seed 同结果，且与输入顺序、其他层无关
    （每层单独用 seed+层名做种子，先按 (page, para) 排序）。返回按层序、页、段排序。"""
    out: list[dict[str, Any]] = []
    for st in STRATA:
        pool = sorted((p for p in paras if p.get('stratum') == st and (p['page'], p['para']) not in exclude),
                      key=lambda p: (p['page'], p['para']))
        k = min(per_stratum, len(pool))
        pick = random.Random(f'{seed}:{st}').sample(pool, k) if k > 0 else []
        out += sorted(pick, key=lambda p: (p['page'], p['para']))
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 得分区间（95% 时 z=1.96）。n == 0 → (0.0, 1.0)。"""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)
