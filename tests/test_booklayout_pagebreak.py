from docx import Document

from booklayout import builder


def test_empty_break_paragraph_becomes_page_break_before():
    doc = Document()
    doc.add_paragraph("authors")
    builder.page_break(doc)
    doc.add_paragraph("Geoffrey B. Read")
    assert builder._breaks_to_before(doc) == 1
    texts = [p.text for p in doc.paragraphs]
    assert texts[-2:] == ["authors", "Geoffrey B. Read"]
    assert doc.paragraphs[-1].paragraph_format.page_break_before


def test_chapter_heading_after_break_adds_no_second_break():
    doc = Document()
    doc.add_paragraph("x")
    builder.page_break(doc)
    h = builder.heading(doc, "1 A History", 1, set(), chapter_start=True)
    assert not h.paragraph_format.page_break_before
