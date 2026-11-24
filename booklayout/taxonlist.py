"""Checklist pages: lists of taxon names set as ONE list (Fauna Ibérica Vol. 21 p. 44).

Added 2026-11-25.  Cause of the mixed styles seen in the Vol. 21 draft (pages 35-36):
the aligner labelled some lines of a species checklist `text` and others
`reference_content`; `headings.promote_headings` then made every single-line
binomial that its strict regex matched a bold level-3 heading, while
"Syllis armillaris (O.F. Müller, 1771)" (a dot inside the author) missed the regex
and stayed an indented 10.5 pt body line.  The scanned page is one uniform list.

* `unify_taxon_lists(data)`  - a run of >= MIN_RUN consecutive one-line taxon names
  becomes role `taxon` (rank 0 = rank line "Género X", rank 1 = species line).
* `pdf_list_style_mismatches(pdf)` - independent gate on the rendered PDF: a run of
  >= MIN_RUN consecutive taxon-name lines (page furniture skipped, runs may cross
  pages) must share one (font size, bold) signature.
"""
from __future__ import annotations

import re
from typing import Any

MIN_RUN = 5
_RANK = re.compile(r"^(?:Familia|Subfamilia|G[eé]nero|Subg[eé]nero|Tribu|Orden|Family|Subfamily|Genus|Subgenus)\s+[A-Z][a-zæøöüéèáíóúñ-]+")
_SPECIES = re.compile(
    r"^[A-Z][a-zæøöüéèáíóúñ-]+ (?:\([A-Z][a-z]+\) )?[a-zı-]{3,}(?: [a-zı-]{3,})? \(?[A-ZÁÉÍÓÚÀ-Ü]")
_DATED = re.compile(r"\d{4}|en prensa|in press|nom\. n|comb\. n|sp\. n")
_CITED = re.compile(r"\d{4}[a-z]?\)?[.:;]\s*\S")  # synonymy line with a journal citation: not a list line
MAX_LEN = 100


def taxon_line_rank(text: str) -> int | None:
    """0 for a rank line, 1 for a species line, None for anything else."""
    t = " ".join((text or "").split())
    if not t or len(t) > MAX_LEN or t.count(" ") > 13:
        return None
    if _RANK.match(t):
        return 0
    if _SPECIES.match(t) and _DATED.search(t) and not _CITED.search(t):
        return 1
    return None


def unify_taxon_lists(data: dict[str, Any], min_run: int = MIN_RUN) -> int:
    """Re-tag runs of one-line taxon names as role 'taxon'.  Returns blocks changed."""
    n = 0
    for page in data.get("pages", []):
        blocks = page.get("blocks", [])
        i = 0
        while i < len(blocks):
            j = i
            ranks: list[int] = []
            while j < len(blocks):
                b = blocks[j]
                tx = b.get("text") or b.get("translation") or ""
                one_line = "\n" not in tx.strip()
                r = taxon_line_rank(tx) if b.get("role") in ("body", "ref", "heading", "taxon") and one_line else None
                if r is None and ranks and one_line and b.get("role") in ("body", "ref") and 0 < len(tx.strip()) <= MAX_LEN:
                    nxt = blocks[j + 1] if j + 1 < len(blocks) else {}
                    if taxon_line_rank(nxt.get("text") or "") is not None:
                        r = 1  # one OCR-garbled name inside a list ("cabezalı"): still a list line
                if r is None:
                    break
                ranks.append(r)
                j += 1
            if j - i >= min_run:
                for k, r in zip(range(i, j), ranks):
                    blocks[k]["role"] = "taxon"
                    blocks[k]["rank"] = r
                    blocks[k].pop("level", None)
                    n += 1
                i = j
            else:
                i = max(j, i + 1)
    return n


def pdf_list_style_mismatches(pdf: str, min_run: int = MIN_RUN) -> list[dict]:
    """Runs of taxon-name lines in the PDF whose (size, bold) signature is not uniform."""
    import fitz

    out: list[dict] = []
    run: list[tuple[int, str, tuple[float, bool]]] = []

    def flush() -> None:
        if len(run) >= min_run and len({sig for _, _, sig in run}) > 1:
            sigs: dict[tuple[float, bool], int] = {}
            for _, _, sig in run:
                sigs[sig] = sigs.get(sig, 0) + 1
            major = max(sigs, key=lambda s: sigs[s])
            # head and tail lines that differ are the neighbouring headings, not list lines
            first = next(k for k, (_, _, s) in enumerate(run) if s == major)
            last = max(k for k, (_, _, s) in enumerate(run) if s == major)
            odd = [(pg, tx) for pg, tx, sig in run[first:last + 1] if sig != major]
            if not odd:
                run.clear()
                return
            out.append({"first_page": run[0][0], "lines": len(run),
                        "majority": {"size": major[0], "bold": major[1]},
                        "odd": [{"page": pg, "text": tx[:60]} for pg, tx in odd[:8]]})
        run.clear()

    with fitz.open(pdf) as doc:
        for pno, page in enumerate(doc, 1):
            h = page.rect.height
            for blk in page.get_text("dict")["blocks"]:
                for ln in blk.get("lines", []):
                    if ln["bbox"][1] < 0.07 * h or ln["bbox"][3] > 0.93 * h:
                        continue  # running head / folio
                    spans = [s for s in ln["spans"] if s["text"].strip()]
                    text = "".join(s["text"] for s in spans)
                    rank = taxon_line_rank(text)
                    bold = any((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                    if rank is None or not spans or (rank == 0 and bold):
                        flush()  # a bold "Subfamilia X" / "Género X" is a section heading: it ends the list
                        continue
                    size = round(max(s["size"] for s in spans) * 2) / 2
                    run.append((pno, text, (size, bool(bold))))
    flush()
    return out
