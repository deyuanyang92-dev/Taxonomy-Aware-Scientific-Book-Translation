"""`booklayout profile --from-pdf`: a style profile measured from a source PDF's page range.

The profile of an edition that should look like its source (trim size, text area, type sizes,
heading ladder, column count, running head at the top with mirrored folios) is measured, not
typed.  Everything comes from the same measurements as `booklayout.fingerprint` (fontlevels,
page columns, furniture); no value is a book's name or a font's name.  Absolute sizes are kept
so a Chinese edition can reuse the profile and only change fonts (`--serif-font`, `--sans-font`,
`cjk_font`).  Sizes that the builder scales with `body_size` are written relative to a 10.5 pt body.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from booklayout import fontlevels
from booklayout.fingerprint import FingerprintConfig, _body_rows, _edge_lines, fingerprint
from booklayout.pdffigures import page_captions

PT_MM = 25.4 / 72
_DIGITS = re.compile(r"^\d{1,4}$")
_TRIM = re.compile(r"^\d{1,4}\s+|\s+\d{1,4}$")


def fit_heading_styles(hstyles: dict[str, dict[str, Any]]) -> None:
    """In place: keep only the levels the builder defines (1..MAX_HEADING_LEVEL) and let unused
    deeper levels up to 4 repeat the deepest measured one.  A measured ladder can be deeper than
    the builder's Word styles (Rouse 2022 measures 7 sizes); the extra levels fold into the last."""
    from .profile import MAX_HEADING_LEVEL
    for k in [k for k in hstyles if int(k) > MAX_HEADING_LEVEL]:
        del hstyles[k]
    last = max((int(k) for k in hstyles), default=0)
    for lv in range(last + 1, 5):
        if last:
            hstyles[str(lv)] = dict(hstyles[str(last)])


def _mm(pt: float) -> float:
    return round(pt * PT_MM, 1)


def _page_margins(pages: list[Any], band: float) -> dict[str, float]:
    """Mean text-area margins (pt) from body lines; a mirrored spread averages out."""
    tops, bots, lefts, rights = [], [], [], []
    for pg in pages:
        rows = _body_rows(pg, [], band)
        if len(rows) < 10:
            continue
        tops.append(min(r["y0"] for r in rows))
        bots.append(pg.rect.height - max(r["y1"] for r in rows))
        lefts.append(min(r["x0"] for r in rows))
        rights.append(pg.rect.width - max(r["x1"] for r in rows))
    if not tops:
        return {}
    side = (median(lefts) + median(rights)) / 2
    return {"top": median(tops), "bottom": median(bots), "side": side}


def _running_heads(pages: list[Any], nums: list[int], band: float) -> tuple[dict[str, float], dict[int, str]]:
    """(header geometry, {parity: running text}) from the top-band lines, folio digits removed.
    Parity is the printed folio's when one is found, else the PDF page's."""
    text_by_par: dict[int, Counter] = {0: Counter(), 1: Counter()}
    ys: list = []
    for n, pg in zip(nums, pages):
        lines = [r for k, r in _edge_lines(pg, band) if k == "top"]
        if not lines:
            continue
        folio = next((int(r["text"].strip()) for r in lines if _DIGITS.match(r["text"].strip())), None)
        for r in lines:
            t = r["text"].strip()
            ys.append(r["y0"])
            if _DIGITS.match(t):
                continue
            parts = re.split(r"\N{EM SPACE}+", re.sub(r"[\x00-\x08\x0a-\x1f]", " ", t))
            t = " ".join(p.strip() for p in parts if p.strip() and not _DIGITS.match(p.strip()))
            if re.search(r"[^\W\d_]{3}", t):
                text_by_par[(folio if folio is not None else n) % 2][t] += 1
    heads = {p: c.most_common(1)[0][0] for p, c in text_by_par.items() if c and c.most_common(1)[0][1] >= 2}
    return {"y": median(ys) if ys else 0.0, **_head_sizes(pages, band)}, heads


def _head_sizes(pages: list[Any], band: float) -> dict[str, float]:
    """Modal span size of the running text and of the folio digits in the top band (pt)."""
    txt: Counter = Counter()
    fol: Counter = Counter()
    for pg in pages:
        lim = band * pg.rect.height
        for b in pg.get_text("dict")["blocks"]:
            if b["bbox"][3] > lim:
                continue
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    t = s["text"].strip()
                    if t:
                        (fol if _DIGITS.match(t) else txt)[round(s["size"], 1)] += len(t)
    out = {}
    if txt:
        out["text_size"] = txt.most_common(1)[0][0]
    if fol:
        out["folio_size"] = fol.most_common(1)[0][0]
    return out


def _heading_ladder(pages: list[Any], res: dict, body: dict) -> list[dict]:
    """Per level: median size, bold, italic (only when every heading of the level is wholly italic), class."""
    by: dict[int, list[dict]] = {}
    for h in res["headings"]:
        by.setdefault(h["level"], []).append(h)
    out = []
    for lv in sorted(by):
        hs = by[lv]
        out.append({"level": lv, "size": median(h["style"]["size"] for h in hs),
                    "bold": sum(h["style"]["bold"] for h in hs) * 2 >= len(hs), "n": len(hs)})
    return out


def measure_profile(pdf: Path | str, pages: list[int] | None = None, serif_font: str = "Times New Roman",
                    sans_font: str = "Arial", name: str | None = None) -> dict[str, Any]:
    """Return a StyleProfile dict measured from `pages` (1-based; default all) of `pdf`."""
    import fitz

    cfg = FingerprintConfig()
    fp = fingerprint(pdf, pages, cfg)
    doc = fitz.open(str(pdf))
    try:
        nums = list(pages) if pages else list(range(1, len(doc) + 1))
        pgs = [doc[n - 1] for n in nums]
        res = fontlevels.analyse(pgs)
        body = res["body"]
        bsize = body["size"] or 10.5
        pw, ph = pgs[0].rect.width, pgs[0].rect.height
        mg = _page_margins(pgs, cfg.band)
        head_geo, heads = _running_heads(pgs, nums, cfg.band)
        # caption size: dominant span size inside caption boxes
        cap_sizes: Counter = Counter()
        cap_fonts: Counter = Counter()
        for pg in pgs:
            for cp in page_captions(pg):
                x0, y0, x1, y1 = cp["bbox"]
                for b in pg.get_text("dict", clip=fitz.Rect(x0, y0, x1, y1))["blocks"]:
                    for ln in b.get("lines", []):
                        for s in ln["spans"]:
                            cap_sizes[round(s["size"], 1)] += len(s["text"].strip())
                            cap_fonts[fontlevels.is_serif(s["font"], s["flags"])] += len(s["text"].strip())
        cap_pt = cap_sizes.most_common(1)[0][0] if cap_sizes else None
        cap_serif = cap_fonts.most_common(1)[0][0] if cap_fonts else None
        # leading: modal baseline distance of consecutive body lines
        gaps: Counter = Counter()
        for pg in pgs:
            rows = sorted(_body_rows(pg, [], cfg.band), key=lambda r: (round(r["x0"] / 50), r["y0"]))
            for a, b in zip(rows, rows[1:]):
                d = b["y0"] - a["y0"]
                if 0.9 * bsize < d < 2.2 * bsize and abs(a["x0"] - b["x0"]) < 5:
                    gaps[round(d, 1)] += 1
        pitch = gaps.most_common(1)[0][0] if gaps else 1.2 * bsize

        def font(serif: bool) -> str:
            return serif_font if serif else sans_font

        body_font = font(body["serif"])
        ladder = _heading_ladder(pgs, res, body)
        head_serif = None
        if res["ladder"]:
            first = next(iter(res["ladder"]), None)
            head_serif = is_serif_family(first["family"]) if first else None
        hstyles: dict[str, dict[str, Any]] = {}
        for rec in ladder:
            size = rec["size"] * 10.5 / bsize   # builder scales heading sizes with body_size / 10.5
            hstyles[str(rec["level"])] = {
                "size": round(size, 2), "bold": bool(rec["bold"]), "italic": False, "align": "left",
                "small_caps": False, "before": 0 if rec["level"] == 1 else round(rec["size"] * 0.9),
                "after": round(rec["size"] * 0.35)}
        fit_heading_styles(hstyles)
        fur = fp["furniture"]
        top = "top" in fur["position"]
        prof: dict[str, Any] = {
            "name": name or f"measured:{Path(str(pdf)).stem}:{nums[0]}-{nums[-1]}",
            "page_w": _mm(pw), "page_h": _mm(ph),
            "body_font": body_font, "body_size": bsize,
            "lang": "en-US", "lang_east_asia": "en-US",
            "columns": fp["columns"],
            "footer_style": "running_top" if top else "center",
            "taxonomic": True,
        }
        if mg:
            prof.update({"margin_top": _mm(mg["top"]), "margin_bottom": _mm(mg["bottom"]),
                         "margin_left": _mm(mg["side"]), "margin_right": _mm(mg["side"])})
        if top and head_geo["y"]:
            prof["header_distance"] = _mm(head_geo["y"])
        if hstyles:
            prof["heading_styles"] = hstyles
        if cap_serif is not None and cap_serif != body["serif"]:
            prof["caption_font"] = font(cap_serif)
        if head_serif is not None and head_serif != body["serif"]:
            prof["heading_font"] = font(head_serif)
        ps: dict[str, dict[str, Any]] = {}
        line = round(pitch / (1.15 * bsize), 2)   # Word's single line is about 1.15 x the size
        ps["Body"] = {"line": line}
        ps["Body Cont"] = {"line": line}
        if cap_pt:
            ps["Caption"] = {"size": round(cap_pt * 10.5 / bsize, 2)}
        prof["para_styles"] = ps
        if top:
            prof["header_size"] = head_geo.get("text_size", bsize)    # running text
            prof["footer_size"] = head_geo.get("folio_size", bsize)   # a top-running source has no footer: its folio size
            if 0 in heads:
                prof["running_even"] = heads[0]
            if 1 in heads:
                prof["running_odd"] = heads[1]
        return prof
    finally:
        doc.close()


def is_serif_family(family: str) -> bool:
    return fontlevels.is_serif(family)


def cmd_from_pdf(a: Any) -> int:
    import fitz

    d = fitz.open(str(a.from_pdf))
    n = len(d)
    d.close()
    nums = fontlevels.parse_pages(a.pages, n) if a.pages else None
    prof = measure_profile(a.from_pdf, nums, a.serif_font, a.sans_font, a.name)
    from booklayout.profile import StyleProfile

    StyleProfile.from_dict(prof)   # validates
    text = json.dumps(prof, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text if not a.out else f"profile: {a.out}  page={prof['page_w']}x{prof['page_h']} mm "
          f"body={prof['body_size']} pt columns={prof['columns']} footer_style={prof['footer_style']} "
          f"heading levels={len(prof.get('heading_styles', {}))}")
    return 0
