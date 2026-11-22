"""德文基础形态术语：占位、按目标语言还原，并与 yiku 已核定名对照。"""
import os
import sqlite3

import pytest
import protect
import term_de


def test_mask_and_restore_zh_en():
    t = "Das Prostomium trägt 4 Antennen und 54 Borstensegmente; die Parapodien fehlen."
    m, s = protect.mask(t, "de")
    assert s == ["Prostomium", "Antennen", "Borstensegmente", "Parapodien"]
    assert protect.restore(m, s, "zh-CN") == "Das 口前叶 trägt 4 触手 und 54 刚节; die 疣足 fehlen."
    assert protect.restore(m, s, "en") == "Das prostomium trägt 4 antennae und 54 chaetigers; die parapodia fehlen."


def test_bis_range_and_paar():
    t = "Der Magen ist 2 bis 2% Segmente lang, 10 Paar Elytren, 1,5 bis 3 mm."
    m, s = protect.mask(t, "de")
    assert s[:2] == ["2 bis 2%", "10 Paar"] or "2 bis 2%" in s
    out = protect.restore(m, s, "zh-CN")
    assert "2–2½" in out and "10对" in out and "bis" not in out
    assert "10 pairs" in protect.restore(m, s, "en")


def test_other_source_language_untouched():
    assert protect.mask("Prostomium", "ja")[1] == []
    assert protect.mask("Prostomium")[1] == []


def test_no_partial_word():
    assert protect.mask("Palpenartig Antennenlos", "de")[1] == []


@pytest.mark.skipif(not os.path.exists(os.path.expanduser("~/.yiku/yiku.db")), reason="no yiku.db")
def test_zh_matches_yiku_checked_terms():
    c = sqlite3.connect(os.path.expanduser("~/.yiku/yiku.db"))
    for *_, zh, _en_s, _en_p, key in [(0, *t[2:]) for t in term_de.TERMS]:
        n = c.execute("select count(*) from terms where en_norm like ? and zh=? and status='已核'",
                      ("%" + key + "%", zh)).fetchone()[0]
        assert n, (key, zh)
