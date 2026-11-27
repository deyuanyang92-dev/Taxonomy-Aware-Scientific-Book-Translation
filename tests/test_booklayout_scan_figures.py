"""Item 3: a scanned page (page-sized image under an OCR text layer) is not a figure."""
import fitz

from booklayout import ingest_native
from booklayout import pdffigures as PF

TEXT = "Plain body sentence number {} runs along the whole line here to look like prose text."


def _png(w=400, h=500, drawing=True):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (235, 235, 235))
    if drawing:   # something inked inside the margins
        pix.set_rect(fitz.IRect(w // 4, h // 4, 3 * w // 4, 3 * h // 4), (60, 60, 60))
    return pix.tobytes("png")


def _scan(path, words=True, caption=False, twice=True):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    img = _png()
    p.insert_image(p.rect, stream=img)
    if twice:
        p.insert_image(p.rect, stream=_png(200, 250))     # low-res twin of the same scan
    if words:
        for i in range(30):
            p.insert_text((40, 60 + 15 * i), TEXT.format(i), fontname="tiro", fontsize=9, render_mode=3)
    if caption:
        p.insert_text((40, 560), "Fig. 3. A worm drawn in the scan.", fontname="tiro", fontsize=9, render_mode=3)
    doc.save(str(path))
    doc.close()


def _plate(path):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_image(p.rect, stream=_png())
    p.insert_image(p.rect, stream=_png(200, 250))
    p.insert_text((40, 570), "Pl. 4", fontname="tiro", fontsize=9)
    doc.save(str(path))
    doc.close()


def test_blank_scan_page_is_not_a_figure(tmp_path):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_image(p.rect, stream=_png(drawing=False))
    p.insert_text((40, 570), "12", fontname="tiro", fontsize=9)
    doc.save(str(tmp_path / "b.pdf"))
    page = fitz.open(str(tmp_path / "b.pdf"))[0]
    assert PF.image_placements(page) == []


def _figure_page(path):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_image(fitz.Rect(60, 60, 360, 300), stream=_png(300, 240))
    p.insert_text((60, 320), "Fig. 1. A figure.", fontname="tiro", fontsize=9)
    for i in range(30):
        p.insert_text((40, 350 + 8 * i), TEXT.format(i), fontname="tiro", fontsize=7)
    doc.save(str(path))
    doc.close()


def test_ocr_scan_page_has_no_image_placements(tmp_path):
    _scan(tmp_path / "s.pdf")
    page = fitz.open(str(tmp_path / "s.pdf"))[0]
    assert PF.is_scan_page(page)
    assert PF.image_placements(page, vector=True) == []


def test_ingest_of_scan_page_emits_no_figure_blocks(tmp_path):
    _scan(tmp_path / "s.pdf", caption=True)
    data = ingest_native.ingest(tmp_path / "s.pdf")
    assert [b for pg in data["pages"] for b in pg["blocks"] if b["role"] == "figure"] == []


def test_textless_plate_stays_one_figure_even_with_twin_layers(tmp_path):
    _plate(tmp_path / "p.pdf")
    page = fitz.open(str(tmp_path / "p.pdf"))[0]
    assert not PF.is_scan_page(page)
    assert len(PF.image_placements(page)) == 1


def test_ordinary_figure_page_unchanged(tmp_path):
    _figure_page(tmp_path / "f.pdf")
    page = fitz.open(str(tmp_path / "f.pdf"))[0]
    assert not PF.is_scan_page(page)
    assert len(PF.image_placements(page)) == 1
