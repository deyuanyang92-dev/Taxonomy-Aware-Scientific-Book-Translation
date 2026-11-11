"""RapidOCR wrapper."""

from __future__ import annotations

import warnings
from typing import Callable

import fitz

_ENGINE = None


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
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    with fitz.open(pdf_path) as doc:
        png = doc[page_no - 1].get_pixmap(dpi=dpi).tobytes("png")
    res, _ = _ENGINE(png)
    rows = res or []
    text = "\n".join(r[1] for r in rows)
    conf = (sum(float(r[2]) for r in rows) / len(rows)) if rows else None
    return text, conf

