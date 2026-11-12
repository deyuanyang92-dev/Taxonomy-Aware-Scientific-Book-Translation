"""RapidOCR wrapper."""

from __future__ import annotations

import warnings
from typing import Any, Callable, Sequence

from ..layout import order_rows
from .pageimg import page_array

_ENGINE = None
_ORT_THREADS: int | None = None


def set_ort_threads(n: int | None) -> None:
    """限制之后新建的 RapidOCR 会话的 onnxruntime 线程数（并行多进程时每进程 1~2 个，避免线程超订）。"""
    global _ORT_THREADS
    _ORT_THREADS = n


def _make_engine():
    from rapidocr_onnxruntime import RapidOCR

    if not _ORT_THREADS:
        return RapidOCR()
    import rapidocr_onnxruntime.utils as rutils

    orig = rutils.SessionOptions
    threads = _ORT_THREADS

    def limited():
        opt = orig()
        opt.intra_op_num_threads = threads
        opt.inter_op_num_threads = 1
        return opt

    rutils.SessionOptions = limited  # RapidOCR 不暴露会话选项，只能在建会话期间替换
    try:
        return RapidOCR()
    finally:
        rutils.SessionOptions = orig


def rows_to_text(res: Sequence[Any] | None) -> tuple[str, float | None]:
    """RapidOCR 行 [box, text, score] -> (按阅读顺序拼接的文本, 平均置信度)。双栏页先左栏后右栏。"""
    rows = order_rows(res or [])
    text = "\n".join(r[1] for r in rows)
    conf = (sum(float(r[2]) for r in rows) / len(rows)) if rows else None
    return text, conf


def rapidocr_run(
    pdf_path: str,
    page_no: int,
    dpi: int,
    *,
    ocr_func: Callable[[str, int, int], tuple[str, float | None]] | None = None,
) -> tuple[str, float | None]:
    """Run RapidOCR on one PDF page."""
    if ocr_func is not None:
        return ocr_func(pdf_path, page_no, dpi)
    global _ENGINE
    warnings.filterwarnings("ignore")
    if _ENGINE is None:
        _ENGINE = _make_engine()
    res, _ = _ENGINE(page_array(pdf_path, page_no, dpi))
    return rows_to_text(res)
