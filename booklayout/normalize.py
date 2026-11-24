"""Deterministic repairs for translation blocks mis-assigned by the page aligner.

The aligner splits a page-level translation blob at source block boundaries.
Two systematic errors survive that split and are fixed here without any model
call:

* a heading absorbs the first line of the citation that follows it (the Latin
  name and year are language-neutral, so the split point is ambiguous);
* a citation absorbs the opening sentence of the species description that
  follows it (again, both are plain prose after the page number).

Three smaller rules remove figure-page artefacts: duplicated captions, blocks
that contain only figure lettering, and abbreviation legends roled as
citations.  Key (identification) pages are re-split from the source line
endings, which the translator preserved as dot leaders.

Every rule is idempotent and records what it changed so the caller can write a
normalization report.
"""
from __future__ import annotations

import re
from typing import Any

_SPACE = re.compile(r"\s+")
_YEAR = re.compile(r"\b(?:1[5-9]\d\d|20\d\d)\b")
_JOURNAL_PAGE = re.compile(r"\b\d+\s*(?:\([^)]*\))?\s*:\s*\d+(?:\s*[-–]\s*\d+)?")
_FIG = re.compile(r"\(\s*(?:fig|ﬁg|lam|pl)[^)]*\)", re.I)
_TAXON_TAIL = re.compile(r"^\*?[A-Z][A-Za-z-]+(?:\s+[A-Za-z().-]+){0,3}\s*\(p\.\s*\d+\)")
_ABBREV = re.compile(r"^Abbreviations?\s*:")
_LETTER_RUN = re.compile(r"(?:\s+\*?[A-Z]{1,2}\*?){4,}\s*$")


def _norm(text: str | None) -> str:
    return _SPACE.sub(" ", text or "").strip()


def _words(text: str) -> list[str]:
    return _norm(text).split()


def _letter_junk(text: str) -> bool:
    """True for blocks that only hold figure lettering (A B C ... sv ld)."""
    tokens = _words(text)
    if len(tokens) < 3:
        return False
    single = sum(1 for tok in tokens if len(re.sub(r"\W", "", tok)) <= 2)
    return single / len(tokens) >= 0.6


def _heading_before(blocks: list[dict], index: int) -> dict | None:
    for j in range(index - 1, max(-1, index - 3), -1):
        if blocks[j].get("role") == "heading":
            return blocks[j]
    return None


def _next_body(blocks: list[dict], index: int) -> dict | None:
    for block in blocks[index + 1:]:
        if block.get("role") == "body":
            return block
    return None


def _citation_anchor(source: str, translation: str) -> re.Match[str] | None:
    """Locate the journal page number that ends the citation in the translation."""
    pages = re.findall(r":\s*(\d+(?:\s*[,–-]\s*\d+)*)", source)
    for page in reversed(pages):
        match = re.search(r":\s*" + re.escape(page) + r"\b", translation)
        if match:
            return match
    figures = re.findall(
        r"(?:fig|figs|pl)\.?\s*(\d+(?:\s*[,–-]\s*\d+)*)\s*$", source, re.I
    )
    for figure in reversed(figures):
        match = re.search(
            r"(?:fig|pl)\.?\s*" + re.escape(figure) + r"\b", translation, re.I
        )
        if match:
            return match
    return None


def _heading_citation_bleed(blocks: list[dict], changed: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if block.get("role") != "heading":
            continue
        citation = next(
            (b for b in blocks[i + 1:i + 3] if b.get("role") == "citation"), None
        )
        if citation is None:
            continue
        head = _norm(block.get("translation"))
        source = _norm(citation.get("text"))
        citation_text = _norm(citation.get("translation"))
        words = head.split()
        for size in range(min(14, len(words) - 1), 2, -1):
            suffix = " ".join(words[-size:])
            if (
                len(suffix) > 8
                and source.lower().startswith(suffix.lower())
                and not citation_text.lower().startswith(suffix.lower())
            ):
                prefix = " ".join(words[:-size]).strip()
                if not re.search(
                    r"\b[A-Z][a-z]{2,}\b", re.sub(
                        r"\b(?:Genus|Subgenus|Family|Subfamily|Order|Suborder)\b",
                        "", prefix,
                    )
                ):
                    continue
                block["translation"] = prefix
                citation["translation"] = (
                    suffix + " " + _norm(citation.get("translation"))
                ).strip()
                changed.append({
                    "rule": "heading_citation_bleed",
                    "block_id": block.get("block_id"),
                    "moved": suffix[:120],
                })
                break


def _heading_figure_ref(blocks: list[dict], changed: list[dict]) -> None:
    """Move a leading (Author, year) (fig. N) of a citation into a short heading."""
    for i, block in enumerate(blocks):
        if block.get("role") != "heading":
            continue
        if re.search(r"\bfig", _norm(block.get("translation")), re.I):
            continue
        if not re.search(r"\bfig", _norm(block.get("text")), re.I):
            continue
        citation = next(
            (b for b in blocks[i + 1:i + 3] if b.get("role") == "citation"), None
        )
        if citation is None:
            continue
        text = _norm(citation.get("translation"))
        match = re.match(r"^\([^)]*\)\s*\(\s*(?:fig|ﬁg)[^)]*\)", text, re.I)
        if not match:
            continue
        prefix = match.group(0).strip()
        block["translation"] = (_norm(block.get("translation")) + " " + prefix).strip()
        citation["translation"] = text[match.end():].strip()
        changed.append({
            "rule": "heading_figure_ref",
            "block_id": block.get("block_id"),
            "moved": prefix,
        })


def _heading_continuation(blocks: list[dict], changed: list[dict]) -> None:
    """Repair a heading split across a line break or overfilled by citation.

    Two shapes survive the aligner:

    * the source heading ends with a comma and the next block starts with the
      rest of the name, the year and the figure reference;
    * the heading translation carries the citation prefix after the figure
      reference, leaving the citation block without its taxon name.
    """
    for i, block in enumerate(blocks):
        if block.get("role") != "heading":
            continue
        source = _norm(block.get("text"))
        head = _norm(block.get("translation"))
        following = blocks[i + 1] if i + 1 < len(blocks) else None
        # Heading cut at a line break.
        if (
            following is not None
            and following.get("role") in ("body", "citation")
            and re.search(r"(?:[,;–-]|\by)\s*$", source)
        ):
            match = re.match(
                r"^(.*?\(\s*(?:fig|ﬁg)\.?\s*\d+[A-Za-z-]*\))\s*(.*)$",
                _norm(following.get("translation")),
                re.I,
            )
            if match is not None:
                continuation = match.group(1)
                block["translation"] = (head + " " + continuation).strip()
                rest = match.group(2).strip()
                citation = next(
                    (b for b in blocks[i + 2:i + 4] if b.get("role") == "citation"),
                    None,
                )
                if rest and citation is not None:
                    cite = _norm(citation.get("translation"))
                    cite_match = re.match(r"^(.+?\b\d{4}[a-z]?\.)\s*(.*)$", rest)
                    if cite_match is not None and not cite.startswith(cite_match.group(1)[:30]):
                        citation["translation"] = (cite_match.group(1) + " " + cite).strip()
                        rest = cite_match.group(2)
                following["translation"] = rest
                if not rest:
                    following["_drop"] = True
                changed.append({
                    "rule": "heading_continuation",
                    "block_id": block.get("block_id"),
                    "moved": continuation,
                })
                continue
        # Heading overfilled with the citation prefix.
        if re.search(r"(?:fig|ﬁg)", source, re.I):
            match = re.match(
                r"^(.*?\(\s*(?:fig|ﬁg)\.?\s*\d+[A-Za-z-]*\))\s+(.+)$", head, re.I
            )
            if match is None:
                continue
            tail = match.group(2).strip()
            citation = next(
                (b for b in blocks[i + 1:i + 3] if b.get("role") == "citation"),
                None,
            )
            if citation is None or not _YEAR.search(tail):
                continue
            block["translation"] = match.group(1)
            citation["translation"] = (
                tail + " " + _norm(citation.get("translation"))
            ).strip()
            changed.append({
                "rule": "heading_citation_tail",
                "block_id": block.get("block_id"),
                "moved": tail[:120],
            })


def _genus_heading_from_citation(blocks: list[dict], changed: list[dict]) -> None:
    """Restore a genus heading whose name was left at the citation's start."""
    for i, block in enumerate(blocks):
        if block.get("role") != "heading":
            continue
        head = _norm(block.get("translation"))
        citation = next(
            (b for b in blocks[i + 1:i + 3] if b.get("role") == "citation"), None
        )
        if citation is None:
            continue
        cite = _norm(citation.get("translation"))
        if not cite:
            continue
        if head in {"Genus", "Subgenus", "Family", "Subfamily"}:
            match = re.match(r"([A-Z][A-Za-zÀ-ÿ-]+)", cite)
            if match is None:
                continue
            again = re.search(
                r"\b" + re.escape(match.group(1)) + r"\b", cite[match.end():]
            )
            if again is None:
                continue
            cut = match.end() + again.start()
            prefix = cite[:cut].strip()
            if len(_words(prefix)) > 12:
                continue
            block["translation"] = (head + " " + prefix).strip()
            citation["translation"] = cite[cut:].strip()
            changed.append({
                "rule": "genus_heading_from_citation",
                "block_id": block.get("block_id"),
                "moved": prefix[:120],
            })
        elif len(cite) > len(head) and cite.startswith(head):
            citation["translation"] = cite[len(head):].lstrip()
            changed.append({
                "rule": "citation_duplicate_heading",
                "block_id": citation.get("block_id"),
                "removed": head[:120],
            })


def _leading_citation_continuation(blocks: list[dict], changed: list[dict]) -> None:
    """Reattach a page-reference or full stop left at the next block's start."""
    for i in range(1, len(blocks)):
        block = blocks[i]
        previous = blocks[i - 1]
        text = _norm(block.get("translation"))
        if not text:
            continue
        match = re.match(r"^,\s*(\d{1,4}(?:\s*,\s*\d{1,4})*)\s+", text)
        if match is not None and previous.get("role") == "citation":
            before = _norm(previous.get("translation")).rstrip(".")
            previous["translation"] = (before + ", " + match.group(1)).strip()
            block["translation"] = text[match.end():].strip()
            changed.append({
                "rule": "citation_page_tail",
                "block_id": block.get("block_id"),
                "moved": match.group(1),
            })
            continue
        match = re.match(
            r"^([A-Z][A-Za-z.]{1,20}\.,?\s+\d{1,4}(?:\(\d+\))?:\s*\d+(?:[-,–]\s*\d+)*)\s+",
            text,
        )
        if match is not None and previous.get("role") == "citation":
            before = _norm(previous.get("translation"))
            previous["translation"] = (before + " " + match.group(1)).strip()
            block["translation"] = text[match.end():].strip()
            changed.append({
                "rule": "citation_journal_tail",
                "block_id": block.get("block_id"),
                "moved": match.group(1),
            })
            continue
        match = re.match(r"^\.\s+", text)
        if match is not None and block.get("role") in ("body", "citation", "key"):
            before = _norm(previous.get("translation"))
            if before and not before.endswith((".", "!", "?")):
                previous["translation"] = before + "."
            block["translation"] = text[match.end():].strip()
            changed.append({
                "rule": "leading_full_stop",
                "block_id": block.get("block_id"),
                "page": block.get("source_page"),
            })


def _figure_ref_body(blocks: list[dict], changed: list[dict]) -> None:
    """Move a figure reference stranded at the next block's start into its heading.

    The aligner sometimes cuts a species heading before its figure reference.
    The next body block then begins "(fig. N)" and repeats the heading name and
    year, which belong to the citation.
    """
    for i, block in enumerate(blocks):
        if block.get("role") != "body":
            continue
        text = _norm(block.get("translation"))
        match = re.match(
            r"^\(\s*(?:fig|ﬁg)\.?\s*(\d+[A-Za-z-]*)\s*\)\s+(.+)$", text, re.I
        )
        if match is None:
            continue
        heading = next(
            (b for b in reversed(blocks[max(0, i - 2):i]) if b.get("role") == "heading"),
            None,
        )
        if heading is None:
            continue
        head = _norm(heading.get("translation"))
        rest = match.group(2).strip()
        if not head or not rest.startswith(head):
            continue
        heading["translation"] = (head + " (fig. " + match.group(1) + ")").strip()
        citation = next(
            (b for b in blocks[i + 1:i + 3] if b.get("role") == "citation"), None
        )
        if citation is not None:
            cite = _norm(citation.get("translation"))
            if not cite.startswith(rest[:20]):
                citation["translation"] = (rest + " " + cite).strip()
        block["_drop"] = True
        changed.append({
            "rule": "figure_ref_body",
            "block_id": block.get("block_id"),
            "moved": match.group(1),
        })


def _citation_name_from_heading(blocks: list[dict], changed: list[dict]) -> None:
    """Restore a citation's taxon name when the heading above kept it twice."""
    for i, block in enumerate(blocks):
        if block.get("role") != "citation":
            continue
        text = _norm(block.get("translation"))
        if _YEAR.search(text):
            continue
        heading = next(
            (b for b in reversed(blocks[max(0, i - 2):i]) if b.get("role") == "heading"),
            None,
        )
        if heading is None:
            continue
        head = _norm(heading.get("translation"))
        match = re.match(
            r"^((?:\(?[A-Z][A-Za-z-]+\)?)(?:\s+[a-z][a-z-]+){0,2}\b.*?\b\d{4}[a-z]?)\.?$",
            head,
        )
        if match is None:
            continue
        name = match.group(1).strip().rstrip(".")
        source = _norm(block.get("text"))
        binomial = " ".join(name.split()[:2])
        if binomial.lower() not in source.lower():
            continue
        block["translation"] = (name + ". " + text).strip()
        changed.append({
            "rule": "citation_name_from_heading",
            "block_id": block.get("block_id"),
            "moved": name[:120],
        })


_SPANISH_HEAD = (
    ("Subfamilia", "Subfamily"),
    ("Subgénero", "Subgenus"),
    ("Subgenero", "Subgenus"),
    ("Familia", "Family"),
    ("Género", "Genus"),
    ("Genero", "Genus"),
    ("Tribu", "Tribe"),
    ("Apéndice", "Appendix"),
    ("APÉNDICE", "APPENDIX"),
    ("Nomenclatura", "Nomenclature"),
    ("NOMENCLATURA", "NOMENCLATURE"),
    ("Lista de sinónimos", "List of synonyms"),
    ("LISTA DE SINÓNIMOS", "LIST OF SYNONYMS"),
)

# Status phrases printed in the Spanish synonym list.  They sit inside
# parentheses after a language-neutral citation, so the aligner often left
# them untranslated while the citation itself came through correctly.
_APPENDIX_TERMS = (
    ("grafía original alternativa incorrecta", "incorrect alternative original spelling"),
    ("grafía posterior incorrecta", "incorrect subsequent spelling"),
    ("grafía original incorrecta", "incorrect original spelling"),
    (
        "colocado en la Lista Oficial de Nombres de Nivel Género",
        "placed on the Official List of Names at Genus Level",
    ),
    (
        "colocado en la Lista Oficial de Nombres de Nivel Especie",
        "placed on the Official List of Names at Species Level",
    ),
    ("Lista Oficial de Nombres de Nivel Género", "Official List of Names at Genus Level"),
    ("Lista Oficial de Nombres de Nivel Especie", "Official List of Names at Species Level"),
    ("Índice Oficial de Nombres de Nivel Género", "Official Index of Names at Genus Level"),
    ("Índice Oficial de Nombres de Nivel Especie", "Official Index of Names at Species Level"),
    # A page break can cut the phrase right after "Oficial de".
    ("Oficial de Nombres de Nivel Género", "Official Index of Names at Genus Level"),
    ("Oficial de Nombres de Nivel Especie", "Official Index of Names at Species Level"),
    ("nombre de reemplazo injustificado", "unjustified replacement name"),
    ("nombre de reemplazo", "replacement name"),
    ("no disponible", "not available"),
    ("no publicado", "unpublished"),
    ("obra suprimida", "work suppressed"),
    ("por designación presente", "by present designation"),
    ("Clave de especies", "Key to species"),
    ("modificada de", "modified from"),
    ("Especie Tipo", "Type species"),
    (
        "Solo se incluyen las denominaciones científicas de Polychaeta "
        "íbero-baleares comprendidas en este tomo.",
        "Only the scientific names of Ibero-Balearic Polychaeta covered "
        "in this volume are included.",
    ),
)

# The aligner sometimes marks the first two words of the intro as italic,
# which defeats the literal replacement above.
_INTRO_RE = re.compile(
    r"\*?Solo se\*?\s+incluyen las denominaciones cient[íi]ficas de Polychaeta "
    r"[íi]bero-baleares comprendidas en este tomo\.",
    re.I,
)


# First words of a wrapped status phrase, never a taxon name.
_ENTRY_STOP_WORDS = frozenset({
    "Oficial", "Índice", "Indice", "Lista", "Nombres", "Nombre", "Clave",
    "Especie", "Género", "Genero", "Apéndice", "Solo", "Non", "Nec",
    # After _source_convert the same phrases start in English.
    "Official", "Index", "List", "Names", "Key", "Only", "Type", "Species",
})


def _source_convert(text: str) -> str:
    """Turn a source heading/citation into its English form.

    Latin names, authors, years, journals and volume:page numbers are
    language-neutral, so only a handful of Spanish structural words and the
    ligatures need converting.
    """
    value = _norm(text).replace("ﬁ", "fi").replace("ﬂ", "fl")
    # Longest, most specific phrases first: _SPANISH_HEAD rewrites the rank
    # words ("Género", "Especie") that the status phrases below contain.
    for spanish, english in _APPENDIX_TERMS:
        value = value.replace(spanish, english)
    for spanish, english in _SPANISH_HEAD:
        value = re.sub(rf"\b{spanish}\b", english, value)
    value = re.sub(r"\bEspecie [Tt]ipo\b", "Type species", value)
    value = re.sub(r"\bEn:\s*", "In: ", value)
    value = re.sub(r"\by\b", "and", value)
    return value


def _source_entry(text: str) -> str:
    """Convert one synonym-list line and italicize its leading taxon name."""
    value = _source_convert(text)
    if value.startswith("*"):
        return value
    match = re.match(
        r"^(?:\?\s*)?([A-Z][A-Za-zÀ-ÿ-]+)(?: ([a-z][A-Za-zÀ-ÿ-]+))?", value
    )
    if match is None:
        return value
    # A wrapped status phrase ("Oficial de Nombres...") is not a taxon name.
    if match.group(1) in _ENTRY_STOP_WORDS:
        return value
    name = match.group(1)
    if match.group(2) is not None:
        name = name + " " + match.group(2)
    # A leading "?" marks a doubtful record; it stays upright.
    mark = "? " if match.group(0).startswith("?") else ""
    return mark + "*" + name + "*" + value[len(match.group(0)):]


def _heading_from_source(block: dict, changed: list[dict]) -> None:
    """Restore a heading whose authority or year the aligner truncated."""
    source = _norm(block.get("text"))
    translation = _norm(block.get("translation"))
    if block.get("role") != "heading" or not source:
        return
    if not _YEAR.search(source) or _YEAR.search(translation):
        return
    repaired = _source_convert(source)
    if repaired != translation:
        block["translation"] = repaired
        changed.append({
            "rule": "heading_year_source",
            "block_id": block.get("block_id"),
        })


def _latin_token(source: str) -> str | None:
    """A token that a correct translation of this heading must contain."""
    upper = re.search(r"\b[A-ZÁÉÍÓÚ]{5,}\b", source)
    if upper is not None:
        return upper.group(0)
    binomial = re.search(r"\b[A-Z][a-z]+\s+([a-z]{3,})\b", source)
    if binomial is not None:
        return binomial.group(1)
    return None


def _duplicated_elsewhere(blocks: list[dict], block: dict, text: str) -> bool:
    value = _norm(text)
    if len(value) < 20:
        return False
    return any(
        value in _norm(other.get("translation"))
        for other in blocks
        if other is not block and len(_norm(other.get("translation"))) > len(value)
    )


def _structured_from_source(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Rebuild self-describing blocks from their source text.

    A heading, citation or contents entry carries its own evidence (Latin
    names, authors, years, journal volume:page).  When the aligned translation
    of such a block is a stray key line or a neighbouring paragraph, the source
    text yields the correct English string without a model.
    """
    for block in blocks:
        role = block.get("role")
        source = _norm(block.get("text"))
        translation = _norm(block.get("translation"))
        if not source:
            continue
        repaired: str | None = None
        if role == "heading":
            structural = re.match(
                r"^(?:Familia|Género|Genero|Subfamilia|Subgénero|Subgenero|Tribu|"
                r"Apéndice|APÉNDICE)\b",
                source,
            )
            token = _latin_token(source)
            contaminated = bool(re.search(r"(?:\.\s*){3,}|…", translation))
            missing = token is not None and token not in translation
            duplicated = _duplicated_elsewhere(blocks, block, translation)
            if structural or contaminated or (missing and duplicated):
                repaired = _source_convert(source)
        elif role == "citation":
            year = re.search(r"\b(?:1[6-9]\d\d|20\d\d)\b", source)
            leader = bool(re.search(r"(?:\.\s*){3,}|…", translation))
            if year is not None and leader:
                repaired = _source_convert(source)
        elif role == "entry":
            # Appendix entries belong to _appendix_entries: rebuilding them
            # here would split off the wrapped tails it has already joined.
            if page.get("kind") == "appendix":
                continue
            genus_line = re.match(r"^(?:Género|Genero|Genus)\s+(\S+)", source)
            species_line = re.match(r"^[A-Z][A-Za-z-]+\s+[a-z][A-Za-z-]+\s", source)
            if genus_line is not None:
                rest = re.sub(r"^(?:Género|Genero|Genus)\s+\S+\s*", "", source)
                repaired = f"Genus *{genus_line.group(1)}* {rest}".strip()
            elif species_line is not None:
                parts = source.split()
                rest = " ".join(parts[2:])
                repaired = f"*{parts[0]} {parts[1]}* {rest}".strip()
            # A translated entry keeps its Spanish status parenthetical
            # ("(grafía posterior incorrecta)"), which makes it longer than
            # the source line.  Rebuilding from source would silently drop
            # that phrase before _appendix_terms can translate it.
            keep = translation.startswith("*") or translation.startswith("Genus *")
            if (
                repaired is not None
                and keep
                and len(translation) <= 2.5 * max(len(source), 1)
            ):
                repaired = None
        if repaired is not None and _norm(repaired) != translation:
            block["translation"] = repaired
            changed.append(
                {
                    "rule": "structured_from_source",
                    "block_id": block.get("block_id"),
                    "role": role,
                }
            )


def _heading_tail_merge(blocks: list[dict], changed: list[dict]) -> None:
    """Join a book title split over two heading blocks.

    The source prints "APÉNDICE 1. ..." and "Y COMBINACIONES" on separate
    lines, and the aligner keeps both as headings.  The second line is the
    continuation of the first, not a heading of its own.
    """
    kept: list[dict] = []
    for block in blocks:
        head = _norm(block.get("translation"))
        previous = kept[-1] if kept else None
        if (
            previous is not None
            and block.get("role") == "heading"
            and previous.get("role") == "heading"
            and re.match(r"^(?:AND|OR|Y|E)\b", head, re.I)
            and len(_norm(previous.get("translation"))) + len(head) <= 160
        ):
            previous["translation"] = (
                _norm(previous.get("translation")) + " " + head
            ).strip()
            changed.append({
                "rule": "heading_tail_merge",
                "block_id": block.get("block_id"),
                "into": previous.get("block_id"),
            })
            continue
        kept.append(block)
    blocks[:] = kept


def _heading_bleed_previous(blocks: list[dict], changed: list[dict]) -> None:
    """Remove a heading duplicated at the end of the preceding entry.

    The aligner sometimes gives the last citation line the following
    heading's text as well, so "175: 31 Genus Acromegalomma ..." prints the
    heading twice.
    """
    for i in range(len(blocks) - 1):
        block = blocks[i]
        heading = blocks[i + 1]
        if block.get("role") not in ("entry", "citation", "body"):
            continue
        if heading.get("role") != "heading":
            continue
        translation = _norm(block.get("translation"))
        candidates = [
            _norm(heading.get("translation")),
            _source_convert(heading.get("text") or ""),
        ]
        for expected in candidates:
            if len(expected) < 12 or len(translation) <= len(expected):
                continue
            if translation.endswith(expected):
                block["translation"] = translation[: -len(expected)].strip()
                changed.append({
                    "rule": "heading_bleed_previous",
                    "block_id": block.get("block_id"),
                    "removed": expected[:120],
                })
                break
            plain_expected = expected.replace("*", "")
            if not translation.replace("*", "").endswith(plain_expected):
                continue
            words = translation.split()
            count = len(plain_expected.split())
            if count < len(words):
                block["translation"] = " ".join(words[:-count]).strip()
                changed.append({
                    "rule": "heading_bleed_previous",
                    "block_id": block.get("block_id"),
                    "removed": expected[:120],
                })
                break
        # The aligner also drops only the heading's rank word ("Genus",
        # "Subfamily") at the end of the entry above it.
        rank = re.match(r"^(Genus|Subgenus|Family|Subfamily|Tribe)\b", candidates[1])
        if rank is not None and _norm(block.get("translation")).endswith(
            " " + rank.group(1)
        ):
            block["translation"] = (
                _norm(block.get("translation"))[: -len(rank.group(1))]
            ).strip()
            changed.append({
                "rule": "heading_bleed_previous",
                "block_id": block.get("block_id"),
                "removed": rank.group(1),
            })


def _entry_prefix_duplicate(blocks: list[dict], changed: list[dict]) -> None:
    """Drop a name and year repeated at the start of the same entry."""
    for block in blocks:
        if block.get("role") not in ("entry", "citation"):
            continue
        text = _norm(block.get("translation"))
        match = re.match(r"^(\S+(?:\s+\S+){1,12}?)\s+\1(?=[\s.,])", text)
        if match is None:
            continue
        block["translation"] = (match.group(1) + text[match.end():]).strip()
        changed.append({
            "rule": "entry_prefix_duplicate",
            "block_id": block.get("block_id"),
            "removed": match.group(1)[:120],
        })


def _appendix_entries(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Fill or reattach synonym-list entries the aligner left empty.

    Appendix entries are citations, so an empty translation is usually
    language-neutral text that the aligner dropped.  A fragment that starts
    with a parenthesis, a bracket or a lower-case word continues the entry
    above it; a complete citation line stands on its own.
    """
    if page.get("kind") != "appendix":
        return
    kept: list[dict] = []
    for block in blocks:
        role = block.get("role")
        source = _norm(block.get("text"))
        translation = _norm(block.get("translation"))
        if role in ("entry", "citation") and translation and source:
            # A wrapped tail of the previous entry: the aligner paired it
            # with a stale translated line, but its content already sits
            # inside the entry above.
            previous = kept[-1] if kept else None
            if previous is not None and previous.get("role") in ("entry", "citation"):
                previous_text = _norm(previous.get("translation")).replace("*", "")
                plain = _source_convert(source).replace("*", "")
                if len(plain) >= 20 and plain in previous_text:
                    changed.append({
                        "rule": "appendix_entry_wrap_duplicate",
                        "block_id": block.get("block_id"),
                    })
                    continue
                fragment = bool(
                    re.match(
                        r"^(?:\(|\[|[a-záéíóúñ]|suprimida\b|Oficial de\b|"
                        r"Nombres de\b|y\b|e\b|o\b|u\b)",
                        source,
                    )
                )
                stale = (
                    not _YEAR.search(translation)
                    or len(translation) < 0.4 * len(_source_entry(source))
                )
                if fragment and stale:
                    appended = _source_entry(source)
                    previous_text = _norm(previous.get("translation"))
                    plain_appended = appended.replace("*", "")
                    tail = " ".join(plain_appended.split()[1:])
                    already = plain_appended in previous_text or (
                        len(tail) >= 20 and tail in previous_text.replace("*", "")
                    )
                    if already:
                        changed.append({
                            "rule": "appendix_entry_join_duplicate",
                            "block_id": block.get("block_id"),
                        })
                        continue
                    previous["translation"] = (
                        previous_text + " " + appended
                    ).strip()
                    changed.append({
                        "rule": "appendix_entry_join",
                        "block_id": block.get("block_id"),
                        "into": previous.get("block_id"),
                    })
                    continue
        if role in ("entry", "citation") and translation and source:
            # The aligner attached a neighbouring entry's line, usually the
            # genus line above or the species line below.  A citation keeps
            # every year of its source, so a missing year plus a much
            # shorter line identifies the stale pairing.
            fragment = bool(re.match(r"^(?:\(|\[|[a-záéíóúñ])", source))
            if not fragment:
                converted = _source_entry(source)
                source_years = _YEAR.findall(source)
                kept_years = set(_YEAR.findall(translation))
                stale = (
                    source_years
                    and any(year not in kept_years for year in source_years)
                ) or len(translation) < 0.5 * len(converted)
                if stale and len(translation) < 0.7 * len(converted):
                    block["translation"] = converted
                    translation = _norm(converted)
                    changed.append({
                        "rule": "appendix_entry_stale",
                        "block_id": block.get("block_id"),
                    })
            # A stale page tail can also sit at the start of a good line.
            tail_match = re.match(r"^:\s*\d{1,4}\s*", translation)
            if tail_match is not None:
                block["translation"] = translation[tail_match.end():].strip()
                translation = _norm(block.get("translation"))
                changed.append({
                    "rule": "appendix_entry_leading_tail",
                    "block_id": block.get("block_id"),
                })
            # Removing the shifted prefix or tail can leave only the scrap of
            # the previous entry; rebuild from this entry's own source.
            converted = _source_entry(source)
            if not translation or len(translation) < 0.7 * len(converted):
                block["translation"] = converted
                translation = _norm(converted)
                changed.append({
                    "rule": "appendix_entry_stale",
                    "block_id": block.get("block_id"),
                })
        if role in ("entry", "citation") and translation and kept:
            # The stale pairing often prepends the previous entry's whole
            # line to the current one; drop the duplicated prefix.
            previous = kept[-1]
            previous_source = _norm(previous.get("text"))
            if previous.get("role") in ("entry", "citation") and previous_source:
                prefix = _source_entry(previous_source).replace("*", "")
                plain = _norm(block.get("translation")).replace("*", "")
                # The master may translate the status parenthetical
                # differently ("unavailable" vs "not available"), so the
                # citation core up to the parenthesis is the stable prefix.
                core = prefix.split("(")[0].strip()
                if len(core) >= 30 and plain.startswith(core):
                    end = plain.find(")", len(core))
                    cut = end + 1 if end != -1 else len(core)
                    block["translation"] = plain[cut:].lstrip(" .;,")
                    translation = _norm(block.get("translation"))
                    changed.append({
                        "rule": "appendix_entry_prefix_shift",
                        "block_id": block.get("block_id"),
                    })
                    # The trimmed remainder is often the previous entry's
                    # page tail; rebuild this entry from its own source.
                    retrim = re.match(r"^:\s*\d{1,4}\s*", translation)
                    if retrim is not None:
                        block["translation"] = translation[retrim.end():].strip()
                        translation = _norm(block.get("translation"))
                    converted = _source_entry(source)
                    if len(translation) < 0.7 * len(converted):
                        block["translation"] = converted
                        translation = _norm(converted)
                        changed.append({
                            "rule": "appendix_entry_stale",
                            "block_id": block.get("block_id"),
                        })
                    else:
                        # The remainder is this entry's own line; restore the
                        # italic taxon name the plain-text trim dropped.
                        block["translation"] = _source_entry(translation)
                        translation = _norm(block.get("translation"))
        if role in ("entry", "citation") and not translation and source:
            previous = kept[-1] if kept else None
            if previous is not None and previous.get("role") in ("entry", "citation"):
                previous_source = _norm(previous.get("text"))
                previous_text = _norm(previous.get("translation"))
                duplicate = (
                    source.lower() == previous_source.lower()
                    or previous_source.lower().endswith(source.lower())
                )
                if duplicate and _source_entry(source) in previous_text:
                    changed.append({
                        "rule": "appendix_entry_duplicate",
                        "block_id": block.get("block_id"),
                    })
                    continue
                continuation = bool(
                    re.match(
                        r"^(?:\(|\[|[a-záéíóúñ]|suprimida\b|Oficial de\b|"
                        r"Nombres de\b|y\b|e\b|o\b|u\b)",
                        source,
                    )
                )
                if continuation:
                    appended = _source_entry(source)
                    plain_appended = appended.replace("*", "")
                    tail = " ".join(plain_appended.split()[1:])
                    previous_plain = previous_text.replace("*", "")
                    if plain_appended in previous_text or (
                        len(tail) >= 20 and tail in previous_plain
                    ):
                        changed.append({
                            "rule": "appendix_entry_join_duplicate",
                            "block_id": block.get("block_id"),
                        })
                        continue
                    previous["translation"] = (
                        previous_text + " " + appended
                    ).strip()
                    changed.append({
                        "rule": "appendix_entry_join",
                        "block_id": block.get("block_id"),
                        "into": previous.get("block_id"),
                    })
                    continue
            converted = _source_entry(source)
            if previous is not None and previous.get("role") in ("entry", "citation"):
                # The entry above can end with the opening words of this one,
                # copied there by the aligner.  The source of this block is
                # authoritative, so drop that trailing copy first.
                previous_plain = _norm(previous.get("translation")).replace("*", "")
                for size in range(min(len(converted.replace("*", "")), 120), 12, -1):
                    if previous_plain.endswith(converted.replace("*", "")[:size]):
                        previous["translation"] = previous_plain[: -size].rstrip()
                        changed.append({
                            "rule": "appendix_entry_next_bleed",
                            "block_id": previous.get("block_id"),
                            "removed": converted[:size][:80],
                        })
                        break
            block["translation"] = converted
            changed.append({
                "rule": "appendix_entry_fill",
                "block_id": block.get("block_id"),
            })
        kept.append(block)
    blocks[:] = kept


def _appendix_terms(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Translate the Spanish status phrases inside synonym-list entries."""
    if page.get("kind") != "appendix":
        return
    for block in blocks:
        if block.get("role") in ("index", "ref"):
            continue
        text = _norm(block.get("translation")).replace("ﬁ", "fi").replace("ﬂ", "fl")
        if not text:
            continue
        repaired = text
        for spanish, english in _APPENDIX_TERMS:
            repaired = repaired.replace(spanish, english)
        repaired = _INTRO_RE.sub(
            "Only the scientific names of Ibero-Balearic Polychaeta covered "
            "in this volume are included.",
            repaired,
        )
        repaired = re.sub(r"\bEn:\s*", "In: ", repaired)
        if repaired != text:
            block["translation"] = repaired
            changed.append({
                "rule": "appendix_terms",
                "block_id": block.get("block_id"),
            })


def _key_leading_target(blocks: list[dict], changed: list[dict]) -> None:
    """Drop a previous couplet's target left at the start of a key line."""
    for block in blocks:
        if block.get("role") != "key":
            continue
        text = _norm(block.get("translation"))
        match = re.match(r"^.{0,120}?\(p\.\s*\d+\)\s*(?=•\s)", text)
        if match is not None:
            block["translation"] = text[match.end():].strip()
            changed.append(
                {"rule": "key_leading_target", "block_id": block.get("block_id")}
            )


def _function_word_join(blocks: list[dict], changed: list[dict]) -> None:
    """Repair a function word duplicated or mispaired by a page-break join.

    The translated master cuts sentences at the source page boundary, so a
    phrase like "ending posteriorly in" + "with a short pointed end" becomes
    "in with" when the aligner joins the pages.  Both shapes are ungrammatical
    and come from the join, not from the content.
    """
    doubled = re.compile(r"\b(in|of|to|for|by|with|on|at|the)\s+\1\b", re.I)
    stray = re.compile(r"\b(?:in|of|to|for|by|on|at)\s+(with)\b", re.I)
    for block in blocks:
        text = _norm(block.get("translation"))
        repaired = doubled.sub(r"\1", text)
        repaired = stray.sub(r"\1", repaired)
        if repaired != text:
            block["translation"] = repaired
            changed.append(
                {"rule": "function_word_join", "block_id": block.get("block_id")}
            )


def _leading_punctuation(blocks: list[dict], changed: list[dict]) -> None:
    """Repair punctuation left at the start of a block by a page-break split."""
    for index, block in enumerate(blocks):
        if block.get("role") not in ("body", "note", "key", "entry", "citation"):
            continue
        text = _norm(block.get("translation"))
        match = re.match(r"^([.,;:)])\s+", text)
        if match is None:
            continue
        if match.group(1) == ")" and index > 0:
            previous = blocks[index - 1]
            before = _norm(previous.get("translation"))
            if before and not before.endswith(")"):
                previous["translation"] = before + ")"
        elif not text[match.end():][:1].isupper():
            continue
        block["translation"] = text[match.end():].strip()
        changed.append(
            {"rule": "leading_punctuation", "block_id": block.get("block_id")}
        )


def _citation_body_bleed(blocks: list[dict], changed: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if block.get("role") != "citation":
            continue
        text = _norm(block.get("translation"))
        anchor = _citation_anchor(_norm(block.get("text")), text)
        if anchor is None:
            continue
        tail = text[anchor.end():].strip()
        if not tail:
            continue
        if re.match(
            r"^\.?\s*(?:Type species|TYPE SPECIES|Especie tipo|Figure|Fig\.|pl\.|=|\*)",
            tail,
            re.I,
        ):
            continue
        if not _words(tail):
            continue
        target = _next_body(blocks, i)
        if target is None:
            continue
        current = _norm(target.get("translation"))
        if current.startswith(tail[:40]):
            block["translation"] = text[:anchor.end()].strip()
            continue
        target["translation"] = (tail + " " + current).strip()
        block["translation"] = text[:anchor.end()].strip()
        changed.append({
            "rule": "citation_body_bleed",
            "block_id": block.get("block_id"),
            "moved": tail[:120],
        })


def _caption_duplicate(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if block.get("role") != "citation":
            continue
        text = _norm(block.get("translation"))
        if not re.match(r"^Fig\.\s*\d", text):
            continue
        following = next(
            (b for b in blocks[i + 1:i + 3] if b.get("role") == "caption"), None
        )
        if following is None:
            continue
        caption = _norm(following.get("translation"))
        if text[:60].lower() == caption[:60].lower():
            block["_drop"] = True
            changed.append({
                "rule": "caption_duplicate",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })


def _abbreviation_note(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if block.get("role") != "citation":
            continue
        text = _norm(block.get("translation"))
        if not _ABBREV.match(text):
            continue
        cleaned = _LETTER_RUN.sub("", text).strip()
        block["role"] = "note"
        block["translation"] = cleaned
        # The legend belongs under the caption, not above it.
        if i + 1 < len(blocks) and blocks[i + 1].get("role") == "caption":
            blocks[i], blocks[i + 1] = blocks[i + 1], blocks[i]
        changed.append({
            "rule": "abbreviation_note",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
        })


def _remove_figure_junk(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    for block in blocks:
        if block.get("role") != "citation":
            continue
        source = _norm(block.get("text"))
        text = _norm(block.get("translation"))
        # A block whose source carries a journal volume:page is a real
        # citation even when its translation is still short.
        if _JOURNAL_PAGE.search(source):
            continue
        if _letter_junk(text):
            block["_drop"] = True
            changed.append({
                "rule": "figure_letter_junk",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })
            continue
        if len(_words(text)) < 3:
            block["_drop"] = True
            changed.append({
                "rule": "empty_fragment",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })


def _citation_role_body(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """A 'citation' with no bibliographic data is prose the aligner mis-roled."""
    if page.get("kind") == "front":
        return
    for i, block in enumerate(blocks):
        if block.get("role") != "citation" or block.get("_drop"):
            continue
        source = _norm(block.get("text"))
        text = _norm(block.get("translation"))
        # Without source text the rule cannot tell a real citation from prose;
        # blocks rebuilt by a page patch carry no `text` until backfilled.
        if not source:
            continue
        if _YEAR.search(source) or _JOURNAL_PAGE.search(source):
            continue
        if _ABBREV.match(text) or _letter_junk(text):
            continue
        if i > 0 and blocks[i - 1].get("role") == "body" and len(_words(text)) < 10:
            previous = blocks[i - 1]
            previous["translation"] = (
                _norm(previous.get("translation")) + " " + text
            ).strip()
            block["_drop"] = True
            changed.append({
                "rule": "citation_fragment_merged",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })
        elif len(_words(text)) >= 10:
            block["role"] = "body"
            changed.append({
                "rule": "citation_role_body",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })


def _type_species_tail(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if block.get("role") != "citation":
            continue
        text = _norm(block.get("translation"))
        if not re.search(r"(?:Type species|TYPE SPECIES|Especie tipo)\s*:?\s*$", text, re.I):
            continue
        target = _next_body(blocks, i)
        if target is None:
            continue
        body = _norm(target.get("translation"))
        sentence = re.match(r"^(.+?\.)\s", body)
        if sentence is not None and len(_words(sentence.group(1))) <= 14:
            moved = sentence.group(1)
            rest = body[sentence.end():]
        else:
            stop = re.search(
                r"\s+(?:Prostomium|Body|Includes|Species|Head|Anterior|Posterior|"
                r"Eyes|Peristomium|Pygidium|Setigers?|Parapodi|No\b|All\b|Length|"
                r"Small|Large|Specimens|Known|Description|The\b|This\b)",
                body,
            )
            if stop is None or stop.start() < 8:
                continue
            moved = body[:stop.start()].strip()
            rest = body[stop.start():].strip()
        if not re.search(r"\b(?:1[5-9]\d\d|20\d\d)\b", moved):
            continue
        block["translation"] = (text + " " + moved).strip()
        target["translation"] = rest
        changed.append({
            "rule": "type_species_tail",
            "block_id": block.get("block_id"),
            "moved": moved[:120],
        })


def _type_species_equals_tail(blocks: list[dict], changed: list[dict]) -> None:
    """Move a leading '= valid combination' back onto the type-species line.

    The aligner sometimes starts the description block at the equal sign of
    the type-species synonymy.  Printed as body it reads as an indented
    paragraph beginning with '='; the tail belongs to the citation above it.
    """
    for i in range(1, len(blocks)):
        block = blocks[i]
        prev = blocks[i - 1]
        if block.get("role") != "body" or prev.get("role") != "citation":
            continue
        citation = _norm(prev.get("translation"))
        if not re.search(r"(?:Type species|TYPE SPECIES|Especie tipo)", citation, re.I):
            continue
        text = _norm(block.get("translation"))
        match = re.match(r"^=\s*(.+?\([^)]*?\b\d{4}[a-z]?\))\s+(\S.*)$", text)
        if match is None:
            continue
        rest = match.group(2)
        if not (rest[:1].isupper() or rest[:1] in "(["):
            continue
        prev["translation"] = (citation + " = " + match.group(1)).strip()
        block["translation"] = rest
        changed.append({
            "rule": "type_species_equals_tail",
            "block_id": block.get("block_id"),
            "moved": match.group(1)[:120],
        })


# Spanish "y" survives inside English author lists ("Audouin y Milne-Edwards").
# These are Spanish titles or place names and must keep the original conjunction.
_Y_KEEP = (
    "Ambiente y Ordenación",
    "Medioambiente y Ordenación",
    "Físicas y Naturales",
    "México y América",
    "Pontevedra y Aldán",
    "Pontevedra y Vigo",
    "Arosa y de Muros",
)


def _spanish_y(blocks: list[dict], changed: list[dict]) -> None:
    simple = re.compile(r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÀ-ÿ-]+) y ([A-ZÁÉÍÓÚÑ][A-Za-zÀ-ÿ-]+)")
    particle = re.compile(
        r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÀ-ÿ-]+) y "
        r"((?:(?:de|van|von|der|del|la|le)\s+)*[A-ZÁÉÍÓÚÑ][A-Za-zÀ-ÿ-]+)"
    )
    letter = re.compile(r"\b([A-Z]) y ([A-Z](?:-[A-Z])?)\b")
    for block in blocks:
        text = block.get("translation")
        if not text or " y " not in text:
            continue
        replaced = text
        for keep in _Y_KEEP:
            replaced = replaced.replace(keep, keep.replace(" y ", " \x00 "))
        replaced = letter.sub(r"\1 and \2", replaced)
        replaced = particle.sub(r"\1 and \2", replaced)
        replaced = simple.sub(r"\1 and \2", replaced)
        replaced = replaced.replace(" \x00 ", " y ")
        if replaced != text:
            block["translation"] = replaced
            changed.append({
                "rule": "spanish_y",
                "block_id": block.get("block_id"),
            })


_CAPTION_TERMS = (
    ("redibujados de", "redrawn from"),
    ("redibujado de", "redrawn from"),
    ("redibujadas de", "redrawn from"),
    ("redibujada de", "redrawn from"),
    ("modificados de", "modified from"),
    ("modificado de", "modified from"),
    ("modificadas de", "modified from"),
    ("modificada de", "modified from"),
    ("tomados de", "taken from"),
    ("tomado de", "taken from"),
    ("adaptados de", "adapted from"),
    ("adaptado de", "adapted from"),
)


def _caption_terms(blocks: list[dict], changed: list[dict]) -> None:
    for block in blocks:
        if block.get("role") != "caption":
            continue
        text = _norm(block.get("translation"))
        replaced = text
        for source, target in _CAPTION_TERMS:
            replaced = replaced.replace(source, target)
        if replaced != text:
            block["translation"] = replaced
            changed.append({
                "rule": "caption_terms",
                "block_id": block.get("block_id"),
            })


def _caption_lettering_tail(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Drop figure-panel lettering appended after a caption's final sentence.

    The PDF text layer emits the labels printed inside a plate (``A B C``,
    Roman numerals, abbreviations) as running text after the caption.  A run of
    at least three consecutive single capital letters right after a full stop
    is never prose; everything from that full stop on is plate lettering.
    """
    label_run = re.compile(r"\.\s+(?=(?:[A-Z][,']?\s+){2,}[A-Z][,']?(?:\s|$))")
    attribution = re.compile(r"\b(?:redrawn|modified|taken|adapted|from|after)\b", re.I)
    for block in blocks:
        if block.get("role") != "caption":
            continue
        text = _norm(block.get("translation"))
        cut = None
        dropped = ""
        for match in label_run.finditer(text):
            tail = text[match.start() + 1:].strip()
            if len(tail.split()) < 5 or attribution.search(tail):
                continue
            cut = match.start() + 1
            dropped = tail
            break
        if cut is None:
            continue
        block["translation"] = text[:cut].strip()
        changed.append({
            "rule": "caption_lettering_tail",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
            "dropped": dropped[:80],
        })


def _merge_split_paragraphs(blocks: list[dict], changed: list[dict]) -> None:
    """Join a body block that starts mid-sentence with the block before it.

    PDF extraction sometimes cuts one paragraph into two blocks.  The second
    block then starts with a lower-case word while the first has no terminal
    punctuation.  Left alone, the builder would set the fragment as a new
    indented paragraph.
    """
    kept: list[dict] = []
    for block in blocks:
        text = _norm(block.get("translation"))
        if (
            kept
            and block.get("role") == "body"
            and kept[-1].get("role") == "body"
            and text
            and text[0].islower()
            and not re.search(r"[.!?;:]\s*$", _norm(kept[-1].get("translation")))
        ):
            kept[-1]["translation"] = (
                _norm(kept[-1].get("translation")) + " " + text
            ).strip()
            changed.append({
                "rule": "merge_split_paragraph",
                "block_id": block.get("block_id"),
                "into": kept[-1].get("block_id"),
            })
            continue
        kept.append(block)
    blocks[:] = kept


def _key_terminator(source: str) -> re.Pattern[str] | None:
    """Regex matching the translated end of one source key line."""
    source = _norm(source).rstrip("•").strip()
    match = re.search(r"\(\s*p\.\s*(\d+)\s*\)\s*$", source)
    if match:
        return re.compile(r"\(\s*p\.\s*" + match.group(1) + r"\s*\)")
    match = re.search(r"(\d{1,2})\s*$", source)
    if match:
        return re.compile(r"(?:[.…]\s*){2,}" + match.group(1) + r"\b")
    match = re.search(r"([A-Z][A-Za-z-]+)\s*\*?\s*$", source)
    if match:
        return re.compile(r"(?<!\w)" + re.escape(match.group(1)) + r"(?!\w)")
    return None


def _reflow_key_run(blocks: list[dict], page: dict, changed: list[dict]) -> bool:
    """Re-split a run of key blocks from its translated line endings.

    The aligner often cuts a key run one line early or late: the previous
    line's page reference starts the next block, and the heading after the key
    absorbs the last couplet.  Each source key line ends with a dot-leader run
    followed by a page reference or a couplet number, and that ending survives
    in the translation, so the run can be re-cut deterministically.
    """
    handled = False
    index = 0
    while index < len(blocks):
        if blocks[index].get("role") != "key":
            index += 1
            continue
        end = index
        while end < len(blocks) and blocks[end].get("role") == "key":
            end += 1
        run = blocks[index:end]
        # A final key line whose source still carries the next bullet is roled
        # as a heading by the source extractor; it belongs to the run.
        probe_index = end
        probe: dict | None = None
        if probe_index < len(blocks):
            probe = blocks[probe_index]
            if probe.get("role") == "heading" and _norm(probe.get("text")).endswith("•"):
                run = blocks[index:probe_index + 1]
                probe_index += 1
        if len(run) < 2:
            index = end
            continue
        anchors = [
            rx for b in run if (rx := _key_terminator(b.get("text") or "")) is not None
        ]
        if len(anchors) != len(run):
            index = end
            continue
        # Join the run's translations, trimming overlaps the aligner left
        # between adjacent blocks.  A heading after the run can start with the
        # run's last line ending, so include it in the stream but not in the
        # segment count: whatever follows the last key terminator belongs to it.
        stream_blocks = list(run)
        probe = blocks[probe_index] if probe_index < len(blocks) else None
        if probe is not None and probe.get("role") == "heading":
            probe_text = _norm(probe.get("translation"))
            if re.search(r"(?:[.…]\s*){3,}|\(\s*p\.\s*\d+\s*\)", probe_text):
                stream_blocks.append(probe)
        parts: list[str] = []
        for block in stream_blocks:
            text = _norm(block.get("translation"))
            if not text:
                parts = []
                break
            if parts:
                previous = parts[-1]
                overlap = 0
                for size in range(min(60, len(previous), len(text)), 15, -1):
                    if previous.endswith(text[:size]):
                        overlap = size
                        break
                text = text[overlap:].strip()
            if text:
                parts.append(text)
        if not parts:
            index = end
            continue
        stream = " ".join(parts)
        pos = 0
        segments: list[str] = []
        for rx in anchors:
            found = rx.search(stream, pos)
            if found is None or found.start() <= pos:
                break
            segments.append(stream[pos:found.end()].strip())
            pos = found.end()
        if len(segments) != len(run):
            index = end
            continue
        if any(len(re.findall(r"(?:[.…]\s*){4,}", segment)) > 1 for segment in segments):
            index = end
            continue
        remainder = stream[pos:].strip().lstrip("• ").strip()
        probe = blocks[probe_index] if probe_index < len(blocks) else None
        if remainder and probe is not None and probe.get("role") == "heading":
            probe["translation"] = remainder
            changed.append({
                "rule": "key_run_reflow_heading",
                "block_id": probe.get("block_id"),
                "page": page.get("page"),
            })
        elif remainder:
            segments[-1] = (segments[-1] + " " + remainder).strip()
        for block, segment in zip(run, segments):
            if _norm(block.get("translation")) != segment:
                block["translation"] = segment
                changed.append({
                    "rule": "key_run_reflow",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })
            if block.get("role") != "key":
                block["role"] = "key"
                changed.append({
                    "rule": "key_run_role",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })
        handled = True
        index = max(end, probe_index)
    return handled


def _realign_key_page(page: dict, changed: list[dict]) -> None:
    """Rebuild a two-column key page from the source line endings."""
    blocks = page["blocks"]
    keys = [b for b in blocks if b.get("role") == "key"]
    if len(keys) < 5 or len(keys) != sum(1 for b in blocks if b.get("role") == "key"):
        return
    indexes = [i for i, b in enumerate(blocks) if b.get("role") == "key"]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        return

    stream_parts: list[str] = []
    stream_blocks = list(keys)
    for block in blocks[indexes[-1] + 1:]:
        text = _norm(block.get("translation"))
        if _TAXON_TAIL.match(text) or re.search(
            r"\(\s*p\.\s*\d+\s*\)|(?:[.…]\s*){2,}\d{1,2}\b", text
        ):
            stream_blocks.append(block)
        else:
            break
    for block in stream_blocks:
        text = _norm(block.get("translation"))
        if not text:
            return
        if stream_parts:
            previous = stream_parts[-1]
            overlap = 0
            for size in range(min(60, len(previous), len(text)), 15, -1):
                if previous.endswith(text[:size]):
                    overlap = size
                    break
            text = text[overlap:].strip()
        if text:
            stream_parts.append(text)
    stream = " ".join(stream_parts)
    if not stream:
        return

    pos = 0
    segments: list[str] = []
    for number, block in enumerate(keys):
        source = _norm(block.get("text"))
        if not source:
            return
        match = re.search(r"\(\s*p\.\s*(\d+)\s*\)\s*$", source)
        if match:
            needle = re.compile(r"\(\s*p\.\s*" + match.group(1) + r"\s*\)")
            found = needle.search(stream, pos)
        else:
            match = re.search(r"(\d{1,2})\s*$", source)
            if match:
                needle = re.compile(
                    r"(?:[.…]\s*){2,}" + match.group(1) + r"\b"
                )
                found = needle.search(stream, pos)
            else:
                match = re.search(r"([A-Z][A-Za-z-]+)\s*\*?\s*$", source)
                found = (
                    re.compile(re.escape(match.group(1)) + r"\s*\*?")
                    .search(stream, pos)
                    if match
                    else None
                )
        if found is None:
            if number == len(keys) - 1:
                segment = stream[pos:].strip()
                if segment:
                    segments.append(segment)
                    pos = len(stream)
                break
            return
        segment = stream[pos:found.end()].strip()
        if not segment:
            return
        segments.append(segment)
        pos = found.end()
    remainder = stream[pos:].strip()
    if re.search(r"\b(?:Genus|Familia|Type species|TYPE SPECIES)\b", remainder):
        remainder = ""
    if remainder and not re.fullmatch(r"\d{1,2}\.", remainder):
        segments[-1] = (segments[-1] + " " + remainder).strip()

    # A key line has exactly one dot-leader run and never two line openings.
    # Pages whose columns were interleaved (for example Vol47 p. 29) fail this
    # test; leave those untouched rather than scramble them further.
    for segment in segments:
        if len(re.findall(r"(?:[.…]\s*){4,}", segment)) > 1:
            return
        if re.match(r"^\d{1,2}\.\s*[•]", segment):
            return

    for block, segment in zip(keys, segments):
        if _norm(block.get("translation")) != segment:
            block["translation"] = segment
            changed.append({
                "rule": "key_page_realign",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })


_SENTENCE_END = re.compile(r"""[.!?]["')\]]?\s+""")
_ABBREVIATION = re.compile(
    r"\b(?:fig|figs|pl|p|pp|sp|spp|no|nos|al|e\.g|i\.e|cf|aff|var|subsp|sect|tab|[A-Z])\.$",
    re.I,
)


def _sentence_end_before(text: str, limit: int) -> int:
    """Last real sentence end before ``limit``; ``limit`` if there is none."""
    floor = max(0, limit - 400)
    best = 0
    for match in _SENTENCE_END.finditer(text, floor, limit):
        if _ABBREVIATION.search(text[:match.end()].rstrip()):
            continue
        best = match.end()
    return best if best > floor else limit


def _overflow_duplicate_tail(data: dict[str, Any], changed: list[dict]) -> None:
    """Drop later pages' text duplicated by a page-level body translation.

    The aligner sometimes gives one block the translation of an entire
    section.  The following pages then repeat the same sentences in their own
    blocks, which produces a giant paragraph and the wide word gaps seen in
    the PDF.  The repeated 80-character prefix identifies the boundary; the
    block is cut there, at the previous real sentence end.
    """
    entries = [
        (page, block)
        for page in data.get("pages", [])
        for block in page.get("blocks", [])
        if not block.get("_drop")
    ]
    for index, (page, block) in enumerate(entries):
        if block.get("role") != "body":
            continue
        translation = _norm(block.get("translation"))
        source = _norm(block.get("text"))
        if len(translation) < 600 or len(source) < 100:
            continue
        # Only an overfilled block can have swallowed later pages.  A normal
        # paragraph may repeat standard description wording, and matching that
        # boilerplate must not cut it.
        if len(translation) <= 1.6 * len(source):
            continue
        cut = None
        duplicate = None
        for later_page, later in entries[index + 1:]:
            if later_page.get("page", 0) > page.get("page", 0) + 6:
                break
            if later.get("role") != "body":
                continue
            later_text = _norm(later.get("translation"))
            if len(later_text) < 80:
                continue
            position = translation.find(later_text[:80])
            if position > max(200, len(translation) // 10):
                if cut is None or position < cut:
                    cut, duplicate = position, later.get("block_id")
        if cut is None or len(translation) - cut < 200:
            continue
        end = _sentence_end_before(translation, cut)
        block["translation"] = translation[:end].rstrip()
        changed.append({
            "rule": "overflow_duplicate_tail",
            "page": page.get("page"),
            "block_id": block.get("block_id"),
            "removed_chars": len(translation) - end,
            "duplicates": duplicate,
        })


_ACKNOWLEDGMENTS = re.compile(r"^(Acknowledg(?:e)?ments)\b[\s.:\-—]*(.*)$", re.I | re.S)


def _acknowledgment_heading_bleed(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Restore an Acknowledgments heading that absorbed the previous paragraph.

    The page translation is occasionally shifted by one block: the last prose
    paragraph becomes a "heading" and the next body block begins with
    "Acknowledgments" plus the thanks.  Move the heading word back, keep the
    prose before it, and leave the thanks as body text.
    """
    for index, block in enumerate(blocks):
        if block.get("role") != "heading":
            continue
        heading_text = _norm(block.get("translation"))
        if len(re.findall(r"[A-Za-z]{2,}", heading_text)) <= 20:
            continue
        body = next(
            (b for b in blocks[index + 1:] if b.get("role") == "body"
             and _norm(b.get("translation"))),
            None,
        )
        if body is None:
            continue
        match = _ACKNOWLEDGMENTS.match(_norm(body.get("translation")))
        if match is None:
            continue
        block["translation"] = match.group(1)
        body["translation"] = match.group(2).strip()
        prose = dict(block)
        prose["role"] = "body"
        prose["translation"] = heading_text
        prose["text"] = ""
        prose["block_id"] = f"{block.get('block_id')}_prose"
        blocks.insert(index, prose)
        changed.append({
            "rule": "acknowledgment_heading_bleed",
            "page": page.get("page"),
            "block_id": block.get("block_id"),
        })
        return


def _trim_embedded_duplicate_list(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """Cut a body paragraph that re-embeds the page's own entry list.

    A page-level translation sometimes continues past a family/genus list and
    repeats that list plus the key inside the running paragraph.  Three
    consecutive preceding translations found in order within 600 characters
    identify the embedded copy; everything from there on is cut.
    """
    for index, block in enumerate(blocks):
        if block.get("role") != "body":
            continue
        translation = _norm(block.get("translation"))
        if len(translation) < 600:
            continue
        matches = []
        for earlier in blocks[:index]:
            earlier_text = _norm(earlier.get("translation"))
            if len(earlier_text) < 30 or earlier.get("role") not in {
                "entry", "body", "heading", "key", "citation",
            }:
                continue
            position = translation.find(earlier_text)
            if position >= 0:
                matches.append((position, earlier.get("block_id")))
        for start in range(len(matches) - 2):
            sequence = matches[start:start + 3]
            if all(sequence[k][0] < sequence[k + 1][0] for k in range(2)) and (
                sequence[2][0] - sequence[0][0] <= 600
            ):
                cut = sequence[0][0]
                if cut < 100 or len(translation) - cut < 200:
                    continue
                end = _sentence_end_before(translation, cut)
                block["translation"] = translation[:end].rstrip()
                changed.append({
                    "rule": "embedded_duplicate_list",
                    "page": page.get("page"),
                    "block_id": block.get("block_id"),
                    "removed_chars": len(translation) - end,
                    "duplicates": sequence[0][1],
                })
                break


_FIG_CAPTION = re.compile(r"^\s*(?:Figs?|L[aá]ms?|Plates?)\.?\s*\d", re.I)


def _caption_like(block: dict) -> bool:
    """A caption, or a body block that opens like one ("Fig. 5. ...").

    OCR layouts leave captions as body; the builder promotes them later
    (promote_captions).  Without this a caption heading the next page hid the
    paragraph continuing under it (Fauna Vol. 21 pp. 13-14, 27-28, 31-32, 35-36).
    """
    if block.get("role") == "caption":
        return True
    if block.get("role") == "body" and block.get("label") == "vision_footnote":
        return True  # PaddleOCR-VL labels figure captions and their continuations so
    return block.get("role") == "body" and bool(_FIG_CAPTION.match(block.get("text") or block.get("translation") or ""))


def _merge_cross_page_paragraphs(pages: list[dict], changed: list[dict]) -> None:
    """Join body paragraphs split by a source page break.

    When a sentence runs over a page break, the next page's first body block
    starts with a lower-case word and the previous block has no terminal
    punctuation. Left as separate blocks the builder indents the continuation,
    which prints a paragraph break in the middle of a sentence. Hyphen-ended
    blocks are skipped: the split word needs a decision, not a join.
    """
    terminal = re.compile(r"""[.!?…]["')\]]*$""")
    carry: tuple[dict, Any] | None = None
    for prev, nxt in zip(pages, pages[1:]):
        a_blocks = prev.get("blocks") or []
        b_blocks = nxt.get("blocks") or []
        if not b_blocks:
            continue
        if prev.get("chapter") != nxt.get("chapter"):
            carry = None
            continue
        # A paragraph can run over more than one page break; after a join the
        # merged block belongs to the next page, so reuse it instead of the
        # page's own last block.
        # A figure caption standing between the two fragments (at the end of
        # this page or the start of the next) does not end the paragraph.
        a_flow = [x for x in a_blocks if not _caption_like(x)]
        b_flow = [x for x in b_blocks if not _caption_like(x)]
        if carry is not None and carry[1] == prev.get("page"):
            a = carry[0]
        elif a_flow:
            a = a_flow[-1]
        else:
            continue
        if not b_flow:
            # A page holding only figures and captions: the paragraph goes on
            # after it (Fauna Vol. 21 pp. 13-15, "desa-" / "parece").
            carry = (a, nxt.get("page")) if a.get("role") == "body" else None
            continue
        b = b_flow[0]
        if a.get("role") != "body" or b.get("role") != "body":
            carry = None
            continue
        ta = (a.get("translation") or "").rstrip()
        tb = (b.get("translation") or "").lstrip()
        if not ta or not tb or ta.endswith("-"):
            carry = None
            continue
        # A page break can fall before a comma or semicolon.  The fragment is
        # still the same paragraph; only its lower-case first word decides the
        # join, after the punctuation is set aside.
        leading = re.match(r"^[,;]\s*", tb)
        probe = tb[leading.end():] if leading else tb
        # "(Heacox y Schröder, 1978)" continues the sentence too (Vol. 21 p. 22).
        if terminal.search(ta) or not (probe[:1].islower() or probe[:1] == "("):
            carry = None
            continue
        a["translation"] = ta + " " + tb
        nxt["blocks"] = [x for x in b_blocks if x is not b]
        # Tell the coverage check that this page's opening source block moved
        # to the previous page; the words are not missing from the book.
        # Patch-rebuilt blocks have no source text, so fall back to the
        # translation's word count: the two lengths track each other.
        moved_words = len(
            (b.get("text") or b.get("translation") or "").split()
        )
        nxt["_merged_first_block_source_words"] = (
            nxt.get("_merged_first_block_source_words", 0) + moved_words
        )
        nxt["_merged_first_block_into"] = prev.get("page")
        # Do not carry the paragraph past blocks that follow it on this page.
        carry = (a, nxt.get("page")) if all(
            x.get("role") == "caption" for x in nxt["blocks"]) else None
        changed.append({
            "rule": "cross_page_paragraph_merge",
            "page": prev.get("page"),
            "block_id": a.get("block_id"),
            "joined_from_page": nxt.get("page"),
        })


def backfill_source(data: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Copy source text and geometry onto aligned blocks that lost them.

    A full-page patch rebuilds the page from block ids and translations; the
    new blocks then carry no `text` and no coordinates.  Without `text` the
    source-based rules cannot judge the block, and the builder cannot italicise
    genus names that occur only on that page.  Blocks are matched by
    `block_id` within the same page number; synthetic blocks with no source
    counterpart are reported and left unchanged.
    """
    source_pages = {int(p["page"]): p for p in source.get("pages", [])}
    filled: list[dict] = []
    unmatched: list[str] = []
    fields = ("text", "x0", "y0", "x1", "y1", "size")
    for page in data.get("pages", []):
        src_page = source_pages.get(int(page.get("page", 0)))
        if src_page is None:
            continue
        src_blocks = {b.get("block_id"): b for b in src_page.get("blocks", [])}
        for block in page.get("blocks", []):
            src = src_blocks.get(block.get("block_id"))
            if src is None:
                if (block.get("translation") or "").strip():
                    unmatched.append(str(block.get("block_id")))
                continue
            copied = []
            for field in fields:
                if block.get(field) in (None, "") and src.get(field) not in (None, ""):
                    block[field] = src[field]
                    copied.append(field)
            if block.get("role") == "heading" and "level" not in block and "level" in src:
                block["level"] = src["level"]
                copied.append("level")
            if copied:
                filled.append({"block_id": block.get("block_id"), "fields": copied})
    return {"filled_blocks": len(filled), "unmatched_blocks": unmatched, "changes": filled}


def block_src_hash(block: dict[str, Any]) -> str:
    """Fingerprint of a block's SOURCE text only (32 hex chars, sha256).

    Blocks without source text hash to "" so that no old_hash can match them:
    a lock that falls back to the translation would go stale on every edit.
    """
    import hashlib

    text = (block.get("text") or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


_EDIT_FIELDS = ("translation", "role", "level")
_OLD_KEY = {"translation": "old_translation", "role": "old_role", "level": "old_level"}
_EDIT_KEYS = {"block_id", "old_hash", "page", "remove", "boundary_reviewed", *_EDIT_FIELDS, *_OLD_KEY.values(), "old_prev", "old_next",
              "old_struct"}
_PATCH_KEYS = {"version", "edits", "inserts"}
NOHASH = "~"  # a neighbour exists but has no usable source hash ("" means: no neighbour at all)


def block_struct_digest(block: dict[str, Any]) -> str:
    """Digest of the WHOLE block (canonical JSON, every field), 32 hex chars.

    A delete binds to it so that replaying the delete after any field changed
    (table cell, list item, figure entry, couplet target/name, ...) is stale
    instead of silently dropping the edit.
    """
    import hashlib
    import json

    raw = json.dumps(block, sort_keys=True, ensure_ascii=False, default=repr)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def neighbour_hash(hashes: list[str], j: int) -> str:
    """Hash of the block at book index ``j``: "" outside the book, NOHASH when textless."""
    if j < 0 or j >= len(hashes):
        return ""
    return hashes[j] or NOHASH


def safe_key(x: Any) -> Any:
    """Hashable key for any JSON id: strings as-is, anything else by type+repr."""
    return x if isinstance(x, str) else ("#nonstr", type(x).__name__, repr(x))


def block_neighbours(data: dict[str, Any]) -> dict[Any, tuple[str, str]]:
    """``block_id`` -> (prev, next) source hashes over the WHOLE book order.

    Same semantics as ``blockid.fingerprint_table`` (neighbours cross page
    boundaries; "" only at the book's first/last block).
    """
    flat = [b for p in data.get("pages", []) for b in p.get("blocks", [])]
    hs = [block_src_hash(b) for b in flat]
    return {safe_key(b.get("block_id")): (neighbour_hash(hs, i - 1), neighbour_hash(hs, i + 1))
            for i, b in enumerate(flat)}


def _old_problem(edit: dict[str, Any]) -> str:
    for f, k in _OLD_KEY.items():
        if k not in edit:
            continue
        v = edit[k]
        if f == "level":
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
                return "old_level must be null or a positive integer"
        elif not isinstance(v, str) and not (f == "role" and v is None):
            return f"{k} must be a string" + (" or null" if f == "role" else "")
    return ""


def _role_problem(block: dict[str, Any]) -> str:
    """Whole-block structure check, the same validator the builder input goes through."""
    from booklayout.profile import validate_aligned

    errs = validate_aligned({"pages": [{"page": 0, "blocks": [block]}]})
    return errs[0].split(": ", 1)[-1] if errs else ""


def _field_problem(field: str, value: Any) -> str:
    if field == "translation":
        return "" if isinstance(value, str) else "translation must be a string"
    if field == "role":
        from booklayout.profile import ROLES

        return "" if isinstance(value, str) and value in ROLES else f"role must be one of {sorted(ROLES)}"
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "level must be a positive integer"
    return ""


def _edit_problem(edit: Any, strict: bool = False) -> str:
    """Why an edit is malformed, or "" when it is well formed."""
    if not isinstance(edit, dict):
        return "edit is not an object"
    bid = edit.get("block_id")
    if not isinstance(bid, str) or not bid:
        return "block_id must be a non-empty string"
    unknown = set(edit) - _EDIT_KEYS
    if unknown:
        return f"unknown field(s): {sorted(unknown)}"
    if "remove" in edit and not isinstance(edit["remove"], bool):
        return "remove must be a JSON boolean"
    if "boundary_reviewed" in edit and not isinstance(edit["boundary_reviewed"], bool):
        return "boundary_reviewed must be a JSON boolean"
    # boundary_reviewed records a reviewer's decision on a page boundary that
    # structure.uncertain_boundaries flagged; it changes no text.
    has_fields = any(f in edit for f in _EDIT_FIELDS) or "boundary_reviewed" in edit
    if edit.get("remove") and has_fields:
        return "remove cannot be combined with field updates"
    if not edit.get("remove") and not has_fields:
        return "edit has no operation"
    for f in _EDIT_FIELDS:
        if f in edit:
            why = _field_problem(f, edit[f])
            if why:
                return why
    for k in ("old_prev", "old_next"):
        if k in edit and not isinstance(edit[k], str):
            return f"{k} must be a string hash"
    why = _old_problem(edit)
    if why:
        return why
    if strict:
        if isinstance(edit.get("page"), bool) or not isinstance(edit.get("page"), int):
            return "version 2 requires integer page"
        if not isinstance(edit.get("old_hash"), str):
            return "version 2 requires old_hash (string)"
        if edit.get("remove") and not isinstance(edit.get("old_struct"), str):
            return "version 2 delete requires old_struct (block_struct_digest)"
        need = list(_EDIT_FIELDS) if edit.get("remove") else [f for f in _EDIT_FIELDS if f in edit]
        for f in need:
            if _OLD_KEY[f] not in edit:
                return f"version 2 requires {_OLD_KEY[f]}"
        for k in ("old_prev", "old_next"):
            if k not in edit:
                return f"version 2 requires {k}"
    return ""


def _patch_problem(patch: Any) -> str:
    if not isinstance(patch, dict):
        return "patch must be a JSON object"
    if set(patch) - _PATCH_KEYS:
        return f"unknown top-level key(s): {sorted(set(patch) - _PATCH_KEYS, key=repr)}"
    ver = patch.get("version", 1)
    if type(ver) is not int or ver not in (1, 2):
        return "version must be integer 1 or 2"
    if not isinstance(patch.get("edits"), list):
        return "edits must be an array"
    if "inserts" in patch and not isinstance(patch["inserts"], list):
        return "inserts must be an array"
    return ""


def apply_block_edits(data: dict[str, Any], patch: dict[str, Any],
                      allow_partial: bool = False) -> dict[str, Any]:
    """Apply block-level translation edits by block_id.

    Companion to :func:`apply_page_patch` for repairs that touch one or two
    blocks of a page: replace a translation, change a role or level, or remove
    a block.  Removed blocks are dropped; the page keeps its other blocks in order.

    The patch must be an object with integer ``version`` (1 or 2) and an
    ``edits`` array, else ``ValueError``.  Edits are validated strictly
    (non-empty string ids, boolean ``remove``, known fields, ``role`` from the
    builder's role set, integer ``level``, at least one operation).
    ``old_hash`` locks the source text; ``old_translation`` / ``old_role`` /
    ``old_level`` are preconditions on the current values.  Patch ``"version": 2``
    makes ``old_hash``, the logical ``page``, ``old_prev`` and ``old_next``
    mandatory, requires an ``old_*`` for every changed field (a delete needs
    ``old_translation``, ``old_role`` and ``old_level``, null allowed), and makes the batch all-or-nothing: any invalid, missing or
    stale edit leaves ``data`` untouched unless ``allow_partial``.  Report keys:
    applied, removed, missing, stale, invalid.  Duplicate block ids in ``data``
    raise ``ValueError`` (an id must name exactly one block).  Optional
    ``old_prev`` / ``old_next`` carry the source hashes of the adjacent blocks
    (``""`` only at the book's first/last block, same as ``fingerprint_table``);
    a mismatch is ``stale`` (same-text re-split guard).  Residual risk: two
    identical blocks with identical neighbours are indistinguishable without a
    persistent docstore block id (P3).
    """
    import copy
    from collections import Counter

    bad = _patch_problem(patch)
    if bad:
        raise ValueError(bad)
    ids: list[Any] = [b.get("block_id") for p in data.get("pages", []) for b in p.get("blocks", [])]
    counts = Counter(i for i in ids if isinstance(i, str) and i)
    dup = sorted(i for i, n in counts.items() if n > 1)
    if dup:
        raise ValueError(f"duplicate block_id in aligned data: {dup[:5]}")
    work = copy.deepcopy(data)
    by_id = {
        safe_key(b.get("block_id")): (p, b)
        for p in work.get("pages", [])
        for b in p.get("blocks", [])
    }
    neigh = block_neighbours(data)
    applied: list[str] = []
    removed: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    invalid: list[str] = []
    strict = patch.get("version", 1) >= 2
    for edit in patch["edits"]:
        problem = _edit_problem(edit, strict)
        if problem:
            who = edit.get("block_id") if isinstance(edit, dict) else repr(edit)
            invalid.append(f"{who}: {problem}")
            continue
        bid = edit["block_id"]
        if safe_key(bid) not in by_id:
            missing.append(bid)
            continue
        page, block = by_id[bid]
        # Optimistic lock: block ids are positional (p004_01), so a re-split can
        # make an id point at different text.  A patch that carries old_hash is
        # applied only if the block's source text still matches.
        locked = "old_hash" in edit or strict
        if locked and (not edit.get("old_hash") or edit["old_hash"] != block_src_hash(block)):
            stale.append(bid)
            continue
        if ("page" in edit and edit["page"] != page.get("page")) or (strict and edit["page"] != page.get("page")):
            stale.append(bid)
            continue
        if "old_struct" in edit and edit["old_struct"] != block_struct_digest(block):
            stale.append(bid)
            continue
        if "old_prev" in edit or "old_next" in edit:
            # Neighbour fingerprint over the ORIGINAL book order: rejects a
            # same-text block that a re-split moved to a different spot.
            prev_h, next_h = neigh[bid]
            if edit.get("old_prev", prev_h) != prev_h or edit.get("old_next", next_h) != next_h:
                stale.append(bid)
                continue
        olds = {"translation": block.get("translation") or "", "role": block.get("role"),
                "level": block.get("level")}
        if any(k in edit and edit[k] != olds[f] for f, k in _OLD_KEY.items()):
            stale.append(bid)
            continue
        if edit.get("remove"):
            page["blocks"] = [b for b in page["blocks"] if b is not block]
            del by_id[safe_key(bid)]
            removed.append(bid)
            applied.append(bid)
            continue
        trial = {**block, **{f: edit[f] for f in _EDIT_FIELDS if f in edit}}
        why = _role_problem(trial)
        if why:
            invalid.append(f"{bid}: {why}")
            continue
        block.update({f: edit[f] for f in _EDIT_FIELDS if f in edit})
        if "boundary_reviewed" in edit:
            block["boundary_reviewed"] = edit["boundary_reviewed"]
        applied.append(bid)
    inserted: list[str] = []
    for ins in patch.get("inserts", []):
        # {"after_block_id": id, "block": {"block_id", "role", "translation", ...}}: a line the
        # page lost (source-check "missing"); goes right after the named block, same page.
        new = ins.get("block") if isinstance(ins, dict) else None
        before = ins.get("before_block_id") if isinstance(ins, dict) else None
        after = ins.get("after_block_id") if isinstance(ins, dict) else None
        nid = new.get("block_id") if isinstance(new, dict) else None
        if not (isinstance(nid, str) and nid and isinstance(new.get("translation"), str)
                and (isinstance(after, str)) != (isinstance(before, str))):
            invalid.append(f"insert {nid or ins!r}: needs exactly one of after_block_id/before_block_id "
                           "and block with block_id, role, translation")
            continue
        after = after if isinstance(after, str) else before
        if safe_key(after) not in by_id:
            missing.append(after)
            continue
        if safe_key(nid) in by_id:
            invalid.append(f"{nid}: insert block_id already exists")
            continue
        why = _role_problem(new)
        if why:
            invalid.append(f"{nid}: {why}")
            continue
        page, anchor = by_id[safe_key(after)]
        pos = next(i for i, b in enumerate(page["blocks"]) if b is anchor) + (0 if ins.get("before_block_id") else 1)
        page["blocks"].insert(pos, dict(new))
        by_id[safe_key(nid)] = (page, page["blocks"][pos])
        inserted.append(nid)
    report: dict[str, Any] = {"applied": applied, "removed": removed, "missing": missing,
                              "stale": stale, "invalid": invalid, "inserted": inserted}
    if strict and not allow_partial and (missing or stale or invalid):
        return {**report, "applied": [], "removed": [],
                "not_applied": applied, "not_applied_removed": removed}
    data["pages"] = work.get("pages", [])
    return report


def _split_reference_blocks(blocks: list[dict], changed: list[dict]) -> None:
    """Issue #37: one ``ref`` block per bibliography entry (hanging indent)."""
    from booklayout.paragraphs import split_reference_entries

    out: list[dict] = []
    for block in blocks:
        parts = (split_reference_entries(block.get("translation") or "")
                 if block.get("role") == "ref" else [])
        if len(parts) < 2:
            out.append(block)
            continue
        src_parts = split_reference_entries(block.get("text") or "")
        if len(src_parts) != len(parts):
            src_parts = [block.get("text") or ""] + [""] * (len(parts) - 1)
        for i, (tr, src) in enumerate(zip(parts, src_parts)):
            new = dict(block)
            new["translation"] = tr
            if "text" in block:
                new["text"] = src
            if i:
                new["block_id"] = f"{block.get('block_id', 'ref')}-r{i + 1}"
            out.append(new)
        changed.append({"block_id": block.get("block_id"), "rule": "reference_entries_split",
                        "entries": len(parts)})
    blocks[:] = out


def normalize_aligned(data: dict[str, Any], source_only: bool = False) -> dict[str, Any]:
    """Apply every deterministic repair in place; return a change report.

    ``source_only``: the "translation" is the source text itself (OCR'd original
    typeset untranslated, e.g. Fauna Iberica Vol. 21 in Spanish).  Only the
    language-neutral repairs run (split/cross-page paragraph joins); the rules
    that rewrite Spanish structure words into the target language
    (``spanish_y``, ``structured_from_source``, ``heading_from_source``, ...) are skipped.
    """
    changed: list[dict] = []
    if source_only:
        for page in data.get("pages", []):
            blocks = page.get("blocks", [])
            _merge_split_paragraphs(blocks, changed)
            page["blocks"] = [b for b in blocks if not b.get("_drop")]
        _merge_cross_page_paragraphs(data.get("pages", []), changed)
        return {"changes": changed, "changed_blocks": len(changed),
                "changed_pages": len({c.get("page", (c.get("block_id") or "")[:5]) for c in changed})}
    for page in data.get("pages", []):
        blocks = page.get("blocks", [])
        _merge_split_paragraphs(blocks, changed)
        _acknowledgment_heading_bleed(blocks, page, changed)
        if not _reflow_key_run(blocks, page, changed):
            _realign_key_page(page, changed)
        _heading_continuation(blocks, changed)
        _figure_ref_body(blocks, changed)
        _genus_heading_from_citation(blocks, changed)
        _citation_name_from_heading(blocks, changed)
        _leading_citation_continuation(blocks, changed)
        _appendix_entries(blocks, page, changed)
        _structured_from_source(blocks, page, changed)
        for block in blocks:
            _heading_from_source(block, changed)
        _heading_tail_merge(blocks, changed)
        _heading_bleed_previous(blocks, changed)
        _entry_prefix_duplicate(blocks, changed)
        _function_word_join(blocks, changed)
        _key_leading_target(blocks, changed)
        _leading_punctuation(blocks, changed)
        _caption_duplicate(blocks, page, changed)
        _caption_lettering_tail(blocks, page, changed)
        _caption_terms(blocks, changed)
        _abbreviation_note(blocks, page, changed)
        _remove_figure_junk(blocks, page, changed)
        _heading_citation_bleed(blocks, changed)
        _heading_figure_ref(blocks, changed)
        _citation_body_bleed(blocks, changed)
        _type_species_tail(blocks, page, changed)
        _type_species_equals_tail(blocks, changed)
        _citation_role_body(blocks, page, changed)
        _appendix_terms(blocks, page, changed)
        _spanish_y(blocks, changed)
        _trim_embedded_duplicate_list(blocks, page, changed)
        _leading_punctuation(blocks, changed)
        _split_reference_blocks(blocks, changed)
        page["blocks"] = [b for b in blocks if not b.get("_drop")]
    # Trim overfilled blocks first: once a page-break continuation is joined
    # into the previous page, the duplicated tail can no longer be matched.
    _overflow_duplicate_tail(data, changed)
    _merge_cross_page_paragraphs(data.get("pages", []), changed)
    return {
        "changes": changed,
        "changed_blocks": len(changed),
        "changed_pages": len({c.get("page", (c.get("block_id") or "")[:5]) for c in changed}),
    }


_PAGE_PATCH_TOP = {"pages", "old_page_digests", "version"}
_PAGE_ENTRY_KEYS = {"block_id", "role", "translation", "level", "text", "rows", "items", "figures",
                    "col_widths_mm", "couplet", "caption"}
_PAGE_EXISTING_KEYS = ("role", "translation", "level")


def page_digest(page: dict[str, Any]) -> str:
    """Digest of a page's ordered block list; binds a whole-page patch to the page it was made from."""
    import hashlib
    import json

    payload = json.dumps([block_struct_digest(b) for b in page.get("blocks", [])], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def apply_page_patch(data: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Replace selected pages' block lists from a declarative patch.

    Patch format::

        {"pages": {"352": [{"block_id": "p352_b07", "role": "body",
                            "level": 2, "translation": "..."}, ...]},
         "old_page_digests": {"352": "<page_digest of the page the patch was made from>"}}

    Existing blocks are looked up by ``block_id`` so their geometry survives
    (only role/translation/level may change).  A new block must carry a valid
    ``role`` and may carry text/rows/items/figures/col_widths_mm/couplet/caption.
    ``old_page_digests`` is optional: when given for a page, the page must still
    be exactly what the patch was made from, otherwise the whole batch is
    rejected.  Everything is validated on a candidate before any page is replaced.
    """
    from booklayout.profile import validate_aligned

    if not isinstance(patch, dict) or "pages" not in patch:
        raise ValueError("page patch must be an object with an explicit `pages` key ({\"pages\": {}} is a no-op)")
    unknown = set(patch) - _PAGE_PATCH_TOP
    if unknown:
        raise ValueError(f"unknown top-level fields in page patch: {sorted(unknown)}")
    pages_patch = patch["pages"]
    if not isinstance(pages_patch, dict):
        raise ValueError("`pages` must be an object mapping page number -> list of blocks")
    digests = patch.get("old_page_digests", {})
    if not isinstance(digests, dict):
        raise ValueError("`old_page_digests` must be an object mapping page number -> digest")
    page_nums = [page.get("page") for page in data.get("pages", [])]
    dups = sorted({n for n in page_nums if page_nums.count(n) > 1}, key=repr)
    if dups:
        raise ValueError(f"aligned file has duplicate page numbers {dups}: refusing page repair")
    by_page = {page["page"]: page for page in data.get("pages", [])}
    owner: dict[Any, int] = {}
    for page in data.get("pages", []):
        for b in page.get("blocks", []):
            owner.setdefault(b.get("block_id"), page["page"])

    def canon(number: Any) -> int:
        try:
            n = int(number)
        except (TypeError, ValueError):
            raise ValueError(f"page key {number!r} is not an integer") from None
        if n not in by_page:
            raise ValueError(f"page {number} not in the aligned file")
        return n

    todo: dict[int, list[dict[str, Any]]] = {}
    for number, entries in pages_patch.items():  # validate everything before mutating
        n = canon(number)
        if n in todo:
            raise ValueError(f"page {n} appears twice in the patch (key {number!r})")
        if not isinstance(entries, list):
            raise ValueError(f"page {number}: value must be a list of blocks ([] clears the page)")
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("block_id"), str) or not e["block_id"]:
                raise ValueError(f"page {number}: every entry needs a non-empty string block_id")
            bad = set(e) - _PAGE_ENTRY_KEYS
            if bad:
                raise ValueError(f"page {number} block {e['block_id']}: unsupported fields {sorted(bad)}")
        todo[n] = entries
    seen_dig: set[int] = set()
    for number, dig in digests.items():
        n = canon(number)
        if n in seen_dig or n not in todo:
            raise ValueError(f"old_page_digests key {number!r} duplicates another or has no page in `pages`")
        seen_dig.add(n)
        if dig != page_digest(by_page[n]):
            raise ValueError(f"page {n} changed since the patch was made (old_page_digests mismatch)")

    candidate: dict[int, list[dict[str, Any]]] = {}
    for n, entries in todo.items():
        page = by_page[n]
        ids_here = [b.get("block_id") for b in page["blocks"]]
        if len(ids_here) != len(set(map(repr, ids_here))):
            raise ValueError(f"page {n} has duplicate block_ids; fix the aligned file before repair")
        existing = {b.get("block_id"): b for b in page["blocks"]}
        new_blocks = []
        for entry in entries:
            is_new = entry["block_id"] not in existing
            if is_new and owner.get(entry["block_id"], n) != n:
                raise ValueError(f"page {n} block {entry['block_id']}: id belongs to page "
                                 f"{owner[entry['block_id']]}; moving a block across pages is not supported")
            block = dict(existing.get(entry["block_id"], {}))
            block.setdefault("block_id", entry["block_id"])
            if is_new:
                block.setdefault("source_page", n)
            block.setdefault("chapter", page.get("chapter", ""))
            block.setdefault("kind", page.get("kind", ""))
            block.setdefault("level", 1)
            if not is_new:  # structural fields of an existing block are not editable here: never accept-and-ignore
                ignored = [f for f in entry if f not in _PAGE_EXISTING_KEYS and f != "block_id"
                           and entry[f] != existing[entry["block_id"]].get(f)]
                if ignored:
                    raise ValueError(f"page {n} block {entry['block_id']}: fields {sorted(ignored)} of an existing "
                                     "block cannot be changed by repair (use patch-blocks or omit them)")
            for field in (_PAGE_EXISTING_KEYS if not is_new else tuple(_PAGE_ENTRY_KEYS - {"block_id"})):
                if field in entry:
                    block[field] = entry[field]
            new_blocks.append(block)
        candidate[n] = new_blocks
    ids: dict[str, int] = {}
    for p in data.get("pages", []):
        for b in candidate.get(p["page"], p.get("blocks", [])):
            bid = b.get("block_id")
            if isinstance(bid, str) and bid in ids:
                raise ValueError(f"duplicate block_id {bid!r} on pages {ids[bid]} and {p['page']}")
            if isinstance(bid, str):
                ids[bid] = p["page"]
    errors = validate_aligned({"pages": [{"page": n, "blocks": bl} for n, bl in candidate.items()]})
    if errors:
        raise ValueError("candidate pages fail validation: " + "; ".join(errors[:5]))
    for n, blocks in candidate.items():
        by_page[n]["blocks"] = blocks
    return {"patched_pages": list(candidate)}
