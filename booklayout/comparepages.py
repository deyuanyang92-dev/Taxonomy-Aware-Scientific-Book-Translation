"""`booklayout compare-pages`: source page left, typeset output page right, one PNG per pair.

    booklayout compare-pages SRC.pdf OUT.pdf --pairs 13:1,14:2 --out-dir DIR [--dpi 80] [--stats stats.json]

Pairs are "source page:output page" (1-based).  --stats also writes, per output page, the counts of
control characters (U+0000-001F except tab/LF/CR), U+FFFD, private-use U+E000-F8FF, box glyphs
(U+25A1 / U+25A0 / U+3013) and bare asterisks, taken from the PDF text layer (PyMuPDF).
Used for visual attribution of defects (H2: look at the reference page next to ours before editing code).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_PUA = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")
_BOX = re.compile("[" + chr(0x25A1) + chr(0x25A0) + chr(0x3013) + "]")


def parse_pairs(spec: str) -> list[tuple[int, int]]:
    pairs = []
    for item in spec.split(","):
        a, _, b = item.strip().partition(":")
        if not a or not b:
            raise ValueError(f"bad pair '{item}', want SRC:OUT")
        pairs.append((int(a), int(b)))
    return pairs


def garble_counts(text: str) -> dict[str, int]:
    return {"ctrl": len(_CTRL.findall(text)), "fffd": text.count(chr(0xFFFD)), "pua": len(_PUA.findall(text)),
            "box": len(_BOX.findall(text)), "star": text.count("*")}


def page_stats(pdf: Path) -> list[dict[str, Any]]:
    import fitz
    with fitz.open(str(pdf)) as doc:
        return [{"page": i, **garble_counts(p.get_text())} for i, p in enumerate(doc, 1)]


def compare(src: Path, out: Path, pairs: list[tuple[int, int]], out_dir: Path, dpi: int = 80) -> list[Path]:
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with fitz.open(str(src)) as a, fitz.open(str(out)) as b:
        for sp, op in pairs:
            if not (1 <= sp <= len(a)) or not (1 <= op <= len(b)):
                raise ValueError(f"page out of range: {sp}:{op} (src {len(a)}, out {len(b)} pages)")
            zoom = fitz.Matrix(dpi / 72, dpi / 72)
            pa, pb = a[sp - 1].get_pixmap(matrix=zoom), b[op - 1].get_pixmap(matrix=zoom)
            gap, head = 12, 22
            h = max(pa.height, pb.height) + head
            doc = fitz.open()
            page = doc.new_page(width=pa.width + pb.width + gap, height=h)
            page.draw_rect(page.rect, fill=(1, 1, 1))
            page.insert_text((4, 15), f"source p{sp}", fontsize=11, color=(0.7, 0, 0))
            page.insert_text((pa.width + gap + 4, 15), f"output p{op}", fontsize=11, color=(0, 0, 0.7))
            page.insert_image(fitz.Rect(0, head, pa.width, head + pa.height), pixmap=pa)
            page.insert_image(fitz.Rect(pa.width + gap, head, pa.width + gap + pb.width, head + pb.height), pixmap=pb)
            page.draw_line((pa.width + gap / 2, head), (pa.width + gap / 2, h), color=(0.5, 0.5, 0.5))
            png = out_dir / f"src{sp:03d}_out{op:03d}.png"
            page.get_pixmap(dpi=72).save(str(png))
            doc.close()
            written.append(png)
    return written


def add_parser(sub: Any) -> None:
    p = sub.add_parser("compare-pages", help="side-by-side PNGs: source page left, typeset output page right")
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--pairs", required=True, help="SRC:OUT page pairs, e.g. 13:1,14:2")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--dpi", type=int, default=80)
    p.add_argument("--stats", type=Path, help="write per-output-page garble counts as JSON")

    def run(a: Any) -> int:
        files = compare(a.src, a.out, parse_pairs(a.pairs), a.out_dir, a.dpi)
        for f in files:
            print(f)
        if a.stats:
            a.stats.write_text(json.dumps(page_stats(a.out), ensure_ascii=False, indent=1), encoding="utf-8")
        return 0

    p.set_defaults(func=run)
