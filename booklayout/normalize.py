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

from .textaudit import looks_like_japanese_prose

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
            # 日/中源文的检索表标题被灌进整表时，译文含 ……；不得回写成源文假名墙
            if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", source):
                contaminated = False
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


_BOX_GLYPH = re.compile(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\u25a1|\u25a1(?=[\u3040-\u30ff\u3400-\u9fff])")


def _box_glyph_to_kou(blocks: list[dict], changed: list[dict]) -> None:
    """OCR reads the kanji 口 as the box glyph U+25A1; it renders as a missing-glyph box.

    Only a box touching a CJK character is repaired (a lone box may be a real symbol).
    Source and translation carry the same OCR residue, so both are repaired.
    """
    for block in blocks:
        for field in ("text", "translation"):
            value = block.get(field)
            if not value or "\u25a1" not in value:
                continue
            fixed = _BOX_GLYPH.sub("\u53e3", value)
            if fixed != value:
                block[field] = fixed
                changed.append({"rule": "box_glyph_to_kou", "block_id": block.get("block_id"),
                                "field": field})


def _leading_punctuation(blocks: list[dict], changed: list[dict]) -> None:
    """Repair punctuation left at the start of a block by a page-break split."""
    for index, block in enumerate(blocks):
        if block.get("role") not in ("body", "note", "key", "entry", "citation"):
            continue
        text = _norm(block.get("translation"))
        match = re.match(r"^([.,;:)])\s*", text)
        if match is None:
            continue
        rest = text[match.end():].strip()
        if not rest:
            continue
        head = rest[:1]
        if match.group(1) == ")" and index > 0:
            previous = blocks[index - 1]
            before = _norm(previous.get("translation"))
            if before and not before.endswith(")"):
                previous["translation"] = before + ")"
        elif match.group(1) == "," and index > 0:
            # 切段残留：",26,29…" 或 ", and on every segment…" → 并回上块
            previous = blocks[index - 1]
            before = _norm(previous.get("translation"))
            if before and (head.isdigit() or head.islower() or head in "*("):
                if before.endswith((",", "…", "—", "-")):
                    previous["translation"] = f"{before} {rest}".replace("  ", " ")
                else:
                    previous["translation"] = f"{before}, {rest}"
                block["translation"] = ""
                block["_drop"] = True
                changed.append({
                    "rule": "leading_comma_merge",
                    "block_id": block.get("block_id"),
                })
                continue
        elif match.group(1) in ";." and index > 0:
            previous = blocks[index - 1]
            before = _norm(previous.get("translation"))
            if before and (head.islower() or head.isdigit() or head in "*("):
                glue = "" if before.endswith(match.group(1)) else match.group(1)
                previous["translation"] = f"{before}{glue} {rest}".replace("  ", " ")
                block["translation"] = ""
                block["_drop"] = True
                changed.append({
                    "rule": "leading_punct_merge",
                    "block_id": block.get("block_id"),
                })
                continue
        elif not head.isupper():
            continue
        block["translation"] = rest
        changed.append(
            {"rule": "leading_punctuation", "block_id": block.get("block_id")}
        )


def _index_leaders_to_entry(page: dict, blocks: list[dict], changed: list[dict]) -> None:
    """学名索引行（含错挂在科名章下的）：Genus Author, year…………页码 → entry。"""
    for block in blocks:
        if block.get("role") not in ("body", "key"):
            continue
        text = _norm(block.get("translation"))
        if not re.search(r"…{2,}\s*\d{1,3}(?:,\s*\d{1,3})*\s*$", text):
            continue
        if not re.search(r"[A-Z][a-z]{2,}", text):
            continue
        if not (
            re.search(r"\b(?:1[789]\d{2}|20\d{2}|\d{3})\b", text)
            or re.search(r"\bsp\.\s*[A-Z]\b", text)
        ):
            continue
        block["role"] = "entry"
        changed.append({
            "rule": "index_leaders_to_entry",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
        })


def _key_heading_from_body(blocks: list[dict], changed: list[dict]) -> None:
    """Body that is only a key title → heading (今岛英译常见)。"""
    for block in blocks:
        if block.get("role") != "body":
            continue
        text = _norm(block.get("translation"))
        if re.match(
            r"Key to (?:the )?(?:species|genera|subfamilies|families)\b",
            text,
            re.I,
        ):
            block["role"] = "heading"
            block["level"] = block.get("level") or 2
            changed.append({
                "rule": "key_heading_from_body",
                "block_id": block.get("block_id"),
            })


def _body_leaders_to_key(blocks: list[dict], changed: list[dict]) -> None:
    """Body with leaders + tabbable taxon → restore key role."""
    from .builder import split_key_couplet
    from .keyrepair import looks_like_species_desc_key

    for block in blocks:
        if block.get("role") != "body":
            continue
        text = _norm(block.get("translation"))
        source = _norm(block.get("text"))
        if not re.search(r"…{2,}|\.{5,}", text):
            continue
        if looks_like_species_desc_key(text, source):
            continue
        if split_key_couplet(text, source or None) is None:
            continue
        block["role"] = "key"
        changed.append({
            "rule": "body_leaders_to_key",
            "block_id": block.get("block_id"),
        })


def _trim_key_dump_heading(blocks: list[dict], changed: list[dict]) -> None:
    """超长「种の検索」标题块被整表灌进 heading → 收成短标题。"""
    for block in blocks:
        if block.get("role") != "heading":
            continue
        source = _norm(block.get("text"))
        trans = _norm(block.get("translation"))
        words = len(re.findall(r"[A-Za-z]{2,}", trans))
        has_key_src = bool(re.search(r"種の検索|の検索", source))
        has_key_en = bool(
            re.search(r"\bKey to\b.{0,40}\b(?:species|genera)\b", trans, re.I)
        )
        # 整表灌进：源文是检索表标题，译文过长或夹带 ……/偶行号
        dumpish = has_key_src and (
            words > 12
            or "…" in trans
            or re.search(r"(?:\.\s*){3,}", trans)
            or re.search(r"\b\d{1,2}\b.+\b\d{1,2}\b", trans)
        )
        already_title = bool(re.match(r"Key to\b", trans, re.I)) and has_key_src
        if not dumpish and not already_title and not (
            words > 20 and (has_key_src or has_key_en)
        ):
            continue

        def _family_from_keys() -> str | None:
            for other in blocks:
                if other is block or other.get("role") != "key":
                    continue
                blob = _norm(other.get("translation"))
                match = re.search(
                    r"\*([A-Z][a-z]{3,}(?:us|is|a|um))(?:\*\s+\*?|\s+)[a-z]{3,}",
                    blob,
                )
                if match and not match.group(1).endswith("ous"):
                    stem = match.group(1)
                    name = stem[:-2] + "idae" if stem.endswith("us") else stem + "idae"
                    if name.endswith("usidae"):
                        name = name[:-6] + "idae"
                    return name
            for other in blocks:
                if other is block or other.get("role") != "key":
                    continue
                blob = _norm(other.get("translation"))
                match = re.search(r"\*?([A-Z][a-z]+idae)\*?", blob)
                if match:
                    return match.group(1)
            return None

        fam = _family_from_keys()
        if re.search(r"日本産|Japanese", source + " " + trans, re.I):
            title = (
                f"Key to Japanese species of {fam}" if fam else "Key to Japanese species"
            )
        else:
            title = f"Key to species of {fam}" if fam else "Key to species"
        if trans == title:
            continue
        block["translation"] = title
        block["level"] = block.get("level") or 2
        changed.append({
            "rule": "trim_key_dump_heading",
            "block_id": block.get("block_id"),
            "title": title,
        })


def _body_couplet_number_to_key(blocks: list[dict], changed: list[dict]) -> None:
    """正文里偶行末跳转号、无点线 → 收回 key，交给 repair-keys 补制表符。"""
    from .keyrepair import looks_like_species_desc_key

    page_has_key = any(b.get("role") == "key" for b in blocks)
    for block in blocks:
        if block.get("role") != "body":
            continue
        # 保留换行：_norm 会把换行压成空格，偶行号就丢了
        raw = (block.get("translation") or "").replace("\r\n", "\n").replace("\r", "\n")
        text = raw.strip()
        if not text or re.search(r"…{2,}|\.{5,}", text):
            continue
        if re.search(r"\(new name\)", text, re.I):
            continue  # 和名索引行，不是检索表
        if looks_like_species_desc_key(text, _norm(block.get("text"))):
            continue
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        hit = next(
            (
                ln
                for ln in lines
                if len(ln) >= 28 and re.search(r"\s([1-9]|[1-9]\d)\s*$", ln)
            ),
            None,
        )
        if hit is None:
            # 已被压成单行：“… smooth 5 Anterior …”
            match = re.search(
                r"(.{28,}?)\s([1-9]|[1-9]\d)(?=\s+[A-Z*])",
                re.sub(r"\s+", " ", text),
            )
            hit = match.group(0) if match else None
        if hit is None:
            continue
        # 避免把普通计量句收成检索表：同页已有 key，或行内像鉴别特征
        if not page_has_key and not re.search(
            r"\b(?:parapod|chaeta|elytr|antenna|segment|notopod|neuropod|"
            r"疣足|刚毛|触手|背鳞)\b",
            hit,
            re.I,
        ):
            continue
        block["role"] = "key"
        changed.append({
            "rule": "body_couplet_number_to_key",
            "block_id": block.get("block_id"),
        })


_PARTIAL_KANA_FIXES = (
    (re.compile(r"ナナテイ?ソ?メ?矶沙蚕科"), "欧努菲虫科"),
    (re.compile(r"ナナテイソメ科"), "欧努菲虫科"),
    (re.compile(r"与ナナテ"), "与欧努菲虫"),
)


def _fix_partial_kana_glosses(blocks: list[dict], changed: list[dict]) -> None:
    """半截片假名科名等明显漏译 → 确定性替换。"""
    for block in blocks:
        text = _norm(block.get("translation"))
        if not text or not re.search(r"[\u3040-\u30ff]", text):
            continue
        updated = text
        for pattern, repl in _PARTIAL_KANA_FIXES:
            updated = pattern.sub(repl, updated)
        if updated != text:
            block["translation"] = updated
            changed.append({
                "rule": "fix_partial_kana_glosses",
                "block_id": block.get("block_id"),
            })


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
            # 含中文句号；也勿把「a：体前部」图注拼回分布段
            and not re.search(r"[.!?;:。．！？]\s*$", _norm(kept[-1].get("translation")))
            and not re.match(r"[a-zA-Zａ-ｚ][:：]", text)
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
        if carry is not None and carry[1] == prev.get("page"):
            a = carry[0]
        elif a_blocks:
            a = a_blocks[-1]
        else:
            continue
        b = b_blocks[0]
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
        if terminal.search(ta) or not probe[:1].islower():
            carry = None
            continue
        a["translation"] = ta + " " + tb
        nxt["blocks"] = b_blocks[1:]
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
        carry = (a, nxt.get("page")) if not nxt["blocks"] else None
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


def apply_block_edits(data: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply block-level translation edits by block_id.

    Companion to :func:`apply_page_patch` for repairs that touch one or two
    blocks of a page: replace a translation, change a role, or remove a block.
    Removed blocks are dropped; the page keeps its other blocks in order.
    """
    by_id = {
        b.get("block_id"): (p, b)
        for p in data.get("pages", [])
        for b in p.get("blocks", [])
    }
    applied: list[str] = []
    removed: list[str] = []
    missing: list[str] = []
    for edit in patch.get("edits", []):
        bid = edit.get("block_id")
        if bid not in by_id:
            missing.append(str(bid))
            continue
        page, block = by_id[bid]
        if edit.get("remove"):
            page["blocks"] = [b for b in page["blocks"] if b is not block]
            removed.append(str(bid))
            applied.append(str(bid))
            continue
        if "translation" in edit:
            block["translation"] = edit["translation"]
        for field in ("role", "level"):
            if field in edit:
                block[field] = edit[field]
        applied.append(str(bid))
    return {"applied": applied, "removed": removed, "missing": missing}


_PANEL_LEGEND = re.compile(
    r"^(?P<head>.+?[。．])\s+(?P<tail>[a-zA-Zａ-ｚ][:：].+)$",
    re.S,
)
# 分布段无句号时：……马达加斯加 a：体前部
_DIST_PANEL = re.compile(
    r"^(?P<head>(?:◆?分布|栖于|产于).+?)"
    r"(?P<tail>\s+[a-zA-Zａ-ｚ][:：].+)$",
    re.S,
)
_PANEL_ONLY = re.compile(
    r"^[a-zA-Zａ-ｚ][:：].*(?:背面|腹面|疣足|刚毛|足刺|吻|咽|齿冠|体前|体中|体后)"
)
_FIG_CAPTION = re.compile(
    r"^(?:Fig\.?\s*|图\s*|図\s*)(?P<num>\d+['′ʹ\"]?[a-zA-Z]?)",
    re.I,
)
_SPECIES_LINE = re.compile(
    r"^(?:[\u4e00-\u9fff]{2,24}(?:属|亞属|亚属|屬|种)?\s+)?"
    r"\*?([A-Z][a-z]{2,})\*?"
    r"(?:\s+\*?([a-z][a-z-]{2,})\*?)?"
    r".{0,40}$"
)
_TAXON_NAME_LINE = re.compile(
    # 可带中文属名前缀：「伪囊鳞虫属 *Paradyte* Pettibone, 1969」
    r"^(?:[\u4e00-\u9fff]{2,24}(?:属|亞属|亚属|屬|种)?\s+)?"
    r"\*?([A-Z][a-z]{2,})\*?"
    r"(?:\s+\*?([a-z][a-z-]{2,})\*?)?"
    r"(?:"
    r"\s+\([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]*\)"  # (Author)
    r"|\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]*(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.']*){0,2}"  # Author
    r")?"
    r"(?:,?\s*\d{4}[a-z]?)?"
    r"\.?\s*$"
)
_REF_HEADINGS = {
    "引用文献",
    "参考文献",
    "references",
    "reference",
    "literature cited",
}
# 残缺命名人年份整段（图旁 OCR）：(Pettibone, 199) → 删
_TRUNCATED_AUTHOR_YEAR = re.compile(
    r"^\(\s*[A-ZÀ-Ö][A-Za-zÀ-ÿ.'-]+(?:\s+(?:&\s*)?[A-ZÀ-Ö][A-Za-zÀ-ÿ.'-]+)*"
    r",\s*\d{1,3}\s*\)\s*$"
)
# 文献条目：Author, year. … / 内田…, 1975-1987.
_BIBLIO_LINE = re.compile(
    r"^(?:"
    r"[A-ZÀ-Ö][A-Za-zÀ-ÿ.'-]+(?:,\s*[A-Z]\.)*(?:\s+(?:&\s*|and\s+)?[A-ZÀ-Ö][A-Za-zÀ-ÿ.'-]+)*"
    r",\s*\d{4}"
    # 日文作者名与年份之间不得跨逗号/句号：描述段里嵌入的「Author, 1974」不是书目条目
    # （2001 p139「体長4mm，…… Fauchald, 1974 ……」被整段回退成日文原文并标 ref）
    # 间隙内也不得出现拉丁字母：「分類—チロリ科には Glycera Savigny, 1818」是科介绍里的
    # 属名权威，不是文献（2007 p176、2001 p136 整段被回退成日文原文）
    r"|[\u4e00-\u9fffぁ-ゖァ-ヶー]{2,20}[^,，。．A-Za-z]{0,40},\s*\d{4}"
    r")"
)


_CAPTION_FIG = re.compile(
    r"^(?P<head>(?:Fig\.?\s*|图\s*|図\s*)\d+['′ʹ\"]?[a-zA-Z]?)\s*(?P<rest>.*)$",
    re.I | re.S,
)
# 图号后误留的日名片假名，或被 OCR/初译成假拉丁的单字（ユビシリス→Ubisilis）
_KANA = re.compile(r"[ァ-ヶーぁ-ゖ]+")
_FAKE_LATIN = re.compile(
    r"^(?P<junk>[A-Za-z][A-Za-z-]{2,24})(?=\s+\*?[A-Z][a-z]{2,}|\s*$)"
)


def _scrub_caption_ocr_junk(blocks: list[dict], changed: list[dict]) -> None:
    """删图题里 Fig.N 后的日名残片/假拉丁（今岛 Fig.3 ユビシリス→Ubisilis）。"""
    for block in blocks:
        if block.get("role") != "caption":
            continue
        text = _norm(block.get("translation"))
        src = _norm(block.get("text"))
        m = _CAPTION_FIG.match(text or "")
        if not m:
            continue
        head, rest = m.group("head"), (m.group("rest") or "").strip()
        if not rest:
            continue
        new_rest = rest.lstrip(".．。 ")
        # 片假名整段去掉（日名应走「日名「…」」块，不进图题）
        if _KANA.search(new_rest):
            # ムカイシマシリス（向岛裂虫）→ 向岛裂虫；纯假名则清空
            new_rest = re.sub(
                r"[ァ-ヶーぁ-ゖ]+（([^）]+)）",
                r"\1",
                new_rest,
            )
            new_rest = _KANA.sub("", new_rest).strip(" ，,")
        # 假拉丁单字后紧跟真属名/双名 → 删假字（Ubisilis *Exogone…*）
        fake = _FAKE_LATIN.match(new_rest)
        if fake:
            after = new_rest[fake.end() :].lstrip(" ，,")
            if after.startswith("*") or re.match(
                r"[A-Z][a-z]{2,}(?:\s+[a-z]|\s+\()", after
            ):
                new_rest = after
            elif src and _KANA.search(src):
                # 源文是假名图题，译文这一个拉丁词就是误译
                new_rest = after
        new_text = (head + (" " + new_rest if new_rest else "")).strip()
        if new_text != text:
            block["translation"] = new_text
            changed.append({
                "rule": "scrub_caption_ocr_junk",
                "block_id": block.get("block_id"),
                "before": text[:80],
                "after": new_text[:80],
            })


# 命名人被误译成「沙蚕目」；(沙蚕目 Grube, 1878)→(Grube, 1878)
_POLYCHAETA_AS_AUTHOR = re.compile(
    r"([（(])\s*沙\s*蚕\s*目\s*[，,]?\s*"
)
_DUP_BINOM_AFTER_TITLE = re.compile(
    r"^(?P<head>(?:图|図)\s*\d+\s+"
    r"\*?[A-Z][a-z]{2,}\*?\s+\*?[a-z][a-z-]+\*?"
    r"(?:\s*[（(][^）)]{0,40}[）)])?)"
    r"(?P<dup>(?:\s+\*?[A-Z][a-z]{2,}\*?(?:\s+\*?[a-z][a-z-]+\*?)?"
    r"(?:\s*[（(][^）)]{0,40}[）)])?)+)"
    r"(?P<tail>.*)$"
)
_OCR_PANEL_PREFIX = re.compile(r"^[A-Z]?C?\d{4,}\s+(?=[a-zA-Zａ-ｚ][:：])")
_LEGEND_TRAILING_SPECIES = re.compile(
    r"\s+\*?[A-Z][a-z]{2,}\*?\s+\*?[a-z][a-z-]+\*?.*$"
)
# 种名行粘了空日名：「图43 日名「」 饭冢脆鳞虫 *Genus…」
_EMPTY_WANAME_IN_TITLE = re.compile(r"日名\s*[「『]\s*[」』]\s*")
# 描述被切成「……23」+「、26、29、32体节」
_BODY_COMMA_CONTINUATION = re.compile(r"^[、，,]\d")


def _join_comma_body_continuations(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """把以「、26、29体节」开头的残段拼回上一段描述。"""
    out: list[dict] = []
    for block in blocks:
        if block.get("_drop"):
            out.append(block)
            continue
        text = _norm(block.get("translation"))
        if (
            out
            and block.get("role") == "body"
            and out[-1].get("role") == "body"
            and text
            and _BODY_COMMA_CONTINUATION.match(text)
            and not (out[-1].get("translation") or "").startswith(("日名", "和名", "◆", "分布"))
        ):
            prev = out[-1]
            prev_t = _norm(prev.get("translation"))
            prev["translation"] = f"{prev_t}{text}"
            block["_drop"] = True
            changed.append({
                "rule": "join_comma_body_continuation",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
                "into": prev.get("block_id"),
            })
        out.append(block)
    blocks[:] = out


def _looks_like_taxon_authority_line(text: str) -> bool:
    """属/亚科标题「Genus Author, year」勿当书目（否则会吃掉居中标题）。"""
    t = _norm(text)
    if not t:
        return False
    if _TAXON_NAME_LINE.match(t.replace("（", "(").replace("）", ")")):
        return True
    if re.match(
        r"^(?:[\u4e00-\u9fff]{2,24}(?:属|亞属|亚属|屬|种)?\s+)?"
        r"\*?[A-Z][A-Za-z-]{2,}\*?"
        r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]*)+(?:,\s*\d{4}[a-z]?)?\s*$",
        t,
    ):
        return True
    if re.match(
        r"^(?:亚科|亞科|总科|科|族|属|屬)\s+\*?[A-Z][A-Za-z-]{3,}",
        t,
    ):
        return True
    return False


def _prefer_source_for_bibliography(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """文献不翻译：书目行用源文（日/英），不保留简译标题。"""
    in_refs = False
    for block in blocks:
        tr = _norm(block.get("translation"))
        src = _norm(block.get("text"))
        if tr.casefold() in _REF_HEADINGS or (src and src.casefold() in _REF_HEADINGS):
            in_refs = True
            continue
        role = block.get("role")
        if role == "heading" and tr and len(tr) < 80:
            # 新章节结束文献区；属/种标题本身不是书目
            if tr.casefold() not in _REF_HEADINGS:
                in_refs = False
            continue
        # 属/亚科/种名权威行 ≠ 书目
        if _looks_like_taxon_authority_line(tr) or _looks_like_taxon_authority_line(src):
            continue
        # 种记述引证「Genus species : Author, year, pp.」保持 citation/ref，不整段替换丢格式
        if re.match(
            # 冒号必须在开头 80 字内：长段正文里的 [TN: ...] 不是引证（2009 p249 误标 ref）
            r"^\*?[A-Z][a-z].{0,80}?\s*:\s*[A-ZÀ-Ö].{0,300}\d{4}",
            tr or "",
        ):
            if role not in ("ref", "citation"):
                block["role"] = "ref"
                changed.append({
                    "rule": "species_citation_role_ref",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })
            continue
        looks_biblio = bool(src and _BIBLIO_LINE.match(src)) or bool(
            tr and _BIBLIO_LINE.match(tr)
        )
        # 真正的书目还常带刊名/页码；纯「Name Name, year」太像属名权威行
        biblio_rich = bool(
            re.search(
                r"(?:pp?\.|pls?\.|figs?\.|Journal|Bull\.|Proc\.|Mem\.|"
                r"报告|専報|研究|南紀|南纪|生物)",
                (src or "") + " " + (tr or ""),
                re.I,
            )
        )
        # 文献区 / 已标 ref·citation / 富书目行（内田…等误标 body）
        use = in_refs or role in ("ref", "citation") or (looks_biblio and biblio_rich)
        if not use or not src:
            continue
        # 文献区之外的日文散文（描述段/科介绍）不是书目：保留译文，不回退源文
        if not in_refs and looks_like_japanese_prose(src):
            continue
        if not (looks_biblio and biblio_rich) and role not in ("ref", "citation") and not in_refs:
            continue
        # 源文已是文献原文；译文被译成简体/中文题名时回退
        if tr == src:
            if role not in ("ref", "citation"):
                block["role"] = "ref"
                changed.append({
                    "rule": "bibliography_role_ref",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })
            continue
        # 仅当译文相对源文被「译」过（含汉字简写题名）才回退；英文书目保持
        src_has_jp = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", src))
        tr_simplified = src_has_jp and tr != src
        if not tr_simplified and role not in ("ref", "citation") and not in_refs:
            # 英文书目误标 body：升 role，不改文
            if looks_biblio and biblio_rich and role == "body":
                block["role"] = "ref"
                changed.append({
                    "rule": "bibliography_role_ref",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })
            continue
        block["translation"] = src
        block["role"] = "ref"
        changed.append({
            "rule": "bibliography_prefer_source",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
            "sample": src[:100],
        })


def _scrub_truncated_author_year(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """删整段残缺命名人年份，如 (Pettibone, 199)。"""
    for block in blocks:
        text = _norm(block.get("translation"))
        if not text or not _TRUNCATED_AUTHOR_YEAR.match(text):
            continue
        block["_drop"] = True
        changed.append({
            "rule": "drop_truncated_author_year",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
            "text": text,
        })


# 图注/正文末尾残缺引证：(Miura &  / (Pettibone, 199
_TRUNCATED_CITE_TAIL = re.compile(
    r"[（(]\s*"
    r"(?P<head>[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]+"
    r"(?:\s*(?:&|and|et)\s*[A-ZÀ-ÖØ-Ý]?[A-Za-zÀ-ÿ.']*)?)"
    r"(?:\s*,\s*\d{1,3})?"
    r"\s*$"
)
# 完整 Author[, Author][, year[a]]
_FULL_AUTHOR_YEAR = re.compile(
    r"\b(?P<full>"
    r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]+"
    r"(?:\s*(?:&|and|et)\s*[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ.'-]+)*"
    r",\s*\d{4}[a-z]?"
    r")\b"
)


def complete_truncated_citation(text: str, evidence: str) -> str | None:
    """用同页/同块完整引证补全残尾。不明则返回 None（不瞎补）。"""
    t = _norm(text)
    ev = _norm(evidence)
    if not t or not ev:
        return None
    m = _TRUNCATED_CITE_TAIL.search(t)
    if m is None:
        return None
    head = re.sub(r"\s+", " ", m.group("head")).strip()
    # 至少要有姓；「Author &」半截也收
    head_key = re.split(r"\s*(?:&|and|et)\s*", head, maxsplit=1)[0].rstrip(" ,.")
    if len(head_key) < 3:
        return None
    candidates: list[str] = []
    for fm in _FULL_AUTHOR_YEAR.finditer(ev):
        full = fm.group("full")
        if full.casefold().startswith(head_key.casefold()):
            # 「Author &」半截：完整式须含 &/and 第二作者
            if "&" in head or re.search(r"\b(?:and|et)\b", head, re.I):
                if not re.search(r"\s*(?:&|and|et)\s*[A-Z]", full, re.I):
                    continue
            candidates.append(full)
    # 唯一候选才补；多个不同完整式 → 不猜
    uniq = list(dict.fromkeys(candidates))
    if len(uniq) != 1:
        return None
    full = uniq[0]
    # 统一成半角括号形式，贴在原文截断位置
    prefix = t[: m.start()].rstrip()
    return f"{prefix} ({full})" if prefix else f"({full})"


def _complete_truncated_citations(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """图注/legend 末尾 (Miura & → 用同页完整引证补全。"""
    page_text = "\n".join(
        _norm(b.get("translation")) or _norm(b.get("text"))
        for b in blocks
        if not b.get("_drop")
    )
    for block in blocks:
        if block.get("_drop"):
            continue
        role = block.get("role")
        if role not in ("legend", "caption", "body", "note"):
            continue
        text = _norm(block.get("translation"))
        if not text or not _TRUNCATED_CITE_TAIL.search(text):
            continue
        # 证据：同页其他块优先，其次本块前缀
        others = "\n".join(
            _norm(b.get("translation"))
            for b in blocks
            if b is not block and not b.get("_drop")
        )
        fixed = complete_truncated_citation(text, others or page_text)
        if fixed is None:
            # 本块内若前半已有完整引证也可
            fixed = complete_truncated_citation(text, text)
        if fixed is None or fixed == text:
            continue
        block["translation"] = fixed
        changed.append({
            "rule": "complete_truncated_citation",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
            "before": text[-40:],
            "after": fixed[-60:],
        })


# 中文译文图号：日文「図N」→简体「图N」。lookahead 数字，避免误伤「図鑑」「図版」。
_ZU_AS_FIG_NUM = re.compile(r"図(?=\s*\d)")


def scrub_zu_fig_to_tu(text: str) -> str:
    """中文输出统一图号用字：図99 → 图99（源文字段 text 可保留日文図）。"""
    return _ZU_AS_FIG_NUM.sub("图", text or "")


def _scrub_imajima_title_and_ocr_junk(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """清图N种名行重复双名/「沙蚕目」假命名人、空日名、C00000 残片、图注尾粘种名。"""
    for block in blocks:
        role = block.get("role")
        text = _norm(block.get("translation"))
        if not text:
            continue

        # 中文稿：heading/caption/body/key/legend 内「図N」→「图N」
        if role in ("heading", "caption", "body", "key", "legend"):
            tu = scrub_zu_fig_to_tu(text)
            if _TARGET_LANG == "en":   # 英文版：図N/图N → Fig. N，不得留汉字
                tu = re.sub(r"[図图]\s*(\d+)", r"Fig. \1", text)
            if tu != text:
                block["translation"] = tu
                changed.append({
                    "rule": "scrub_zu_fig_to_tu",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                    "before": text[:80],
                    "after": tu[:80],
                })
                text = tu

        # OCR 页码残片「C00000 a：…」→ 当作 legend
        if role == "body" and _OCR_PANEL_PREFIX.match(text):
            cleaned = _OCR_PANEL_PREFIX.sub("", text).strip()
            block["translation"] = cleaned
            block["role"] = "legend"
            changed.append({
                "rule": "scrub_ocr_panel_prefix",
                "block_id": block.get("block_id"),
                "page": page.get("page"),
            })
            text = cleaned
            role = "legend"

        def _strip_polychaeta(s: str) -> str:
            s2 = _POLYCHAETA_AS_AUTHOR.sub(r"\1", s)
            s2 = re.sub(r"([（(])\s*[，,]\s*", r"\1", s2)
            return s2

        if role in ("heading", "caption", "legend", "body"):
            new = _strip_polychaeta(text)
            if new != text:
                block["translation"] = new
                changed.append({
                    "rule": "scrub_polychaeta_as_author",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                    "sample": new[:100],
                })
                text = new

        if role in ("heading", "caption") and re.match(r"^(?:图|図)\s*\d+", text):
            cleaned = _EMPTY_WANAME_IN_TITLE.sub("", text)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            if cleaned != text:
                block["translation"] = cleaned
                changed.append({
                    "rule": "scrub_empty_waname_in_title",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                    "after": cleaned[:100],
                })
                text = cleaned
            m = _DUP_BINOM_AFTER_TITLE.match(text)
            if m and m.group("dup"):
                # 只留首个「图N *种名* (命名人)」；去掉重复粘连
                kept = m.group("head").strip()
                # 若 head 括号只剩年份，试从 dup 段取带命名人的括号
                if re.search(r"[（(]\s*\d{4}\s*[）)]", kept):
                    better = re.search(
                        r"[（(]\s*[A-ZÀ-Ö][^）)]*\d{4}\s*[）)]",
                        m.group("dup"),
                    )
                    if better:
                        kept = re.sub(
                            r"[（(][^）)]*[）)]\s*$",
                            better.group(0),
                            kept,
                        )
                kept = _strip_polychaeta(kept)
                kept = _EMPTY_WANAME_IN_TITLE.sub("", kept)
                kept = re.sub(r"\s{2,}", " ", kept).strip()
                block["translation"] = kept
                changed.append({
                    "rule": "scrub_dup_species_title",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                    "before": text[:100],
                    "after": kept[:100],
                })
                text = kept

        if role == "legend":
            # 图注末尾误粘种名行
            stripped = _LEGEND_TRAILING_SPECIES.sub("", text).rstrip(" 。．;")
            stripped = _strip_polychaeta(stripped)
            if stripped != text and re.search(r"[a-zA-Zａ-ｚ][:：]", stripped):
                block["translation"] = stripped
                changed.append({
                    "rule": "scrub_legend_trailing_species",
                    "block_id": block.get("block_id"),
                    "page": page.get("page"),
                })


def _split_distribution_lettering(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """今岛式：分布段后的「a：体前部…」是图注，必须拆出（docs/monograph_layout_ja.md）。"""
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.get("role") != "body":
            i += 1
            continue
        text = _norm(block.get("translation"))
        m = _PANEL_LEGEND.match(text) or _DIST_PANEL.match(text)
        if not m:
            i += 1
            continue
        head, tail = m.group("head").strip(), m.group("tail").strip()
        letters = re.findall(r"[a-zA-Zａ-ｚ][:：]", tail)
        if len(letters) < 2 and not re.search(
            r"(背面|腹面|疣足|刚毛|足刺|咽|齿冠)", tail
        ):
            i += 1
            continue
        if not re.search(r"(分布|栖于|产于|模式)", head):
            i += 1
            continue
        block["translation"] = head
        new_block = {
            **{k: v for k, v in block.items() if k != "translation"},
            "block_id": f"{block.get('block_id', 'b')}_leg",
            "role": "legend",
            "translation": tail,
            "level": block.get("level"),
        }
        blocks.insert(i + 1, new_block)
        changed.append({
            "rule": "split_distribution_lettering",
            "block_id": block.get("block_id"),
            "page": page.get("page"),
            "tail": tail[:80],
        })
        i += 2


def _mark_panel_legends(blocks: list[dict], changed: list[dict]) -> None:
    """独立成段的 a：b：c：标成 legend，便于并入 Fig 图题。"""
    for block in blocks:
        if block.get("role") not in ("body", "legend"):
            continue
        text = _norm(block.get("translation"))
        if not text or not _PANEL_ONLY.match(text):
            continue
        if block.get("role") != "legend":
            block["role"] = "legend"
            changed.append({
                "rule": "mark_panel_legend",
                "block_id": block.get("block_id"),
                "sample": text[:60],
            })


_GLUED_GENUS_TAIL = re.compile(
    r"\s+(\*?[A-Z][a-z]{2,}\*?\s+[A-ZÀ-Ö][A-Za-zÀ-ÿ.'-]+(?:,\s*\d{4})?)\s*$"
)
_WA_NAME_START = re.compile(r"^(?:日名|和名)|[ァ-ヶー]{3,}|（新称）\s*$")


def _is_imajima_species_caption(text: str) -> bool:
    """短行「图N *Genus species* Author」——种名标题，不是插图下长图注。"""
    t = _norm(text)
    if not t or not _FIG_CAPTION.match(t):
        return False
    if re.search(r"[a-zA-Zａ-ｚ][:：]", t):
        return False
    # 须含拉丁种名（属+种加词）或至少属名+命名人
    return bool(
        re.search(r"\*?[A-Z][a-z]{2,}\*?\s+\*?[a-z][a-z-]{2,}", t)
        or re.search(r"\*?[A-Z][a-z]{2,}\*?\s+[A-ZÀ-Ö]", t)
    )


def _split_glued_genus_from_caption(cap: str) -> tuple[str, str | None]:
    """图10 *G s* Author *Genus* Author → (种名行, 属名行)。"""
    t = _norm(cap)
    # 去掉已并入的 a：…
    panel = re.search(r"\s+([a-zA-Zａ-ｚ][:：].+)$", t)
    if panel and re.search(r"(背面|疣足|刚毛|足刺|吻)", panel.group(1)):
        t = t[: panel.start()].strip()
    m = _GLUED_GENUS_TAIL.search(t)
    if not m:
        return t, None
    genus = m.group(1).strip()
    head = t[: m.start()].strip()
    # 尾部必须是「仅属名」（无种加词）
    if re.search(r"\*?[A-Z][a-z]{2,}\*?\s+\*?[a-z][a-z-]{2,}", genus):
        return t, None
    if genus and genus not in head:
        return head, genus
    return head, None


def _is_genus_only_heading(block: dict) -> bool:
    if block.get("role") != "heading":
        return False
    pt = _norm(block.get("translation"))
    if not pt:
        return False
    if not _TAXON_NAME_LINE.match(pt.replace("（", "(").replace("）", ")")):
        return False
    return not bool(re.search(r"\*?[A-Z][a-z]+\*?\s+\*?[a-z][a-z-]+", pt))


def _is_wa_name_block(block: dict) -> bool:
    role = block.get("role")
    if role not in ("heading", "body"):
        return False
    nt = _norm(block.get("translation"))
    if not nt:
        return False
    if nt.startswith(("日名", "和名")):
        return True
    return bool(
        _WA_NAME_START.search(nt)
        and len(nt) <= 48
        and re.search(r"[ァ-ヶー]{3,}", nt)
    )


def _is_fig_species_heading_block(block: dict) -> bool:
    """heading「图N *Genus species* …」种名行。"""
    if block.get("role") != "heading":
        return False
    t = _norm(block.get("translation"))
    if not t or not re.match(r"^(?:图|図)\s*\d+", t):
        return False
    if re.search(r"[a-zA-Zａ-ｚ][:：]", t):
        return False
    return bool(re.search(r"[A-Z][a-z]{2,}", t)) and len(t) <= 160


def _is_legend_block(block: dict) -> bool:
    role = block.get("role")
    nt = _norm(block.get("translation"))
    if role == "legend":
        return True
    return role == "body" and bool(_PANEL_ONLY.match(nt or ""))


def _fig_num_of(text: str | None) -> str | None:
    m = re.match(r"^(?:图|図)\s*(\d+)", _norm(text) or "")
    return m.group(1) if m else None


def _binom_from_species_title(text: str) -> str | None:
    """从图N种名行抽出 Genus epithet。"""
    t = _norm(text) or ""
    m = re.search(
        r"\*?([A-Z][a-z]{2,})\*?\s+\*?([a-z][a-z-]{2,})\*?",
        t,
    )
    if not m:
        return None
    return f"{m.group(1)} {m.group(2)}"


def _lookup_zh_vernacular(binom: str | None) -> str | None:
    """yiku 种中文名；查不到不强编。与学名行阶元中文名不同层。"""
    if not binom or _TARGET_LANG == "en":
        return None
    try:
        from .taxonzh import load_higher_taxon_zh

        table = load_higher_taxon_zh()
    except Exception:
        return None
    zh = table.get(binom) or table.get(binom.replace(" ", " "))
    if not zh:
        # try without hybrid markers
        zh = table.get(re.sub(r"\s+", " ", binom))
    if not zh or not re.search(r"[\u4e00-\u9fff]", zh):
        return None
    # 属名「…属」不当作种俗名行
    if zh.endswith("属") and " " not in binom:
        return None
    return zh


def _is_zh_vernacular_block(block: dict) -> bool:
    if block.get("_zh_vernacular"):
        return True
    if block.get("role") not in ("heading", "body"):
        return False
    t = _norm(block.get("translation"))
    if not t or len(t) > 40:
        return False
    if t.startswith(("日名", "和名", "图", "図", "分布", "◆")):
        return False
    if re.search(r"[A-Za-z]", t):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fff·、]{2,24}", t))


def _emit_imajima_species_account(
    out: list[dict],
    *,
    genus_block: dict | None,
    species_heading: dict,
    wa_names: list[dict],
    zh_names: list[dict],
    refs: list[dict],
    bodies: list[dict],
    others: list[dict],
    figure_blocks: list[dict],
    legends: list[dict],
) -> None:
    """物种逻辑块序（硬）：属?→图N+学名→日名→中文名?→文献→描述/分布→图版→图注。

    页首上种图版/图注尾巴不得并入本种开头；本种图版在分布之后。
    """
    if genus_block is not None:
        out.append(genus_block)
    out.append(species_heading)
    for b in wa_names:
        out.append(b)
    for b in zh_names:
        out.append(b)
    for b in refs:
        out.append(b)
    for b in bodies:
        out.append(b)
    for b in others:
        out.append(b)
    for b in figure_blocks:
        out.append(b)
    for lb in legends:
        lb["role"] = "legend"
        out.append(lb)


_FIG_TITLE_ZH = re.compile(
    r"^(?P<figure>(?:图|図)\s*\d+)\s+"
    r"(?:(?P<zh>[\u4e00-\u9fff·、]{2,24})\s+)?"
    r"(?P<rest>\*?[A-Z].*)$"
)
_RANK_ZH_TAIL = re.compile(r"(?:属|亚科|科|目|纲|门)$")


def _split_zh_from_fig_species_title(text: str) -> tuple[str, str | None]:
    """图N [中文] *Genus species* … → (图N *Genus…*, 种中文名或 None)。

    标题行只留图号+拉丁（+命名人）；种中文名另作 `_zh_vernacular`。
    属/科级「…属」从标题去掉，但不当作种俗名行。
    """
    t = _norm(text) or ""
    m = _FIG_TITLE_ZH.match(t)
    if not m:
        return t, None
    zh = m.group("zh")
    cleaned = f"{m.group('figure')} {m.group('rest')}".strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not zh:
        return cleaned, None
    if _RANK_ZH_TAIL.search(zh):
        return cleaned, None
    return cleaned, zh


def _maybe_zh_vernacular_block(
    species_heading: dict,
    existing: list[dict],
    *,
    extracted_zh: str | None = None,
) -> list[dict]:
    """日名下插入中文俗名行；标题拆出的优先，否则 yiku；已有则不重复。"""
    if any(_is_zh_vernacular_block(b) for b in existing):
        return list(existing)
    zh = extracted_zh
    if not zh:
        binom = _binom_from_species_title(species_heading.get("translation") or "")
        zh = _lookup_zh_vernacular(binom)
    if not zh:
        return list(existing)
    block = {
        "block_id": f"{species_heading.get('block_id')}_zhname",
        "role": "heading",
        "level": 4,
        "translation": zh,
        "_zh_vernacular": True,
        "source_page": species_heading.get("source_page"),
    }
    return list(existing) + [block]


_REF_BINOM = re.compile(
    r"(?<!\*)\b([A-Z][a-z]{2,})\s+([a-z][a-z-]{2,})\b(?!\*)"
)
# 文献题名里常见的英文词对，不是属种双名（曾把 Bay and / Polychaetous annelids 包斜体）
_REF_BINOM_STOP2 = frozenset({
    "and", "from", "with", "during", "aus", "der", "des", "die", "und",
    "the", "of", "by", "in", "on", "to", "for", "its", "or", "an", "a",
    "collected", "annelids", "polychaetes", "commensal", "coastal",
    "vicinity", "institute", "marine", "biology", "through", "worms", "expedition", "history",
    "natural", "antarctic", "regions", "iate", "errantia", "sedentaria",
})
_REF_FAMILY_SUFFIX = re.compile(r"(?:idae|inae|oidea|acea)$")
_REF_BINOM_STOP1 = frozenset({
    "marine", "polychaetous", "polychaeta", "polychaetes", "japanese", "annelida",
    "annelids", "the", "on", "report", "families", "errant", "sagami",
    "suruga", "matsushima", "onagawa", "ryukyu", "challenger", "siboga",
    "bay", "sea", "japan", "kamchatka", "bering", "antarctic",
})


def _italicize_ref_citation_binomia(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """文献/引证行：属种双名 Markdown 斜体；命名人年份保持正体。

    只包真正的 Genus species；文献英文题名里的词对一律不包，避免 taxostyle 误报。
    """
    for block in blocks:
        if block.get("role") not in ("ref", "citation"):
            continue
        text = _norm(block.get("translation"))
        if not text:
            continue

        def _wrap(m: re.Match[str]) -> str:
            genus, epithet = m.group(1), m.group(2)
            if genus.lower() in _REF_BINOM_STOP1 or epithet.lower() in _REF_BINOM_STOP2:
                return m.group(0)
            # 科/亚科/总科名（-idae 等）不是属名：Aphroditidae through 不是双名
            if _REF_FAMILY_SUFFIX.search(genus):
                return m.group(0)
            # 种加词几乎不以 -ous/-ing 等英文后缀出现
            if epithet.endswith(("ous", "ing", "tion", "ted", "ies")):
                return m.group(0)
            return f"*{genus} {epithet}*"

        # 已有 *...* 区间内不再包一层：先占位再还原
        held: list[str] = []

        def _hold(m: re.Match[str]) -> str:
            held.append(m.group(0))
            return f"\0ITAL{len(held) - 1}\0"

        protected = re.sub(r"\*[^*]+\*", _hold, text)
        new = _REF_BINOM.sub(_wrap, protected)
        for i, chunk in enumerate(held):
            new = new.replace(f"\0ITAL{i}\0", chunk)
        if new != text:
            block["translation"] = new
            changed.append({
                "rule": "italicize_ref_citation_binomia",
                "page": page.get("page"),
                "block_id": block.get("block_id"),
                "sample": new[:100],
            })


def _demote_zh_from_fig_species_titles(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """种名标题去中文种名，并保证日名后有 `_zh_vernacular`（若有中文名）。"""
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if not _is_fig_species_heading_block(block):
            i += 1
            continue
        cleaned, extracted = _split_zh_from_fig_species_title(
            block.get("translation") or ""
        )
        if cleaned != _norm(block.get("translation")):
            block["translation"] = cleaned
            changed.append({
                "rule": "strip_zh_from_fig_species_title",
                "page": page.get("page"),
                "block_id": block.get("block_id"),
                "zh": extracted,
            })
        zh = extracted
        if not zh:
            zh = _lookup_zh_vernacular(_binom_from_species_title(cleaned))
        # 扫描本种块：已有 zhname 则跳过；否则插在 waname 后 / ref 前
        j = i + 1
        has_zh = False
        insert_at = i + 1
        waname_at = None
        while j < len(blocks):
            nb = blocks[j]
            if _is_fig_species_heading_block(nb) or _is_genus_only_heading(nb):
                break
            if _is_zh_vernacular_block(nb):
                has_zh = True
                break
            if _is_wa_name_block(nb):
                waname_at = j
                insert_at = j + 1
            elif nb.get("role") in ("ref", "citation") and waname_at is None:
                insert_at = j
                break
            j += 1
        if zh and not has_zh:
            blocks.insert(
                insert_at,
                {
                    "block_id": f"{block.get('block_id')}_zhname",
                    "role": "heading",
                    "level": 4,
                    "translation": zh,
                    "_zh_vernacular": True,
                    "source_page": block.get("source_page"),
                },
            )
            changed.append({
                "rule": "insert_zh_vernacular_after_waname",
                "page": page.get("page"),
                "zh": zh,
            })
            i = insert_at + 1
            continue
        i += 1


def _attach_legend_to_caption(blocks: list[dict], page: dict, changed: list[dict]) -> None:
    """今岛种记述硬顺序：图N+学名→日名→中文名?→文献→描述→图版→图注。"""
    out: list[dict] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        cap = _norm(block.get("translation"))
        if block.get("role") != "caption" or not _is_imajima_species_caption(cap):
            out.append(block)
            i += 1
            continue

        title_text, glued_genus = _split_glued_genus_from_caption(cap)
        fig_m = _FIG_CAPTION.match(title_text)
        fig_label = f"图{fig_m.group('num')}" if fig_m else "图"
        fig_num = fig_m.group("num") if fig_m else None

        genus_block = None
        dup_species: list[dict] = []
        own_figs: list[dict] = []
        # 只回吞：本种 figure_only、属名、重复种名。figure 可能在属名之前，须越过属名继续取。
        # 页首 legend / 上种尾巴不回吞。
        while out:
            prev = out[-1]
            pt = _norm(prev.get("translation"))
            role = prev.get("role")
            if (
                prev.get("_figure_only")
                and role == "caption"
                and fig_num
                and _fig_num_of(prev.get("translation")) == fig_num
            ):
                own_figs.insert(0, out.pop())
                continue
            if _is_genus_only_heading(prev) and genus_block is None:
                genus_block = out.pop()
                continue
            if role in ("heading", "body") and _SPECIES_LINE.match(pt or "") and re.search(
                r"[a-z]{3,}", pt or ""
            ):
                if any(
                    tok and tok in title_text
                    for tok in re.findall(r"[A-Z][a-z]{2,}\s+[a-z][a-z-]+", pt or "")
                ):
                    dup_species.append(out.pop())
                    continue
            break

        j = i + 1
        legends: list[dict] = []
        wa_names: list[dict] = []
        zh_names: list[dict] = []
        refs: list[dict] = []
        bodies: list[dict] = []
        others: list[dict] = []
        while j < n:
            nb = blocks[j]
            role = nb.get("role")
            nt = _norm(nb.get("translation"))
            if role == "caption" and not nb.get("_figure_only"):
                if _is_imajima_species_caption(nt or ""):
                    break
            if role == "heading" and (
                _is_imajima_species_caption(nt or "") or _is_fig_species_heading_block(nb)
            ):
                break
            if nb.get("_figure_only") and role == "caption":
                own_figs.append(nb)
                j += 1
                continue
            if _is_legend_block(nb):
                legends.append(nb)
                j += 1
                continue
            if _is_wa_name_block(nb):
                wa_names.append(nb)
                j += 1
                continue
            if _is_zh_vernacular_block(nb):
                zh_names.append(nb)
                j += 1
                continue
            if role in ("ref", "citation"):
                refs.append(nb)
                j += 1
                continue
            if role == "body":
                bodies.append(nb)
                j += 1
                continue
            if _is_genus_only_heading(nb):
                break
            others.append(nb)
            j += 1

        if genus_block is None and glued_genus:
            genus_block = {
                "block_id": f"{block.get('block_id')}_genus",
                "role": "heading",
                "level": 2,
                "translation": glued_genus,
                "text": block.get("text"),
                "source_page": block.get("source_page"),
            }
            changed.append({
                "rule": "split_genus_from_species_caption",
                "page": page.get("page"),
                "genus": glued_genus[:60],
            })

        species_heading = {
            "block_id": block.get("block_id"),
            "role": "heading",
            "level": 3,
            "translation": title_text,
            "text": block.get("text"),
            "source_page": block.get("source_page"),
            "y0": block.get("y0"),
        }
        for d in dup_species:
            d["_drop"] = True
            changed.append({
                "rule": "drop_duplicate_species_before_title",
                "block_id": d.get("block_id"),
            })

        if not own_figs:
            own_figs = [{
                "block_id": f"{block.get('block_id')}_fig",
                "role": "caption",
                "translation": fig_label,
                "_figure_only": True,
                "source_page": block.get("source_page"),
                "y0": block.get("y0"),
            }]
        cleaned_title, extracted_zh = _split_zh_from_fig_species_title(
            species_heading.get("translation") or ""
        )
        if cleaned_title != _norm(species_heading.get("translation")):
            species_heading["translation"] = cleaned_title
        zh_names = _maybe_zh_vernacular_block(
            species_heading, zh_names, extracted_zh=extracted_zh
        )

        _emit_imajima_species_account(
            out,
            genus_block=genus_block,
            species_heading=species_heading,
            wa_names=wa_names,
            zh_names=zh_names,
            refs=refs,
            bodies=bodies,
            others=others,
            figure_blocks=own_figs,
            legends=legends,
        )
        changed.append({
            "rule": "reorder_imajima_species_account",
            "page": page.get("page"),
            "title": cleaned_title[:80],
            "wa": len(wa_names),
            "zh": len(zh_names),
            "legends": len(legends),
        })
        i = j

    blocks[:] = out


def _reorder_imajima_species_blocks(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """已升 heading 的种块：硬序 图N→日名→中文?→文献→描述→图版→图注。

    页首 legend/上种尾巴不回吞；仅把误插在种名前后的本种 `_figure_only` 挪到分布后。
    """
    if not any(_is_fig_species_heading_block(b) for b in blocks):
        return

    out: list[dict] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        if not _is_fig_species_heading_block(block):
            out.append(block)
            i += 1
            continue

        fig_num = _fig_num_of(block.get("translation"))
        genus_block = None
        own_figs: list[dict] = []
        # figure→genus→title：须越过属名回吞本种 _figure_only，否则会留孤儿图并再造一张。
        while out:
            prev = out[-1]
            if (
                prev.get("_figure_only")
                and prev.get("role") == "caption"
                and fig_num
                and _fig_num_of(prev.get("translation")) == fig_num
            ):
                own_figs.insert(0, out.pop())
                continue
            if _is_genus_only_heading(prev) and genus_block is None:
                genus_block = out.pop()
                continue
            break  # 页首 legend 等上种尾巴留在原位

        j = i + 1
        legends: list[dict] = []
        wa_names: list[dict] = []
        zh_names: list[dict] = []
        refs: list[dict] = []
        bodies: list[dict] = []
        others: list[dict] = []
        while j < n:
            nb = blocks[j]
            if _is_fig_species_heading_block(nb):
                break
            if _is_genus_only_heading(nb) and (wa_names or refs or bodies):
                break
            if nb.get("_figure_only") and nb.get("role") == "caption":
                own_figs.append(nb)
                j += 1
                continue
            if _is_legend_block(nb):
                legends.append(nb)
                j += 1
                continue
            if _is_wa_name_block(nb):
                wa_names.append(nb)
                j += 1
                continue
            if _is_zh_vernacular_block(nb):
                zh_names.append(nb)
                j += 1
                continue
            if nb.get("role") in ("ref", "citation"):
                refs.append(nb)
                j += 1
                continue
            if nb.get("role") == "body":
                bodies.append(nb)
                j += 1
                continue
            if _is_genus_only_heading(nb):
                if genus_block is None and not (wa_names or refs or bodies):
                    genus_block = nb
                    j += 1
                    continue
                break
            others.append(nb)
            j += 1

        created_fig = False
        if not own_figs and fig_num:
            own_figs = [{
                "block_id": f"{block.get('block_id')}_fig",
                "role": "caption",
                "translation": f"图{fig_num}",
                "_figure_only": True,
                "source_page": block.get("source_page"),
                "y0": block.get("y0"),
            }]
            created_fig = True

        cleaned_title, extracted_zh = _split_zh_from_fig_species_title(
            block.get("translation") or ""
        )
        if cleaned_title != _norm(block.get("translation")):
            block["translation"] = cleaned_title
        zh_names = _maybe_zh_vernacular_block(
            block, zh_names, extracted_zh=extracted_zh
        )
        _emit_imajima_species_account(
            out,
            genus_block=genus_block,
            species_heading=block,
            wa_names=wa_names,
            zh_names=zh_names,
            refs=refs,
            bodies=bodies,
            others=others,
            figure_blocks=own_figs,
            legends=legends,
        )
        changed.append({
            "rule": "reorder_imajima_species_blocks",
            "page": page.get("page"),
            "title": cleaned_title[:80],
            "figs": len(own_figs),
            "legends": len(legends),
            "wa": len(wa_names),
            "zh": len(zh_names),
            "created_fig": created_fig,
        })
        i = j

    blocks[:] = out


_BARE_FIG = re.compile(r"^(?:图|図)\s*(?P<num>\d+)\s*$")
_SPECIES_BINOM_LINE = re.compile(
    r"^(?:[\u4e00-\u9fff]{2,24}(?:属|种)?\s+)?"
    r"\*?([A-Z][a-z]{2,})\*?\s+\*?([a-z][a-z-]{2,})\*?"
    r".{0,60}$"
)


def _merge_bare_fig_with_species(
    blocks: list[dict], page: dict, changed: list[dict]
) -> None:
    """裸「图7」+ 邻行种名 → 「图7 *Genus species* …」种名标题；插图另留 _figure_only。"""
    out: list[dict] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        cap = _norm(block.get("translation"))
        if block.get("role") == "caption" and _BARE_FIG.match(cap or ""):
            fig_m = _BARE_FIG.match(cap)
            fig_label = f"图{fig_m.group('num')}" if fig_m else cap
            species = None
            # 优先上一块种名（属标题后常见）
            if out:
                prev = out[-1]
                pt = _norm(prev.get("translation"))
                if prev.get("role") in ("body", "heading") and _SPECIES_BINOM_LINE.match(
                    pt or ""
                ):
                    species = out.pop()
            # 否则下一块
            if species is None and i + 1 < n:
                nxt = blocks[i + 1]
                nt = _norm(nxt.get("translation"))
                if nxt.get("role") in ("body", "heading") and _SPECIES_BINOM_LINE.match(
                    nt or ""
                ):
                    species = nxt
                    i += 1
            if species is not None:
                st = _norm(species.get("translation"))
                title = f"{fig_label} {st}".strip()
                # 种名在前；_figure_only 暂随其后，由 _reorder_imajima_species_blocks 挪到分布后
                out.append({
                    "block_id": species.get("block_id") or block.get("block_id"),
                    "role": "heading",
                    "level": 3,
                    "translation": title,
                    "text": species.get("text") or block.get("text"),
                    "source_page": block.get("source_page"),
                    "y0": block.get("y0"),
                })
                out.append({
                    "block_id": f"{block.get('block_id')}_fig",
                    "role": "caption",
                    "translation": fig_label,
                    "_figure_only": True,
                    "source_page": block.get("source_page"),
                    "y0": block.get("y0"),
                })
                changed.append({
                    "rule": "merge_bare_fig_with_species",
                    "page": page.get("page"),
                    "title": title[:80],
                })
                i += 1
                continue
        out.append(block)
        i += 1
    blocks[:] = out


def _promote_taxon_name_heading(blocks: list[dict], changed: list[dict]) -> None:
    """属/种名独占一行时升为标题，避免与下一段挤在一起。"""
    for block in blocks:
        if block.get("role") not in ("body", "caption"):
            continue
        text = _norm(block.get("translation"))
        if not text or len(text) > 120:
            continue
        if text.startswith(("分布", "◆", "形态", "体长")):
            continue
        # 図/图N 种名行 → heading（与插图 caption 区分）
        if _is_imajima_species_caption(text) or (
            re.match(r"^(?:图|図)\s*\d+", text)
            and re.search(r"[A-Z][a-z]{2,}", text)
            and not re.search(r"[a-zA-Zａ-ｚ][:：]", text)
            and len(text) <= 120
        ):
            if block.get("role") != "heading":
                block["role"] = "heading"
                block["level"] = 3
                changed.append({
                    "rule": "promote_fig_species_heading",
                    "block_id": block.get("block_id"),
                    "text": text[:80],
                })
            continue
        if text.startswith(("Fig.", "图", "図")):
            continue
        if not _TAXON_NAME_LINE.match(text.replace("（", "(").replace("）", ")")):
            continue
        # 有种加词 → 种级标题；仅属名 → 属级
        has_species = bool(
            re.search(r"\*?[A-Z][a-z]+\*?\s+\*?[a-z][a-z-]+", text)
        )
        block["role"] = "heading"
        block["level"] = 3 if has_species else 2
        changed.append({
            "rule": "promote_taxon_name_heading",
            "block_id": block.get("block_id"),
            "level": block["level"],
            "text": text[:80],
        })


def _promote_references_heading(blocks: list[dict], changed: list[dict]) -> None:
    """「引用文献」单独成段时升为标题，上下留空。"""
    for block in blocks:
        if block.get("role") not in ("body", "key", "entry"):
            continue
        text = _norm(block.get("translation")).strip()
        if text.casefold() not in _REF_HEADINGS:
            continue
        block["role"] = "heading"
        block["level"] = 2
        changed.append({
            "rule": "promote_references_heading",
            "block_id": block.get("block_id"),
            "text": text[:40],
        })


def _apply_higher_taxon_zh_page(
    blocks: list[dict], changed: list[dict], seen: set[str]
) -> None:
    from .taxonzh import apply_to_blocks

    for item in apply_to_blocks(blocks, seen=seen):
        changed.append(item)


_TARGET_LANG = "zh"  # normalize_aligned(lang=...) 设置；en 版不得注入中文名


def normalize_aligned(data: dict[str, Any], lang: str = "zh") -> dict[str, Any]:
    """Apply every deterministic repair in place; return a change report.

    lang="en"：不注入科/亚科/种的中文名（英文版不得含中文）。
    """
    global _TARGET_LANG
    _TARGET_LANG = lang
    changed: list[dict] = []
    higher_seen: set[str] = set()
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
        _key_heading_from_body(blocks, changed)
        _trim_key_dump_heading(blocks, changed)
        _body_leaders_to_key(blocks, changed)
        _body_couplet_number_to_key(blocks, changed)
        # 种记述误升 key、文献误标等：与 repair-keys 同规则，normalize 时一并收掉
        from .keyrepair import repair_key_blocks as _repair_keys_page

        page_wrap = {"pages": [page]}
        rep = _repair_keys_page(page_wrap)
        for ch in rep.get("changes") or []:
            changed.append({"rule": f"repair_keys:{ch.get('action')}", **ch})
        _fix_partial_kana_glosses(blocks, changed)
        _index_leaders_to_entry(page, blocks, changed)
        _leading_punctuation(blocks, changed)
        _box_glyph_to_kou(blocks, changed)
        _caption_duplicate(blocks, page, changed)
        _caption_lettering_tail(blocks, page, changed)
        _caption_terms(blocks, changed)
        _scrub_caption_ocr_junk(blocks, changed)
        _split_distribution_lettering(blocks, page, changed)
        _mark_panel_legends(blocks, changed)
        _attach_legend_to_caption(blocks, page, changed)
        _scrub_caption_ocr_junk(blocks, changed)  # 并入种名后再清一次假拉丁
        _scrub_imajima_title_and_ocr_junk(blocks, page, changed)
        _scrub_truncated_author_year(blocks, page, changed)
        _complete_truncated_citations(blocks, page, changed)
        _prefer_source_for_bibliography(blocks, page, changed)
        _join_comma_body_continuations(blocks, page, changed)
        _merge_bare_fig_with_species(blocks, page, changed)
        _promote_taxon_name_heading(blocks, changed)
        # 种名已升 heading：硬序 图N→日名→中文?→文献→描述→图版→图注
        _reorder_imajima_species_blocks(blocks, page, changed)
        _promote_references_heading(blocks, changed)
        if _TARGET_LANG != "en":
            _apply_higher_taxon_zh_page(blocks, changed, higher_seen)
        # taxonzh 后仍可能残留：种名标题去中文；文献双名斜体
        _demote_zh_from_fig_species_titles(blocks, page, changed)
        _italicize_ref_citation_binomia(blocks, page, changed)
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
        page["blocks"] = [b for b in blocks if not b.get("_drop")]
    # Trim overfilled blocks first: once a page-break continuation is joined
    # into the previous page, the duplicated tail can no longer be matched.
    _overflow_duplicate_tail(data, changed)
    _merge_cross_page_paragraphs(data.get("pages", []), changed)
    _attach_legend_across_pages(data.get("pages", []), changed)
    _clean_page_chapters(data.get("pages", []), changed)
    return {
        "changes": changed,
        "changed_blocks": len(changed),
        "changed_pages": len({c.get("page", c.get("block_id", "")[:5]) for c in changed}),
    }


def _clean_page_chapters(pages: list[dict], changed: list[dict]) -> None:
    """Wash dirty page.chapter (key couplet / TOC junk) down to chapter titles.

    build_aligned may promote a key-shaped「亚科 …种名（图N）」line to chapter;
    clean_toc_title already exists for CONTENTS display — apply the same wash
    to the stored field so headers/qa/page_map stop carrying the junk.
    """
    from .builder import clean_toc_title

    for page in pages:
        raw = page.get("chapter")
        if not isinstance(raw, str) or not raw.strip():
            continue
        source = ""
        for b in page.get("blocks") or []:
            if (
                b.get("role") == "heading"
                and b.get("level") == 1
                and (b.get("text") or b.get("translation"))
            ):
                source = b.get("text") or ""
                break
        cleaned = clean_toc_title(raw, source=source)
        if cleaned == raw:
            continue
        page["chapter"] = cleaned
        changed.append(
            {
                "rule": "clean_page_chapter",
                "page": page.get("page"),
                "before": raw,
                "after": cleaned,
            }
        )


def _attach_legend_across_pages(pages: list[dict], changed: list[dict]) -> None:
    """上页末的 a：… 挪到下页 caption 之后（插图常跨页；不并进图题短行）。"""
    for prev, nxt in zip(pages, pages[1:]):
        a_blocks = prev.get("blocks") or []
        b_blocks = nxt.get("blocks") or []
        if not a_blocks or not b_blocks:
            continue
        trailing: list[dict] = []
        for block in reversed(a_blocks):
            if block.get("_drop"):
                continue
            role = block.get("role")
            text = _norm(block.get("translation"))
            if role == "legend" or (role == "body" and _PANEL_ONLY.match(text or "")):
                trailing.append(block)
                continue
            break
        if not trailing:
            continue
        trailing.reverse()
        # 本页已是「图N占位 + a/b/c」成套，勿把图注挪到下页
        kept = [b for b in a_blocks if b not in trailing and not b.get("_drop")]
        if kept and kept[-1].get("role") == "caption" and kept[-1].get("_figure_only"):
            continue
        cap_i = next(
            (i for i, b in enumerate(b_blocks) if b.get("role") == "caption"),
            None,
        )
        if cap_i is None:
            continue
        for b in trailing:
            b["role"] = "legend"
            b.pop("_drop", None)
        # 从上页移除，插入下页 caption 后
        prev["blocks"] = [b for b in a_blocks if b not in trailing]
        insert_at = cap_i + 1
        nxt["blocks"] = b_blocks[:insert_at] + trailing + b_blocks[insert_at:]
        changed.append({
            "rule": "attach_legend_across_pages",
            "from_page": prev.get("page"),
            "to_page": nxt.get("page"),
            "caption": b_blocks[cap_i].get("block_id"),
            "n": len(trailing),
        })


def apply_page_patch(data: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Replace selected pages' block lists from a declarative patch.

    Patch format::

        {"pages": {"352": [{"block_id": "p352_b07", "role": "body",
                            "level": 2, "translation": "..."}, ...]}}

    Existing blocks are looked up by ``block_id`` so their geometry survives;
    blocks whose id is new are appended with only the fields given.
    """
    applied = []
    by_page = {page["page"]: page for page in data.get("pages", [])}
    for number, entries in patch.get("pages", {}).items():
        page = by_page[int(number)]
        existing = {b.get("block_id"): b for b in page["blocks"]}
        new_blocks = []
        for entry in entries:
            block = dict(existing.get(entry["block_id"], {}))
            block.setdefault("block_id", entry["block_id"])
            block.setdefault("source_page", str(number))
            block.setdefault("chapter", page.get("chapter", ""))
            block.setdefault("kind", page.get("kind", ""))
            block.setdefault("level", 1)
            for field in ("role", "translation", "level"):
                if field in entry:
                    block[field] = entry[field]
            new_blocks.append(block)
        page["blocks"] = new_blocks
        applied.append(int(number))
    return {"patched_pages": applied}
