"""OCR 行框的阅读顺序：单栏保持检测顺序；双栏先左栏自上而下，再右栏自上而下。

纯函数，不依赖 OCR 引擎。输入的每一行是 RapidOCR 的 [box, text, score]，
box 为四个角点 [[x, y], ...]；只用到框的外接矩形。

判栏方法：把所有框的 x 区间做覆盖计数，在页面中间 30%~70% 内找「覆盖数很低」的最宽空带（中缝）。
跨过中缝的通栏框（标题、图注、页脚）不计入覆盖容忍度之外的判断，只作为分隔符：
它们把页面切成若干纵向区段，每个区段内先左栏后右栏。
只出现在一半页面上的页眉/页码（位于另一栏内容之上或之下、且与同栏文字相隔较远）同样当作分隔符。
"""

from __future__ import annotations

import bisect
from typing import Any, Sequence

MAX_HEADER_ROWS = 2
MIN_SIDE = 3          # 每栏至少要有这么多框，才算分栏
MID_BAND = (0.30, 0.70)  # 中缝必须落在内容宽度的这一段内
GUTTER_MIN_FRAC = 0.01   # 中缝最小宽度 / 内容宽度
SPAN_TOL_FRAC = 0.10     # 中缝处允许被通栏框（标题、图注、页脚）覆盖的比例
SPAN_TOL_MIN = 3         # 并且至少容忍这么多个
OVERLAP_MIN = 0.25       # 两栏纵向重叠占较矮一栏的最小比例
ISOLATION_LINES = 2.0    # 页脚判定：与同栏上一行的间距至少是中位行高的几倍


class _Box:
    __slots__ = ("i", "x0", "y0", "x1", "y1")

    def __init__(self, i: int, row: Sequence[Any]):
        pts = row[0]
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        self.i = i
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _find_gutter(boxes: list[_Box]) -> tuple[float, float] | None:
    """返回中缝 (g0, g1)；找不到返回 None。"""
    n = len(boxes)
    xmin = min(b.x0 for b in boxes)
    xmax = max(b.x1 for b in boxes)
    width = xmax - xmin
    if width <= 0:
        return None
    lo, hi = xmin + MID_BAND[0] * width, xmin + MID_BAND[1] * width
    tol = max(SPAN_TOL_MIN, int(SPAN_TOL_FRAC * n))
    starts = sorted(b.x0 for b in boxes)
    ends = sorted(b.x1 for b in boxes)
    coords = sorted({lo, hi, *[c for b in boxes for c in (b.x0, b.x1) if lo < c < hi]})
    best: tuple[float, float] | None = None
    run_start: float | None = None
    for a, b in zip(coords, coords[1:]):
        # 区间 [a, b] 的覆盖数 = x0 <= a 的框数 - x1 <= a 的框数
        cov = bisect.bisect_right(starts, a) - bisect.bisect_right(ends, a)
        if cov <= tol:
            if run_start is None:
                run_start = a
            cand = (run_start, b)
            if best is None or cand[1] - cand[0] > best[1] - best[0]:
                best = cand
        else:
            run_start = None
    if best is None:
        return None
    min_w = max(GUTTER_MIN_FRAC * width, 0.5 * _median([b.h for b in boxes]))
    if best[1] - best[0] < min_w:
        return None
    return best


def _line_sorted(items: list[_Box]) -> list[_Box]:
    """栏内自上而下；同一行被切成多个框的，按 x 自左向右。"""
    groups: list[list[_Box]] = []
    for b in sorted(items, key=lambda t: (t.yc, t.x0)):
        if groups:
            g0 = groups[-1][0]
            if abs(b.yc - g0.yc) <= 0.5 * min(b.h, g0.h):
                groups[-1].append(b)
                continue
        groups.append([b])
    return [b for g in groups for b in sorted(g, key=lambda t: t.x0)]


def _v_overlap(a: list[_Box], b: list[_Box]) -> float:
    a0, a1 = min(t.y0 for t in a), max(t.y1 for t in a)
    b0, b1 = min(t.y0 for t in b), max(t.y1 for t in b)
    inter = min(a1, b1) - max(a0, b0)
    shorter = min(a1 - a0, b1 - b0)
    return inter / shorter if shorter > 0 else 0.0


def order_rows(rows: Sequence[Any]) -> list[Any]:
    """按阅读顺序重排 OCR 行；单栏页原样返回（保持检测顺序）。"""
    out = list(rows)
    if len(out) < 2 * MIN_SIDE + 1:
        return out
    boxes = [_Box(i, r) for i, r in enumerate(out)]
    gutter = _find_gutter(boxes)
    if gutter is None:
        return out
    g0, g1 = gutter
    gc = (g0 + g1) / 2

    neutral: list[_Box] = []  # 通栏框、页眉页脚：只当分隔符
    left: list[_Box] = []
    right: list[_Box] = []
    for b in boxes:
        if b.x0 < g0 and b.x1 > g1:
            neutral.append(b)
        elif b.xc < gc:
            left.append(b)
        else:
            right.append(b)
    if len(left) < MIN_SIDE or len(right) < MIN_SIDE or _v_overlap(left, right) < OVERLAP_MIN:
        return out

    medh = _median([b.h for b in boxes])
    l_top, l_bot = min(b.y0 for b in left), max(b.y1 for b in left)
    r_top, r_bot = min(b.y0 for b in right), max(b.y1 for b in right)

    def split_margin(col: list[_Box], o_top: float, o_bot: float) -> list[_Box]:
        """把栏内的页眉（整体在另一栏首行之上）、孤立页脚（整体在另一栏末行之下、与上一行相隔甚远）摘出去。"""
        keep: list[_Box] = []
        srt = sorted(col, key=lambda t: t.yc)
        n_above = sum(1 for t in srt if t.y1 < o_top)
        for k, b in enumerate(srt):
            if b.y1 < o_top and n_above <= MAX_HEADER_ROWS:  # 多于两行就是正文（另一栏被图推后），不摘
                neutral.append(b)
            elif b.y0 > o_bot and (k == 0 or b.y0 - srt[k - 1].y1 >= ISOLATION_LINES * medh):
                neutral.append(b)
            else:
                keep.append(b)
        return keep

    left = split_margin(left, r_top, r_bot)
    right = split_margin(right, l_top, l_bot)

    neutral = _line_sorted(neutral)
    ncuts: list[float] = []
    for t in neutral:
        ncuts.append(max(ncuts[-1], t.yc) if ncuts else t.yc)

    def band(b: _Box) -> int:
        return bisect.bisect_left(ncuts, b.yc)

    result: list[int] = []
    for k in range(len(neutral) + 1):
        if k > 0:
            result.append(neutral[k - 1].i)
        result += [b.i for b in _line_sorted([b for b in left if band(b) == k])]
        result += [b.i for b in _line_sorted([b for b in right if band(b) == k])]
    if len(result) != len(out):
        return list(rows)  # 防御：不应发生
    return [out[i] for i in result]
