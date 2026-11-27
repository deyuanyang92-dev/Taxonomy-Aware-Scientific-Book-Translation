"""Layout fingerprint of a PDF page range (source or finished book), language-free.

The same function measures the source PDF and the output PDF; `booklayout.likeness`
compares the two.  Nothing here knows a book's name, font, size or column count:
every value is measured, and per-book tolerances live in the likeness config.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from booklayout import fontlevels
from booklayout.furniture import detect_furniture, signature
from booklayout.nativefonts import span_style
from booklayout.pdffigures import image_placements, page_captions

VERSION = "booklayout-fingerprint 1"
_LATIN = re.compile(r"^[A-Z][a-z]+(?: [a-z]{3,}){0,2}$|^[a-z]{4,}$")
_DIGIT = re.compile(r"^\d{1,4}$")


@dataclass
class FingerprintConfig:
    band: float = 0.08          # page-edge band (fraction of page height) = furniture
    min_col_lines: int = 20     # a page votes on column count only with this many body lines
    vector: bool = True         # count vector drawings as figures
    min_fig_side: float = 40.0  # pt


def _fitz() -> Any:
    import fitz

    return fitz


def _edge_lines(page: Any, band: float) -> list[tuple[str, dict]]:
    from docstore.probe import _line_rows

    h = page.rect.height
    out = []
    for r in _line_rows(page):
        if r["y1"] <= band * h:
            out.append(("top", r))
        elif r["y0"] >= (1 - band) * h:
            out.append(("bottom", r))
    return out


def _hpos(x0: float, x1: float, width: float) -> str:
    c = (x0 + x1) / 2 / width
    return "left" if c < 0.38 else "right" if c > 0.62 else "center"


def _has_rule(page: Any, where: str, band: float) -> bool:
    h = page.rect.height
    for d in page.get_drawings():
        r = d["rect"]
        if r.height < 2 and r.width > 0.3 * page.rect.width:
            y = r.y0 / h
            if (where == "top" and y < band + 0.03) or (where == "bottom" and y > 1 - band - 0.03):
                return True
    return False


def furniture_type(doc: Any, nums: list[int], band: float = 0.08) -> dict:
    """Running head/foot kind: position, text/folio kind, folio placement rule."""
    pages = [{"page": n, "height": doc[n - 1].rect.height,
              "lines": [r for _k, r in _edge_lines(doc[n - 1], band)]} for n in nums]
    rep = detect_furniture(pages, min_repeat=max(2, min(3, len(nums) // 3)), band=band)
    per: list[dict[str, Any]] = []
    for n in nums:
        pg = doc[n - 1]
        width = pg.rect.width
        items: list[tuple[str, str, str]] = []
        for where, r in _edge_lines(pg, band):
            t = r["text"].strip()
            if signature(t) not in rep.signatures and not _DIGIT.match(t):
                if not re.match(r"^\d{1,4}\s|\s\d{1,4}$", t):
                    continue
            folio = bool(_DIGIT.match(t) or re.match(r"^\d{1,4}\s|.*\s\d{1,4}$", t))
            if _DIGIT.match(t):
                pos = _hpos(r["x0"], r["x1"], width)
            else:
                pos = "left" if re.match(r"^\d{1,4}\s", t) else "right" if re.search(r"\s\d{1,4}$", t) else _hpos(r["x0"], r["x1"], width)
            items.append((where, "folio" if _DIGIT.match(t) else ("text+folio" if folio else "text"), pos if folio else "-"))
        rule = _has_rule(pg, "top", band) or _has_rule(pg, "bottom", band)
        per.append({"page": n, "items": sorted(set(items)), "rule": rule})
    need = max(1, len(nums) // 3)
    wheres = Counter(w for p in per for w, _k, _p in p["items"])
    kinds = Counter(k for p in per for _w, k, _p in p["items"])
    fpos: dict[int, Counter] = {}
    for p in per:
        for _w, k, pos in p["items"]:
            if "folio" in k:
                fpos.setdefault(p["page"] % 2, Counter())[pos] += 1
    ev = fpos.get(0, Counter()).most_common(1)
    od = fpos.get(1, Counter()).most_common(1)
    evp = ev[0][0] if ev else None
    odp = od[0][0] if od else None
    if evp and odp and evp != odp and {evp, odp} == {"left", "right"}:
        folio_rule = "alternating"
    else:
        folio_rule = evp or odp or "none"
    return {"position": sorted(w for w, c in wheres.items() if c >= need),
            "kinds": sorted(k for k, c in kinds.items() if c >= need),
            "folio_rule": folio_rule,
            "head_rule_line": sum(p["rule"] for p in per) > len(per) / 2,
            "pages_without": [p["page"] for p in per if not p["items"]]}


def _body_rows(page: Any, boxes: list, band: float) -> list[dict]:
    from docstore.probe import _inside_any, _line_rows

    h = page.rect.height
    return [r for r in _line_rows(page)
            if not (r["y1"] <= band * h or r["y0"] >= (1 - band) * h) and not _inside_any(r, boxes)]


def fingerprint(pdf: Path | str, pages: list[int] | None = None, cfg: FingerprintConfig | None = None) -> dict:
    """Measure the layout of `pages` (1-based; default all) of `pdf`."""
    from docstore.probe import _bookmarks, _contents_page, page_columns

    cfg = cfg or FingerprintConfig()
    band = cfg.band
    doc = _fitz().open(str(pdf))
    try:
        nums = list(pages) if pages else list(range(1, len(doc) + 1))
        pgs = [doc[n - 1] for n in nums]
        fl = fontlevels.analyse(pgs)
        body = fl["body"]
        head_at = {(h["page"], h["text"]): h["level"] for h in fl["headings"]}
        seq: list[str] = []
        cols: list[int] = []
        figs = caps = 0
        ital_chars = tot_chars = latin_italic = italic_spans = 0
        for n, pg in zip(nums, pgs):
            f = image_placements(pg, vector=cfg.vector, min_side=cfg.min_fig_side)
            cap_boxes = [cp["bbox"] for cp in page_captions(pg)]
            rows = _body_rows(pg, [p["bbox"] for p in f] + cap_boxes, band)
            c, gut = page_columns(rows)
            if len(rows) >= cfg.min_col_lines:
                cols.append(c)
            mid = (gut[0] + gut[1]) / 2 if gut else None
            h = pg.rect.height
            figs += len(f)
            caps += len(cap_boxes)
            items: list[tuple[tuple, str]] = [(p["bbox"], "FIG") for p in f]
            for b in pg.get_text("dict")["blocks"]:
                if b.get("type") != 0:
                    continue
                lines = b.get("lines", [])
                text = " ".join(" ".join("".join(s["text"] for s in ln["spans"]).split()) for ln in lines).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = b["bbox"]
                if y1 <= band * h or y0 >= (1 - band) * h:
                    continue
                role = "BODY"
                if any(abs(cb[1] - y0) < 2 and abs(cb[0] - x0) < 2 for cb in cap_boxes):
                    role = "CAP"
                else:
                    for ln in lines:
                        t = " ".join("".join(s["text"] for s in ln["spans"]).split())
                        if (n, t) in head_at:
                            role = f"H{head_at[(n, t)]}"
                            break
                items.append(((x0, y0, x1, y1), role))
                if role == "BODY":
                    for ln in lines:
                        for s in ln["spans"]:
                            k = len(s["text"].strip())
                            if not k:
                                continue
                            it, _bd = span_style(s)
                            tot_chars += k
                            if it:
                                ital_chars += k
                                italic_spans += 1
                                if _LATIN.match(s["text"].strip().strip(".,;:()")):
                                    latin_italic += 1

            def key(it: tuple, mid: float | None = mid, h: float = h) -> tuple:
                (x0, y0, x1, _y1), _r = it
                span = mid is not None and x0 < mid < x1
                col = 0 if mid is None or (x0 + x1) / 2 < mid else 1
                return (-1 if y0 < h * 0.3 else 2, y0) if span else (col, y0)

            items.sort(key=key)
            seq.extend(r for _b, r in items)
        collapsed = [r for i, r in enumerate(seq) if i == 0 or seq[i - 1] != r]
        ladder = [{"level": r["level"], "rel_size": round(r["size"] / body["size"], 2) if body["size"] else None,
                   "bold": r["bold"], "count": r["count"]} for r in fl["ladder"]]
        used = sorted({h["level"] for h in fl["headings"]})
        cc = Counter(cols)
        contents = _contents_page(doc)
        return {
            "version": VERSION, "source": Path(str(pdf)).name, "pages": nums, "n_pages": len(nums),
            "roles": collapsed, "role_counts": dict(Counter(seq)),
            "heading": {"n_levels": len(used), "ladder": ladder,
                        "numbered": any(h["number"] for h in fl["headings"]), "n_headings": len(fl["headings"])},
            "columns": cc.most_common(1)[0][0] if cc else 1, "columns_by_page": {str(k): v for k, v in cc.items()},
            "figures": figs, "captions": caps,
            "italic": {"italic_char_frac": round(ital_chars / tot_chars, 3) if tot_chars else 0,
                       "latin_share_of_italic": round(latin_italic / italic_spans, 2) if italic_spans else 0,
                       "present": latin_italic > 0},
            "furniture": furniture_type(doc, nums, band),
            "book": {"contents_page": contents, "bookmarks": _bookmarks(doc)["count"],
                     "front_before_contents": (contents or 1) - 1},
            "allowed_info": {"body_font": body["family"], "body_pt": body["size"],
                             "page_w": round(doc[nums[0] - 1].rect.width)},
        }
    finally:
        doc.close()


def cmd_fingerprint(a: Any) -> int:
    doc = _fitz().open(str(a.pdf))
    n = len(doc)
    doc.close()
    nums = fontlevels.parse_pages(a.pages, n) if a.pages else None
    fp = fingerprint(a.pdf, nums)
    text = json.dumps(fp, ensure_ascii=False, indent=1)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    h = fp["heading"]
    print(f"{fp['source']}: pages={fp['n_pages']} columns={fp['columns']} levels={h['n_levels']} "
          f"figures={fp['figures']} captions={fp['captions']} furniture={fp['furniture']['position']}/"
          f"{fp['furniture']['kinds']}/{fp['furniture']['folio_rule']} roles={len(fp['roles'])}")
    return 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("fingerprint", help="language-free layout fingerprint of a PDF page range")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", help="1-based, e.g. 13-40 or 3,7,10-12 (default: all)")
    p.add_argument("--json", type=Path, help="write the full fingerprint here")
    p.set_defaults(func=cmd_fingerprint)
