import pytest

from keykit.profile import detect_style, for_lang


def test_for_lang():
    p = for_lang("zh", "dash")
    assert p.overflow == "wrap" and p.dest_zh_name
    e = for_lang("en", "prime")
    assert e.overflow == "fill" and not e.dest_zh_name and e.second_lead == "prime"
    with pytest.raises(ValueError):
        for_lang("zh")


def test_detect_style():
    assert detect_style(["1.", "—", "2.", "—", "3.", "-"]) == "dash"
    assert detect_style(["1.", "1'", "2.", "2′"]) == "prime"
    assert detect_style(["1.", "—", "2 (1).", "—", "3 (1)."]) == "backref"
    assert detect_style(["1", "2", "3", "4"]) == "number"
    assert detect_style(["1.", "—", "2.", "2'"]) is None
