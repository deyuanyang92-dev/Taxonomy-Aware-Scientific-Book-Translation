"""profilegen, family_of weight/slant tokens, ingest short-line rules."""
from __future__ import annotations

from booklayout import fontlevels
from booklayout.profile import StyleProfile


def test_family_of_strips_stacked_weight_tokens():
    f = fontlevels.family_of
    assert f("Arial-BoldItalicMT") == f("Arial-BoldMT") == "Arial"
    assert f("ABCDEF+Meta-BoldItalic") == "Meta"


def test_profile_columns_and_running_top_validate():
    p = StyleProfile.from_dict({"columns": 2, "footer_style": "running_top", "page_w": 210, "page_h": 280})
    assert p.columns == 2 and p.footer_style == "running_top"


def test_profile_rejects_bad_columns():
    import pytest

    with pytest.raises(Exception):
        StyleProfile.from_dict({"columns": 9})


def test_measure_profile_two_columns(tmp_path):
    import fitz

    from booklayout.profilegen import measure_profile

    doc = fitz.open()
    for n in range(4):
        pg = doc.new_page(width=420, height=600)
        pg.insert_text((190, 30), f"Running head text {n}", fontsize=8)
        pg.insert_text((40 if n % 2 else 380, 30), str(n + 1), fontsize=9)
        for col, x in enumerate((40, 220)):
            for i in range(30):
                pg.insert_text((x, 70 + i * 14), f"word{i} body line of text in column {col} here", fontsize=9)
    pdf = tmp_path / "s.pdf"
    doc.save(str(pdf))
    prof = measure_profile(pdf)
    assert prof["columns"] == 2
    assert prof["footer_style"] == "running_top"
    StyleProfile.from_dict(prof)
