"""Per-line and per-word typographic features measured on a scanned page image.

Zero model, CPU only.  Input is a page image (grey, any dpi) plus OCR line
boxes (PP-OCR rows [polygon, text, score] in the OCR raster's pixel space).
Output per line: x-height and ascender height in points, relative stroke
width (bold cue), and per-word slant angle (italic cue).

Slant: each word crop is sheared by candidate angles; the angle that makes
the vertical ink projection sharpest (max sum of squares) is the stroke slant.
Upright roman lands near 0 deg, italic near 10-20 deg.
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

ANGLES = np.arange(-6.0, 26.0, 1.0)


@dataclass
class Word:
    text: str
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in page-image px
    slant: float


@dataclass
class Line:
    text: str
    score: float
    box: tuple[int, int, int, int]
    x_height_pt: float
    asc_pt: float
    stroke_rel: float  # stroke width / x-height
    caps_ratio: float  # x-height / ascender height (high = all caps)
    words: list[Word] = field(default_factory=list)
    slant: float = 0.0  # width-weighted mean over words


def binarize(gray: np.ndarray) -> np.ndarray:
    return gray < 128


def _bands(ink: np.ndarray) -> tuple[int, int, int]:
    """(top of ink, top of x band, baseline) inside a line crop."""
    prof = ink.sum(axis=1).astype(float)
    if prof.max() <= 0:
        return 0, 0, ink.shape[0]
    rows = np.nonzero(prof > 0.02 * prof.max())[0]
    core = np.nonzero(prof >= 0.35 * prof.max())[0]
    return int(rows[0]), int(core[0]), int(core[-1]) + 1


def stroke_width(ink: np.ndarray) -> float:
    if ink.sum() == 0:
        return 0.0
    dt = ndimage.distance_transform_edt(ink)
    ridge = (dt == ndimage.maximum_filter(dt, size=3)) & ink
    vals = dt[ridge]
    return float(2.0 * np.median(vals)) if vals.size else 0.0


def slant_angle(ink: np.ndarray, baseline: int) -> float:
    if ink.sum() < 20 or ink.shape[1] < 4:
        return 0.0
    ys, xs = np.nonzero(ink)
    best, best_a = -1.0, 0.0
    for a in ANGLES:
        t = math.tan(math.radians(a))
        x2 = np.round(xs + t * (ys - baseline)).astype(int)
        x2 -= x2.min()
        s = float((np.bincount(x2).astype(float) ** 2).sum())
        if s > best:
            best, best_a = s, float(a)
    return best_a


def _blank_cols(ink: np.ndarray, deg: float) -> np.ndarray:
    """Ink presence per column after shearing by deg about the crop's middle row."""
    if deg == 0:
        return ink.any(axis=0)
    ys, xs = np.nonzero(ink)
    col = np.zeros(ink.shape[1], bool)
    if xs.size:
        x2 = np.round(xs + math.tan(math.radians(deg)) * (ys - ink.shape[0] / 2)).astype(int)
        col[np.clip(x2, 0, ink.shape[1] - 1)] = True
    return col


def split_words(ink: np.ndarray, gap: int) -> list[tuple[int, int]]:
    # a gap is blank either upright or along the italic slant: italic overhang
    # closes the upright gap between an italic word and a following roman word
    col = _blank_cols(ink, 0) & _blank_cols(ink, 14)
    spans: list[tuple[int, int]] = []
    start, blank, last = None, 0, 0
    for x, v in enumerate(col):
        if v:
            if start is None:
                start = x
            blank, last = 0, x
        elif start is not None:
            blank += 1
            if blank >= gap:
                spans.append((start, last + 1))
                start, blank = None, 0
    if start is not None:
        spans.append((start, last + 1))
    return spans


def align_words(ink: np.ndarray, xh: int, n_tokens: int) -> list[tuple[int, int]]:
    """Ink spans for words; the gap threshold is searched so the span count equals
    the OCR token count when possible (otherwise the 0.33 x-height default)."""
    default = split_words(ink, max(2, int(round(0.33 * xh))))
    if len(default) == n_tokens or n_tokens == 0:
        return default
    for f in (0.25, 0.3, 0.4, 0.45, 0.5, 0.6, 0.2, 0.7, 0.8):
        sp = split_words(ink, max(2, int(round(f * xh))))
        if len(sp) == n_tokens:
            return sp
    return default


DIAGONAL = set("vwxyAVWXYkK")
WIDE_MIN = 1.2  # min word width (x-heights) for a slant reading


def split_mixed(ink: np.ndarray, span: tuple[int, int], xh: int, base: int,
                hi: float = 10.0, lo: float = 3.0) -> list[tuple[int, int]]:
    """Split a long span where the slant changes between italic and roman.

    An italic word followed by a roman one often leaves no blank column, so
    the two arrive as one span.  Windows of ~2.5 x-heights are read for slant;
    at an italic/roman transition the span is cut at the emptiest column."""
    a, b = span
    if b - a < 6 * xh:
        return [span]
    win, step = int(2.5 * xh), max(1, xh)
    marks = []
    for x in range(a, b - win + 1, step):
        s = slant_angle(ink[:, x:x + win], base)
        marks.append((x, 1 if s >= hi else (0 if s <= lo else None)))
    cuts = []
    prev = None
    for x, m in marks:
        if m is None:
            continue
        if prev is not None and m != prev[1]:
            lo_x, hi_x = prev[0] + win // 2, x + win // 2
            if hi_x > lo_x:
                col = ink[:, lo_x:hi_x].sum(axis=0)
                cuts.append(lo_x + int(np.argmin(col)))
        prev = (x, m)
    out, s0 = [], a
    for c in cuts:
        if c - s0 >= xh and b - c >= xh:
            out.append((s0, c))
            s0 = c
    out.append((s0, b))
    return out


def italic_words(line: "Line", xh_px: float, thr: float = 9.0) -> list[bool | None]:
    """True/False per word; None when the word is too narrow for a slant reading
    or made mostly of letters with diagonal strokes (v, w, y, A ...), which read
    as slanted even in roman."""
    out: list[bool | None] = []
    for w in line.words:
        wide = (w.box[2] - w.box[0]) >= WIDE_MIN * xh_px
        letters = [c for c in w.text if c.isalpha()]
        diag = bool(letters) and sum(c in DIAGONAL for c in letters) / len(letters) >= 0.3
        out.append((w.slant >= thr) if wide and not diag else None)
    # narrow words inherit when both neighbours agree
    for i, v in enumerate(out):
        if v is None:
            left = next((out[j] for j in range(i - 1, -1, -1) if out[j] is not None), None)
            right = next((out[j] for j in range(i + 1, len(out)) if out[j] is not None), None)
            if left is not None and left == right:
                out[i] = left
    return out


def book_threshold(lines: "list[Line]", default: float = 9.0, min_gap: float = 4.0,
                   min_frac: float = 0.01) -> float:
    """Per-book italic slant threshold: Otsu split of the slant of wide, non-diagonal
    words.  Falls back to `default` when the two clusters are closer than min_gap
    degrees or the upper cluster holds under min_frac of the words (no italic)."""
    vals = []
    for ln in lines:
        xh = ln.x_height_pt * 300 / 72 if ln.x_height_pt else 0
        for w in ln.words:
            letters = [c for c in w.text if c.isalpha()]
            diag = bool(letters) and sum(c in DIAGONAL for c in letters) / len(letters) >= 0.3
            if (w.box[2] - w.box[0]) >= 2.2 * xh and not diag:
                vals.append(w.slant)
    if len(vals) < 50:
        return default
    v = np.sort(np.array(vals, float))
    best, bt = -1.0, default
    for t in np.unique(v)[1:]:
        lo, hi = v[v < t], v[v >= t]
        s = len(lo) * len(hi) * (hi.mean() - lo.mean()) ** 2
        if s > best:
            best, bt = s, float(t)
    lo, hi = v[v < bt], v[v >= bt]
    if len(hi) < min_frac * len(v) or hi.mean() - lo.mean() < min_gap:
        return default
    return (lo.mean() + hi.mean()) / 2


def token_styles(line: "Line", xh_px: float, thr: float = 9.0) -> list[tuple[str, bool | None]]:
    """Italic flag per OCR token of the line text.

    Each token gets an x range proportional to its character position in the
    line, clipped to the line's ink extent; the token is italic when most of
    that range is covered by ink spans read as italic (None when no span with
    a reading covers it)."""
    flags = italic_words(line, xh_px, thr)
    tokens = line.text.split()
    if not tokens or not line.words:
        return [(t, None) for t in tokens]
    if len(tokens) == len(line.words):
        return list(zip(tokens, flags))
    x0 = line.words[0].box[0]
    x1 = line.words[-1].box[2]
    n = len(line.text)
    out: list[tuple[str, bool | None]] = []
    pos = 0
    for t in tokens:
        i = line.text.index(t, pos)
        pos = i + len(t)
        a = x0 + (x1 - x0) * i / n
        b = x0 + (x1 - x0) * pos / n
        cov = {True: 0.0, False: 0.0}
        for w, f in zip(line.words, flags):
            ov = min(b, w.box[2]) - max(a, w.box[0])
            if ov > 0 and f is not None:
                cov[f] += ov
        tot = cov[True] + cov[False]
        out.append((t, None if tot == 0 else cov[True] > cov[False]))
    return out


def book_token_styles(lines: "list[Line]", thr: float = 9.0, min_votes: int = 3,
                      agree: float = 0.8) -> list[list[tuple[str, bool | None]]]:
    """token_styles for every line, then fill undecided short tokens from book context.

    1. initial ("N.") before an italic token -> italic (genus abbreviation).
    2. other undecided token: majority style of the same token elsewhere in the
       book (needs min_votes decided occurrences, agree share)."""
    per = [token_styles(ln, ln.x_height_pt * 300 / 72, thr) for ln in lines]
    votes: dict[str, list[int]] = {}
    for toks in per:
        for t, f in toks:
            if f is not None:
                v = votes.setdefault(t.strip(".,;:()[]").lower(), [0, 0])
                v[int(f)] += 1
    out = []
    for toks in per:
        res = list(toks)
        for i, (t, f) in enumerate(toks):
            if f is not None:
                continue
            if len(t) == 2 and t[0].isupper() and t[1] == "." and i + 1 < len(toks) \
                    and toks[i + 1][1] is True:
                res[i] = (t, True)
                continue
            v = votes.get(t.strip(".,;:()[]").lower())
            if v and sum(v) >= min_votes and len(t) > 1 and not (len(t) == 2 and t[0].isupper()):
                if v[1] >= agree * sum(v):
                    res[i] = (t, True)
                elif v[0] >= agree * sum(v):
                    res[i] = (t, False)
        out.append(res)
    return out


def line_features(page_ink: np.ndarray, row: list[Any], scale: float, dpi: float) -> Line | None:
    poly, text, score = row
    xs = [p[0] * scale for p in poly]
    ys = [p[1] * scale for p in poly]
    x0, x1 = max(0, int(min(xs))), min(page_ink.shape[1], int(math.ceil(max(xs))))
    y0, y1 = max(0, int(min(ys))), min(page_ink.shape[0], int(math.ceil(max(ys))))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    ink = page_ink[y0:y1, x0:x1]
    top, xtop, base = _bands(ink)
    xh, asc, pt = max(1, base - xtop), max(1, base - top), 72.0 / dpi
    tokens = text.split()
    spans = [s for sp in align_words(ink, xh, len(tokens)) for s in split_mixed(ink, sp, xh, base)]
    words = [Word(tokens[i] if len(spans) == len(tokens) else "",
                  (x0 + a, y0, x0 + b, y1), slant_angle(ink[:, a:b], base))
             for i, (a, b) in enumerate(spans)]
    wts = np.array([w.box[2] - w.box[0] for w in words], float)
    sl = float((wts * np.array([w.slant for w in words])).sum() / wts.sum()) if words else 0.0
    return Line(text, float(score), (x0, y0, x1, y1), round(xh * pt, 2), round(asc * pt, 2),
                round(stroke_width(ink) / xh, 3), round(xh / asc, 3), words, round(sl, 1))


def page_features(gray: np.ndarray, rows: list[Any], ocr_width: int, dpi: float) -> list[Line]:
    ink = binarize(gray)
    scale = gray.shape[1] / float(ocr_width)
    return [ln for r in rows if (ln := line_features(ink, r, scale, dpi)) is not None]


def main(argv: list[str] | None = None) -> int:
    import argparse

    from PIL import Image

    ap = argparse.ArgumentParser(description="typographic features of a scanned page")
    ap.add_argument("image")
    ap.add_argument("rows", help="PP-OCR rows json {width, rows}")
    ap.add_argument("--dpi", type=float, required=True, help="dpi of IMAGE")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    gray = np.asarray(Image.open(a.image).convert("L"))
    d = json.loads(pathlib.Path(a.rows).read_text())
    js = json.dumps([asdict(x) for x in page_features(gray, d["rows"], d["width"], a.dpi)],
                    ensure_ascii=False)
    if a.out:
        pathlib.Path(a.out).write_text(js)
    else:
        print(js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
