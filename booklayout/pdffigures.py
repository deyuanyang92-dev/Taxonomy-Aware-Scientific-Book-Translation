"""Generic figure extraction from a source PDF (issue #7, #13).

Book independent: no label vocabulary, page layout or publisher is hard coded
beyond the caption-label patterns in ``CAPTION_RE`` (extend by argument).

Why a *display rectangle* crop and not ``extract_image(xref)``: the black page
background behind a figure is page composition, not image data.  Extracting
the embedded JPEG alone gives a white background (Fauna Iberica vol. 48
p.17).  Rendering the page clip at the image's display rectangle keeps
background, labels, panels and colours exactly as printed.

Pipeline (deterministic, no model call):

1. ``image_placements``    every raster placement (bbox, xref, pixel size);
   optional ``vector=True`` adds clusters of vector drawings.
2. ``extract_figures``     crop each placement from the page render, write
   PNG, sha256, resolution, caption candidate (label + text + bbox).
3. ``link_figures`` (booklayout.figures) pairs figure and caption one-to-one.
4. ``audit_manifest``      missing/duplicate labels, repeated furniture
   (logos on many pages), low resolution, unmatched captions, placement
   problems from ``figures.audit_placement``.
5. ``write_outputs``       ``figures_manifest.json`` (full, machine readable),
   ``source_figure_audit.json`` (the file ``booklayout build`` reads) and the
   crops.

CLI: ``python3 -m booklayout figures extract --pdf book.pdf --out DIR``.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from .figures import audit_placement, link_figures

BBox = tuple[float, float, float, float]
VERSION = "booklayout-pdffigures 1"

# Caption openers in the languages seen so far; pass ``caption_re`` to extend.
CAPTION_RE = re.compile(
    r"^[\s*_]*(?:Figs?\.?|Figures?|Figura|Figuras|L[aá]m(?:ina)?\.?|Plates?|Pl\.|Abb(?:ildung)?\.?|"
    r"Fig\.|图|図|圖)\s*(?P<label>[0-9]+(?:\.[0-9]+)*[A-Za-z]?(?:\s*[-–,]\s*[0-9]+(?:\.[0-9]+)*[A-Za-z]?)*[’'′]?)",
    re.I,
)
# Placements smaller than this (pt) are rules, bullets and logos, not figures.
MIN_SIDE_PT = 40.0
# The same image digest on this many pages is page furniture (logo, rule).
REPEAT_PAGES = 3
MIN_PX_SHORT_SIDE = 300


def _fitz() -> Any:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc
    return fitz


SCAN_COVER = 0.85     # a raster covering this share of the page is the page itself (a scan), not a figure
SCAN_MIN_WORDS = 30    # ... and a text layer this long means it is an OCR'd scan


def _covers_page(page: Any, bbox: Sequence[float]) -> bool:
    area = max(float(page.rect.width * page.rect.height), 1.0)
    return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) >= SCAN_COVER * area


def is_scan_page(page: Any) -> bool:
    """True for a page-sized image under a real text layer (scanned page with OCR).  A page-sized image with
    (almost) no text is a plate and stays a figure."""
    if not any(_covers_page(page, i["bbox"]) for i in page.get_image_info()):
        return False
    return len(page.get_text("words")) >= SCAN_MIN_WORDS


BLANK_INK = 0.005      # inner-area share of dark pixels below which a page-sized image is a blank scan
INK_GRAY = 190


def _is_blank(page: Any) -> bool:
    """Inner 76% of the page rendered small: nearly no ink -> an empty scanned page (borders/bleed only)."""
    import fitz
    pix = page.get_pixmap(dpi=40, colorspace=fitz.csGRAY)
    w, h, s = pix.width, pix.height, pix.samples
    mx, my = int(w * 0.12), int(h * 0.12)
    tot = dark = 0
    for y in range(my, h - my):
        row = s[y * w + mx:y * w + w - mx]
        tot += len(row)
        dark += sum(1 for v in row if v < INK_GRAY)
    return tot > 0 and dark / tot < BLANK_INK


def image_placements(page: Any, vector: bool = False, min_side: float = MIN_SIDE_PT) -> list[dict[str, Any]]:
    """Display rectangles of raster images (and optionally vector clusters).

    The image layers of one scan (same box, several resolutions) count once; on an OCR scan page
    the page-sized image is the page, not a figure."""
    out: list[dict[str, Any]] = []
    scan = is_scan_page(page) or (any(_covers_page(page, i["bbox"]) for i in page.get_image_info())
                                  and _is_blank(page))
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = (float(v) for v in info["bbox"])
        if x1 - x0 < min_side or y1 - y0 < min_side:
            continue
        if scan and _covers_page(page, (x0, y0, x1, y1)):
            continue
        twin = next((o for o in out if all(abs(a - b) <= 1.0 for a, b in zip(o["bbox"], (x0, y0, x1, y1)))), None)
        px = (int(info.get("width", 0)), int(info.get("height", 0)))
        if twin is not None:
            if px[0] * px[1] > twin["px"][0] * twin["px"][1]:
                twin["px"], twin["xref"] = px, int(info.get("xref") or 0)
            continue
        out.append({"kind": "raster", "bbox": (x0, y0, x1, y1), "xref": int(info.get("xref") or 0), "px": px})
    if vector:
        drawings = [d for d in page.get_drawings() if d["rect"].width > 1 or d["rect"].height > 1]
        rects = [d["rect"] for d in drawings]
        spans = _text_spans(page)
        for box in _cluster(rects):
            w, h = box[2] - box[0], box[3] - box[1]
            if w < min_side or h < min_side:
                continue
            if any(_inside(box, p["bbox"]) for p in out):
                continue
            if _is_furniture_or_table(page, box, [d for d in drawings if _inside(tuple(d["rect"]), box)], spans):
                continue
            out.append({"kind": "vector", "bbox": box, "xref": 0, "px": (0, 0)})
    out.sort(key=lambda p: (round(p["bbox"][1]), p["bbox"][0]))
    return out


EDGE_BAND = 0.15      # header/footer band: fraction of the page height at top and bottom
TABLE_TEXT_FRAC = 0.05  # text area / box area above which a ruled grid is a table, not a figure
AXIS_FRAC = 0.9       # share of straight, axis-aligned strokes that makes a drawing a ruled grid
TEXT_DENSE_FRAC = 0.35


def _text_spans(page: Any) -> list[BBox]:
    out: list[BBox] = []
    for blk in page.get_text("dict").get("blocks", []):
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip():
                    out.append(tuple(float(v) for v in sp["bbox"]))  # type: ignore[arg-type]
    return out


def _is_furniture_or_table(page: Any, box: BBox, drawings: list[dict], spans: list[BBox]) -> bool:
    """True for a vector cluster that is a header/footer rule, a boxed running head, a ruled table
    or a block of text with underlines: not a figure."""
    ph = float(page.rect.height)
    if box[3] < EDGE_BAND * ph or box[1] > (1 - EDGE_BAND) * ph:   # lies wholly in the top/bottom band
        return True
    area = max((box[2] - box[0]) * (box[3] - box[1]), 1.0)
    text = sum((min(s[2], box[2]) - max(s[0], box[0])) * (min(s[3], box[3]) - max(s[1], box[1]))
               for s in spans if s[0] < box[2] and s[2] > box[0] and s[1] < box[3] and s[3] > box[1]
               and _inside(s, box))
    frac = text / area
    if frac > TEXT_DENSE_FRAC:
        return True
    strokes = axis = 0
    for d in drawings:
        if d.get("fill") is not None:
            return False                      # filled shapes are drawing, not a table grid
        for it in d.get("items", []):
            strokes += 1
            if it[0] == "re":
                axis += 1
            elif it[0] == "l" and (abs(it[1].x - it[2].x) < 0.5 or abs(it[1].y - it[2].y) < 0.5):
                axis += 1
            elif it[0] in ("c", "qu"):
                return False
    return strokes >= 4 and axis / strokes >= AXIS_FRAC and frac >= TABLE_TEXT_FRAC


def _inside(a: BBox, b: BBox, tol: float = 2.0) -> bool:
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def _cluster(rects: Iterable[Any], gap: float = 6.0) -> list[BBox]:
    boxes = [(r.x0, r.y0, r.x1, r.y1) for r in rects]
    merged = True
    while merged:
        merged = False
        out: list[BBox] = []
        for b in boxes:
            for i, o in enumerate(out):
                if b[0] <= o[2] + gap and b[2] >= o[0] - gap and b[1] <= o[3] + gap and b[3] >= o[1] - gap:
                    out[i] = (min(b[0], o[0]), min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3]))
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def page_captions(page: Any, caption_re: re.Pattern[str] = CAPTION_RE) -> list[dict[str, Any]]:
    """Text blocks that open with a figure label, with their bbox.

    The caption ends at the block end: the PDF text block is the only
    boundary used here, so a caption that PyMuPDF merges with following body
    text is reported by ``audit_placement`` as oversize rather than guessed.
    """
    caps = []
    for n, b in enumerate(page.get_text("blocks")):
        if b[6] != 0:
            continue
        text = " ".join(str(b[4]).split())
        m = caption_re.match(text)
        if m:
            caps.append({"id": f"c{n}", "bbox": tuple(float(v) for v in b[:4]), "text": text,
                         "chars": len(text), "label": re.sub(r"\s+", "", m.group("label"))})
    return caps


def extract_figures(pdf: Path, out_dir: Path, pages: Sequence[int] | None = None, dpi: int = 300,
                    vector: bool = False, caption_re: re.Pattern[str] = CAPTION_RE) -> dict[str, Any]:
    """Crop every figure placement from the rendered page; return the manifest."""
    fitz = _fitz()
    crops = out_dir / "source_figure_crops"
    crops.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    sel = list(pages) if pages else list(range(1, doc.page_count + 1))
    figures: list[dict[str, Any]] = []
    unmatched: dict[str, list[str]] = {"figures": [], "captions": []}
    problems: list[dict[str, Any]] = []
    for pno in sel:
        page = doc[pno - 1]
        places = image_placements(page, vector=vector)
        if not places:
            continue
        caps = page_captions(page, caption_re)
        pf = [{"id": f"p{pno:04d}_{i + 1:02d}", "page": pno, "bbox": pl["bbox"]} for i, pl in enumerate(places)]
        objs, um = link_figures(pf, [{**c, "page": pno, "id": f"p{pno:04d}_{c['id']}"} for c in caps])
        unmatched["figures"] += um.get("figures", [])
        unmatched["captions"] += um.get("captions", [])
        rect = page.rect
        problems += audit_placement(objs, um, {"width": rect.width, "height": rect.height})
        for i, (pl, o) in enumerate(zip(places, objs)):
            clip = fitz.Rect(*pl["bbox"]) & rect
            fname = f"fig_source_p{pno:03d}_{i + 1:02d}.png"
            try:
                if clip.is_empty or clip.width < 1 or clip.height < 1:
                    raise ValueError(f"empty clip {tuple(clip)}")
                pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=False)
                data = pix.tobytes("png")
            except Exception as exc:  # one bad placement must not abort the whole book
                problems.append({"page": pno, "kind": "crop_failed", "bbox_pt": list(pl["bbox"]),
                                 "error": str(exc)[:160]})
                continue
            (crops / fname).write_bytes(data)
            cap_label = next((c["label"] for c in caps if f"p{pno:04d}_{c['id']}" == o.caption_id), None)
            figures.append({
                "id": o.id, "source_pdf_page": pno, "order": i + 1, "kind": pl["kind"],
                "bbox_pt": [round(v, 2) for v in pl["bbox"]], "xref": pl["xref"],
                "embedded_px": list(pl["px"]), "crop": f"source_figure_crops/{fname}",
                "crop_px": [pix.width, pix.height], "crop_sha256": hashlib.sha256(data).hexdigest(),
                "dpi": dpi, "source_label": cap_label, "caption_id": o.caption_id,
                "caption_bbox_pt": [round(v, 2) for v in o.caption_bbox] if o.caption_bbox else None,
                "caption_text": o.caption_text,
            })
    doc.close()
    manifest = {"version": VERSION, "pdf": str(pdf), "pdf_sha256": _sha(pdf), "dpi": dpi,
                "pages_scanned": len(sel), "figures": figures, "unmatched": unmatched,
                "placement_problems": problems}
    manifest["audit"] = audit_manifest(manifest)
    return manifest


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_manifest(manifest: dict[str, Any], min_px: int = MIN_PX_SHORT_SIDE,
                   expected_labels: Sequence[str] | None = None) -> dict[str, Any]:
    """Deterministic checks; ``ok`` only when nothing needs a human."""
    figs = manifest["figures"]
    by_hash: dict[str, set[int]] = defaultdict(set)
    for f in figs:
        by_hash[f["crop_sha256"]].add(f["source_pdf_page"])
    furniture = sorted(h for h, pg in by_hash.items() if len(pg) >= REPEAT_PAGES)
    for f in figs:
        f["furniture"] = f["crop_sha256"] in furniture
    sci = [f for f in figs if not f["furniture"]]
    labels = Counter(f["source_label"] for f in sci if f["source_label"])
    dup_labels = sorted(k for k, v in labels.items() if v > 1)
    unlabeled = [f["id"] for f in sci if not f["source_label"]]
    low_res = [f["id"] for f in sci if min(f["crop_px"]) < min_px]
    dup_content = sorted(h for h, pg in by_hash.items() if 1 < len(pg) < REPEAT_PAGES)
    missing: list[str] = []
    unexpected: list[str] = []
    if expected_labels is not None:
        want = set(expected_labels)
        missing = sorted(want - set(labels))
        unexpected = sorted(set(labels) - want)
    um = manifest["unmatched"]
    problems = {
        "unmatched_figures": um["figures"], "unmatched_captions": um["captions"],
        "duplicate_labels": dup_labels, "unlabeled_figures": unlabeled, "low_resolution": low_res,
        "duplicate_content_on_few_pages": dup_content, "missing_labels": missing,
        "unexpected_labels": unexpected,
        "placement": manifest["placement_problems"],
    }
    return {"ok": not any(problems.values()), "figures": len(figs), "scientific_figures": len(sci),
            "furniture_figures": len(figs) - len(sci), "problems": problems}


def write_outputs(manifest: dict[str, Any], out_dir: Path, command: str = "") -> None:
    """Write ``figures_manifest.json`` and the ``source_figure_audit.json`` build input."""
    manifest["command"] = command
    manifest["tool"] = VERSION
    try:
        import fitz
        manifest["pymupdf"] = fitz.VersionBind
    except ImportError:  # pragma: no cover
        pass
    (out_dir / "figures_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    keep = [{"source_pdf_page": f["source_pdf_page"], "source_label": f["source_label"] or "",
             "crop": f["crop"], "id": f["id"], "caption_text": f["caption_text"]}
            for f in manifest["figures"] if not f.get("furniture")]
    (out_dir / "source_figure_audit.json").write_text(
        json.dumps({"figures": keep, "audit": manifest["audit"]}, ensure_ascii=False, indent=1), encoding="utf-8")


def map_to_translation(manifest: dict[str, Any], blocks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Pair each figure with the translated caption block that carries its label.

    ``blocks``: aligned-JSON blocks (``role``, ``block_id``, ``translation`` or
    ``text``).  Returns ``{"placements": {block_id: [figure ids]}, "unresolved": [...]}``;
    a figure whose label matches no, or more than one, caption block is listed
    as unresolved instead of being attached to a guess.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for b in blocks:
        if b.get("role") != "caption":
            continue
        m = CAPTION_RE.match((b.get("translation") or b.get("text") or "").strip())
        if m:
            index[re.sub(r"\s+", "", m.group("label"))].append(b.get("block_id", ""))
    placements: dict[str, list[str]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    for f in manifest["figures"]:
        if f.get("furniture"):
            continue
        hits = index.get(f["source_label"] or "", [])
        if len(hits) == 1:
            placements[hits[0]].append(f["id"])
        else:
            unresolved.append({"figure": f["id"], "label": f["source_label"],
                               "reason": "no_caption_block" if not hits else "ambiguous_caption_blocks",
                               "candidates": hits})
    return {"placements": dict(placements), "unresolved": unresolved}


def fit_check(manifest: dict[str, Any], max_w_mm: float = 118.0, max_h_mm: float = 150.0) -> list[dict[str, Any]]:
    """Aspect ratio and page-fit: report figures the builder must shrink a lot."""
    out = []
    for f in manifest["figures"]:
        w, h = f["crop_px"]
        if not w or not h:
            continue
        w_mm, h_mm = w / f["dpi"] * 25.4, h / f["dpi"] * 25.4
        scale = min(1.0, max_w_mm / w_mm, max_h_mm / h_mm)
        eff_dpi = f["dpi"] * scale if scale else 0.0
        if eff_dpi < 150:
            out.append({"id": f["id"], "scale": round(scale, 3), "effective_dpi": round(eff_dpi, 1)})
    return out


def add_parser(sub: Any) -> None:
    f = sub.add_parser("figures", help="extract source-PDF figures (display-rectangle crops + manifest)")
    fs = f.add_subparsers(dest="figures_cmd", required=True)
    e = fs.add_parser("extract", help="crop figures from a PDF; write figures_manifest.json and source_figure_audit.json")
    e.add_argument("--pdf", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--first", type=int, default=1)
    e.add_argument("--last", type=int, default=0, help="last page (default: all)")
    e.add_argument("--aligned", type=Path, help="only crop the source pages present in this aligned JSON (sample builds)")
    e.add_argument("--dpi", type=int, default=300)
    e.add_argument("--vector", action="store_true", help="also crop vector-only figures")
    e.add_argument("--lenient", action="store_true",
                   help="exit 0 whenever the manifest was written (audit problems stay in the audit file); "
                        "for unattended pipelines (sample, run)")
    e.add_argument("--expected-labels", help="comma list; missing/unexpected labels are reported")
    e.set_defaults(func=cmd_extract)
    s = fs.add_parser("scan", help="crop figures from an image-only (scanned) PDF by connected components")
    s.add_argument("--pdf", type=Path, required=True)
    s.add_argument("--aligned", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--dpi", type=int, default=200)
    s.set_defaults(func=cmd_scan)
    m = fs.add_parser("map", help="pair figures with translated caption blocks of an aligned JSON")
    m.add_argument("--manifest", type=Path, required=True)
    m.add_argument("--aligned", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    m.set_defaults(func=cmd_map)


def cmd_extract(args: Any) -> int:
    fitz = _fitz()
    n = fitz.open(str(args.pdf)).page_count
    last = args.last or n
    args.out.mkdir(parents=True, exist_ok=True)
    pages: Sequence[int] = range(args.first, last + 1)
    if args.aligned:
        al = json.loads(args.aligned.read_text(encoding="utf-8"))
        pages = sorted({int(p["page"]) for p in al["pages"] if args.first <= int(p["page"]) <= last})
    mf = extract_figures(args.pdf, args.out, pages, args.dpi, args.vector)
    if args.expected_labels:
        mf["audit"] = audit_manifest(mf, expected_labels=[s for s in args.expected_labels.split(",") if s])
    write_outputs(mf, args.out, " ".join(["python3", "-m", "booklayout", *sys.argv[1:]]))
    a = mf["audit"]
    print(f"figures={a['figures']} scientific={a['scientific_figures']} furniture={a['furniture_figures']} ok={a['ok']}")
    return 0 if (a["ok"] or getattr(args, "lenient", False)) else 1


def cmd_scan(args: Any) -> int:
    from .scanfigures import scan_pdf
    from .headings import promote_captions
    al = json.loads(args.aligned.read_text(encoding="utf-8"))
    promote_captions(al)
    a = scan_pdf(args.pdf, al, args.out, args.dpi)
    p = a["problems"]
    print(f"figures={a['figures']} figure_without_caption={len(p['figure_without_caption'])} "
          f"caption_without_figure={len(p['caption_without_figure'])} ok={a['ok']}")
    return 0 if a["ok"] else 1


def cmd_map(args: Any) -> int:
    mf = json.loads(args.manifest.read_text(encoding="utf-8"))
    aligned = json.loads(args.aligned.read_text(encoding="utf-8"))
    blocks = [b for p in aligned["pages"] for b in p["blocks"]]
    res = map_to_translation(mf, blocks)
    args.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"placed={sum(len(v) for v in res['placements'].values())} unresolved={len(res['unresolved'])}")
    return 0 if not res["unresolved"] else 1
