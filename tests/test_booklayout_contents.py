"""Issue #14: structured contents entries with aligned page references."""
from __future__ import annotations

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER

from booklayout.builder import TEXT_W, setup
from booklayout.contents import (
    ContentsEntry,
    check_contents_paragraphs,
    parse_contents,
    render_contents,
)

SYNTHETIC = """\
1. Introduction ........ 7
1.1 Scope of the
    present revision and its
    limits ..... 9
2. Systematic account .... 15
2.1 Family Testidae ..... 15
2.1.1 Genus Alpha ...... 16
Acknowledgments ........ ix
"""


def test_parse_multiline_multilevel() -> None:
    entries, rest = parse_contents(SYNTHETIC)
    assert rest == []
    assert [e.level for e in entries] == [0, 1, 0, 1, 2, 0]
    assert entries[1].title == "1.1 Scope of the present revision and its limits"
    assert [e.source_page for e in entries] == ["7", "9", "15", "15", "16", "ix"]
    assert all(e.output_page is None for e in entries)


def test_flattened_paragraph_is_split_into_entries() -> None:
    flat = "Introduction ...... 7 Methods ...... 9 Results ...... 15 Discussion .... 30"
    entries, rest = parse_contents(flat)
    assert [e.title for e in entries] == ["Introduction", "Methods", "Results", "Discussion"]
    assert [e.source_page for e in entries] == ["7", "9", "15", "30"]
    assert rest == []


def test_indentation_gives_level_when_unnumbered() -> None:
    text = "Part One ..... 1\n  Chapter A ..... 3\n    Section x ..... 4\nPart Two ..... 9\n"
    entries, _ = parse_contents(text)
    assert [e.level for e in entries] == [0, 1, 2, 0]


def test_unparsed_lines_are_reported_not_dropped() -> None:
    entries, rest = parse_contents("Preface ..... 3\nstray words without page\n")
    assert len(entries) == 1
    assert rest == ["stray words without page"]


def _entries() -> list[ContentsEntry]:
    entries, _ = parse_contents(SYNTHETIC)
    for e, out in zip(entries, ["8", "10", "16", "16", "17", "x"]):
        e.output_page = out
    return entries


def test_render_uses_tab_leaders_levels_and_output_pages() -> None:
    doc = Document()
    setup(doc)
    render_contents(doc, _entries())
    pars = doc.paragraphs
    assert len(pars) == 6
    for par in pars:
        stops = list(par.paragraph_format.tab_stops)
        assert len(stops) == 1
        assert stops[0].alignment == WD_TAB_ALIGNMENT.RIGHT
        assert stops[0].leader == WD_TAB_LEADER.DOTS
        assert abs(stops[0].position.mm - TEXT_W) < 0.01
        assert par.text.count("\t") == 1
        assert "   " not in par.text
    # Output pages, not source pages, are printed.
    assert pars[0].text.endswith("\t8")
    assert pars[1].text.endswith("\t10")
    # Deeper entries are indented, wrapped lines hang.
    assert pars[1].paragraph_format.left_indent.mm > pars[0].paragraph_format.left_indent.mm
    assert pars[4].paragraph_format.left_indent.mm > pars[3].paragraph_format.left_indent.mm
    assert pars[1].paragraph_format.first_line_indent.mm < 0


def test_unresolved_output_page_is_marked_as_source_page() -> None:
    entries, _ = parse_contents("Preface ..... 3\n")
    doc = Document()
    setup(doc)
    render_contents(doc, entries, source_label="src. p. ")
    assert doc.paragraphs[0].text.endswith("\tsrc. p. 3")


def test_check_accepts_rendered_and_flags_flattened() -> None:
    doc = Document()
    setup(doc)
    render_contents(doc, _entries())
    assert check_contents_paragraphs(doc.paragraphs, expected=6) == []
    bad = Document()
    setup(bad)
    bad.add_paragraph("Introduction ...... 7 Methods ...... 9 Results ...... 15")
    bad.add_paragraph("Padded title          12")
    problems = check_contents_paragraphs(bad.paragraphs, expected=3)
    reasons = {p["reason"] for p in problems}
    assert {"no_tab_leader", "hand_padding", "entry_count"} <= reasons


def test_build_contents_block_passes_render_check(tmp_path) -> None:
    from pathlib import Path

    from booklayout.builder import BookPaths, build
    from tests.test_booklayout import make_book  # noqa: PLC0415

    aligned, figs, meta = make_book(Path(tmp_path))
    out = Path(tmp_path) / "book.docx"
    build(out, {"1": 5, "2": 6}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    pars = Document(str(out)).paragraphs
    start = next(i for i, p in enumerate(pars) if p.text == meta.contents_title)
    block = []
    for p in pars[start + 1:]:
        if "\t" not in p.text:
            break
        block.append(p)
    assert block, "contents entries are one paragraph each"
    assert check_contents_paragraphs(block) == []
    assert block[0].text.endswith("\t5")
