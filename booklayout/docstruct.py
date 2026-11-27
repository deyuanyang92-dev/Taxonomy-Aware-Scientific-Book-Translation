"""Structure stage for native PDFs (issue #71): native text + PaddleOCR-VL layout labels -> docstruct/1.

B (structure from the model): every page's PaddleOCR-VL blocks (label, box, reading order), cached by
'docstore layout <key> --pages ...' in <root>/layout/<key>/pNNNN.json.  Region types (title, section
title, table with rows, figure caption, header/footer, footnote) come from here.
A (rules, cross-check and correction): the native text layer supplies all text (exact characters,
italics, bold); repeated edge lines decide what is really running furniture; page kinds (cover,
title, copyright, contents, authors, chapter start, body) come from page-level cues; contents
entries are parsed from native lines ('Title — 133') and compared with booklayout.contents;
heading levels come from section numbers; the contents entries are checked against the headings
found in the body.  Disagreements are listed in "problems"; severity "error" blocks translation.

Pure functions take fitz pages + layout dicts, so tests need no files.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from booklayout import ingest_native as N
from booklayout.furniture import signature

SCHEMA = "docstruct/1"
FURNITURE_LABELS = {"header", "footer", "number", "header_image", "footer_image", "aside_text", "seal"}
WATERMARK = re.compile(r"^(Authenticated\b|Download Date\b)|Authenticated \|", re.I)
TOC_LINE = re.compile(r"^(?P<title>.+?)\s*[—–]\s*(?P<page>[ivxlcdm]+|\d+)\s*$", re.I)
NUMBERED = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$")
CHAPTER_TITLE = re.compile(r"^\d{1,2}\s+[A-Z]")
COPYRIGHT = re.compile(r"\bISBN\b|©|Library of Congress|Bibliographic information|Deutsche Nationalbibliothek", re.I)
PANEL = re.compile(r"^[A-Za-z]{1,2}\)?$")
TABLE_CAP = re.compile(r"^\W{0,2}T?ab(?:le)?\.?\s*\d", re.I)
EMAIL = re.compile(r"\S+@\S+\.\w+")
KIND_TITLES = {"contents": "toc", "list of contributing authors": "authors", "contributors": "authors",
               "list of contributors": "authors", "preface": "preface", "foreword": "preface",
               "index": "index"}
TRANSLATE_FALSE = {"author_name", "furniture", "panel_label", "figure_text", "email"}


def _bare(t: str) -> str:
    m = NUMBERED.match(t)
    return m.group("title") if m else t


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ----------------------------------------------------------------- native lines with direction


def native_lines(page: Any) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = ln["spans"]
            if not any(s["text"].strip() for s in spans):
                continue
            x0, y0, x1, y1 = ln["bbox"]
            text = " ".join("".join(s["text"] for s in spans).replace("\x07", "").split())
            out.append(dict(spans=spans, x0=x0, y0=y0, x1=x1, y1=y1, dir=tuple(round(d) for d in ln["dir"]),
                            text=N.unglue(text) if len(spans) == 1 else text))
    return out


def _order(lines: list[dict]) -> list[dict]:
    if lines and all(ln["dir"] == (0, -1) for ln in lines):   # rotated 90 deg, reads bottom-up
        return sorted(lines, key=lambda ln: (round(ln["x0"]), -ln["y1"]))
    if lines and all(ln["dir"] == (0, 1) for ln in lines):
        return sorted(lines, key=lambda ln: (-round(ln["x1"]), ln["y0"]))
    return sorted(lines, key=lambda ln: (round(ln["y0"]), ln["x0"]))


def _text(lines: list[dict]) -> tuple[str, str, bool]:
    """(marked text, plain text, all bold)."""
    lines = _order(lines)
    runs = N._runs(lines)
    bold = bool(runs) and all(r.get("b") for r in runs if r["t"].strip())
    return N._mark(runs, bold).replace("\x07", ""), " ".join(N._plain(lines).replace("\x07", "").split()), bold


# ----------------------------------------------------------------- B: PaddleOCR-VL layout


def load_layout(layout_dir: Path, page: int) -> dict | None:
    f = Path(layout_dir) / f"p{page:04d}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def paddle_blocks(lay: dict, page_w_pt: float) -> list[dict]:
    pr = lay.get("pruned_result") or {}
    scale = page_w_pt / float(lay.get("width_px") or pr.get("width") or page_w_pt)
    out = []
    for b in pr.get("parsing_res_list") or []:
        x0, y0, x1, y1 = (v * scale for v in b["block_bbox"])
        out.append({"label": b["block_label"], "text": b.get("block_content") or "", "order": b.get("block_order"),
                    "bbox": [x0, y0, x1, y1]})
    return out


def _inside(ln: dict, bb: list[float], pad: float = 2.0) -> bool:
    cx, cy = (ln["x0"] + ln["x1"]) / 2, (ln["y0"] + ln["y1"]) / 2
    return bb[0] - pad <= cx <= bb[2] + pad and bb[1] - pad <= cy <= bb[3] + pad


def assign_lines(lines: list[dict], pblocks: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    """Each native line goes to the smallest Paddle box containing its centre."""
    owned: list[list[dict]] = [[] for _ in pblocks]
    orphans = []
    for ln in lines:
        hits = [i for i, b in enumerate(pblocks) if _inside(ln, b["bbox"])]
        if not hits:
            orphans.append(ln)
            continue
        i = min(hits, key=lambda i: (pblocks[i]["bbox"][2] - pblocks[i]["bbox"][0]) * (pblocks[i]["bbox"][3] - pblocks[i]["bbox"][1]))
        owned[i].append(ln)
    return owned, orphans


SUP = str.maketrans("0123456789+-=()abcn", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜⁿ")
SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def unlatex(s: str) -> str:
    """OCR LaTeX left in table cells: '$ ^{1} $' -> '¹', '$ _{2} $' -> '₂' (the gate rejects literal markup)."""
    def rep(m: re.Match) -> str:
        body = m.group(2).strip()
        return body.translate(SUP if m.group(1) == "^" else SUB)
    return re.sub(r"\s*\$\s*([\^_])\{([^}]*)\}\s*\$", rep, s)


def _cell_text(c: str) -> str:
    return unlatex(" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split()))


def table_rows(html_text: str) -> list[list[Any]]:
    """HTML table -> rows; a cell is its text, or {"text", "colspan"} when it spans columns."""
    rows: list[list[Any]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        row: list[Any] = []
        for attrs, c in re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.S | re.I):
            m = re.search(r"colspan\s*=\s*[\"']?(\d+)", attrs, re.I)
            span = int(m.group(1)) if m else 1
            row.append({"text": _cell_text(c), "colspan": span} if span > 1 else _cell_text(c))
        rows.append(row)
    return rows


def cell_text(c: Any) -> str:
    return c.get("text", "") if isinstance(c, dict) else str(c)


def split_table_notes(rows: list[list[Any]]) -> tuple[list[list[Any]], list[str]]:
    """Trailing rows made of one cell spanning the whole table are the table's notes/footnotes
    (OCR puts them inside the table); they are typeset as notes below it, not in the first column."""
    width = max((sum(c.get("colspan", 1) if isinstance(c, dict) else 1 for c in r) for r in rows), default=0)
    notes: list[str] = []
    while len(rows) > 1 and len(rows[-1]) == 1 and width > 1 and isinstance(rows[-1][0], dict) \
            and rows[-1][0].get("colspan", 1) >= width:
        notes.insert(0, rows[-1][0]["text"])
        rows = rows[:-1]
    return rows, [n for n in notes if n]


# ----------------------------------------------------------------- A: contents lines


def _rows(lines: list[dict], page_w: float) -> list[list[dict]]:
    """Native lines -> visual rows (left column first, then right), each row sorted by x."""
    out: list[list[dict]] = []
    mid = _gutter(lines, page_w)
    for col in ([ln for ln in lines if ln["x0"] < mid], [ln for ln in lines if ln["x0"] >= mid]):
        col = sorted(col, key=lambda ln: (ln["y0"] + ln["y1"]) / 2)
        rows: list[list[dict]] = []
        for ln in col:
            cy = (ln["y0"] + ln["y1"]) / 2
            if rows and abs(cy - sum((r["y0"] + r["y1"]) / 2 for r in rows[-1]) / len(rows[-1])) <= 3.5:
                rows[-1].append(ln)
            else:
                rows.append([ln])
        out += [sorted(r, key=lambda ln: ln["x0"]) for r in rows]
    return out


def _gutter(lines: list[dict], page_w: float) -> float:
    """x of the empty vertical strip between two columns (no line crosses it), nearest the middle."""
    body = [ln for ln in lines if ln["y0"] > 50]
    free = [x for x in range(int(page_w * 0.35), int(page_w * 0.65), 2)
            if not any(ln["x0"] < x < ln["x1"] for ln in body)]
    return min(free, key=lambda x: abs(x - page_w / 2)) if free else page_w


FOLIO = re.compile(r"^(?:[ivxlcdm]+|\d{1,4})$", re.I)
NUM_ONLY = re.compile(r"^\d+(?:\.\d+)*\.?$")


def _bold(ln: dict) -> bool:
    return any("bold" in s["font"].lower() or s["flags"] & 16 for s in ln["spans"] if s["text"].strip())


def parse_toc_lines(lines: list[dict], page_w: float = 595.0) -> list[dict]:
    """Native contents lines -> entries.  A visual row ending in a page number is an entry
    ('5.1 | Apistobranchidae ... | 133').  A row without one is the first half of a wrapped title
    when the next entry row starts indented under it ('5.1 Apistobranchidae Mesnil & Caullery,' +
    '1898 133'); a large bold row is a part heading ('Part 1: Introduction'); any other row is an
    author line, printed above the entry it belongs to.  Separators ('—') may be drawn, not text."""
    lines = [ln for ln in lines if not (WATERMARK.match(ln["text"]) or EMAIL.search(ln["text"]))]
    rows = [r for r in _rows(lines, page_w)
            if not (min(ln["y0"] for ln in r) < 50 and (any(_norm(ln["text"]) == "contents" for ln in r)
                                                         or len(r) == 1 and FOLIO.match(r[0]["text"].strip())))
            and not (len(r) == 1 and _norm(r[0]["text"]) == "contents")]
    entries: list[dict] = []
    pending: list[list[dict]] = []
    for r in rows:
        texts = [ln["text"].strip() for ln in r]
        if len(r) >= 2 and FOLIO.match(texts[-1]):
            body = r[:-1]
            num = texts[0].rstrip(".") if len(body) >= 2 and NUM_ONLY.match(texts[0]) else None
            title = " ".join(ln["text"].strip() for ln in (body[1:] if num else body))
            if pending and not num and r[0]["x0"] > min(ln["x0"] for ln in pending[-1]) + 5:
                ftexts = [ln["text"].strip() for ln in pending.pop()]
                if len(ftexts) >= 2 and NUM_ONLY.match(ftexts[0]):
                    num, ftexts = ftexts[0].rstrip("."), ftexts[1:]
                title = " ".join(ftexts) + " " + title
            title = re.sub(r"\s*[—–]\s*$", "", title.replace("\x07", "")).strip()
            e: dict[str, Any] = {"title": title, "printed": texts[-1], "number": num, "bold": _bold(body[-1])}
            authors = [" ".join(ln["text"].strip() for ln in p) for p in pending]
            if authors:
                e["authors"] = authors
            pending = []
            entries.append(e)
        elif _bold(r[0]) and max(s["size"] for s in r[0]["spans"]) >= 11:
            entries.append({"title": " ".join(texts), "printed": None, "number": None, "bold": True, "part": True})
        else:
            pending.append(r)
    if pending and entries:
        entries[-1]["trailing"] = [" ".join(ln["text"].strip() for ln in p) for p in pending]
    return entries


def toc_levels(entries: list[dict]) -> None:
    """Level from section number depth; an unnumbered entry sits one below the last numbered one;
    parts are level 0; front-matter entries before the first number are level 1."""
    last = 0
    for e in entries:
        if e.get("part"):
            e["level"], last = 0, 0
        elif e["number"]:
            last = e["number"].count(".") + 1
            e["level"] = last
        elif e.get("bold"):                  # Preface, Index: bold, unnumbered, at the column edge
            e["level"], last = 1, 0
        else:
            e["level"] = last + 1 if last else 1


# ----------------------------------------------------------------- page kinds


def page_kind(page_no: int, labels: list[tuple[str, str]], first_lines: list[str], running: str,
              seen_chapter: bool) -> tuple[str, str]:
    """labels: (paddle label, text) in order; first_lines: top native lines; running: header text."""
    titles = [t for lab, t in labels if lab in ("doc_title", "paragraph_title")]
    cues = [_norm(t) for t in titles[:2] + first_lines[:2]] + [_norm(running)]
    for c in cues:
        for k, kind in KIND_TITLES.items():
            if c == k or (c.endswith(" " + k) or c.startswith(k + " ")) and len(c) <= len(k) + 12:
                return kind, f"title/running head '{k}'"
    if any(lab == "doc_title" and CHAPTER_TITLE.match(t) for lab, t in labels):
        return "chapter_start", "numbered doc_title"
    alltext = " ".join(t for _, t in labels) + " " + " ".join(first_lines)
    if not seen_chapter:
        if COPYRIGHT.search(alltext):
            return "copyright", "ISBN/©"
        if page_no == 1:
            return "cover", "first page"
        if any(lab == "doc_title" for lab, _ in labels):
            return "title", "doc_title before first chapter"
        if not alltext.strip():
            return "blank", "no text"
        return "front", "before first chapter"
    if not alltext.strip():
        return "blank", "no text"
    return "body", "after first chapter"


# ----------------------------------------------------------------- build


def build(pdf: Path, pages: list[int], layout_dir: Path) -> dict:
    import fitz

    doc = fitz.open(str(pdf))
    fpages = [doc.load_page(n - 1) for n in pages]
    repeated = N.edge_furniture(fpages)
    out_pages: list[dict] = []
    problems: list[dict] = []
    toc: list[dict] = []
    authors: list[dict] = []
    seen_chapter = False
    printed: dict[int, str] = {}
    for n, pg in zip(pages, fpages):
        lay = load_layout(layout_dir, n)
        lines = native_lines(pg)
        if lay is None:
            problems.append({"page": n, "severity": "error", "code": "no_layout",
                             "msg": f"no PaddleOCR layout; run: docstore layout <key> --pages {n}"})
            out_pages.append({"page": n, "kind": None, "blocks": []})
            continue
        pbs = paddle_blocks(lay, pg.rect.width)
        owned, orphans = assign_lines(lines, pbs)
        # furniture: Paddle header/footer/number confirmed by repetition, a folio, or the watermark
        furniture, running = [], ""
        keep: list[tuple[dict, list[dict]]] = []
        for b, lns in zip(pbs, owned):
            plain = _text(lns)[1] if lns else " ".join(b["text"].split())
            sig = signature(plain)
            is_folio = bool(re.fullmatch(r"[ivxlcdm]+|\d+", plain.strip(), re.I))
            if b["label"] in FURNITURE_LABELS and (sig in repeated or is_folio or WATERMARK.match(plain)
                                                   or b["label"] in ("header_image", "footer_image")):
                furniture.append({"label": b["label"], "text": "[watermark]" if WATERMARK.match(plain) else plain})
                if is_folio:
                    printed[n] = plain.strip()
                elif b["label"] == "header" and not WATERMARK.match(plain):
                    running = plain
                continue
            # a one-off header is the byline on a chapter's first page, elsewhere a running head
            if b["label"] == "header" and not any(lab == "doc_title" for lab in (x["label"] for x in pbs)):
                furniture.append({"label": "header", "text": plain})
                running = running or plain
                continue
            if b["label"] in FURNITURE_LABELS and WATERMARK.match(plain):
                furniture.append({"label": b["label"], "text": "[watermark]"})
                continue
            keep.append((b, lns))
        # lines Paddle did not box: watermark / repeated edge lines are furniture, the rest is reported
        for ln in orphans:
            if WATERMARK.match(ln["text"]) or signature(ln["text"]) in repeated:
                continue
            problems.append({"page": n, "severity": "warn", "code": "a_only",
                             "msg": f"native text outside every layout box: {ln['text'][:60]!r}"})
        labels = [(b["label"], _text(lns)[1] if lns else " ".join(b["text"].split())) for b, lns in keep]
        top = [ln["text"] for ln in sorted(lines, key=lambda ln: ln["y0"]) if not WATERMARK.match(ln["text"])
               and signature(ln["text"]) not in repeated][:2]
        kind, why = page_kind(n, labels, top, running, seen_chapter)
        if kind in ("toc", "authors", "index", "preface") and not running:
            pass
        # a page continues the kind of the previous one when only the running head says so
        if kind == "body" and out_pages and out_pages[-1].get("kind") in ("toc", "authors") \
                and _norm(running) in ("", ) and not any(lab == "doc_title" for lab, _ in labels):
            kind, why = out_pages[-1]["kind"], "continues previous page (no running head)"
        if kind == "chapter_start":
            seen_chapter = True
        blocks: list[dict] = []
        # Paddle gives header/footer no reading order: a kept header (the byline) goes first, the rest last
        keep.sort(key=lambda bl: (1 if bl[0]["order"] is not None else (0 if bl[0]["label"] == "header" else 2),
                                  bl[0]["order"] or 0, bl[0]["bbox"][1]))
        for bi, (b, lns) in enumerate(keep):
            blk = _block(n, bi, b, lns, kind, problems)
            blocks.append(blk)
        if kind == "toc":
            es = parse_toc_lines(lines, pg.rect.width)
            for e in es:
                e["page"] = n
            toc.extend(es)
        if kind == "authors":
            blocks = authors_page(blocks, pg.rect.width)
            authors.extend(_authors(blocks))
        _bind_captions(n, blocks, problems)
        out_pages.append({"page": n, "printed": printed.get(n), "kind": kind, "kind_reason": why,
                          "running_head": running, "furniture": furniture, "blocks": blocks})
    toc_levels(toc)
    offset = _offset(printed)
    tree = [{"level": b["level"], "number": b.get("number"), "title": _bare(b["text"]), "page": p["page"]}
            for p in out_pages for b in p["blocks"] if b["role"] == "heading"]
    problems += check_toc(toc, tree, offset, pages)
    problems += check_toc_rules(doc, out_pages, toc)
    kinds: dict[str, int] = {}
    for p in out_pages:
        kinds[str(p["kind"])] = kinds.get(str(p["kind"]), 0) + 1
    summary = {"pages": len(out_pages), "kinds": kinds, "toc_entries": len(toc), "headings": len(tree),
               "authors": len(authors), "tables": sum(1 for p in out_pages for b in p["blocks"] if b["role"] == "table"),
               "errors": sum(1 for x in problems if x["severity"] == "error"),
               "warnings": sum(1 for x in problems if x["severity"] == "warn")}
    return {"schema": SCHEMA, "source": {"pdf": str(pdf), "pages": [pages[0], pages[-1]], "kind": "native"},
            "layout_dir": str(layout_dir), "folio_offset": offset, "pages": out_pages, "toc": toc,
            "tree": tree, "authors": authors, "problems": problems, "summary": summary}


ROLE = {"doc_title": "heading", "paragraph_title": "heading", "text": "body", "abstract": "body",
        "figure_title": "caption", "table": "table", "image": "figure", "chart": "figure",
        "footnote": "footnote", "vision_footnote": "figure_text", "content": "toc_entry",
        "reference_content": "ref", "reference": "ref", "display_formula": "body", "formula": "body",
        "header": "byline", "footer": "footnote", "number": "body", "algorithm": "body"}


def _block(n: int, bi: int, b: dict, lns: list[dict], kind: str, problems: list[dict]) -> dict:
    label = b["label"]
    text, plain, bold = _text(lns) if lns else (" ".join(b["text"].split()),) * 2 + (False,)
    role = ROLE.get(label, "body")
    blk: dict[str, Any] = {"id": f"p{n:04d}-s{bi + 1:02d}", "role": role, "text": text,
                           "src": {"b": label, "bbox": [round(v, 1) for v in b["bbox"]],
                                   "text_from": "native" if lns else "paddle", "lines": len(lns)}}
    if role == "heading":
        m = NUMBERED.match(plain)
        if m:
            blk["number"] = m.group("num")
            blk["level"] = m.group("num").count(".") + 1
        elif label == "doc_title":
            blk["level"] = 1
        else:
            blk["level"] = None   # unnumbered: resolved below by kind
        if kind in ("toc",):
            blk["role"] = "toc_entry"
        elif kind == "authors":
            blk["role"] = "author_name"
        elif kind in ("cover", "title", "front", "copyright", "preface") and label == "paragraph_title" and not m:
            blk["level"] = 2
        elif blk["level"] is None:
            if lns and not bold and len(plain.split()) <= 8 and "," not in plain:
                pass
            # unnumbered sub-heading inside a numbered section: one below the deepest number so far
            blk["level"] = None
        blk["text"] = plain
    if role == "body" and kind == "authors":
        blk["role"] = "author_affil"
        if lns:                       # one printed line per address line; a bold first line is a name
            ol = [ln for ln in _order(lns) if " ".join(ln["text"].split())]
            if len(ol) > 1 and _bold(ol[0]) and not all(_bold(ln) for ln in ol):
                blk["lead_name"] = " ".join(ol.pop(0)["text"].split())
            blk["text"] = "\n".join(" ".join(ln["text"].split()) for ln in ol)
    if role == "toc_entry" or (kind == "toc" and role == "body"):
        blk["role"] = "toc_entry"
    if role == "caption" and PANEL.match(plain or ""):
        blk["role"] = "panel_label"
    if role == "caption" and TABLE_CAP.match(plain or ""):
        blk["caption_of"] = "table"
    if role == "table":
        rows, notes = split_table_notes(table_rows(b["text"]))
        blk["rows"] = rows
        if notes:
            blk["notes"] = notes
        blk["src"]["text_from"] = "paddle"
        blk["text"] = ""
        problems.extend(_table_check(n, rows + [[t] for t in notes], lns))
    if role == "byline" and not lns:
        blk["role"] = "body"
    if lns and not plain.strip() and role not in ("figure", "table"):
        problems.append({"page": n, "severity": "warn", "code": "empty_block", "msg": f"{label} block without text"})
    if not lns and role not in ("figure", "table") and b["text"].strip():
        problems.append({"page": n, "severity": "warn", "code": "b_only",
                         "msg": f"{label} text only from OCR (no native line): {b['text'][:60]!r}"})
    blk["translate"] = blk["role"] not in TRANSLATE_FALSE and not (role == "body" and EMAIL.fullmatch(plain or ""))
    return blk


def _table_check(n: int, rows: list[list[Any]], lns: list[dict]) -> list[dict]:
    if not lns:
        return []
    cell_words = set(_norm(" ".join(cell_text(c) for r in rows for c in r)).split())
    nat = [w for ln in lns for w in _norm(ln["text"]).split() if len(w) > 2]
    if not nat:
        return []
    miss = [w for w in nat if w not in cell_words]
    cov = 1 - len(miss) / len(nat)
    if cov < 0.97:
        return [{"page": n, "severity": "warn" if cov >= 0.9 else "error", "code": "table_text",
                 "msg": f"table cells cover {cov:.0%} of native words; e.g. {miss[:6]}"}]
    return []


def authors_page(blocks: list[dict], page_w: float) -> list[dict]:
    """List-of-authors page: the page title is a heading, not a name; a name the layout model
    merged into the address below it becomes its own block; reading order is column by column,
    top to bottom (the layout model sometimes puts an address above its name)."""
    out: list[dict] = []
    for b in blocks:
        if b["role"] in ("author_name", "heading") and _norm(b["text"]) in KIND_TITLES:
            b["role"], b["level"], b["front_title"] = "heading", 2, True
        if b.get("lead_name"):
            bb = b["src"]["bbox"]
            out.append({"id": b["id"] + "n", "role": "author_name", "text": b.pop("lead_name"),
                        "src": dict(b["src"], bbox=[bb[0], bb[1] - 0.5, bb[2], bb[1]])})
        out.append(b)
    mid = page_w / 2

    def key(b: dict) -> tuple:
        x0, y0, x1 = b["src"]["bbox"][:3]
        return (0 if b["role"] == "heading" else 1, 1 if (x0 + x1) / 2 >= mid else 0, y0)
    return sorted(out, key=key)


def _authors(blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        if b["role"] == "author_name":
            out.append({"name": b["text"], "affiliation": "", "email": ""})
        elif b["role"] == "author_affil" and out:
            t = b["text"]
            em = EMAIL.findall(t)
            out[-1]["email"] = em[-1] if em else out[-1]["email"]
            out[-1]["affiliation"] = (out[-1]["affiliation"] + " " + EMAIL.sub("", t)).strip()
    return out


def _bind_captions(n: int, blocks: list[dict], problems: list[dict]) -> None:
    targets = [b for b in blocks if b["role"] in ("figure", "table")]
    for b in blocks:
        if b["role"] != "caption":
            continue
        want = "table" if b.get("caption_of") == "table" else "figure"
        cand = [t for t in targets if t["role"] == want] or targets
        if not cand:
            problems.append({"page": n, "severity": "warn", "code": "caption_unbound", "msg": b["text"][:60]})
            continue
        cy = (b["src"]["bbox"][1] + b["src"]["bbox"][3]) / 2
        t = min(cand, key=lambda t: abs((t["src"]["bbox"][1] + t["src"]["bbox"][3]) / 2 - cy))
        b["binds"] = t["id"]


def _offset(printed: dict[int, str]) -> int | None:
    diffs = [n - int(p) for n, p in printed.items() if p.isdigit()]
    if not diffs:
        return None
    best = max(set(diffs), key=diffs.count)
    return best


def check_toc(toc: list[dict], tree: list[dict], offset: int | None, pages: list[int]) -> list[dict]:
    """Every contents entry whose page falls in the processed range must be a heading on that page."""
    probs: list[dict] = []
    if not toc or offset is None:
        return probs
    lo, hi = pages[0], pages[-1]
    heads = {(_norm(h["title"]), h["page"]) for h in tree}
    titles: dict[str, list[int]] = {}
    for h in tree:
        titles.setdefault(_norm(h["title"]), []).append(h["page"])
    for e in toc:
        if not (e.get("printed") or "").isdigit():
            continue
        pdfp = int(e["printed"]) + offset
        if not lo <= pdfp <= hi:
            continue
        key = _norm(e["title"])
        ok = any((key, p) in heads for p in (pdfp - 1, pdfp, pdfp + 1)) or \
            any(k.startswith(key) or key.startswith(k) for k, p in heads if abs(p - pdfp) <= 1 and k)
        if not ok:
            probs.append({"page": pdfp, "severity": "error", "code": "toc_no_heading",
                          "msg": f"contents entry {e['title']!r} (p.{e['printed']}) has no heading on PDF p{pdfp}"})
    return probs


def check_toc_rules(doc: Any, pages: list[dict], toc: list[dict]) -> list[dict]:
    """A vs A': entries from native '— N' lines vs booklayout.contents geometry parser."""
    from booklayout.contents import contents_from_pdf_page

    probs: list[dict] = []
    for p in pages:
        if p["kind"] != "toc":
            continue
        mine = {_norm(e["title"]) for e in toc if e["page"] == p["page"]}
        other = {_norm(e.title) for e in contents_from_pdf_page(doc.load_page(p["page"] - 1))}
        if not mine:
            probs.append({"page": p["page"], "severity": "error", "code": "toc_empty", "msg": "contents page, 0 entries"})
            continue
        lost = [t for t in other if t and not t.isdigit() and not any(t in m or m in t for m in mine)]
        if lost:
            probs.append({"page": p["page"], "severity": "warn", "code": "toc_ab",
                          "msg": f"{len(lost)} titles found by contents.py but not here: {lost[:4]}"})
    return probs


def resolve_levels(sd: dict) -> None:
    """Unnumbered headings in body pages: one level below the last numbered heading."""
    last = 1
    for p in sd["pages"]:
        for b in p["blocks"]:
            if b["role"] != "heading":
                continue
            if b.get("level") is None:
                b["level"] = last + 1
                b["level_source"] = "after-number"
            else:
                b.setdefault("level_source", "number" if b.get("number") else "doc_title")
                if b.get("number"):
                    last = b["level"]
    sd["tree"] = [{"level": b["level"], "number": b.get("number"), "title": _bare(b["text"]), "page": p["page"]}
                  for p in sd["pages"] for b in p["blocks"] if b["role"] == "heading"]


# ----------------------------------------------------------------- docstruct -> aligned/2 + meta

FRONT_KINDS = {"cover", "front", "title", "copyright", "authors", "preface", "blank"}
ALIGNED_ROLE = {"heading": "heading", "body": "body", "footnote": "body", "caption": "caption", "ref": "ref",
                "table": "table", "author_affil": "body", "author_name": "entry", "byline": "entry"}


def _toc_text(entries: list[dict]) -> str:
    out = []
    for e in entries:
        head = f"{e['number']} {e['title']}" if e.get("number") else e["title"]
        out.append(f"{head} . . {e['printed']}" if e.get("printed") else head)   # authors stay in the JSON
    return "\n".join(out)


def to_aligned(sd: dict) -> dict:
    """Typesetting input (aligned/2) from the checked structure: page kinds, chapter names, roles,
    table rows, contents lines.  Panel letters and text inside figures stay with the figure image."""
    pages = []
    chapter = ""
    toc_seen = False
    for p in sd["pages"]:
        kind = p.get("kind") or "chapter"
        blocks = []
        if kind == "toc":
            es = [e for e in sd["toc"] if e.get("page") == p["page"]]
            if es and not toc_seen:          # the source prints "Contents" once, above the first page
                blocks.append({"block_id": f"p{p['page']:04d}-toc-h", "role": "heading", "level": 2,
                               "text": "Contents", "front_title": True,
                               "src": {"label": "toc_title"}})
            if es:
                blocks.append({"block_id": f"p{p['page']:04d}-toc", "role": "index", "text": _toc_text(es),
                               "entries": [{k: e[k] for k in ("level", "number", "bold", "part", "authors", "printed")
                                            if e.get(k) is not None} for e in es]})
            toc_seen = True
        for b in p["blocks"]:
            if kind == "toc" or b["role"] not in ALIGNED_ROLE:
                continue
            if b["role"] == "heading" and b.get("level") == 1 and kind in ("chapter_start", "body"):
                chapter = _bare(b["text"])
            nb: dict[str, Any] = {"block_id": b["id"], "role": ALIGNED_ROLE[b["role"]], "text": b["text"],
                                  **({"author": True} if b["role"] in ("author_name", "author_affil") else {}),
                                  "y0": b["src"]["bbox"][1], "src": {"struct": b["id"], "label": b["src"]["b"]}}
            if b.get("level") is not None and nb["role"] == "heading":
                nb["level"] = b["level"]
            if b["role"] == "table":
                nb["rows"] = b.get("rows") or []
            if b.get("front_title"):
                nb["front_title"] = True   # "Contents", "List of contributing authors": source 22 pt
            if b.get("binds"):
                nb["binds"] = b["binds"]
            blocks.append(nb)
            for k, t in enumerate(b.get("notes") or []):
                note: dict[str, Any] = {"block_id": f"{b['id']}-n{k + 1}", "role": "note", "text": t,
                                        "y0": nb["y0"], "src": {"struct": b["id"], "label": "table_note"}}
                blocks.append(note)
        pages.append({"page": p["page"], "columns": 2, "chapter": chapter if kind in ("chapter_start", "body") else "",
                      "kind": "index" if kind == "index" else ("front" if kind in FRONT_KINDS or kind == "toc" else "chapter"),
                      "struct_kind": kind, "blocks": blocks})
    return {"schema": "aligned/2", "source": dict(sd["source"], structure=SCHEMA), "pages": pages}


def meta_from_struct(sd: dict, title: str = "") -> dict:
    """Book metadata from the structure instead of a test-run stub: front-matter pages are typeset
    in place, the source contents pages are printed in place, running heads from the book title and
    chapter names."""
    kinds = {p["page"]: p.get("kind") for p in sd["pages"]}
    titles = [b["text"] for p in sd["pages"] if p.get("kind") == "title" for b in p["blocks"]
              if b["role"] == "heading" and b.get("level") == 1]
    book = title or (titles[-1] if titles else "")
    # The builder skips every page before body_start_page; front pages are printed in place (front_pages),
    # so the book starts at the first page of the range, not at the first chapter page.
    first_body = min(sd["source"]["pages"])
    # cover/title/copyright, contents and author-list pages print no book running head or footer
    # (the source opens each of them bare; MISTAKES H8): footers start at the first other page
    later = [n for n, k in sorted(kinds.items()) if k not in FRONT_KINDS and k != "toc"]
    folio_first = later[0] if later and later[0] > first_body else 0
    return {"folio_first_page": folio_first,"title": book, "volume": "", "running_left": book, "running_right": "",
            "include_front_matter": False, "include_contents": False, "contents_in_place": True,
            "title_page": False, "chapter_headings": True, "body_start_page": first_body,
            "front_pages": sorted(n for n, k in kinds.items() if k in FRONT_KINDS),
            "toc_pages": sorted(n for n, k in kinds.items() if k == "toc"),
            # each front page on a page of its own, and the contents start on a new page
            "own_pages": sorted(n for n, k in kinds.items()
                                if k in FRONT_KINDS or (k == "toc" and kinds.get(n - 1) != "toc"))}


COLORS = {"heading": (0.8, 0, 0), "body": (0, 0, 0.8), "caption": (0, 0.6, 0), "table": (0.8, 0.4, 0),
          "figure": (0.5, 0.5, 0.5), "toc_entry": (0.6, 0, 0.6), "author_name": (0.8, 0, 0.5),
          "author_affil": (0.4, 0.2, 0.6), "byline": (0, 0.6, 0.6), "footnote": (0.4, 0.4, 0)}


def review_images(pdf: Path, sd: dict, out: Path, dpi: int = 60) -> list[Path]:
    """Source page with structure boxes + page kind, for checking against the original side by side."""
    import fitz

    out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    files = []
    for p in sd["pages"]:
        pg = doc.load_page(p["page"] - 1)
        for b in p["blocks"]:
            c = COLORS.get(b["role"], (0.3, 0.3, 0.3))
            r = fitz.Rect(b["src"]["bbox"])
            pg.draw_rect(r, color=c, width=1.2)
            pg.insert_text((r.x0, max(8, r.y0 - 1)), f"{b['role']}{b.get('level') or ''}", fontsize=6, color=c)
        pg.insert_text((10, 12), f"p{p['page']} {p['kind']}", fontsize=10, color=(1, 0, 0))
        f = out / f"p{p['page']:04d}.png"
        pg.get_pixmap(dpi=dpi).save(str(f))
        files.append(f)
    return files


def cmd_struct_native(a: Any) -> int:
    import fitz

    from docstore.probe import parse_pages

    with fitz.open(a.pdf) as d:
        pages = parse_pages(a.pages) if a.pages else list(range(1, len(d) + 1))
    sd = build(Path(a.pdf), pages, Path(a.layout_dir))
    resolve_levels(sd)
    Path(a.out).write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.review:
        review_images(Path(a.pdf), sd, Path(a.review))
    if a.aligned:
        Path(a.aligned).write_text(json.dumps(to_aligned(sd), ensure_ascii=False, indent=1), encoding="utf-8")
    if a.meta:
        Path(a.meta).write_text(json.dumps(meta_from_struct(sd, a.title or ""), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{SCHEMA} -> {a.out} {json.dumps(sd['summary'], ensure_ascii=False)}")
    for p in sd["problems"][:40]:
        print(f"  [{p['severity']}] p{p['page']} {p['code']}: {p['msg']}")
    return 20 if sd["summary"]["errors"] else 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("struct-native", help="native PDF + PaddleOCR layout -> structure JSON (docstruct/1), issue #71")
    p.add_argument("pdf")
    p.add_argument("--layout-dir", required=True, help="<docstore root>/layout/<key> (fill with: docstore layout <key> --pages ...)")
    p.add_argument("--pages", help="e.g. 1-20")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--review", help="dir for source pages with structure boxes (PNG)")
    p.add_argument("--aligned", help="also write the typesetting input (aligned/2) built from the structure")
    p.add_argument("--meta", help="also write book metadata (front pages, contents in place, running heads)")
    p.add_argument("--title", help="book title for running heads (default: the title page)")
    p.set_defaults(func=cmd_struct_native)
