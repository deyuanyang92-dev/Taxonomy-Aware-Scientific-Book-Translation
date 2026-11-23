"""Key address: taxon italics and visible unbreakable spaces (Imajima/t41 keys)."""
from docx import Document
from docx.oxml.ns import qn

from booklayout import builder
from booklayout.builder import italicize_key_address


def test_italicize_abbreviated_and_bare_names():
    assert italicize_key_address("M. fragilis（第287页）") == "*M. fragilis*（第287页）"
    assert italicize_key_address("Pontogenia") == "*Pontogenia*"
    assert italicize_key_address("Syllis gracilis Grube (p. 12)") == "*Syllis gracilis* Grube (p. 12)"


def test_leave_suprageneric_numbers_and_marked():
    for s in ("亚科 Iphioninae", "Polynoidae", "12", "M.", "*Aphrodita*", "Family", ""):
        assert italicize_key_address(s) == s


def test_space_before_author_after_italic():
    assert italicize_key_address("*P. macleari*(Haswell)") == "*P. macleari* (Haswell)"


def test_couplet_glue_is_own_widened_run():
    doc = Document()
    block = {"couplet": {"marker": "5.", "name": None, "target": "Aphrodita aculeata Linnaeus （图1）"}}
    p = builder.couplet_para(doc, block, "背刚毛黄褐色", set())
    runs = p.runs
    glue = [r for r in runs if r.text == builder._GLUE]
    assert glue, [r.text for r in runs]
    assert all(r._r.rPr.find(builder.qn("w:spacing")) is not None for r in glue)
    assert any(r.italic and r.text == "Aphrodita" for r in runs)
    assert not any(" " in r.text for r in runs[runs.index(glue[0]) - 1:])
    text = "".join(r.text for r in runs)
    assert "Aphrodita" + builder._GLUE + "aculeata" + builder._GLUE + "Linnaeus" in text


def _couplet(text, target="6"):
    doc = Document()
    block = {"couplet": {"marker": "—", "target": target}}
    return builder.couplet_para(doc, block, text, set())


def _breaks(p):
    return [r for r in p.runs if r._r.findall(qn("w:br"))]


def test_couplet_short_tail_fills_line_then_wraps():
    # Imajima 2001 p.5: the address did not fit after the text; the dots must
    # run to the margin of that line and continue on the next, not leave a
    # blank tail.
    p = _couplet("背" * 28, "亚科 Harmothoinae")  # ~104 of 118 mm used
    texts = [r.text for r in p.runs]
    assert texts[:2] == ["—", "\t"]
    assert texts[3:6] == ["\t", "\n", "\t"]  # fill tab, line break, leader tab


def test_couplet_address_that_fits_stays_on_the_line():
    p = _couplet("侧触手自口前叶前端腹侧生出，具基节；触须基节无刚毛")
    assert not _breaks(p)
    assert sum(r.text.count("\t") for r in p.runs) == 2  # marker tab + leader tab


def test_number_glued_to_measure_word():
    glued = builder.join_number_measure("背鳞13对；2对颚")
    assert glued == "背鳞13" + builder._GLUE + "对；2" + builder._GLUE + "对颚"


def test_last_line_mm_wraps():
    one = builder.last_line_mm("背刚毛", 10.5, 118)
    assert 10 < one < 12
    assert builder.last_line_mm("背" * 40, 10.5, 118) < 40


def test_marker_tab_survives_so_text_starts_at_one_column():
    # KR1/KR2: clean_text() turned the marker tab into a space, so "1." text,
    # "—" text and wrapped lines started at three different x.
    for marker in ("1.", "10.", "—"):
        doc = Document()
        p = builder.couplet_para(doc, {"couplet": {"marker": marker, "target": "2"}}, "背刚毛", set())
        texts = [r.text for r in p.runs]
        assert texts[:2] == [marker, "\t"], texts


def test_couplet_pair_kept_on_one_page():
    # KR7: "n." keeps with its "—" partner; no lead splits over pages.
    doc = Document()
    first = builder.couplet_para(doc, {"couplet": {"marker": "11.", "target": "12"}}, "背刚毛", set())
    second = builder.couplet_para(doc, {"couplet": {"marker": "—", "target": "13"}}, "腹刚毛", set())
    assert first.paragraph_format.keep_with_next and first.paragraph_format.keep_together
    assert not second.paragraph_format.keep_with_next and second.paragraph_format.keep_together
