"""章界回退（issue #61）：书签不可用时回退到 PDF 目录页（行几何法）。"""
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import chapter_split as cs  # noqa: E402
from booklayout.contents import contents_from_pdf_page  # noqa: E402

RIGHT = 540.0


def _row(page, y, text, x=60.0, right=False):
    if right:
        x = RIGHT - fitz.get_text_length(text, fontname="helv", fontsize=10)
    page.insert_text((x, y), text, fontname="helv", fontsize=10)


def _toc_page(page, items):
    """Handbook 式：章号、标题、页码各占一行（页码右对齐）。"""
    y = 100.0
    _row(page, 70, "Contents")
    for num, title, pg in items:
        _row(page, y, num)
        _row(page, y + 14, title)
        _row(page, y + 28, str(pg), right=True)
        y += 50


ITEMS = [("7.4", "Sedentaria: Spionida", 1), ("7.5", "Sedentaria: Sabellida", 40),
         ("7.6", "Errantia: Phyllodocida", 90)]


def test_bookmarks_usable():
    assert cs.bookmarks_usable([("Cover", 1), ("Libro completo", 1)], 1) is False
    assert cs.bookmarks_usable([("A", 1), ("B", 10), ("C", 20)], 1) is True
    assert cs.bookmarks_usable([(1, "A", 1), (1, "B", 1), (1, "C", 7)], 1) is False  # 2/3 同页首页
    assert cs.bookmarks_usable([], 1) is False


def test_contents_from_pdf_page_split_lines():  # 测试 7
    doc = fitz.open()
    pg = doc.new_page()
    _toc_page(pg, ITEMS)
    es = contents_from_pdf_page(pg)
    assert [e.source_page for e in es] == ["1", "40", "90"]
    assert es[0].title == "7.4 Sedentaria: Spionida"
    assert all(e.level == 1 for e in es)


def test_contents_from_pdf_page_nested_levels():
    doc = fitz.open()
    pg = doc.new_page()
    _row(pg, 100, "7 Annelida")
    _row(pg, 100, "5", right=True)
    _row(pg, 120, "7.4.1 Spionidae")
    _row(pg, 120, "12", right=True)
    _row(pg, 140, "7.4.1.2 Spio")
    _row(pg, 140, "15", right=True)
    es = contents_from_pdf_page(pg)
    assert [e.level for e in es] == [0, 2, 3]
    assert [e.source_page for e in es] == ["5", "12", "15"]


def _vol1_pdf(path, n=12):
    """2 条同页书签 + 目录在 PDF p.2，印刷页 1 = PDF p.3。"""
    doc = fitz.open()
    for i in range(n):
        pg = doc.new_page()
        if i == 1:
            _toc_page(pg, [("1", "Alpha chapter", 1), ("2", "Beta chapter", 4), ("3", "Gamma chapter", 7)])
        else:
            pg.insert_text((72, 72), f"page {i + 1}")
    doc.set_toc([[1, "Cover003", 1], [1, "Libro completo", 1]])
    doc.save(str(path))
    doc.close()


def _md(n=12, heads=None):
    out = []
    for p in range(1, n + 1):
        out.append(f"<!-- PDF p.{p} -->")
        out.append((heads or {}).get(p, f"Body text of page {p}."))
        out.append("")
    return "\n".join(out)


def test_contents_from_pdf(tmp_path):
    pdf = tmp_path / "v.pdf"
    _vol1_pdf(pdf)
    got = cs.contents_from_pdf(pdf)
    assert [(n, lv) for _t, n, lv in got] == [(1, 0), (4, 0), (7, 0)]
    assert got[0][0] == "1 Alpha chapter"


def test_plan_vol1_falls_back_to_contents(tmp_path):
    pdf, src = tmp_path / "v.pdf", tmp_path / "v.md"
    _vol1_pdf(pdf)
    src.write_text(_md(heads={3: "1 Alpha chapter", 6: "2 Beta chapter", 9: "3 Gamma chapter"}),
                   encoding="utf-8")
    plan = cs.build_plan(src, pdf)
    assert plan["chapter_source"] == "contents"
    real = [c for c in plan["chapters"] if c["source"] == "contents"]
    assert [c["start"] for c in real] == [3, 6, 9]
    assert plan["chapters"][0]["title"] == "Front matter"


def test_plan_chapter_source_bookmarks(tmp_path):
    pdf, src = tmp_path / "b.pdf", tmp_path / "b.md"
    doc = fitz.open()
    for i in range(12):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    doc.set_toc([[1, "Intro", 1], [1, "Methods", 5], [1, "Results", 9]])
    doc.save(str(pdf))
    src.write_text(_md(), encoding="utf-8")
    assert cs.build_plan(src, pdf)["chapter_source"] == "bookmarks"


def test_plan_chapter_source_single(tmp_path):
    src = tmp_path / "s.md"
    src.write_text(_md(), encoding="utf-8")
    plan = cs.build_plan(src)
    assert plan["chapter_source"] == "single"
    assert plan["needs_review"] is True


def _inline_page(page, x, y, title, pg, num=None, gap=14.0):
    """Handbook 式行：章号（自成一格）+ 标题 + 紧随标题的页码（不贴右缘，各自成 span）。"""
    if num:
        page.insert_text((x, y), num, fontname="helv", fontsize=10)
    tx = x + 50
    page.insert_text((tx, y), title, fontname="helv", fontsize=10)
    w = fitz.get_text_length(title, fontname="helv", fontsize=10)
    page.insert_text((tx + w + gap, y), pg, fontname="helv", fontsize=10)


def test_contents_inline_page_not_right_aligned():
    """Vol3 p7：页码紧跟标题、不在右缘；作者行不得并入下一条标题；子节随上一级编号。"""
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((51, 52), "Contents", fontname="helv", fontsize=10)
    _inline_page(pg, 51, 100, "Pleistoannelida", "1", "7")
    pg.insert_text((51, 114), "Andreas Bick", fontname="helv", fontsize=10)
    _inline_page(pg, 51, 130, "Sedentaria: Spionida/Sabellida", "1", "7.4")
    _inline_page(pg, 51, 144, "Fabriciidae Rioja, 1923", "1", "7.4.8")
    _inline_page(pg, 51, 158, "Introduction", "1")
    _inline_page(pg, 51, 172, "References", "28")
    es = contents_from_pdf_page(pg)
    assert [e.title for e in es][:2] == ["7 Pleistoannelida", "7.4 Sedentaria: Spionida/Sabellida"]
    assert [(e.level, e.source_page) for e in es] == [(0, "1"), (1, "1"), (2, "1"), (3, "1"), (3, "28")]


def test_contents_two_columns_with_running_head():
    """Vol1 式双栏：左右栏同一水平线上的行不得并成一行；右栏页眉 'Contents ix' 丢弃。"""
    doc = fitz.open()
    pg = doc.new_page()
    for i in range(6):
        _inline_page(pg, 51, 100 + 14 * i, f"Left heading {i}", str(10 + i), f"1.{i}")
        _inline_page(pg, 310, 100 + 14 * i, f"Right heading {i}", str(100 + i), f"2.{i}")
    pg.insert_text((450, 40), "Contents  ix", fontname="helv", fontsize=10)
    es = contents_from_pdf_page(pg)
    assert len(es) == 12
    assert es[0].title == "1.0 Left heading 0" and es[6].title == "2.0 Right heading 0"
    assert [e.source_page for e in es[:2]] == ["10", "11"]
