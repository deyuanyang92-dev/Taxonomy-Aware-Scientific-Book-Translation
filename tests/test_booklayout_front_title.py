"""Contents / author-list pages of the Handbook of Zoology (2026-11-27): no book running head,
titles at the source size (DGMetaScience-Bold 22 pt)."""
from booklayout import docstruct


def _sd():
    kinds = {1: "cover", 2: "title", 6: "toc", 7: "toc", 10: "authors", 12: "chapter_start", 13: "body"}
    return {"source": {"pages": sorted(kinds)},
            "pages": [{"page": n, "kind": k, "blocks": []} for n, k in kinds.items()]}


def test_footers_start_after_contents_and_authors():
    m = docstruct.meta_from_struct(_sd(), "Book")
    assert m["folio_first_page"] == 12
    assert m["toc_pages"] == [6, 7]


def test_author_page_title_is_front_title():
    blocks = [{"id": "a", "role": "author_name", "text": "List of contributing authors",
               "src": {"bbox": [50, 50, 300, 70]}}]
    out = docstruct.authors_page(blocks, 595.0)
    t = [b for b in out if b["role"] == "heading"]
    assert t and t[0].get("front_title") is True


def test_author_page_title_already_heading_is_front_title():
    """Vol1 p10: the layout model labels the title paragraph_title (role heading), not author_name."""
    blocks = [{"id": "a", "role": "heading", "level": 2, "text": "List of contributing authors",
               "src": {"bbox": [50, 50, 300, 70]}}]
    out = docstruct.authors_page(blocks, 595.0)
    assert out[0].get("front_title") is True
