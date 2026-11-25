"""检索表行尾跳转号补读（零模型）。

问题：日文志书检索表的「描述……号」行，PP-OCR 的检测器常把「点线 + 号」整段漏掉（缓存里根本没有那个数字行），
语法层无从恢复，条目就成了「无终点」。这里只对「无终点、且有末行位置」的条目，裁出该行右边缘的窄条，
用 tesseract 只认数字重读。

接受条件（防止把噪声当终点）：读出的号必须 ① 是本表已有的条目号，② 大于本条目号（检索表只向前跳）。
不满足的不改动，保留原有的「无终点」告警，由图检查和人工处理。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import keys

STRIP_X0 = 0.84  # 号在页宽 0.92–0.98 处；留出点线余量
_PADS = (14, 26)
_SCALES = (2, 3)


def _lead_num(lead: str) -> int | None:
    m = re.match(r"(\d+)", lead)
    return int(m.group(1)) if m else None


def recover_tail_jumps(data: dict[str, Any], render: Callable[[int], Any],
                       ocr: Callable[[Any], str]) -> list[dict[str, Any]]:
    """就地补 data["couplets"] 里无终点条目的跳转号，重算 data["keys"]；返回逐条记录。

    render(页号) → 整页 PIL 图（像素宽须与 data["widths"][页] 同一刻度）；ocr(PIL 图) → 文本。
    """
    couplets = data["couplets"]
    valid: dict[int, set[int]] = {}
    for c in couplets:
        n = _lead_num(c["lead"])
        if n is not None and "'" not in c["lead"]:
            valid.setdefault(c["key"], set()).add(n)
    log: list[dict[str, Any]] = []
    pages: dict[int, Any] = {}
    for c in couplets:
        bad_jump = (len(c["terminals"]) == 1 and c["terminals"][0].isdigit()
                    and int(c["terminals"][0]) not in valid.get(c["key"], set()))
        if (c["terminals"] and not bad_jump) or "geom" not in c:
            continue  # 有终点就不动；唯一例外是跳转号不是本表任何条目（OCR 多/错一位，如「50」读成「500」）
        me = _lead_num(c["lead"])
        rec: dict[str, Any] = {"page": c["page"], "lead": c["lead"], "key": c["key"], "got": None,
                               **({"was": c["terminals"][0]} if bad_jump else {})}
        log.append(rec)
        if me is None:
            continue
        img = pages.get(c["page"]) or pages.setdefault(c["page"], render(c["page"]))
        scale_px = img.width / float(data["widths"][str(c["page"])])
        y0, y1 = c["geom"]["y0"] * scale_px, c["geom"]["y1"] * scale_px
        seen: list[str] = []
        for pad in _PADS:
            for sc in _SCALES:
                box = (int(STRIP_X0 * img.width), max(0, int(y0 - pad)), img.width, min(img.height, int(y1 + pad)))
                crop = img.crop(box)
                crop = crop.resize((crop.width * sc, crop.height * sc))
                for d in re.findall(r"\d{1,3}", ocr(crop)):
                    seen.append(d)
                    if int(d) > me and int(d) in valid.get(c["key"], set()):
                        c["terminals"] = [d]
                        c["slots"] = [keys.term_struct(keys.default_grammar(), d)]
                        c["recovered"] = "tail-ocr"
                        rec["got"] = d
                        break
                if rec["got"]:
                    break
            if rec["got"]:
                break
        rec["seen"] = seen
    data["keys"] = [{"key": k, **v} for k, v in keys.check_couplets(couplets).items()]
    return log


def pdf_renderer(pdf: str, dpi: int) -> Callable[[int], Any]:
    from PIL import Image

    from .engines.pageimg import page_pixmap

    def render(pg: int) -> Any:
        pix = page_pixmap(pdf, pg, dpi)
        return Image.frombytes("RGB" if pix.n == 3 else "L", (pix.width, pix.height), pix.samples)

    return render


def tesseract_digits(img: Any) -> str:
    """tesseract 单行（psm 7）只认数字；失败返回空串。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "c.png"
        img.save(p)
        try:
            r = subprocess.run(["tesseract", str(p), "-", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789"],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return r.stdout.strip()
