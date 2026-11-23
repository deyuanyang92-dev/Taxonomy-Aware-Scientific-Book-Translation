"""Figure-region detection on scanned (image-only) pages.

Image-only PDFs have no text layer and the page is one big picture, so placement
based extraction (pdffigures) returns whole pages.  Here the page is rendered,
binarised and split by connected components: text glyphs are small, figure
strokes form large components.  Large components seed a figure; ink within
`gap` px of a seed is merged into it (panel letters, label text); a figure box
is the union.  Boxes are returned in page pixels at the render DPI.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

DPI = 150


@dataclass
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0


def render_gray(page, dpi: int = DPI) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace="gray", alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()


def find_figures(gray: np.ndarray, dpi: int = DPI, big_mm: float = 7.0, gap_mm: float = 6.0,
                 min_area_mm2: float = 600.0, lenient: bool = False) -> list[Box]:
    px_mm = dpi / 25.4
    h, w = gray.shape
    bw = (cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 18))
    # drop page-border dirt
    m = int(6 * px_mm)
    bw[:m, :] = 0
    bw[-m:, :] = 0
    bw[:, :m] = 0
    bw[:, -m:] = 0
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    big = int(big_mm * px_mm)
    seed = np.zeros_like(bw)
    for i in range(1, n):
        x, y, cw, ch, area = st[i]
        if max(cw, ch) >= big and area >= 0.02 * cw * ch and not (ch < 0.12 * big and cw > 3 * big):
            seed[lab == i] = 255
    if not seed.any():
        return []
    gap = int(gap_mm * px_mm)
    grow = cv2.dilate(seed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1)))
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(grow, connectivity=8)
    boxes: list[Box] = []
    for i in range(1, n2):
        x, y, cw, ch, _a = st2[i]
        in_reg = (lab2 == i)
        sy, sx = np.where(in_reg & (seed > 0))
        if len(sx) == 0:
            continue
        x0, y0, x1, y1 = int(sx.min()), int(sy.min()), int(sx.max()) + 1, int(sy.max()) + 1
        sx0, sy0, sx1, sy1 = x0, y0, x1, y1
        # small ink near the seeds: isolated glyphs (panel letters A, B...) belong to the
        # figure; words/lines (the printed caption) do not.
        small = ((in_reg & (bw > 0)) & (seed == 0)).astype(np.uint8) * 255
        wide = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_RECT, (int(3 * px_mm) | 1, 3)))
        n3, _l3, st3, _ = cv2.connectedComponentsWithStats(wide, connectivity=8)
        cand = [tuple(int(v) for v in st3[j][:4]) for j in range(1, n3)
                if st3[j][2] <= 12 * px_mm and st3[j][3] <= 9 * px_mm]
        near = 9 * px_mm
        for bx, by, bw_, bh_ in cand:
            # a word of a caption line has neighbours on its row; a panel letter has none
            lonely = not any(
                (ox, oy, ow, oh) != (bx, by, bw_, bh_)
                and abs((oy + oh / 2) - (by + bh_ / 2)) < max(bh_, oh)
                and (ox - (bx + bw_) < near and bx - (ox + ow) < near)
                for ox, oy, ow, oh in cand)
            # panel letters sit at the plate edge; glyphs well outside the seed box are caption text
            slack = 3 * px_mm
            inside = (bx > sx0 - slack and by > sy0 - slack and bx + bw_ < sx1 + slack and by + bh_ < sy1 + slack)
            if lonely and inside:
                x0, y0, x1, y1 = min(x0, bx), min(y0, by), max(x1, bx + bw_), max(y1, by + bh_)
        b = Box(x0, y0, x1, y1)
        if lenient or ((b.w / px_mm) * (b.h / px_mm) >= min_area_mm2 and b.w > 15 * px_mm and b.h > 15 * px_mm):
            boxes.append(b)
    # panels of one plate: merge boxes that overlap or sit side by side
    hx, hy = int(16 * px_mm), int(4 * px_mm)
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, c = boxes[i], boxes[j]
                if a.x0 - hx < c.x1 and c.x0 - hx < a.x1 and a.y0 - hy < c.y1 and c.y0 - hy < a.y1:
                    boxes[i] = Box(min(a.x0, c.x0), min(a.y0, c.y0), max(a.x1, c.x1), max(a.y1, c.y1))
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    boxes.sort(key=lambda b: (b.y0, b.x0))
    return boxes


def _label_of(block: dict) -> str:
    import re
    for key in ("translation", "text"):
        m = re.search(r"(?:\bFigs?\.|图)\s*(\d+[′']?)", block.get(key) or "")
        if m:
            return m.group(1)
    return ""


def scan_pdf(pdf, aligned: dict, out_dir, dpi: int = 200, pad_mm: float = 1.0) -> dict:
    """Crop figures of the aligned pages from an image-only PDF.

    Figures are paired top-to-bottom with the page's caption blocks in reading
    order; the label comes from the caption ("Fig. 12" or the Chinese equivalent).
    Writes source_figure_crops/*.png and source_figure_audit.json (same schema as
    "figures extract") and returns the audit dict.
    """
    import json
    from pathlib import Path

    import fitz

    out = Path(out_dir)
    (out / "source_figure_crops").mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    rows: list[dict] = []
    problems: dict[str, list] = {"figure_without_caption": [], "caption_without_figure": []}
    pad = int(pad_mm * dpi / 25.4)
    for page in aligned["pages"]:
        pno = int(page["page"])
        gray = render_gray(doc[pno - 1], dpi)
        boxes = find_figures(gray, dpi)
        caps = [b for b in page["blocks"] if b.get("role") == "caption"]
        if caps and not boxes:
            # a plate made of flat diagrams (setal formulae, strips): each piece is too thin
            # to pass the size filter alone, so keep them all and let the union below join them
            boxes = find_figures(gray, dpi, lenient=True)
            if len(boxes) < 2:
                boxes = []
            else:
                # the labels and formulae beside the strips are not seeds: take the full text width
                px = dpi / 25.4
                hh, ww = gray.shape
                boxes = [Box(int(10 * px), max(0, min(b.y0 for b in boxes) - int(12 * px)),
                             ww - int(10 * px), min(hh, max(b.y1 for b in boxes) + int(10 * px)))]
        if len(caps) == 1 and len(boxes) > 1:
            # one caption, several disconnected pieces: a plate whose panels do not touch
            boxes = [Box(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                         max(b.x1 for b in boxes), max(b.y1 for b in boxes))]
        h, w = gray.shape
        for i, b in enumerate(boxes, 1):
            fid = f"p{pno:04d}_{i:02d}"
            cap = caps[i - 1] if i <= len(caps) else None
            if cap is None:
                problems["figure_without_caption"].append(fid)
            x0, y0, x1, y1 = max(0, b.x0 - pad), max(0, b.y0 - pad), min(w, b.x1 + pad), min(h, b.y1 + pad)
            name = f"source_figure_crops/fig_scan_p{pno:03d}_{i:02d}.png"
            cv2.imwrite(str(out / name), gray[y0:y1, x0:x1])
            rows.append({"source_pdf_page": pno, "source_label": _label_of(cap) if cap else "",
                         "crop": name, "id": fid, "caption_text": (cap or {}).get("text", "")[:120],
                         "bbox_px": [x0, y0, x1, y1], "dpi": dpi})
        if len(caps) > len(boxes):
            problems["caption_without_figure"].append(pno)
    audit = {"ok": not any(problems.values()), "figures": len(rows), "problems": problems,
             "method": "scanfigures.find_figures (connected components)"}
    (out / "source_figure_audit.json").write_text(
        json.dumps({"figures": rows, "audit": audit}, ensure_ascii=False, indent=1), encoding="utf-8")
    return audit
