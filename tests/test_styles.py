"""Typography measurement: label filter, bold/italic cues, CLI registration (synthetic pages, no OCR)."""
from __future__ import annotations


import numpy as np
from PIL import Image, ImageDraw, ImageFont

from booklayout import styles

FD = "/usr/share/fonts/truetype/dejavu/"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FD + name, size)


def _page(lines: list[tuple[str, str, int]], w: int = 900, h: int = 400) -> np.ndarray:
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    y = 20
    for text, font, size in lines:
        f = _font(font, size)
        d.text((20, y), text, font=f, fill="black")
        y += int(size * 1.9)
    return np.array(img)


def test_non_text_labels_are_skipped():
    for lab in ("image", "chart", "seal", "header_image", "footer_image", "figure"):
        assert not styles.is_text_block(lab)
    for lab in ("text", "content", "paragraph_title", "doc_title", "number", "footer"):
        assert styles.is_text_block(lab)


def test_bold_has_larger_stroke_than_regular():
    reg = styles.to_gray(_page([("Species nov anatomy", "DejaVuSans.ttf", 36)]))
    bold = styles.to_gray(_page([("Species nov anatomy", "DejaVuSans-Bold.ttf", 36)]))
    box = (0, 0, reg.shape[1], 80)
    a = styles.measure_block(reg, box, 300)
    b = styles.measure_block(bold, box, 300)
    assert a["stroke_rel"] and b["stroke_rel"]
    assert b["stroke_rel"] > a["stroke_rel"] * 1.2


def test_larger_font_has_larger_x_height():
    small = styles.to_gray(_page([("xxxx zzzz", "DejaVuSans.ttf", 24)]))
    big = styles.to_gray(_page([("xxxx zzzz", "DejaVuSans.ttf", 48)]))
    a = styles.measure_block(small, (0, 0, small.shape[1], 80), 300)
    b = styles.measure_block(big, (0, 0, big.shape[1], 120), 300)
    assert a["x_height_pt"] and b["x_height_pt"]
    assert b["x_height_pt"] > a["x_height_pt"] * 1.6


def test_oblique_words_have_positive_slant():
    obl = styles.to_gray(_page([("slanted words here", "DejaVuSansMono-Oblique.ttf", 40)]))
    m = styles.measure_block(obl, (0, 0, obl.shape[1], 90), 300)
    slants = [w["slant"] for w in m["words"]]
    assert slants and np.median(slants) > 5


def test_parse_pages_ranges():
    assert styles._parse_pages("1-3,7") == [1, 2, 3, 7]
    assert styles._parse_pages("5") == [5]


def test_cli_registered():
    import booklayout.cli as c
    assert c.styles_module is styles
