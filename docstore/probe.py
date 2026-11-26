"""PDF 体检：不 OCR、不入库，只抽样页判定原生/扫描/OCR 层、分栏、书签、字体、版式特征（issue #59）。

规则见 docs/probe_spec.md §1 §2。booklayout 模块只在函数内惰性导入，失败则对应字段为 None。
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .textify import MIN_CHARS, OCR_LAYER_PRODUCERS

CONTENTS_RE = re.compile(r"^\s*(Contents|Table of contents|目录|目錄|Índice|Indice|Inhalt|Sommaire)\b", re.I)
NUMBERED_RE = re.compile(r"^\d+(?:\.\d+)+\.?\s+\S")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TAIL_DIGITS = re.compile(r"\d+$")
COVER_FRAC = 0.8
MIXED_FRAC = 1 / 3


def _fitz() -> Any:
    import fitz

    return fitz


def sample_indices(n: int, k: int = 5, pages: list[int] | None = None) -> list[int]:
    """0 基页号：[0.1n, 0.9n] 均匀 k 页 + 用户指定的 1 基页号（越界忽略）。"""
    if n <= 0:
        return []
    out: set[int] = set()
    if k > 0:
        lo, hi = int(0.1 * n), max(int(0.1 * n), min(n - 1, int(0.9 * n)))
        if k == 1:
            out.add((lo + hi) // 2)
        else:
            out.update(round(lo + (hi - lo) * i / (k - 1)) for i in range(k))
    for p in pages or []:
        if 1 <= p <= n:
            out.add(p - 1)
    return sorted(out)


def page_kind(page: Any) -> dict:
    """页级判定：chars、cover_image、page_kind。"""
    chars = len(page.get_text().strip())
    area = abs(page.rect) or 1
    cover = False
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        if (x1 - x0) * (y1 - y0) >= COVER_FRAC * area:
            cover = True
            break
    if chars < MIN_CHARS:
        kind = "scan" if cover else "blank"
    else:
        kind = "ocr-layer" if cover else "native"
    return {"chars": chars, "cover_image": cover, "page_kind": kind}


def book_kind(meta: dict, sampled: list[dict]) -> tuple[str, str]:
    """书级判定与理由。"""
    kinds = [s["page_kind"] for s in sampled if s["page_kind"] != "blank"]
    if not kinds:
        return "empty", f"抽样 {len(sampled)} 页全为空白"
    prod = ((meta or {}).get("producer") or "").lower() + " " + ((meta or {}).get("creator") or "").lower()
    hit = next((w for w in OCR_LAYER_PRODUCERS if w in prod), None)
    has_text = any(s["page_kind"] in ("native", "ocr-layer") for s in sampled)
    if hit and has_text:
        return "ocr-layer", f"producer/creator 含 OCR 标记 {hit!r} 且有文字层"
    cnt = Counter(kinds).most_common()
    top, n1 = cnt[0]
    desc = ",".join(f"{k}={v}" for k, v in cnt)
    if len(cnt) > 1 and cnt[1][1] / len(kinds) >= MIXED_FRAC:
        return "mixed", f"抽样页类型不一：{desc}"
    return top, f"非空白抽样页多数为 {top}（{desc}）"


def _line_rows(page: Any) -> list[dict]:
    rows = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                x0, y0, x1, y1 = ln["bbox"]
                rows.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return rows


def page_columns(rows: list[dict]) -> tuple[int, list[float] | None]:
    """行框 -> layout._find_gutter；两侧各 >= MIN_SIDE 行才算 2 栏。"""
    from . import layout

    if len(rows) < 2 * layout.MIN_SIDE:
        return 1, None
    boxes = [layout._Box(i, [[[r["x0"], r["y0"]], [r["x1"], r["y0"]], [r["x1"], r["y1"]], [r["x0"], r["y1"]]],
                             r["text"], 1.0]) for i, r in enumerate(rows)]
    g = layout._find_gutter(boxes)
    if not g:
        return 1, None
    mid = (g[0] + g[1]) / 2
    left = sum(b.x1 <= g[0] + 1e-6 or b.xc < mid and b.x1 <= mid for b in boxes)
    right = sum(b.x0 >= g[1] - 1e-6 or b.xc > mid and b.x0 >= mid for b in boxes)
    if left >= layout.MIN_SIDE and right >= layout.MIN_SIDE:
        return 2, [round(g[0], 1), round(g[1], 1)]
    return 1, None


def _family(font: str) -> str:
    return _TAIL_DIGITS.sub("", _SUBSET.sub("", font))


def _font_info(pages: list[Any]) -> tuple[dict, dict]:
    from collections import defaultdict

    chars: dict[tuple, int] = defaultdict(int)
    bold = ital = total = 0
    line_styles: list[tuple[tuple, str]] = []
    span_style = None
    try:
        from booklayout.nativefonts import span_style as _ss

        span_style = _ss
    except Exception:  # noqa: BLE001
        pass
    for pg in pages:
        for b in pg.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                keys = set()
                text = ""
                for sp in ln["spans"]:
                    n = len(sp["text"].strip())
                    if not n:
                        continue
                    it, bd = span_style(sp) if span_style else (bool(sp["flags"] & 2), bool(sp["flags"] & 16))
                    key = (_family(sp["font"]), round(sp["size"], 1), bd, it)
                    chars[key] += n
                    total += n
                    bold += n * bd
                    ital += n * it
                    keys.add(key)
                    text += sp["text"]
                if len(keys) == 1 and text.strip():
                    line_styles.append((next(iter(keys)), text.strip()))
    if not total:
        return {}, {}
    bkey = max(chars, key=lambda k: chars[k])
    fonts = {
        "body": {"family": bkey[0], "size": bkey[1], "bold": bkey[2], "italic": bkey[3]},
        "top": [{"font": k[0], "size": k[1], "chars": c}
                for k, c in sorted(chars.items(), key=lambda kv: -kv[1])[:8]],
        "sizes": [[s, c] for s, c in sorted(_size_totals(chars).items(), key=lambda kv: -kv[1])],
        "bold_frac": round(bold / total, 3),
        "italic_frac": round(ital / total, 3),
    }
    cnt: Counter = Counter()
    ex: dict[tuple, str] = {}
    numbered = False
    for key, text in line_styles:
        if NUMBERED_RE.match(text):
            numbered = True
        if key[:2] == bkey[:2] and key[2] == bkey[2]:
            continue
        if (key[1] >= bkey[1] * 1.1 or key[2]) and len(text) <= 120 and not text.endswith(":") \
                and not text.isdigit():
            cnt[key] += 1
            ex.setdefault(key, text)
    styles = [{"family": k[0], "size": k[1], "bold": k[2], "example": ex[k]} for k, _ in cnt.most_common(5)]
    return fonts, {"numbered": numbered, "styles": styles}


def _size_totals(chars: dict[tuple, int]) -> dict[float, int]:
    out: dict[float, int] = {}
    for k, c in chars.items():
        out[k[1]] = out.get(k[1], 0) + c
    return out


def _bookmarks(doc: Any) -> dict:
    toc = doc.get_toc()
    pages = [t[2] for t in toc]
    distinct = sorted(set(pages))
    usable = len(distinct) >= 2 and sum(p != 1 for p in pages) / len(pages) > 0.5 if toc else False
    return {"count": len(toc), "levels": sorted({t[0] for t in toc}), "distinct_pages": len(distinct),
            "first": [[t[0], t[1], t[2]] for t in toc[:3]], "usable": bool(usable)}


def _contents_page(doc: Any) -> int | None:
    for i in range(min(15, len(doc))):
        for ln in doc[i].get_text().splitlines():
            if CONTENTS_RE.match(ln):
                return i + 1
    return None


def _features(doc: Any, idx: list[int], rows_by: dict[int, list[dict]]) -> dict:
    feat: dict[str, Any] = {"contents_page": _contents_page(doc), "key_heading_pages": None,
                            "caption_pages": None, "caption_labels": None}
    try:
        from booklayout.keygraph import HEADING_RE

        feat["key_heading_pages"] = [i + 1 for i in idx
                                     if any(HEADING_RE.match(r["text"]) for r in rows_by[i])]
    except Exception:  # noqa: BLE001
        pass
    try:
        from booklayout.pdffigures import page_captions

        pp: list[int] = []
        labels: list[str] = []
        for i in idx:
            caps = page_captions(doc[i])
            if caps:
                pp.append(i + 1)
                labels += [c["label"] for c in caps]
        feat["caption_pages"] = pp
        feat["caption_labels"] = labels
    except Exception:  # noqa: BLE001
        pass
    return feat


def _furniture(doc: Any, idx: list[int], rows_by: dict[int, list[dict]]) -> dict:
    out: dict[str, Any] = {"header_lines": None, "footer_lines": None}
    try:
        from booklayout.furniture import detect_furniture, signature

        pages = [{"page": i + 1, "height": doc[i].rect.height,
                  "lines": sorted(rows_by[i], key=lambda r: (r["y0"], r["x0"]))} for i in idx]
        rep = detect_furniture(pages, min_repeat=max(2, min(3, len(idx))) if len(idx) > 1 else 1)
        hdr: list[str] = []
        ftr: list[str] = []
        for pg in pages:
            h = pg["height"]
            for ln in pg["lines"]:
                t = ln["text"].strip()
                if len(t) > 100 or signature(t) not in rep.signatures:
                    continue
                if ln["y1"] <= 0.1 * h and t not in hdr:
                    hdr.append(t)
                elif ln["y0"] >= 0.9 * h and t not in ftr:
                    ftr.append(t)
        out["header_lines"], out["footer_lines"] = hdr[:3], ftr[:3]
    except Exception:  # noqa: BLE001
        pass
    return out


def probe_pdf(path: Path, sample: int = 5, pages: list[int] | None = None, fonts: bool = True) -> dict:
    t0 = time.time()
    fitz = _fitz()
    path = Path(path)
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read(1 << 20)).hexdigest()
    doc = fitz.open(str(path))
    try:
        meta = doc.metadata or {}
        n = len(doc)
        idx = sample_indices(n, sample, pages)
        sampled: list[dict] = []
        rows_by: dict[int, list[dict]] = {}
        cols: list[int] = []
        for i in idx:
            pk = page_kind(doc[i])
            rows_by[i] = _line_rows(doc[i]) if pk["chars"] else []
            c, gut = page_columns(rows_by[i])
            if pk["page_kind"] != "blank":
                cols.append(c)
            sampled.append({"page": i + 1, **pk, "columns": c, "gutter": gut})
        kind, reason = book_kind(meta, sampled)
        columns: Any = (cols[0] if len(set(cols)) == 1 else "mixed") if cols else 1
        fnt = hint = None
        if fonts and kind in ("native", "ocr-layer", "mixed"):
            tp = [doc[i] for i in idx if rows_by[i]]
            f, h = _font_info(tp)
            fnt, hint = (f or None), (h or None)
        from .classify import guess

        gs = guess(path)
        return {
            "path": str(path), "sha256_head": sha, "pages": n,
            "producer": meta.get("producer") or "", "creator": meta.get("creator") or "",
            "meta_title": meta.get("title") or "",
            "kind": kind, "kind_reason": reason, "sampled": sampled,
            "bookmarks": _bookmarks(doc), "fonts": fnt,
            "layout": {"columns": columns, **_furniture(doc, idx, rows_by)},
            "features": _features(doc, idx, rows_by),
            "heading_hint": hint,
            "classify": {"kind": gs.get("kind"), "lang": gs.get("lang")},
            "seconds": round(time.time() - t0, 2),
        }
    finally:
        doc.close()


def summary_line(r: dict) -> str:
    bm = r["bookmarks"]
    body = r["fonts"]["body"] if r.get("fonts") else None
    font = f"{body['family']} {body['size']}pt" if body else "-"
    return (f"{r['kind']}\t{r['pages']}页\t书签{bm['count']}({'可用' if bm['usable'] else '不可用'})\t"
            f"{font}\t{r['layout']['columns']}栏\t{Path(r['path']).name}")


def parse_pages(spec: str | None) -> list[int]:
    out: list[int] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out
