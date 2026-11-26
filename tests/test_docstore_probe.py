import json

import fitz

from docstore import cli
from docstore.probe import book_kind, page_kind, probe_pdf


def _save(doc, path, **meta):
    if meta:
        doc.set_metadata(meta)
    doc.save(str(path))
    return path


def _img(pg):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), 0)
    pix.clear_with(200)
    pg.insert_image(pg.rect, pixmap=pix)


TEXT = "The quick brown fox jumps over the lazy dog near the river bank today."


def test_native(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    for i in range(6):
        pg.insert_text((60, 100 + 20 * i), TEXT, fontsize=10)
    r = probe_pdf(_save(doc, tmp_path / "a.pdf"))
    assert r["kind"] == "native"
    assert r["layout"]["columns"] == 1
    assert r["pages"] == 1 and r["sampled"][0]["page_kind"] == "native"
    assert r["fonts"]["body"]["size"] == 10.0
    json.dumps(r)


def test_scan(tmp_path):
    doc = fitz.open()
    _img(doc.new_page())
    r = probe_pdf(_save(doc, tmp_path / "s.pdf"))
    assert r["kind"] == "scan"
    assert r["fonts"] is None


def test_ocr_layer_invisible_text_and_producer(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    _img(pg)
    pg.insert_text((60, 100), TEXT, fontsize=10, render_mode=3)
    assert page_kind(pg)["page_kind"] == "ocr-layer"
    assert probe_pdf(_save(doc, tmp_path / "o.pdf"))["kind"] == "ocr-layer"
    doc2 = fitz.open()
    doc2.new_page().insert_text((60, 100), TEXT, fontsize=10)
    p = _save(doc2, tmp_path / "p.pdf", producer="ABBYY FineReader 12")
    assert probe_pdf(p)["kind"] == "ocr-layer"
    assert book_kind({}, [{"page_kind": "native"}, {"page_kind": "scan"}])[0] == "mixed"
    assert book_kind({}, [{"page_kind": "blank"}])[0] == "empty"


def test_two_columns_and_header(tmp_path):
    doc = fitz.open()
    for n in (1, 2):
        pg = doc.new_page()
        pg.insert_text((50, 40), "Handbook of Zoology", fontsize=9)
        for i in range(8):
            pg.insert_text((50, 100 + 18 * i), "left column text line number %d here" % i, fontsize=9)
            pg.insert_text((310, 100 + 18 * i), "right column text line number %d here" % i, fontsize=9)
        pg.insert_text((290, 780), str(n + 10), fontsize=9)
    r = probe_pdf(_save(doc, tmp_path / "c.pdf"), sample=2)
    assert r["layout"]["columns"] == 2
    assert "Handbook of Zoology" in r["layout"]["header_lines"]
    assert all(s["gutter"] for s in r["sampled"])


def test_bookmarks_and_cli(tmp_path, capsys):
    doc = fitz.open()
    for _ in range(30):
        doc.new_page().insert_text((60, 100), TEXT, fontsize=10)
    doc.set_toc([[1, "Cover", 1], [1, "Libro completo", 1]])
    p1 = _save(doc, tmp_path / "bad.pdf")
    assert probe_pdf(p1)["bookmarks"]["usable"] is False
    doc.set_toc([[1, "A", 1], [1, "B", 10], [1, "C", 20]])
    p2 = _save(doc, tmp_path / "good.pdf")
    bm = probe_pdf(p2, sample=3, pages=[7, 99])["bookmarks"]
    assert bm["usable"] is True and bm["count"] == 3 and bm["distinct_pages"] == 3
    out = tmp_path / "o.json"
    assert cli.main(["probe", str(p2), "--sample", "2", "--pages", "1,7", "--no-fonts", "--json", str(out)]) == 0
    assert "native" in capsys.readouterr().out
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["fonts"] is None and {1, 7} <= {s["page"] for s in data[0]["sampled"]}
