"""Family-group names (-oidea, -idae, -inae, -ini) must print roman, not italic.

Genus- and species-group names are italic; names above the genus are not.
The builder enforces it (`add_runs`); this check proves it on the delivered PDF.
"""
from __future__ import annotations

import re

FAMILY_GROUP_RX = re.compile(r"\b[A-Z][a-z]{2,}(?:oidea|idae|inae|ini)\b")


def pdf_italic_family_group(pdf: str) -> list[dict]:
    import fitz

    hits: list[dict] = []
    with fitz.open(pdf) as doc:
        for pno, page in enumerate(doc, 1):
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    for sp in line["spans"]:
                        italic = bool(sp["flags"] & 2) or "italic" in sp["font"].lower() \
                            or "oblique" in sp["font"].lower()
                        if not italic:
                            continue
                        for m in FAMILY_GROUP_RX.finditer(sp["text"]):
                            hits.append({"page": pno, "name": m.group(0)})
    return hits
