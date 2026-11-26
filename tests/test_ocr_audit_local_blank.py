"""audit 误报回归：本地空白页（未提交云端）不应被判为缺 model/job_id（2026-11-25 质检 1996 条全是这类误报）。"""

from docstore import ocr_batch


def test_local_blank_page_not_flagged():
    assert ocr_batch.page_meta_missing({"job_id": "local-blank", "empty_reason": "blank", "model": None}) is False


def test_cloud_page_missing_meta_still_flagged():
    assert ocr_batch.page_meta_missing({"job_id": "", "model": "PaddleOCR-VL-1.6", "text": "x"}) is True
    assert ocr_batch.page_meta_missing({"job_id": "abc", "model": None, "text": "x"}) is True


def test_cloud_page_with_meta_ok():
    assert ocr_batch.page_meta_missing({"job_id": "abc", "model": "PaddleOCR-VL-1.6", "text": "x"}) is False
