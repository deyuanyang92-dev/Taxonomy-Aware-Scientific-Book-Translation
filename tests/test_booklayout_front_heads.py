import fitz

from booklayout import folio


def _pdf(path, heads):
    doc = fitz.open()
    for h in heads:
        pg = doc.new_page(width=595, height=842)
        if h:
            pg.insert_text((60, 30), h, fontsize=8)     # running head band
        pg.insert_text((60, 200), "page body", fontsize=10)
    doc.save(str(path))


def test_running_head_on_cover_is_flagged(tmp_path):
    f = tmp_path / "o.pdf"
    _pdf(f, ["Volume 1: Annelida", "", "Volume 1: Annelida", "Volume 1: Annelida"])
    meta = {"front_pages": [1, 2, 3], "body_start_page": 1}
    got = folio.front_heads(f, meta, [1, 2, 3, 6], band_bottom=20 * 72 / 25.4)
    assert [g["page"] for g in got] == [1, 3]          # page 4 = source p6, not a front or contents page


def test_running_head_on_contents_page_is_flagged(tmp_path):
    """Handbook Vol1 2026-11-27: contents pages printed the book running head; the source has none."""
    f = tmp_path / "o.pdf"
    _pdf(f, ["", "", "Volume 1: Annelida", "Volume 1: Annelida"])
    meta = {"front_pages": [1, 2], "toc_pages": [6], "body_start_page": 1}
    got = folio.front_heads(f, meta, [1, 2, 6, 12], band_bottom=20 * 72 / 25.4)
    assert [g["page"] for g in got] == [3]


def test_clean_front_pages_pass(tmp_path):
    f = tmp_path / "o.pdf"
    _pdf(f, ["", "", "Volume 1"])
    assert folio.front_heads(f, {"front_pages": [1, 2]}, [1, 2, 6], 20 * 72 / 25.4) == []
