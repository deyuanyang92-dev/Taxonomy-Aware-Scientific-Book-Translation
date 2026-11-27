"""Printed contents without leaders (Springer Handbook style): number | title | page, author lines."""
import fitz

from booklayout import contents as C
from booklayout import ingest_native

LONG = ("Terebellidae s.l.: Polycirridae Malmgren, 1866, Terebellidae Johnston, 1846, Thelepodidae Hessle, 1917, "
        "Trichobranchidae Malmgren, 1866, and Telothelepodidae Nogueira, Fitzhugh and Hutchings, 2013")


def _page(rows):
    """rows: (y, [(x, text)]) on an A5-ish page; page numbers sit right after their title (no right alignment)."""
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_text((50, 50), "Contents", fontname="hebo", fontsize=16)
    for y, spans in rows:
        for x, t in spans:
            p.insert_text((x, y), t, fontname="tiro", fontsize=9)
    return doc, p


def _rows():
    return [
        (90, [(50, "Foreword"), (100, "v")]),
        (102, [(50, "7"), (80, "Pleistoannelida"), (170, "1")]),
        (114, [(50, "Andreas Bick")]),
        (126, [(50, "7.4"), (80, "Sedentaria: Spionida/Sabellida"), (250, "1")]),
        (138, [(80, "Introduction"), (150, "1")]),
        (150, [(80, "Morphology"), (150, "11")]),
        (162, [(50, "Pat Hutchings and Orlemir Carrerette")]),
        (174, [(50, "7.7.1"), (80, "Pectinariidae Quatrefages,")]),
        (186, [(80, "1866"), (120, "34")]),
        (198, [(80, "Introduction"), (150, "34")]),
        (210, [(50, "7.7.3"), (80, "Terebellidae s.l.: Polycirridae")]),
        (222, [(80, "Malmgren, 1866, Terebellidae Johnston, 1846, Thelepodidae Hessle, 1917,")]),
        (234, [(80, "Trichobranchidae Malmgren, 1866, and Telothelepodidae Nogueira, Fitzhugh and")]),
        (246, [(80, "Hutchings, 2013"), (200, "68")]),
        (258, [(80, "Introduction"), (150, "68")]),
        (270, [(50, "Index"), (100, "461")]),
    ]


def test_wrapped_numbered_title_keeps_number_and_year():
    doc, p = _page(_rows())
    es = C.contents_from_pdf_page(p)
    titles = [(e.level, e.title, e.source_page) for e in es]
    assert (2, "7.7.1 Pectinariidae Quatrefages, 1866", "34") in titles


def test_long_numbered_title_not_dropped():
    doc, p = _page(_rows())
    es = C.contents_from_pdf_page(p)
    got = [e for e in es if e.title.startswith("7.7.3")]
    assert len(got) == 1 and got[0].source_page == "68" and got[0].title.endswith("Hutchings, 2013")


def test_author_lines_are_not_entries_or_title_parts():
    doc, p = _page(_rows())
    es = C.contents_from_pdf_page(p)
    assert not [e for e in es if "Bick" in e.title or "Hutchings and Orlemir" in e.title]


def test_flush_left_unnumbered_entry_is_top_level_and_entry_count():
    doc, p = _page(_rows())
    es = C.contents_from_pdf_page(p)
    assert [e for e in es if e.title == "Index"][0].level == 0
    assert [e for e in es if e.title == "Foreword"][0].level == 0
    # one entry per page number span: 10 rows end in a page span
    assert len(es) == 10
    assert [e.level for e in es if e.title == "Morphology"] == [2]


def test_toc_entries_count_without_leaders():
    doc, p = _page(_rows())
    assert len(ingest_native.toc_entries(p, False)) == 10
