"""Item 2: structure anchors - outline pages, printed-contents levels, wrapped headings with control characters."""
import fitz

from booklayout import anchors, ingest_native
from booklayout.profile import validate_aligned

BODY = "Plain body sentence number {} runs along the whole line here to look like prose text."


def _book(path, ctrl=True, outline=True):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_text((50, 60), "Contents", fontname="hebo", fontsize=20)
    rows = [("7.4", "Sedentaria: Spionida", 3, 1), ("7.4.1", "Fabriciidae", 3, 1), ("", "Introduction", 3, 1),
            ("", "Morphology", 4, 1), ("7.7", "Sedentaria: Terebellida/ Arenicolida", 5, 1),
            ("7.7.1", "Pectinariidae", 5, 1), ("", "Introduction", 5, 1), ("", "Morphology", 6, 1)]
    y = 100
    for num, title, pg, _ in rows:
        if num:
            p.insert_text((50, y), num, fontname="tiro", fontsize=10)
        p.insert_text((100, y), title, fontname="tiro", fontsize=10)
        p.insert_text((330, y), str(pg), fontname="tiro", fontsize=10)
        y += 16
    def page(heads):
        q = doc.new_page(width=420, height=600)
        y = 60
        for text, size in heads:
            q.insert_text((50, y), text, fontname="hebo", fontsize=size)
            y += size + 8
        for i in range(12):
            q.insert_text((50, y + 14 * i), BODY.format(i), fontname="tiro", fontsize=10)
    page([("7.4 Sedentaria: Spionida", 16), ("7.4.1 Fabriciidae", 13), ("Introduction", 11)])
    page([("Morphology", 11)])
    first = "7.7 \x07Sedentaria: Terebellida/" if ctrl else "7.7 Sedentaria: Terebellida/"
    page([(first, 16), ("Arenicolida", 16), ("7.7.1 Pectinariidae", 13), ("Introduction", 11)])
    page([("Morphology", 11)])
    if outline:
        doc.set_toc([[1, "x1", 2], [1, "x2", 4]])
    doc.save(str(path))
    doc.close()


def _heads(data):
    return [(b["text"], b["level"], pg["page"]) for pg in data["pages"] for b in pg["blocks"] if b["role"] == "heading"
            and pg.get("kind") != "toc"]


def test_wrapped_heading_with_control_char_is_one_heading(tmp_path):
    _book(tmp_path / "b.pdf")
    data = ingest_native.ingest(tmp_path / "b.pdf")
    texts = [h[0] for h in _heads(data)]
    assert "7.7 Sedentaria: Terebellida/ Arenicolida" in texts


def test_levels_follow_printed_contents_depth(tmp_path):
    _book(tmp_path / "b.pdf")
    data = ingest_native.ingest(tmp_path / "b.pdf")
    lv = {t: lv_ for t, lv_, _p in _heads(data)}
    assert lv["7.4 Sedentaria: Spionida"] == 2
    assert lv["7.4.1 Fabriciidae"] == 3
    assert lv["7.7 Sedentaria: Terebellida/ Arenicolida"] == 2
    assert {lv_ for t, lv_, _p in _heads(data) if t in ("Introduction", "Morphology")} == {4}


def test_chapter_field_uses_outline_page_anchors(tmp_path):
    _book(tmp_path / "b.pdf")
    data = ingest_native.ingest(tmp_path / "b.pdf")
    ch = {pg["page"]: pg["chapter"] for pg in data["pages"]}
    assert ch[2] == ch[3] == "7.4 Sedentaria: Spionida"
    assert ch[4] == ch[5] == "7.7 Sedentaria: Terebellida/ Arenicolida"
    assert validate_aligned(data) == []


def test_without_outline_chapter_falls_back(tmp_path):
    _book(tmp_path / "b.pdf", outline=False)
    data = ingest_native.ingest(tmp_path / "b.pdf")
    assert all(isinstance(pg["chapter"], str) and pg["chapter"] for pg in data["pages"])


def test_match_is_sequential_so_repeated_titles_get_their_own_entry():
    toc = [("Introduction", 3), ("Morphology", 3), ("Introduction", 1), ("Morphology", 1)]
    heads = [("Introduction", 9), ("Morphology", 9), ("Introduction", 9), ("Morphology", 9)]
    got = anchors.match_headings(toc, heads)
    assert got == [0, 1, 2, 3]


def test_conflict_is_recorded_not_overwritten():
    pages = [{"page": 1, "kind": "chapter", "chapter": "", "blocks": [
        {"role": "heading", "text": "2 Methods", "level": 3, "level_source": "number", "style": "Heading 3"}]},
        {"page": 2, "kind": "toc", "blocks": [{"role": "toc_entry", "text": "2 Methods", "toc_level": 0}]}]
    rep = anchors.apply_anchors(pages, [])
    assert pages[0]["blocks"][0]["level"] == 3
    assert rep["conflicts"] and rep["conflicts"][0]["text"] == "2 Methods"
