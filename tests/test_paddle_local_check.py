"""第二道防线：云端空返回页用本机 tesseract 复核。"""
import fitz
import pytest

from docstore.engines import paddle_vl as pv


@pytest.fixture
def pdf(tmp_path):
    doc = fitz.open()
    pg = doc.new_page(width=300, height=400)  # 0: 只有一块黑图，无字
    pg.draw_rect(fitz.Rect(40, 40, 260, 360), color=None, fill=(0, 0, 0))
    pg = doc.new_page(width=300, height=400)  # 1: 有字（以图片形式，无文本层）
    pg.insert_text((20, 60), "Nereis diversicolor Mueller 1776 body", fontsize=14)
    pix = pg.get_pixmap(dpi=150)
    doc2 = fitz.open()
    p2 = doc2.new_page(width=300, height=400)
    p2.insert_image(p2.rect, pixmap=pix)
    doc.insert_pdf(doc2)
    f = str(tmp_path / "a.pdf")
    doc.save(f)
    return f


def test_empty_cloud_and_no_local_text_is_confirmed(pdf):
    ok, failed = pv._judge_pages(pdf, [1], [""])
    assert not failed and ok[1][1]["empty_reason"] == "no_text_local"


def test_empty_cloud_but_local_ocr_finds_text_is_suspect(pdf):
    ok, failed = pv._judge_pages(pdf, [3], [""])
    assert 3 in failed and failed[3].startswith("empty_suspect") and "本地 OCR 识别出" in failed[3]


def test_local_check_unavailable_keeps_suspect(monkeypatch, pdf):
    monkeypatch.setattr(pv.shutil, "which", lambda n: None)
    ok, failed = pv._judge_pages(pdf, [1], [""])
    assert failed[1].startswith("empty_suspect") and "不可用" in failed[1]
