"""Taxon-rank classifier for headings whose source level is flat.

Fauna Iberica aligned JSON tags every heading level 2.  With
`StyleProfile.heading_levels == "taxon"` the builder derives the level from the
heading text instead, so the named styles Heading 1-4 give a real hierarchy:

1  Familia / Orden / Clase / APENDICE / Capitulo
2  Subfamilia / Genero
3  species heading (binomial + author, optional "(fig. N)") and "Clave de ..."
4  synonymy or citation line (contains a journal reference "...: 582")
"""
from __future__ import annotations

import re

_RANK1 = re.compile(r"^(Familia|Superfamilia|Orden|Clase|Subclase|Filo|Cap[ií]tulo|AP[EÉ]NDICE|ANEXO|Family|Superfamily|Order|Class|Subclass|Phylum|Chapter|APPENDIX|ANNEX)(?:\s+[A-Z]|\s*$)", re.I)
_RANK2 = re.compile(r"^(Subfamilia|Tribu|G[eé]nero|Subfamily|Tribe|Genus|Subgenus)\s+[A-Z]", re.I)
_KEY = re.compile(r"^(Clave|Key)\b", re.I)
_CITE = re.compile(r"[.,]\s+[A-Z][\w. ]{2,60},?\s+\d+(\(\w+\))?:\s*\d+")


_BINOMIAL = re.compile(r"^[A-Z][a-zæøöüéèáíóúñ-]+ (\([A-Z][a-z]+\) )?[a-z-]{3,}\b")
_FIGREF = re.compile(r"[（(]\s*(?:图|figs?\.)", re.I)


def toc_title(text: str) -> str:
    """Contents text of a heading: its first line, cut after a trailing figure reference."""
    first = " ".join(text.strip().split("\n")[0].split())
    m = re.match(r"^(.*?[（(]\s*(?:图|figs?\.)[^）)]*[）)])\s*\S", first, re.I)
    return m.group(1) if m else first


_ZH2 = re.compile(r"^[A-Z][A-Za-zæøöüéèáíóúñ-]+\s*(?:亚科|族|属)(?![一-鿿])")
_ZH1 = re.compile(r"^[A-Z][A-Za-zæøöüéèáíóúñ-]+\s*(?:超科|科|目|纲|亚纲|门)(?![一-鿿])")
_HEAD_SRC = re.compile(r"^(Familia|Subfamilia|G[eé]nero|Orden|Clase|Tribu)\s+[A-Z]")


def promote_headings(data: dict, max_first: int = 110) -> int:
    """Body blocks that open with a taxon-rank line ("Género X Author, 1887") become headings.

    The aligner tags only some of them; the rest stay body and never reach the
    contents.  The first line becomes a heading block, the remainder (synonymy,
    type species) stays a body block.  Returns the number of headings made.
    """
    n = 0
    for page in data.get("pages", []):
        out: list[dict] = []
        for b in page.get("blocks", []):
            tx = b.get("text") or ""
            if b.get("role") == "body" and _HEAD_SRC.match(tx):
                first, _, rest = tx.partition("\n")
                if len(first) <= max_first and not first.rstrip().endswith((".", ",", ";")) or re.search(r"\d{4}$", first):
                    tr = b.get("translation") or ""
                    tfirst, _, trest = tr.partition("\n")
                    head = dict(b, role="heading", text=first, translation=tfirst or tr, level=2)
                    head.pop("block_id", None)
                    out.append(head)
                    n += 1
                    if rest.strip():
                        out.append(dict(b, text=rest, translation=trest))
                    continue
            out.append(b)
        page["blocks"] = out
    return n


def taxon_level(text: str, default: int = 2) -> int:
    t = " ".join(text.split())
    if _ZH2.match(t):
        return 2
    if _ZH1.match(t):
        return 1
    if _RANK1.match(t):
        return 1
    if _RANK2.match(t):
        return 2
    if _KEY.match(t):
        return 3
    first = text.strip().split("\n")[0]
    if _CITE.search(first):
        # a species heading that carries its first synonym on the same line
        if _BINOMIAL.match(first) and _FIGREF.search(first):
            return 3
        return 4
    if re.match(r"^[A-Z][a-zæøöüéèáíóúñ-]+ (\([A-Z][a-z]+\) )?[a-z-]{3,}\b", first):
        return 3
    return default


_CAP_TEXT = re.compile(r"^\s*(?:Figs?|L[aá]ms?)\.?\s*\d", re.I)
_CAP_TRANS = re.compile(r"^\s*图\s*\d")


_PANEL_LABEL = re.compile(r"^\(?[A-Za-z]\)?[.)]?$")


def stray_label_blocks(data: dict) -> list[dict]:
    """Body blocks that are a lone figure-panel letter ("D", "(E)"): OCR leftovers of a plate."""
    found = []
    for page in data.get("pages", []):
        for b in page.get("blocks", []):
            tx = (b.get("text") or "").strip()
            tr = (b.get("translation") or tx).strip()
            if b.get("role") == "body" and _PANEL_LABEL.match(tx) and _PANEL_LABEL.match(tr):
                found.append({"page": page.get("page"), "text": tx})
    return found


def drop_stray_labels(data: dict) -> int:
    """Remove lone panel-letter body blocks (in memory); returns how many."""
    n = 0
    for page in data.get("pages", []):
        keep: list[dict] = []
        pending = False
        for b in page.get("blocks", []):
            if (b.get("role") == "body" and _PANEL_LABEL.match((b.get("text") or "").strip())
                    and _PANEL_LABEL.match((b.get("translation") or b.get("text") or "").strip())):
                n += 1
                pending = True
                continue
            if pending:
                b["_after_panel"] = True  # may be the caption's tail, split by the plate letters
                pending = False
            keep.append(b)
        page["blocks"] = keep
    return n


def promote_captions(data: dict, max_len: int = 700) -> int:
    """Re-tag body blocks that are figure captions (role body -> caption), in memory.

    The Fauna aligner leaves most captions as plain body blocks, so no figure
    could be paired with them.  Returns the number of blocks changed.
    """
    n = drop_stray_labels(data)
    for page in data.get("pages", []):
        blocks = page.get("blocks", [])
        keep: list[dict] = []
        prev_cap: dict | None = None
        for b in blocks:
            tr, tx = b.get("translation") or "", b.get("text") or ""
            if b.get("role") == "body" and (_CAP_TRANS.match(tr) or _CAP_TEXT.match(tx)) and len(tx) <= max_len:
                b["role"] = "caption"
                n += 1
                prev_cap = b
            elif (prev_cap is not None and b.get("role") == "body"
                  and (b.get("label") == "vision_footnote" or (b.pop("_after_panel", False) and tx[:1].islower()))):
                # the caption's remaining columns/lines: fold into the caption block
                prev_cap["text"] = (prev_cap.get("text") or "") + " " + tx.replace("\n", " ")
                if tr:
                    prev = (prev_cap.get("translation") or "").rstrip()
                    piece = tr.replace("\n", "")
                    glue = "" if (not prev or ord(prev[-1]) >= 0x2E80 or ord(piece[:1] or " ") >= 0x2E80) else " "
                    prev_cap["translation"] = prev + glue + piece
                n += 1
                continue
            else:
                prev_cap = b if b.get("role") == "caption" else None
            keep.append(b)
        page["blocks"] = keep
    promote_headings(data)
    return n
