"""Per-block typographic record measured on the page image (local, no OCR call).

Input: the cloud layout store (`参考资料/_资料库/layout/<key>/pNNNN.json`, saved by
docstore paddle_vl.save_layout: `pruned_result.parsing_res_list` with block_bbox in
cloud px, `width_px` = cloud page width in px) and the rendered source page.

Output per page (`styles/<key>/pNNNN.json`): for every layout block, the measured
line features from `typo_features` (x-height, ascender height, relative stroke
width, per-word slant) aggregated to the block, plus the block label and text.
Nothing is inferred about font family.  Font size in pt is NOT measured here; only
x-height in pt (size = x-height / font-specific x-height ratio, unknown per face).
"""
from __future__ import annotations

import json
import os
import pathlib
from pathlib import Path
from typing import Any

import numpy as np

from . import typo_features as tf

RENDER_DPI = 300
DEFAULT_ROOT = "/mnt/p/翻译-译作/参考资料/_资料库"


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """HxWxC uint8 -> HxW uint8 grey (ITU-R 601 luma)."""
    if rgb.ndim == 2:
        return rgb
    w = np.array([0.299, 0.587, 0.114])
    return (rgb[..., :3] @ w).astype(np.uint8)


def ink_row_bands(ink: np.ndarray, min_gap: int = 2, min_h: int = 3) -> list[tuple[int, int]]:
    """Text-line bands: runs of rows with ink, separated by >= min_gap empty rows."""
    on = ink.sum(axis=1) > 0
    bands: list[tuple[int, int]] = []
    start: int | None = None
    last = -1
    for y, v in enumerate(on):
        if v:
            if start is None:
                start = y
            last = y
        elif start is not None and y - last > min_gap:
            bands.append((start, last + 1))
            start = None
    if start is not None:
        bands.append((start, last + 1))
    return [(a, b) for a, b in bands if b - a >= min_h]


def scale_bbox(bbox: list[float], k: float, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """Cloud-px bbox -> render-px bbox clipped to the page."""
    h, w = shape
    x0, y0, x1, y1 = (int(round(v * k)) for v in bbox)
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def measure_block(gray: np.ndarray, bbox_render: tuple[int, int, int, int], dpi: float,
                  text: str = "") -> dict[str, Any]:
    """Line features of one block.  text (OCR lines) is used for token/word matching
    only when its non-empty line count equals the measured band count."""
    x0, y0, x1, y1 = bbox_render
    out: dict[str, Any] = {"bbox_render": list(bbox_render), "lines": 0}
    if x1 - x0 < 4 or y1 - y0 < 4:
        return out
    ink = tf.binarize(gray[y0:y1, x0:x1])
    bands = ink_row_bands(ink)
    if not bands:
        return out
    texts = [t for t in text.split("\n") if t.strip()]
    rows = []
    for i, (a, b) in enumerate(bands):
        t = texts[i] if len(texts) == len(bands) else ""
        ya, yb = y0 + a, y0 + b
        rows.append([[[x0, ya], [x1, ya], [x1, yb], [x0, yb]], t, 1.0])
    lines = tf.page_features(gray, rows, ocr_width=gray.shape[1], dpi=dpi)
    if not lines:
        return out
    xh = [ln.x_height_pt for ln in lines if ln.x_height_pt > 0]
    asc = [ln.asc_pt for ln in lines if ln.asc_pt > 0]
    sr = [ln.stroke_rel for ln in lines if ln.stroke_rel > 0]
    words = [{"text": w.text, "w_px": w.box[2] - w.box[0], "slant": round(w.slant, 1)}
             for ln in lines for w in ln.words]
    out.update(
        lines=len(lines),
        x_height_pt=round(float(np.median(xh)), 2) if xh else None,
        asc_pt=round(float(np.median(asc)), 2) if asc else None,
        stroke_rel=round(float(np.median(sr)), 3) if sr else None,
        line_xh_pt=[ln.x_height_pt for ln in lines],
        line_stroke_rel=[ln.stroke_rel for ln in lines],
        words=words,
    )
    return out


NON_TEXT = ("image", "chart", "seal", "header_image", "footer_image", "figure")


def is_text_block(label: str) -> bool:
    """False for picture-like layout labels, which carry no text typography."""
    return label not in NON_TEXT and not label.endswith("_image")


def measure_page(pdf: str, page_no: int, layout: dict[str, Any], dpi: int = RENDER_DPI) -> dict[str, Any]:
    """Measure every layout block of one page.  layout = parsed layout/<key>/pNNNN.json."""
    from docstore.engines.pageimg import page_array

    gray = to_gray(page_array(pdf, page_no, dpi))
    cw = float(layout["width_px"])
    k = gray.shape[1] / cw
    blocks = (layout.get("pruned_result") or {}).get("parsing_res_list") or []
    recs = []
    for i, b in enumerate(blocks):
        if not is_text_block(str(b.get("block_label", ""))):
            recs.append({"block_id": b.get("block_id", i), "label": b.get("block_label"),
                         "order": b.get("block_order"), "lines": 0, "skipped": "non-text block"})
            continue
        text = b.get("block_content", "") or ""
        r = measure_block(gray, scale_bbox(b["block_bbox"], k, gray.shape), dpi, text)
        recs.append({"block_id": b.get("block_id", i), "label": b.get("block_label"),
                     "order": b.get("block_order"), "text": text, **r})
    return {"page": page_no, "dpi": dpi, "render_w": gray.shape[1], "cloud_w": cw,
            "blocks": recs}


def write_page(root: pathlib.Path, key: str, page_no: int, rec: dict[str, Any]) -> pathlib.Path:
    d = root / "styles" / key
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"p{page_no:04d}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


XH_OUTLIER_RATIO = 2.0   # block x-height > 2x body x-height -> not text (e.g. header/figure artifacts)
BOLD_STROKE_RATIO = 1.25  # stroke_rel >= 1.25x body stroke median -> bold cue
HEADING_LABELS = ("doc_title", "paragraph_title")
# only blocks that the layout model already calls headings/titles yield heading levels;
# bold lines in body/content blocks (e.g. masthead on p2, section line in a content block) stay bold-only
HEADING_LINE_LABELS = ("doc_title", "paragraph_title", "figure_title", "content")  # content: mixed key/TOC blocks
BODY_LABELS = ("text", "content")
LINE_REF_MIN_LINES = 5  # pages with at least this many measured lines use their own line-stroke median
ITALIC_SLANT_DEG = 9.0    # word slant above this counts as italic (typo_features default)
ITALIC_MIN_WORDS = 3
ITALIC_FRAC = 0.5


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def annotate_book(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Book-level pass over measured blocks (mutates recs in place).

    body = median of body-label blocks.  Sets:
      outlier     : x-height > XH_OUTLIER_RATIO * body x-height (excluded from heading/bold)
      bold        : stroke_rel >= BOLD_STROKE_RATIO * body stroke (cue, unverified)
      heading_level : rank (1 = largest) of distinct x-height clusters among HEADING_LABELS
                      blocks; clusters merge within 0.4 pt.  Unverified: needs crop check.
    Returns the thresholds used, so they can be recorded with the output."""
    body_xh = _median([r["x_height_pt"] for r in recs if r.get("label") in BODY_LABELS and r.get("x_height_pt")])
    body_sr = _median([r["stroke_rel"] for r in recs if r.get("label") in BODY_LABELS and r.get("stroke_rel")])
    # line-level reference: same-page median of line stroke (serif display lines on a contents page
    # sit above the book's body median, so a book-wide reference falsely flags them).  Pages with
    # fewer than LINE_REF_MIN_LINES lines fall back to the book body median.
    page_lines: dict[Any, list[float]] = {}
    for r in recs:
        page_lines.setdefault(r.get("page"), []).extend(v for v in (r.get("line_stroke_rel") or []) if v)
    page_sr = {p: _median(v) for p, v in page_lines.items() if len(v) >= LINE_REF_MIN_LINES}
    for r in recs:
        r["outlier"] = bool(body_xh and r.get("x_height_pt") and r["x_height_pt"] > XH_OUTLIER_RATIO * body_xh)
        ok = bool(r.get("x_height_pt")) and not r["outlier"]
        ref = page_sr.get(r.get("page"), body_sr)  # same-page reference, as for lines below
        r["bold"] = bool(ok and ref and r.get("stroke_rel") and r["stroke_rel"] >= BOLD_STROKE_RATIO * ref)
        ws = [w["slant"] for w in r.get("words") or [] if w.get("slant") is not None]
        lsr = r.get("line_stroke_rel") or []
        r["bold_line_idx"] = [i for i, v in enumerate(lsr) if ref and v and v >= BOLD_STROKE_RATIO * ref]
        if r["bold_line_idx"] and len(r["bold_line_idx"]) * 2 >= len(lsr):
            r["bold"] = True  # block-level median hides a bold heading line inside a mixed block
        r["italic"] = bool(len(ws) >= ITALIC_MIN_WORDS
                           and sum(1 for s in ws if s > ITALIC_SLANT_DEG) >= ITALIC_FRAC * len(ws))
    heads = sorted({round(r["x_height_pt"], 2) for r in recs
                    if r.get("label") in HEADING_LABELS and r.get("x_height_pt") and not r.get("outlier")},
                   reverse=True)
    clusters: list[float] = []
    for v in heads:
        if not clusters or clusters[-1] - v > 0.4:
            clusters.append(v)
    # line-level headings: bold lines (also inside mixed blocks), rank by line x-height clusters
    bold_xh = sorted({round(x, 2) for r in recs if not r.get("outlier") and r.get("label") in HEADING_LINE_LABELS
                      for i, x in enumerate(r.get("line_xh_pt") or [])
                      if i in set(r.get("bold_line_idx") or []) and body_xh and x >= 0.8 * body_xh},
                     reverse=True)
    lclusters: list[float] = []
    for v in bold_xh:
        if not lclusters or lclusters[-1] - v > 0.4:
            lclusters.append(v)
    for r in recs:
        xs = r.get("line_xh_pt") or []
        r["heading_lines"] = [{"idx": i, "x_height_pt": xs[i],
                               "level": 1 + sum(1 for c in lclusters if c - xs[i] > 0.4)}
                              for i in (r.get("bold_line_idx") or [])
                              if i < len(xs) and not r.get("outlier") and body_xh and xs[i] >= 0.8 * body_xh
                              and r.get("label") in HEADING_LINE_LABELS
                              # figure panel letters (A, B, C…) are bold but are not headings
                              and not (r.get("label") == "figure_title" and r.get("text") is not None
                                       and len(_norm(r["text"])) <= 2)]
    for r in recs:
        r["heading_level"] = None
        # a block-level heading needs a style cue: bold stroke, or all-caps text (bold cue misses some caps headings)
        t = (r.get("text") or "").strip()
        caps = bool(t) and t.isupper() and sum(ch.isalpha() for ch in t) >= 3
        if (r.get("label") in HEADING_LABELS and r.get("x_height_pt") and not r.get("outlier")
                and (r.get("bold") or caps or r.get("label") == "doc_title")):
            v = r["x_height_pt"]
            r["heading_level"] = 1 + sum(1 for c in clusters if c - v > 0.4) if clusters else None
    return {"body_x_height_pt": body_xh, "body_stroke_rel": body_sr,
            "bold_ratio": BOLD_STROKE_RATIO, "outlier_ratio": XH_OUTLIER_RATIO,
            "italic_slant_deg": ITALIC_SLANT_DEG, "italic_frac": ITALIC_FRAC,
            "heading_clusters_pt": clusters, "bold_line_clusters_pt": lclusters, "status": "unverified"}


def cmd_annotate(args: Any) -> int:
    """Second pass: rewrite styles/<key>/pNNNN.json with outlier/bold/heading_level filled in."""
    d = pathlib.Path(args.root) / "styles" / args.key
    files = sorted(d.glob("p*.json"))
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    for doc in docs:
        for b in doc["blocks"]:
            b.setdefault("page", doc["page"])  # same-page line reference needs the page of each block
    recs = [b for doc in docs for b in doc["blocks"]]
    thr = annotate_book(recs)  # mutates the block dicts that are written back below
    for f, doc in zip(files, docs):
        f.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "_book.json").write_text(json.dumps(thr, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(thr, ensure_ascii=False))
    return 0


ATTACH_MIN_SIM = 0.6


def _norm(t: str) -> str:
    return "".join(ch for ch in t if ch.isalnum()).lower()


def attach_aligned(aligned_pages: list[dict[str, Any]], styled: dict[int, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Match aligned blocks to measured layout blocks on the same page by text similarity.

    aligned_pages: [{"page": n, "blocks": [{"block_id": "p{n}-b{i}", "text": ...}]}]
    styled: {page: measured block records (with 'text' from layout block_content)}
    Returns {block_id: {typo fields, "sim": float, "layout_block_id": ...}} for matches >= ATTACH_MIN_SIM.
    The source aligned.json is NOT modified; the mapping is a sidecar."""
    import difflib

    out: dict[str, dict[str, Any]] = {}
    for pg in aligned_pages:
        cands = styled.get(int(pg["page"]), [])
        for b in pg.get("blocks", []):
            bt = _norm(b.get("text", ""))
            if not bt or not cands:
                continue
            best, best_s = None, 0.0
            for c in cands:
                ct = _norm(c.get("text", ""))
                if not ct:
                    continue
                s = difflib.SequenceMatcher(None, bt, ct).ratio()
                if s > best_s:
                    best, best_s = c, s
            if best is not None and best_s >= ATTACH_MIN_SIM:
                out[b["block_id"]] = {"sim": round(best_s, 3), "layout_block_id": best.get("block_id"),
                                      "label": best.get("label"), "x_height_pt": best.get("x_height_pt"),
                                      "bold": best.get("bold"), "italic": best.get("italic"),
                                      "heading_level": best.get("heading_level"), "outlier": best.get("outlier")}
    return out


def cmd_attach(args: Any) -> int:
    """Write sidecar styles/<key>/aligned_typo.json for an aligned file.  aligned.json is not touched."""
    root = pathlib.Path(args.root)
    d = root / "styles" / args.key
    aligned = json.loads(pathlib.Path(args.aligned).read_text(encoding="utf-8"))
    pages = aligned["pages"] if isinstance(aligned, dict) else aligned
    for pg in pages:  # aligned blocks carry no id in some files: use position, as p{page}-b{i}
        for i, b in enumerate(pg.get("blocks", [])):
            b.setdefault("block_id", f"p{pg['page']}-b{i}")
    styled: dict[int, list[dict[str, Any]]] = {}
    for f in sorted(d.glob("p*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        pg = int(doc["page"])
        styled[pg] = []
        for b in doc["blocks"]:
            if b.get("lines"):
                styled[pg].append({**b, "text": b.get("text", "")})
    res = attach_aligned(pages, styled)
    outp = d / "aligned_typo.json"
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.inplace:  # opt-in: add a "typo" field to each matched block; keep a .bak of the original
        src = pathlib.Path(args.aligned)
        bak = src.with_suffix(src.suffix + ".bak")
        if not bak.exists():
            bak.write_bytes(src.read_bytes())
        n = 0
        for pg in pages:
            for b in pg.get("blocks", []):
                if b.get("block_id") in res:
                    b["typo"] = {k: v for k, v in res[b["block_id"]].items() if k != "sim"}
                    n += 1
        src.write_text(json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"inplace_blocks": n, "backup": str(bak)}, ensure_ascii=False))
    print(json.dumps({"matched": len(res), "aligned_blocks": sum(len(p.get("blocks", [])) for p in pages),
                      "out": str(outp)}, ensure_ascii=False))
    return 0


def _parse_pages(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    return sorted(set(out))


def cmd_measure(args: Any) -> int:
    """Measure layout blocks of pages -> styles/<key>/pNNNN.json.  Local only: no OCR call."""
    root = pathlib.Path(args.root)
    ldir = root / "layout" / args.key
    missing: list[int] = []
    done = 0
    for p in _parse_pages(args.pages):
        lp = ldir / f"p{p:04d}.json"
        if not lp.exists():
            missing.append(p)
            continue
        lay = json.loads(lp.read_text(encoding="utf-8"))
        rec = measure_page(str(args.pdf), p, lay, args.dpi)
        rec.update(key=args.key, layout_file=str(lp))
        write_page(root, args.key, p, rec)
        done += 1
    print(json.dumps({"key": args.key, "measured": done, "no_layout_pages": missing}, ensure_ascii=False))
    return 0


def cmd_summary(args: Any) -> int:
    """Per-label distribution of measured text blocks (x-height pt, relative stroke width)."""
    import statistics as stt

    d = pathlib.Path(args.root) / "styles" / args.key
    by: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(d.glob("p*.json")):
        for b in json.loads(f.read_text(encoding="utf-8"))["blocks"]:
            if b.get("x_height_pt"):
                by.setdefault(str(b.get("label")), []).append(b)
    summ = {}
    for lab, bs in sorted(by.items()):
        xh = [b["x_height_pt"] for b in bs]
        sr = [b["stroke_rel"] for b in bs if b.get("stroke_rel")]
        summ[lab] = {"blocks": len(bs), "xh_median": round(stt.median(xh), 2),
                     "stroke_rel_median": round(stt.median(sr), 3) if sr else None,
                     "stroke_rel_p90": round(sorted(sr)[int(0.9 * (len(sr) - 1))], 3) if sr else None}
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return 0


def add_parser(sub: Any) -> None:
    m = sub.add_parser("styles-measure", help="measure per-block x-height/stroke/slant from page image (no OCR)")
    m.add_argument("--pdf", type=Path, required=True)
    m.add_argument("--key", required=True)
    m.add_argument("--pages", required=True, help="e.g. 1-50 or 3,7,9")
    m.add_argument("--root", default=os.environ.get("DOCSTORE_ROOT", DEFAULT_ROOT))
    m.add_argument("--dpi", type=int, default=RENDER_DPI)
    m.set_defaults(func=cmd_measure)
    s = sub.add_parser("styles-summary", help="per-label style distribution of measured blocks")
    s.add_argument("--key", required=True)
    s.add_argument("--root", default=os.environ.get("DOCSTORE_ROOT", DEFAULT_ROOT))
    s.set_defaults(func=cmd_summary)
    a = sub.add_parser("styles-annotate", help="book-level bold / heading_level / outlier pass over styles/<key>")
    a.add_argument("--key", required=True)
    a.add_argument("--root", default=os.environ.get("DOCSTORE_ROOT", DEFAULT_ROOT))
    a.set_defaults(func=cmd_annotate)
    t = sub.add_parser("styles-attach", help="sidecar: match aligned blocks to measured typography by text")
    t.add_argument("--key", required=True)
    t.add_argument("--aligned", required=True)
    t.add_argument("--root", default=os.environ.get("DOCSTORE_ROOT", DEFAULT_ROOT))
    t.add_argument("--inplace", action="store_true", help="also write typo field into --aligned (backup .bak first)")
    t.set_defaults(func=cmd_attach)
