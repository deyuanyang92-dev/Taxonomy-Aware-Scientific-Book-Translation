"""Recover a paragraph lost at the top of a page.

The OCR-to-aligned step sometimes drops the first block of a page, typically the
tail of a paragraph that began on the previous page ("encontró que están compuestos ...").
Nothing downstream reports it.  "booklayout recover-top" re-reads the cached
Tesseract lines of each source page, finds the lines printed above the first
aligned body block, and inserts them as a new body block (b00r) when the
previous page ends without terminal punctuation and the recovered text starts in
lower case.  Prints every insertion for review.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .sourcecheck import SrcLine, SrcTok, fold

WORD = re.compile(r"[^\W\d_]+", re.U)
TERMINAL = re.compile(r"[.!?:;…)\]\"”»]\s*$")


def _words(s: str) -> list[str]:
    return [fold(w) for w in WORD.findall(s)]


def lines_above(lines: list[SrcLine], first_text: str, min_conf: float = 55.0) -> list[SrcLine]:
    """OCR lines (reading order) before the line where first_text starts; [] if no anchor."""
    want = _words(first_text)[:3]
    if len(want) < 3:
        return []
    for i, ln in enumerate(lines):
        if _words(ln.text)[:3] == want:
            above = lines[:i]
            return above if above and all(a.conf >= min_conf and len(_words(a.text)) >= 3 for a in above) else []
    return []


def join_lines(lines: list[SrcLine]) -> str:
    out = ""
    for ln in lines:
        t = ln.text.strip()
        if out.endswith("-") and out[-2:-1].isalpha():
            out = out[:-1] + t
        else:
            out = (out + " " + t).strip()
    return out


def recover_top(data: dict[str, Any], page_lines: dict[int, list[SrcLine]]) -> list[dict[str, Any]]:
    pages = data["pages"]
    done: list[dict[str, Any]] = []
    prev = None  # last page with body text: plates in between do not break a paragraph
    for cur in pages:
        cb = [b for b in cur["blocks"] if b.get("role") == "body"]
        if not cb:
            continue
        last, prev = prev, cur
        if last is None or cur["page"] not in page_lines:
            continue
        pb = [b for b in last["blocks"] if b.get("role") == "body"]
        if not pb or TERMINAL.search(pb[-1].get("text", "").rstrip()):
            continue
        first = cb[0]
        if first["text"][:1].islower():
            continue  # a continuation block is present
        above = lines_above(page_lines[cur["page"]], first["text"])
        heads = {" ".join(_words(b.get("text", ""))) for b in cur["blocks"] if b.get("role") == "heading"}
        for k, ln in enumerate(above):  # a heading sitting above the first paragraph is not part of the lost text
            if " ".join(_words(ln.text)) in heads:
                above = above[:k]
                break
        text = join_lines(above)
        if not text or not text[:1].islower():
            continue
        blk = {"block_id": f"p{cur['page']:03d}_b00r", "role": "body", "text": text, "translation": text,
               "recovered_from": "ocr_top"}
        cur["blocks"].insert(0, blk)
        done.append({"page": cur["page"], "block_id": blk["block_id"], "text": text})
    return done


def recover_gaps(data: dict[str, Any], page_lines: dict[int, list[SrcLine]], min_lines: int = 2,
                 min_conf: float = 55.0) -> list[dict[str, Any]]:
    """Re-insert runs of OCR lines that no block of the page contains (mid-page loss, e.g. a
    page whose block ids jump b00 -> b03).  A run needs >= min_lines lines, each with >= 3
    words and confidence >= min_conf; it becomes a body block placed by reading order."""
    done: list[dict[str, Any]] = []
    for pg in data["pages"]:
        lines = page_lines.get(pg["page"])
        blocks = pg.get("blocks") or []
        if not lines or not blocks or any(b.get("role") in ("key", "couplet", "index") for b in blocks):
            continue  # keys and indexes are tables: OCR line order is not paragraph order
        blob = " " + " ".join(" ".join(_words(b.get("text", ""))) for b in blocks) + " "
        vocab = set(blob.split())

        def is_covered(ln: SrcLine) -> bool:
            if (" " + " ".join(_words(ln.text)[:3]) + " ") in blob:
                return True
            long_w = [w for w in _words(ln.text) if len(w) >= 5]
            return bool(long_w) and sum(w in vocab for w in long_w) / len(long_w) >= 0.6

        covered = [is_covered(ln) for ln in lines]
        anchors: list[int | None] = []
        for b in blocks:
            head = " ".join(_words(b.get("text", ""))[:4])
            best = max(range(len(lines)), key=lambda i: SequenceMatcher(None, head, " ".join(_words(lines[i].text)[:4])).ratio())
            ok = SequenceMatcher(None, head, " ".join(_words(lines[best].text)[:4])).ratio() >= 0.8
            anchors.append(best if head and ok else None)
        i, runs = 0, []
        while i < len(lines):
            if covered[i]:
                i += 1
                continue
            j = i
            while j < len(lines) and not covered[j]:
                j += 1
                if len(_words(lines[j - 1].text)) < 3:
                    break  # a short line ends a paragraph or caption: split the run there
            run = lines[i:j]
            if len(run) >= min_lines and all(ln.conf >= min_conf for ln in run) \
                    and all(len(_words(ln.text)) >= 3 for ln in run[:-1]):
                runs.append((i, run))
            i = j
        for start, run in runs:
            pos = next((n for n, a in enumerate(anchors) if a is not None and a > start), len(blocks))
            text = join_lines(run)
            prev_blk = blocks[pos - 1] if pos > 0 else {}
            if len(run) <= 4 and (prev_blk.get("role") == "caption" or prev_blk.get("text", "").startswith("Fig.")):
                prev_b = blocks[pos - 1]  # the rest of a legend that the block lost
                prev_b["text"] = prev_b["text"].rstrip() + " " + text
                prev_b["translation"] = prev_b["text"]
                done.append({"page": pg["page"], "block_id": prev_b.get("block_id", ""), "text": text})
                continue
            blk = {"block_id": f"p{pg['page']:03d}_g{start:02d}", "role": "body", "text": text, "translation": text,
                   "recovered_from": "ocr_gap"}
            blocks.insert(pos, blk)
            anchors.insert(pos, start)
            done.append({"page": pg["page"], "block_id": blk["block_id"], "text": text})
    return sorted(done, key=lambda d: d["block_id"])


def add_parser(sub: Any) -> None:
    p = sub.add_parser("recover-top", help="re-insert a paragraph lost at the top of a page (from the source OCR)")
    p.add_argument("--aligned", type=Path, required=True)
    p.add_argument("--source-pdf", type=Path, required=True)
    p.add_argument("--pages", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lang", default="spa")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--furniture", action="append", default=[], help="regex of running-head lines to ignore")
    p.set_defaults(func=run)


def run(args: Any) -> int:
    import hashlib
    import os

    from .sourcecheck import ocr_page, parse_pages, read_tsv

    st = args.source_pdf.stat()
    key = hashlib.sha1(f"{args.source_pdf.resolve()}|{st.st_size}|{st.st_mtime_ns}|{args.lang}|{args.dpi}".encode()).hexdigest()[:16]
    cache = Path(os.environ.get("BOOKLAYOUT_OCR_CACHE", Path.home() / ".cache" / "booklayout" / "ocr")) / key
    cache.mkdir(parents=True, exist_ok=True)
    furn = [re.compile(p) for p in args.furniture] + [re.compile(r"^\W*\d{1,4}\W*$")]
    page_lines: dict[int, list[SrcLine]] = {}
    for pg in parse_pages(args.pages):
        toks: list[SrcTok] = []
        lines: list[SrcLine] = []
        read_tsv(ocr_page(args.source_pdf, pg, cache, args.lang, args.dpi), pg, furn, toks, lines)
        page_lines[pg] = lines
    data = json.loads(args.aligned.read_text(encoding="utf8"))
    done = recover_top(data, page_lines)
    done += recover_gaps(data, page_lines)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    for d in done:
        print(f"p{d['page']}: +{len(d['text'])} chars: {d['text'][:70]}")
    print(f"{len(done)} paragraphs recovered")
    return 0
