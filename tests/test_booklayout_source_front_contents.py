from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from booklayout import builder as B


def _data():
    def blk(i, role, t):
        return {"block_id": i, "role": role, "text": t, "translation": t}
    return {"pages": [
        {"page": 1, "chapter": "Book", "kind": "chapter", "blocks": [blk("a", "body", "FAUNA IBERICA"), blk("b", "body", "Vol. 21")]},
        {"page": 6, "chapter": "Book", "kind": "chapter", "blocks": [
            blk("c", "index", "Familia Syllidae ..... 11"), blk("d", "index", "Género Syllis ..... 336")]},
        {"page": 10, "chapter": "Book", "kind": "chapter", "blocks": [blk("e", "body", "Los Syllidae son poliquetos.")]},
    ]}


def _render(meta):
    doc = Document()
    B.render_body(doc, _data(), set(), {}, {}, meta, figs_dir=__import__("pathlib").Path("."))
    return doc


def _breaks(doc):
    return sum(1 for p in doc.paragraphs for r in p.runs if 'w:type="page"' in r._element.xml)


def test_contents_dropped_unless_in_place():
    texts = [p.text for p in _render(B.BookMeta(chapter_headings=False)).paragraphs]
    assert not any("Syllis" in t and "336" in t for t in texts)


def test_contents_in_place_dot_leader_and_indent():
    meta = B.BookMeta(chapter_headings=False, contents_in_place=True, contents_indent_prefixes=["Género"])
    pars = [p for p in _render(meta).paragraphs if "336" in p.text or "Familia" in p.text]
    assert [p.text for p in pars] == ["Familia Syllidae\t11", "Género Syllis\t336"]
    assert pars[1].paragraph_format.left_indent > pars[0].paragraph_format.left_indent
    assert 'w:leader="dot"' in pars[1]._element.xml


def test_own_and_centered_pages():
    plain = _render(B.BookMeta(chapter_headings=False))
    assert _breaks(plain) == 0
    meta = B.BookMeta(chapter_headings=False, own_pages=[1, 6], centered_pages=[1],
                         contents_in_place=True)
    doc = _render(meta)
    assert _breaks(doc) == 2  # before p6, and before p10 after an own page
    cover = [p for p in doc.paragraphs if p.text == "FAUNA IBERICA"][0]
    assert cover.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    body = [p for p in doc.paragraphs if p.text.startswith("Los Syllidae")][0]
    assert body.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.CENTER


def test_image_page_prints_the_scan(tmp_path):
    from PIL import Image
    (tmp_path / "source_pages").mkdir()
    Image.new("RGB", (100, 140), "brown").save(tmp_path / "source_pages" / "p0001.png")
    doc = Document()
    meta = B.BookMeta(chapter_headings=False, image_pages=[1])
    B.render_body(doc, _data(), set(), {}, {}, meta, figs_dir=tmp_path)
    assert len(doc.inline_shapes) == 1
    assert not any(p.text == "FAUNA IBERICA" for p in doc.paragraphs)
    assert _breaks(doc) == 1  # the scan page owns its page; p10 starts a new one
    # no scan file: falls back to the OCR text
    doc2 = Document()
    B.render_body(doc2, _data(), set(), {}, {}, meta, figs_dir=tmp_path / "none")
    assert any(p.text == "FAUNA IBERICA" for p in doc2.paragraphs)


def test_title_page_can_be_switched_off():
    doc = Document()
    B.front_matter(doc, {"pages": []}, set(), {}, B.BookMeta(title="Fauna Ibérica Vol. 21", volume="Vol. 21",
                                                             title_page=False, include_contents=False), None)
    assert not any(p.text for p in doc.paragraphs)
