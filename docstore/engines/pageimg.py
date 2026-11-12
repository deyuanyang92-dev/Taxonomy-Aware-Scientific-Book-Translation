"""PDF 页面渲染：同一进程内复用已打开的 PDF，同一页同一 dpi 只渲染一次（多个引擎共用）。"""

from __future__ import annotations

import os
from typing import Any

import fitz

_DOC: tuple[tuple[str, int, int], Any] | None = None
_PIX: tuple[tuple[str, int, int, int, int], Any] | None = None


def _sig(pdf_path: str) -> tuple[str, int, int]:
    st = os.stat(pdf_path)
    return (pdf_path, st.st_mtime_ns, st.st_size)


def _doc(pdf_path: str):
    global _DOC
    sig = _sig(pdf_path)
    if _DOC is None or _DOC[0] != sig:
        if _DOC is not None:
            _DOC[1].close()
        _DOC = (sig, fitz.open(pdf_path))
    return _DOC[1]


def page_pixmap(pdf_path: str, page_no: int, dpi: int):
    """第 page_no 页（1 起）在 dpi 下的 fitz.Pixmap；只缓存最近一页。"""
    global _PIX
    key = (*_sig(pdf_path), page_no, dpi)
    if _PIX is None or _PIX[0] != key:
        _PIX = None
        _PIX = (key, _doc(pdf_path)[page_no - 1].get_pixmap(dpi=dpi))
    return _PIX[1]


def page_png(pdf_path: str, page_no: int, dpi: int) -> bytes:
    return page_pixmap(pdf_path, page_no, dpi).tobytes("png")


def page_array(pdf_path: str, page_no: int, dpi: int):
    """HxWxC uint8 数组（与 PNG 经 PIL 解码所得像素完全相同，省掉一次编码/解码）。"""
    import numpy as np

    pix = page_pixmap(pdf_path, page_no, dpi)
    buf = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    return buf[:, : pix.width * pix.n].reshape(pix.height, pix.width, pix.n).copy()
