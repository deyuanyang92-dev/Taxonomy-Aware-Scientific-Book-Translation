"""English word list used to keep prose out of scientific-name italics.

The builder italicises generic names and their epithets.  A genus-like
capitalised word followed by an ordinary English word ("Lopadorrhynchus
comprises the") must not become italic: only the genus is a name.  The
word list is the system hunspell dictionary, the same source that
``scripts/taxoformat.py`` uses, so both tools agree on what is English.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ENGLISH_DICT = Path(os.environ.get("BOOKLAYOUT_ENGLISH_DICT",
                                   "/usr/share/hunspell/en_US.dic"))


def load_english_words(path: Path | None = None) -> frozenset[str]:
    """hunspell .dic stems (flags stripped), lower case; missing file -> empty."""
    path = ENGLISH_DICT if path is None else path
    if path is None or not path.exists():
        return frozenset()
    words: set[str] = set()
    try:
        with path.open(encoding="latin-1") as f:
            next(f, None)  # first line is the entry count
            for line in f:
                w = line.split("/", 1)[0].strip().lower()
                if w and w.isalpha():
                    words.add(w)
    except OSError:
        return frozenset()
    return frozenset(words)


_WORDS: frozenset[str] | None = None


def english_words() -> frozenset[str]:
    """Cached word list; empty when the dictionary is not installed."""
    global _WORDS
    if _WORDS is None:
        _WORDS = load_english_words()
    return _WORDS


_SUFFIXES = (("s", ""), ("es", ""), ("ed", ""), ("ed", "e"), ("d", ""),
             ("ing", ""), ("ing", "e"), ("ly", ""))


def is_english_word(word: str, english: frozenset[str] | None = None) -> bool:
    """True when ``word`` or a regular inflection of it is an English word."""
    words = english_words() if english is None else english
    word = word.lower().strip(".,;:()[]")
    if not words or not word:
        return False
    if word in words:
        return True
    for suffix, add in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            if word[:-len(suffix)] + add in words:
                return True
    # doubled consonant + ed/ing: occurred -> occur
    if word.endswith(("ed", "ing")) and len(word) > 4 and word[-3] == word[-4]:
        stem = word[:-3] if word.endswith("ed") else word[:-4]
        if stem in words:
            return True
    return False


GENERA_DB = Path(os.environ.get("BOOKLAYOUT_GENERA_DB",
                                "/root/.specimen_inventory/worms_cache.sqlite"))

# 动物命名法规（ICZN 29.2）的科级名称词尾：总科 -oidea、科 -idae、亚科
# -inae、族 -ini。科级以上阶元（目、纲、门）同样正体，由 WoRMS 的阶元记录
# 提供名称，不靠词尾猜。
FAMILY_GROUP = re.compile(r"(?:idae|inae|ini|oidea)$")
FAMILY_WORD = re.compile(r"\b[A-Z][a-z]{2,}(?:idae|inae|ini|oidea)\b")
# 「Lumbrineridae, Oenonidae」「Syllidae and Nereididae」整串都正体。
FAMILY_RUN = re.compile(
    r"\b[A-Z][a-z]{2,}(?:idae|inae|ini|oidea)"
    r"(?:\s*(?:,|and|y|e|et|&)\s*[A-Z][a-z]{2,}(?:idae|inae|ini|oidea))*\b")
HIGHER_RANKS = ("Superfamily", "Family", "Subfamily", "Tribe", "Subtribe",
                "Superorder", "Order", "Suborder", "Infraorder",
                "Superclass", "Class", "Subclass", "Phylum", "Subphylum",
                "Kingdom", "Subkingdom")


def is_family_group(name: str) -> bool:
    """True for an ICZN family-group name (family, subfamily, tribe, superfamily)."""
    return bool(FAMILY_GROUP.search(name.strip()))


def family_group_words(text: str) -> list[str]:
    """Capitalised family-group names found in ``text``."""
    return FAMILY_WORD.findall(text)


def load_worms_higher_taxa(path: Path | None = None) -> frozenset[str]:
    """Family-group and higher taxon names of Annelida in the local WoRMS cache.

    These are printed in roman; only genus and species-group names are italic
    (zoological convention, user 2026-11-17).  The suffix rule covers names the
    cache lacks; the rank query covers order/class names that have no shared
    ending.
    """
    import sqlite3

    path = GENERA_DB if path is None else path
    if path is None or not path.exists():
        return frozenset()
    names: set[str] = set()
    placeholders = ",".join("?" * len(HIGHER_RANKS))
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = con.execute(
            "select valid_name from worms_taxa "
            f"where phylum='Annelida' and rank in ({placeholders}) "
            "and valid_name is not null",
            HIGHER_RANKS,
        ).fetchall()
    except sqlite3.Error:
        return frozenset()
    finally:
        try:
            con.close()
        except (sqlite3.Error, UnboundLocalError):
            pass
    for (name,) in rows:
        name = (name or "").strip()
        if name and " " not in name:
            names.add(name)
    return frozenset(names)


_HIGHER: frozenset[str] | None = None


def worms_higher_taxa() -> frozenset[str]:
    """Cached higher-taxon list; empty when the cache is not installed."""
    global _HIGHER
    if _HIGHER is None:
        _HIGHER = load_worms_higher_taxa()
    return _HIGHER


def load_worms_genera(path: Path | None = None) -> frozenset[str]:
    """Genus names of Annelida in the local WoRMS cache; empty when absent.

    ``scripts/taxoformat.py`` builds its lexicon from the same database, so
    the builder and the italic audit agree on which words are genera.  A
    name that is not in the cache (a new genus, or a non-annelid book) still
    reaches the set through the Markdown asterisks and the heading heuristics.
    """
    import sqlite3

    path = GENERA_DB if path is None else path
    if path is None or not path.exists():
        return frozenset()
    genera: set[str] = set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = con.execute(
            "select valid_name, rank from worms_taxa "
            "where phylum='Annelida' and valid_name is not null"
        ).fetchall()
    except sqlite3.Error:
        return frozenset()
    finally:
        try:
            con.close()
        except (sqlite3.Error, UnboundLocalError):
            pass
    for name, rank in rows:
        name = (name or "").strip()
        if not name:
            continue
        if rank in ("Genus", "Subgenus"):
            genera.add(name)
        elif rank in ("Species", "Subspecies", "Variety", "Forma") and " " in name:
            # 只有种级名称的首词才是属名。``Syllidae incertae sedis``（Subfamily）
            # 的首词是科名，按首词一律取属会把 Syllidae 收进属名集合、排成斜体。
            genera.add(name.split()[0])
    return frozenset(genera)


_WORMS: frozenset[str] | None = None


def worms_genera() -> frozenset[str]:
    """Cached WoRMS genus list; empty when the cache is not installed."""
    global _WORMS
    if _WORMS is None:
        _WORMS = load_worms_genera()
    return _WORMS
