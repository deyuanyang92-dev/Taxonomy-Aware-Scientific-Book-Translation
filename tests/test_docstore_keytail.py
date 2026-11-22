"""keytail：检索表行尾跳转号补读（零模型）。用桩图像和桩 OCR，不依赖 PDF/tesseract。"""
from __future__ import annotations

from docstore import keytail


class _Img:
    width, height = 1000, 1000

    def crop(self, box):
        return self

    def resize(self, size):
        return self


def _c(lead, key=1, terminals=(), page=5):
    return {"lead": lead, "key": key, "terminals": list(terminals), "slots": [], "page": page,
            "geom": {"y0": 100.0, "y1": 120.0}}


def _data(couplets):
    return {"couplets": couplets, "widths": {"5": 1000}, "keys": []}


def _run(couplets, text):
    d = _data(couplets)
    log = keytail.recover_tail_jumps(d, lambda p: _Img(), lambda img: text)
    return d, log


def test_accept_forward_existing_target():
    d, log = _run([_c("1"), _c("1'"), _c("2", terminals=["a"]), _c("2'", terminals=["b"])], "2")
    assert d["couplets"][0]["terminals"] == ["2"]
    assert d["couplets"][0]["recovered"] == "tail-ocr"
    assert log[0]["got"] == "2"


def test_reject_backward_or_unknown():
    d, log = _run([_c("3"), _c("3'", terminals=["a"]), _c("4", terminals=["b"])], "2 99 7")
    assert d["couplets"][0]["terminals"] == []
    assert log[0]["got"] is None and log[0]["seen"]


def test_nothing_read_leaves_untouched():
    d, log = _run([_c("1"), _c("2", terminals=["a"])], "")
    assert d["couplets"][0]["terminals"] == []
    assert log[0]["got"] is None


def test_existing_terminal_kept():
    d, log = _run([_c("1", terminals=["2"]), _c("2", terminals=["a"])], "2")
    assert log == [] and d["couplets"][0]["terminals"] == ["2"]


def test_bad_jump_number_replaced():
    # 「50」被读成「500」：500 不是本表任何条目 → 重读
    d, log = _run([_c("49", terminals=["500"]), _c("50", terminals=["a"])], "50")
    assert d["couplets"][0]["terminals"] == ["50"]
    assert log[0]["was"] == "500"
