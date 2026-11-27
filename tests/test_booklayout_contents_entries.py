from docx import Document
from docx.oxml.ns import qn

from booklayout import builder
from booklayout.docstruct import to_aligned


def _sd():
    toc = [{"title": "Part 1: Introduction", "printed": None, "number": None, "bold": True, "part": True,
            "page": 6, "level": 0},
           {"title": "A History", "printed": "3", "number": "1", "bold": True, "authors": ["G. Read"],
            "page": 6, "level": 1},
           {"title": "Introduction", "printed": "3", "number": "1.1", "bold": False, "page": 6, "level": 2}]
    return {"pages": [{"page": 6, "kind": "toc", "blocks": []}, {"page": 7, "kind": "toc", "blocks": []}],
            "toc": toc + [dict(toc[2], page=7, number="1.2")], "source": {"pages": [6, 7]}}


def test_contents_title_once_and_entries_carried():
    pages = to_aligned(_sd())["pages"]
    roles = [[b["role"] for b in p["blocks"]] for p in pages]
    assert roles == [["heading", "index"], ["index"]]
    assert pages[0]["blocks"][0]["text"] == "Contents"
    es = pages[0]["blocks"][1]["entries"]
    assert [e["level"] for e in es] == [0, 1, 2] and es[1]["authors"] == ["G. Read"]


def test_contents_entry_levels_authors_bold_page():
    builder._TOC_COLS.clear()
    doc = Document()
    blk = to_aligned(_sd())["pages"][0]["blocks"][1]
    builder.contents_lines(doc, blk["text"], set(), builder.BookMeta(), blk["entries"])
    ps = [p for p in doc.paragraphs if p.text]          # drop the section-break paragraph
    assert [p.text for p in ps] == ["Part 1: Introduction", "G. Read", "1\tA History —— 3",
                                    "1.1\tIntroduction —— 3"]
    assert not any(r.italic for r in ps[1].runs)                      # authors roman, as the source
    assert ps[2].runs[0].bold and ps[2].runs[1].bold and ps[2].runs[-1].bold   # number, title, page
    assert not ps[3].runs[1].bold and ps[3].runs[-1].bold              # title roman, page bold
    assert ps[3].paragraph_format.left_indent == ps[2].paragraph_format.left_indent   # no per-level indent
    assert doc.sections[-1]._sectPr.xpath('./w:cols')[0].get(qn('w:num')) == '2'
    builder._TOC_COLS.clear()


def test_contents_line_count_mismatch_falls_back_flat():
    doc = Document()
    builder.contents_lines(doc, "A . . 3\nB . . 4", set(), builder.BookMeta(), [{"level": 1}])
    assert [p.text for p in doc.paragraphs] == ["A\t3", "B\t4"]
