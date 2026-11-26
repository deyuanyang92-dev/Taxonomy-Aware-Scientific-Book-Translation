"""pdfdiff (layout regression) and the Key Table strut fix (T3b)."""
import shutil

import pytest

from booklayout import builder, pdfdiff
from booklayout.profile import StyleProfile

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext missing")


def _pdf(path, words):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    for text, y in words:
        page.insert_text((72, y), text)
    doc.save(str(path))


@needs_pdftotext
def test_compare_equal_and_shift(tmp_path):
    _pdf(tmp_path / "a.pdf", [("alpha", 100), ("beta", 200)])
    _pdf(tmp_path / "b.pdf", [("alpha", 100), ("beta", 200)])
    _pdf(tmp_path / "c.pdf", [("alpha", 100), ("beta", 202)])
    _pdf(tmp_path / "d.pdf", [("alpha", 100), ("gamma", 200)])
    assert pdfdiff.compare(tmp_path / "a.pdf", tmp_path / "b.pdf")["ok"]
    shifted = pdfdiff.compare(tmp_path / "a.pdf", tmp_path / "c.pdf")
    assert not shifted["ok"] and shifted["over_tol_pages"] == [1] and shifted["max_bbox"] > 1.5
    assert pdfdiff.compare(tmp_path / "a.pdf", tmp_path / "c.pdf", tol=3)["ok"]
    assert pdfdiff.compare(tmp_path / "a.pdf", tmp_path / "d.pdf")["text_diff_pages"] == [1]


@needs_pdftotext
def test_main_exit_code(tmp_path):
    _pdf(tmp_path / "a.pdf", [("alpha", 100)])
    _pdf(tmp_path / "c.pdf", [("alpha", 105)])
    assert pdfdiff.main([str(tmp_path / "a.pdf"), str(tmp_path / "a.pdf")]) == 0
    assert pdfdiff.main([str(tmp_path / "a.pdf"), str(tmp_path / "c.pdf")]) == 1


def test_key_table_style_keeps_normal_strut_and_runs_carry_size():
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    builder.define_styles(doc, StyleProfile())
    assert doc.styles["Key Table"].font.size == Pt(10.5)
    # other styles still carry their own size
    assert doc.styles["Caption"].font.size != Pt(10.5)
