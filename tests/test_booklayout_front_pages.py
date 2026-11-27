"""Front pages of a printed book (Handbook of Zoology Vol. 3, 2026-11-27): each of Foreword / Contents /
List of contributing authors starts its own page, the contents carry their author lines in source order,
contents lines fit the column they sit in, and front pages print their own running head (roman folio +
section title; none on the first page), not the book's body running head."""
import fitz
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Mm

from booklayout import builder as B
from booklayout import contents as C
from booklayout import ingest_native
from booklayout.profile import validate_aligned
from tests.test_booklayout_toc_geometry import _page, _rows


# ---- contents: author lines belong to the entry they stand above -------------------------------

def test_author_lines_attach_to_next_numbered_entry():
    doc, p = _page(_rows())
    es = {e.title.split()[0]: e for e in C.contents_from_pdf_page(p)}
    assert es["7.4"].authors == ["Andreas Bick"]
    assert es["7.7.1"].authors == ["Pat Hutchings and Orlemir Carrerette"]
    assert not es["7"].authors and not es["Foreword"].authors


def test_author_line_at_column_end_goes_to_first_entry_of_next_column():
    rows = []
    for i in range(4):
        rows.append((90 + 12 * i, [(40, f"Part{i} title"), (120, str(i + 1))]))
    rows.append((150, [(40, "Katrine Worsaae")]))
    for i in range(4):
        rows.append((90 + 12 * i, [(250, f"7.{i + 1}"), (275, f"Family{i}"), (380, str(10 + i))]))
    doc, p = _page(rows)
    es = [e for e in C.contents_from_pdf_page(p) if e.title.startswith("7.1")]
    assert es and es[0].authors == ["Katrine Worsaae"]


# ---- ingest: toc_author blocks sit right before their entry ---------------------------------------

def _toc_pdf(path):
    doc, p = _page(_rows())
    q = doc.new_page(width=420, height=600)
    q.insert_text((50, 60), "1 Introduction", fontname="hebo", fontsize=14)
    for i in range(10):
        q.insert_text((50, 100 + 12 * i), f"Plain body sentence number {i} runs along the line here.",
                      fontname="tiro", fontsize=9)
    doc.save(str(path))


def test_ingest_emits_toc_author_before_its_entry(tmp_path):
    _toc_pdf(tmp_path / "t.pdf")
    data = ingest_native.ingest(tmp_path / "t.pdf")
    blocks = data["pages"][0]["blocks"]
    roles = [(b["role"], b["text"]) for b in blocks if b["role"] in ("toc_author", "toc_entry")]
    i = roles.index(("toc_author", "Andreas Bick"))
    assert roles[i + 1][0] == "toc_entry" and roles[i + 1][1].startswith("7.4 ")
    assert not [b for b in blocks if b["role"] == "body" and "Bick" in b["text"]]
    assert validate_aligned(data) == []


def test_ingest_records_running_head_with_roman_folio(tmp_path):
    doc = fitz.open()
    for folio in ("viii", "ix"):
        pg = doc.new_page(width=420, height=600)
        pg.insert_text((50, 25), folio, fontname="hebo", fontsize=9)
        pg.insert_text((90, 25), "Contents", fontname="tiro", fontsize=9)
        for i in range(12):
            pg.insert_text((50, 100 + 12 * i), f"Body sentence {i} runs along the line here for a while.",
                           fontname="tiro", fontsize=10)
    doc.save(str(tmp_path / "h.pdf"))
    data = ingest_native.ingest(tmp_path / "h.pdf")
    assert [p["head"] for p in data["pages"]] == [{"text": "Contents", "folio": "viii"},
                                                  {"text": "Contents", "folio": "ix"}]


# ---- builder ---------------------------------------------------------------------------------------

def test_toc_entry_tab_stop_is_the_column_width():
    doc = Document()
    B._COLS["n"] = 2
    try:
        B.render_toc_entry(doc, {"role": "toc_entry", "printed": "15", "toc_level": 1}, "Results", None)
    finally:
        B._COLS["n"] = 1
    tab = doc.paragraphs[-1].paragraph_format.tab_stops[0]
    assert abs(tab.position - Mm((B.TEXT_W - B.PROFILE.column_gap_mm) / 2)) < Mm(0.5)
    assert tab.position < Mm(B.TEXT_W)


def _blk(role, text, **kw):
    return {"block_id": text[:6] + role, "role": role, "text": text, "translation": text, **kw}


def _pages(heads=True):
    def pg(n, ch, kind, blocks, head=None):
        d = {"page": n, "chapter": ch, "kind": kind, "blocks": blocks}
        if heads and head is not None:
            d["head"] = head
        return d
    def h1(t):
        return _blk("heading", t, level=1)
    return [
        pg(1, "Foreword", "chapter", [h1("Foreword"), _blk("body", "Annelida is an ancient group.")]),
        pg(2, "Foreword", "chapter", [_blk("body", "Continued text of the foreword.")], {"text": "", "folio": "vi"}),
        pg(3, "Contents", "toc", [h1("Contents"), _blk("toc_entry", "7 Pleistoannelida", printed="1", toc_level=0)]),
        pg(4, "Contents", "toc", [_blk("toc_author", "Andreas Bick"),
                                  _blk("toc_entry", "7.4 Sedentaria", printed="2", toc_level=1)],
           {"text": "Contents", "folio": "viii"}),
        pg(5, "List of contributing authors", "chapter", [h1("List of contributing authors"),
                                                          _blk("body", "Universitat Rostock")]),
        pg(6, "List of contributing authors", "chapter", [_blk("body", "Germany")],
           {"text": "List of contributing authors", "folio": "x"}),
        pg(7, "1 Introduction", "chapter", [h1("1 Introduction"), _blk("body", "Body text of chapter one.")]),
        pg(8, "1 Introduction", "chapter", [_blk("body", "More body text.")], {"text": "Book", "folio": "2"}),
    ]


def _render(pages, meta=None):
    doc = Document()
    B.TOC_ROWS.clear()
    B.render_body(doc, {"pages": pages}, set(), {}, {}, meta or B.BookMeta(chapter_headings=False),
                  figs_dir=__import__("pathlib").Path("."))
    return doc


def _page_starts(doc):
    n = 0
    for p in doc.paragraphs:
        if p.paragraph_format.page_break_before:
            n += 1
        n += sum(1 for r in p.runs if 'w:type="page"' in r._element.xml)
    return n


def _new_page_sections(doc):
    return [s for s in doc.sections[1:] if s._sectPr.xpath("./w:type")
            and s._sectPr.xpath("./w:type")[0].get(qn("w:val")) in (None, "nextPage")] if False else \
        [s for s in doc.sections[1:] if not s._sectPr.xpath("./w:type")
         or s._sectPr.xpath("./w:type")[0].get(qn("w:val")) == "nextPage"]


def test_foreword_contents_and_authors_each_start_a_page_without_heads():
    doc = _render(_pages(heads=False))
    # Foreword | Contents | authors | chapter: three starts (the first page needs none)
    assert _page_starts(doc) + len(_new_page_sections(doc)) >= 3


def test_same_chapter_continuation_does_not_break():
    pages = [p for p in _pages(heads=False) if p["page"] in (7, 8)]
    doc = _render(pages)
    assert _page_starts(doc) + len(_new_page_sections(doc)) == 0


def test_front_groups_get_their_own_running_head_and_roman_folio():
    doc = _render(_pages())
    fronts = [s for s in doc.sections if s._sectPr.xpath("./w:pgNumType[@w:fmt='lowerRoman']")]
    assert len(fronts) == 3
    heads = []
    for s in fronts:
        assert s.different_first_page_header_footer          # the first page prints no head
        assert not "".join(p.text for p in s.first_page_header.paragraphs).strip()
        heads.append("".join(p.text for p in s.header.paragraphs) + "".join(p.text for p in s.even_page_header.paragraphs))
    assert "Foreword" in heads[0] and "Contents" in heads[1] and "List of contributing authors" in heads[2]
    starts = [int(s._sectPr.xpath("./w:pgNumType")[0].get(qn("w:start"))) for s in fronts]
    assert starts == [5, 7, 9]                                  # printed folios vi, viii, x minus the page offset
    body = doc.sections[-1]
    fmt = body._sectPr.xpath("./w:pgNumType")
    assert not fmt or fmt[0].get(qn("w:fmt")) in (None, "decimal")
    assert fmt and fmt[0].get(qn("w:start")) == "1"            # printed folio 2 on the book's second body page


def test_book_without_roman_front_folios_gets_no_front_sections():
    pages = [p for p in _pages() if p["page"] in (7, 8)]
    assert len(_render(pages).sections) == 1


def test_toc_author_is_rendered_before_its_entry():
    doc = _render(_pages(heads=False))
    texts = [p.text for p in doc.paragraphs]
    assert texts.index("Andreas Bick") + 1 == texts.index("7.4 Sedentaria\t2")


def test_run_cache_stamp_changes_with_stage_code(monkeypatch, tmp_path):
    from booklayout import run as R_
    a = R_._code_stamp()
    monkeypatch.setattr(R_, "__file__", str(tmp_path / "run.py"))
    (tmp_path / "ingest_native.py").write_text("x")
    assert R_._code_stamp() != a


def test_headless_foreword_and_doubled_head_text_still_form_front_groups():
    pages = _pages()
    for p in pages:
        if p["chapter"] == "Foreword":
            p.pop("head", None)                       # the source prints no head on these pages
        if p["chapter"] == "List of contributing authors" and p.get("head"):
            p["head"] = {"text": "List of contributing authors x List of contributing authors", "folio": "x"}
    fronts, after = B.front_groups(pages)
    assert sorted(fronts) == [1, 2, 3, 4, 5, 6]
    assert fronts[1]["start"] == 5 and fronts[3]["start"] == 7 and after == {7: 1}
