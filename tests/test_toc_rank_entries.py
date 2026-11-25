import fitz

from booklayout.taxonlist import pdf_toc_rank_entries


def _pdf(path, lines):
    d = fitz.open()
    p = d.new_page()
    y = 72
    for t in lines:
        p.insert_text((50, y), t)
        y += 14
    d.save(path)


def test_rank_lines_in_contents_flagged(tmp_path):
    f = str(tmp_path / "a.pdf")
    _pdf(f, ["Índice de apartados", "Orden Abida Kuznetsov ........ 15", "Familia Aclisidae ........ 15"])
    assert len(pdf_toc_rank_entries(f)) == 2


def test_book_own_index_not_flagged(tmp_path):
    f = str(tmp_path / "c.pdf")
    _pdf(f, ["ÍNDICE", "Familia Aclisidae ........ 15"])
    assert pdf_toc_rank_entries(f) == []


def test_normal_contents_ok(tmp_path):
    f = str(tmp_path / "b.pdf")
    _pdf(f, ["INTRODUCCION ........ 7", "Familia Aclisidae Kuznetsov, 1960"])
    assert pdf_toc_rank_entries(f) == []
