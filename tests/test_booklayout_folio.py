"""Folio footer checks and builder fixes (MISTAKES H8, Fauna Ibérica Vol. 25, 2026-11-25)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
from docx import Document  # noqa: E402

from booklayout import builder, folio  # noqa: E402
from booklayout.builder import BookMeta  # noqa: E402

META = {"running_left": "<i>ANNELIDA POLYCHAETA</i> I", "running_right": "FAUNA IBÉRICA",
        "own_pages": [1, 2, 3, 4, 5, 6, 7], "folio_start": 4, "folio_first_page": 8}
HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def _tsv(path: Path, words: list[tuple[int, int, str]]) -> Path:
    rows = [HEAD, "1\t1\t0\t0\t0\t0\t0\t0\t1960\t2752\t-1\t\n"]
    rows += [f"5\t1\t1\t1\t1\t{i}\t{x}\t{y}\t60\t22\t95\t{w}\n" for i, (x, y, w) in enumerate(words)]
    path.write_text("".join(rows), encoding="utf-8")
    return path


def test_source_footer_reads_number_and_side_by_position(tmp_path):
    odd = _tsv(tmp_path / "a.tsv", [(185, 2390, "de"), (164, 2490, "ANNELIDA"), (330, 2490, "POLYCHAETA"),
                                    (541, 2491, "1"), (1732, 2495, "13")])
    f = folio.source_footer(odd, 10, META)
    assert (f["number"], f["side"], f["has_footer"]) == (13, "left", True)  # "POLYCHAETA 1" is not the folio
    even = _tsv(tmp_path / "b.tsv", [(185, 2490, "12"), (1500, 2490, "FAUNA"), (1650, 2490, "IBERICA")])
    assert folio.source_footer(even, 9, META)["side"] == "right"
    front = _tsv(tmp_path / "c.tsv", [(500, 1200, "Madrid"), (900, 2000, "1998")])
    assert not folio.source_footer(front, 3, META)["has_footer"]


def test_source_baseline_offset_parity_and_front(tmp_path):
    tsvs = {}
    for p in range(1, 13):
        if p < 8:
            words = [(500, 1200, "Madrid")]
        elif (p + 3) % 2:
            words = [(164, 2490, "ANNELIDA"), (330, 2490, "POLYCHAETA"), (1732, 2495, str(p + 3))]
        else:
            words = [(185, 2490, str(p + 3)), (1500, 2490, "FAUNA"), (1650, 2490, "IBÉRICA")]
        tsvs[p] = _tsv(tmp_path / f"p{p}.tsv", words)
    base = folio.source_baseline(tsvs, META)
    assert base["offset"] == 3 and base["odd_side"] == "left"
    assert base["no_footer"] == [1, 2, 3, 4, 5, 6, 7]


def _pdf(path: Path, pages: int, footer, body_lines: int = 50) -> Path:
    """170x240 mm pages, text block 51-430 pt; footer(page) -> list of (x, text) or None."""
    doc = fitz.open()
    for i in range(1, pages + 1):
        pg = doc.new_page(width=481.9, height=680.3)
        for k in range(body_lines):
            pg.insert_text((51.1, 70 + k * 11), "lorem ipsum dolor sit amet", fontsize=9)
            pg.insert_text((330, 70 + k * 11), "consectetur adip", fontsize=9)
            pg.insert_text((430.5 - fitz.get_text_length("x", fontsize=9), 70 + k * 11), "x", fontsize=9)
        for x, t in footer(i) or []:
            pg.insert_text((x, 651), t, fontsize=8)
    doc.save(path)
    return path


def _right(t: str) -> float:
    return 430.5 - fitz.get_text_length(t, fontsize=8)


def test_qa_flags_the_old_vol25_footers(tmp_path):
    # old Vol. 25: right item at the Word centre tab (x~283), footer on front pages, numbers 1-based
    def old(i):
        return None if i == 1 else ([(51.1, str(i)), (254.1, "FAUNA IBÉRICA")] if i % 2 == 0
                                    else [(51.1, "ANNELIDA POLYCHAETA I"), (283.2, str(i))])
    pdf = _pdf(tmp_path / "old.pdf", 10, old)
    feet, n, left, right = folio.output_footers(pdf, 600)
    probs = folio.qa_problems(feet, n, left, right, BookMeta(**META))
    kinds = {p["kind"] for p in probs}
    assert {"footer_on_front_page", "wrong_folio", "footer_not_flush"} <= kinds
    base = {"offset": 3, "odd_side": "left", "no_footer": list(range(1, 8)),
            "pages": [{"page": p} for p in range(1, 11)]}
    src = {p["kind"] for p in folio.compare_source(base, feet, n, META)}
    assert {"folio_differs_from_source", "footer_not_in_source"} <= src


def test_qa_passes_footers_that_match_the_source(tmp_path):
    def good(i):  # accent-free: Base-14 Helvetica measures É differently from what fitz extracts
        if i < 8:
            return None
        n = i + 3
        return ([(51.1, str(n)), (_right("FAUNA IBERICA"), "FAUNA IBERICA")] if n % 2 == 0
                else [(51.1, "ANNELIDA POLYCHAETA I"), (_right(str(n)), str(n))])
    pdf = _pdf(tmp_path / "good.pdf", 12, good)
    feet, n, left, right = folio.output_footers(pdf, 600)
    assert folio.qa_problems(feet, n, left, right, BookMeta(**META)) == []
    base = {"offset": 3, "odd_side": "left", "no_footer": list(range(1, 8)),
            "pages": [{"page": p} for p in range(1, 13)]}
    assert folio.compare_source(base, feet, n, META) == []


def test_qa_flags_swapped_odd_even_text(tmp_path):
    def swapped(i):  # LibreOffice picked footers by physical page: p8 prints 11 with the even text
        if i < 8:
            return None
        n = i + 3
        return ([(51.1, str(n)), (_right("FAUNA IBÉRICA"), "FAUNA IBÉRICA")] if i % 2 == 0
                else [(51.1, "ANNELIDA POLYCHAETA I"), (_right(str(n)), str(n))])
    pdf = _pdf(tmp_path / "sw.pdf", 10, swapped)
    feet, n, left, right = folio.output_footers(pdf, 600)
    assert any(p["kind"] == "wrong_running_text" for p in folio.qa_problems(feet, n, left, right, BookMeta(**META)))


@pytest.fixture
def folio_profile(monkeypatch):
    monkeypatch.setattr(builder.PROFILE, "footer_style", "folio")


def _folio_doc(meta: BookMeta):
    doc = Document()
    builder.setup(doc)
    builder._blank_header_footer(doc.sections[0])
    builder._set_folio_start(doc.sections[0], meta.folio_start)
    doc.add_paragraph("front")
    builder.start_folio_section(doc, meta)
    doc.add_paragraph("body")
    return doc


def test_builder_front_section_blank_body_section_folio_no_restart(folio_profile):
    meta = BookMeta(**{**META, "folio_bold": False, "footer_italic": False})
    doc = _folio_doc(meta)
    front, body = doc.sections
    assert not "".join(p.text for p in front.footer.paragraphs + front.even_page_footer.paragraphs)
    assert front._sectPr.find(builder.qn("w:pgNumType")).get(builder.qn("w:start")) == "4"
    assert body._sectPr.find(builder.qn("w:pgNumType")) is None  # numbering continues
    fp = body.footer.paragraphs[0]
    runs = [(r.text, r.italic) for r in fp.runs if r.text.strip() and r.text not in ("1",)]
    assert ("ANNELIDA POLYCHAETA", True) in runs and (" I\t", False) in runs
    assert all(not r.bold for r in fp.runs)
    # the style's centre/right tabs are cleared, only the text-block right tab is active
    tabs = [(t.alignment, t.position) for t in fp.paragraph_format.tab_stops]
    from docx.enum.text import WD_TAB_ALIGNMENT
    assert any(a == WD_TAB_ALIGNMENT.CLEAR for a, _ in tabs)
    assert [a for a, _ in tabs if a != WD_TAB_ALIGNMENT.CLEAR] == [WD_TAB_ALIGNMENT.RIGHT]


def test_lo_parity_copy_swaps_only_for_even_start(tmp_path, folio_profile):
    meta = BookMeta(**META)
    doc = _folio_doc(meta)
    doc.save(tmp_path / "a.docx")
    (tmp_path / "o").mkdir()
    cp = folio.lo_parity_copy(tmp_path / "a.docx", tmp_path / "o")
    assert cp is not None
    orig = zipfile.ZipFile(tmp_path / "a.docx").read("word/document.xml").decode()
    new = zipfile.ZipFile(cp).read("word/document.xml").decode()
    pick = lambda s: re.findall(r'w:footerReference w:type="(\w+)" r:id="(\w+)"', s)  # noqa: E731
    assert dict(pick(new))["even"] == dict(pick(orig))["default"]
    meta5 = BookMeta(**{**META, "folio_start": 5})
    _folio_doc(meta5).save(tmp_path / "b.docx")
    assert folio.lo_parity_copy(tmp_path / "b.docx", tmp_path / "o") is None


def test_body_section_does_not_write_into_front_footer():
    # default (non-folio) profile: a linked footer would resolve to the front section's definition
    meta = BookMeta(**{**META, "running_left": "LEFT", "running_right": "RIGHT"})
    doc = _folio_doc(meta)
    front = doc.sections[0]
    assert not "".join(p.text for hf in (front.header, front.footer, front.even_page_header,
                                         front.even_page_footer) for p in hf.paragraphs)


def test_contents_refs_follow_printed_folios(tmp_path):
    # pdf page 1 prints 4; the reproduced ÍNDICE cites printed pages, two beyond the excerpt
    from booklayout import cli
    doc = fitz.open()
    body = {1: ["ÍNDICE", "Introducción ........ 5", "Morfología ........ 6", "Bibliografía ........ 457"],
            2: ["INTRODUCCIÓN", "texto"], 3: ["texto"], 4: ["MORFOLOGÍA", "texto"]}
    for i in range(1, 5):
        pg = doc.new_page(width=481.9, height=680.3)
        for k, line in enumerate(body[i]):
            pg.insert_text((51.1, 70 + k * 14), line, fontsize=9)
        pg.insert_text((51.1, 651), str(i + 3), fontsize=8)
    doc.save(tmp_path / "t.pdf")
    r = cli._reference_problems(tmp_path / "t.pdf", BookMeta())
    assert r["page_refs_checked"] == 2  # 457 is not printed in the excerpt: skipped
    # Introducción prints 5 (pdf 2): right; Morfología prints 7 (pdf 4), the ÍNDICE says 6
    assert [(w["entry"], w["ref"]) for w in r["wrong_page_refs"]] == [("Morfología", 6)]
