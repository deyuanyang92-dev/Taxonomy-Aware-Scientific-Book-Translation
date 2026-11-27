from booklayout.docstruct import authors_page


def _b(i, role, text, bbox, **kw):
    return {"id": f"p0010-s{i:02d}", "role": role, "text": text, "src": {"b": "text", "bbox": bbox}, **kw}


def test_authors_page_title_split_name_and_column_order():
    blocks = [_b(1, "author_name", "List of contributing authors", [48, 63, 314, 88]),
              _b(2, "author_name", "James A. Blake", [48, 107, 104, 119]),
              _b(3, "author_affil", "Aquatic Research", [48, 120, 221, 152]),
              _b(4, "author_affil", "University of Vechta", [48, 240, 207, 284]),   # layout model: address first
              _b(5, "author_name", "Markus B.", [49, 228, 122, 239]),
              _b(6, "author_name", "Dieter Fiege", [295, 107, 341, 119]),            # right column, x0 < page mid
              _b(7, "author_affil", "Lund University", [48, 626, 190, 680], lead_name="Mats E. Eriksson")]
    out = authors_page(blocks, 595.3)
    assert [(b["role"], b["text"]) for b in out] == [
        ("heading", "List of contributing authors"), ("author_name", "James A. Blake"),
        ("author_affil", "Aquatic Research"), ("author_name", "Markus B."), ("author_affil", "University of Vechta"),
        ("author_name", "Mats E. Eriksson"), ("author_affil", "Lund University"), ("author_name", "Dieter Fiege")]
