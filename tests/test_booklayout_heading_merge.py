"""Heading levels: number depth and font ladder merged (fix 2026-11-27 item 1); synthetic PDFs only."""
import fitz

from booklayout import fontlevels, ingest_native
from booklayout.builder import define_heading_styles
from booklayout.profile import validate_aligned


def _book(path, with_big=False):
    doc = fitz.open()
    for n in range(3):
        page = doc.new_page(width=420, height=600)
        page.insert_text((200, 30), "RUNNING HEAD TEXT", fontname="helv", fontsize=8)
        page.insert_text((200, 580), f"{100 + n}", fontname="helv", fontsize=8)
        y = 60
        if n == 0:
            if with_big:
                page.insert_text((50, y), "Annelid Biology Volume", fontname="tibo", fontsize=20)
                y += 30
            page.insert_text((50, y), "1 Introduction", fontname="tibo", fontsize=10)
            y += 22
            for i in range(3):
                page.insert_text((50, y), f"Body text line {i} of the first paragraph goes here ok.", fontname="tiro", fontsize=10)
                y += 12
            y += 8
            page.insert_text((50, y), "1.1 Methods", fontname="tibo", fontsize=10)
            y += 22
        if n == 1:
            page.insert_text((50, y), "2 Results", fontname="tibo", fontsize=10)
            y += 22
            page.insert_text((50, y), "2.1 Morphology", fontname="tibo", fontsize=10)
            y += 22
        for i in range(8):
            page.insert_text((50, y), f"Body text line {i} on page {n} goes here and runs on ok.", fontname="tiro", fontsize=10)
            y += 12
        # a body paragraph opening with a bold genus must stay body; its wrapped lines merge
        page.insert_text((50, y + 10), "Nereis", fontname="tibo", fontsize=10)
        w = fitz.get_text_length("Nereis ", fontname="tibo", fontsize=10)
        page.insert_text((50 + w, y + 10), "virens is a large errant polychaete found", fontname="tiro", fontsize=10)
        page.insert_text((50, y + 22), "on the shores of the northern Atlantic coast.", fontname="tiro", fontsize=10)
    doc.save(str(path))
    doc.close()


def _heads(data):
    return {b["text"]: b for p in data["pages"] for b in p["blocks"] if b["role"] == "heading"}


def test_same_size_bold_numbered_headings(tmp_path):
    _book(tmp_path / "a.pdf")
    data = ingest_native.ingest(tmp_path / "a.pdf")
    assert validate_aligned(data) == []
    h = _heads(data)
    assert {"1 Introduction", "1.1 Methods", "2 Results", "2.1 Morphology"} <= set(h)
    assert h["1 Introduction"]["level"] == 1
    assert h["1.1 Methods"]["level"] == 2
    assert h["1 Introduction"]["level"] < h["2.1 Morphology"]["level"]
    assert data["pages"][0]["chapter"] == "1 Introduction"


def test_bold_genus_paragraph_stays_one_body_block(tmp_path):
    _book(tmp_path / "a.pdf")
    data = ingest_native.ingest(tmp_path / "a.pdf")
    blocks = [b for p in data["pages"] for b in p["blocks"]]
    assert [b["role"] for b in blocks if "virens" in b["text"]] == ["body"] * 3   # one per page, none a heading
    assert not any(t.startswith("Nereis") for t in _heads(data))
    # wrapped body lines still merge into one paragraph
    wrapped = [b for b in blocks if b["role"] == "body" and "line 0 on page 2" in b["text"]]
    assert wrapped and "line 7 on page 2" in wrapped[0]["text"]


def test_bigger_unnumbered_title_not_below_numbered(tmp_path):
    _book(tmp_path / "a.pdf", with_big=True)
    data = ingest_native.ingest(tmp_path / "a.pdf")
    h = _heads(data)
    big = h["Annelid Biology Volume"]["level"]
    assert big <= h["2.1 Morphology"]["level"]
    assert big < h["1.1 Methods"]["level"] or big == h["1 Introduction"]["level"]
    assert big <= h["1 Introduction"]["level"]


def test_fontlevels_number_regex_bare_number():
    assert fontlevels.number_depth("1 Introduction") == ("1", 1)
    assert fontlevels.number_depth("1. Introduction") == ("1", 1)
    assert fontlevels.number_depth("2.1 Morphology") == ("2.1", 2)
    assert fontlevels.number_depth("12 mm long") is None   # lowercase word: not a heading number


def test_merge_levels_unnumbered_between():
    lv, shift = fontlevels.merge_levels({"big": ((-20,), []), "a": ((-14,), [1]), "mid": ((-12,), []), "b": ((-11,), [2]),
                                  "tiny": ((-9,), [])})
    assert lv["a"] == 2 and lv["b"] == 3 and lv["big"] == 1   # shifted: nothing sits above level 1
    assert lv["a"] <= lv["mid"] <= lv["b"]
    assert lv["tiny"] > lv["b"] and shift == 1


def test_deep_levels_get_styles():
    from docx import Document
    doc = Document()
    define_heading_styles(doc)
    for lv in range(1, 7):
        assert doc.styles[f"Heading {lv}"].font.size is not None
