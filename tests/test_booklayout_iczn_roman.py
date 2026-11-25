from docx import Document

from booklayout.builder import add_runs


def _runs(text, genera=None, italic=False):
    d = Document()
    p = d.add_paragraph()
    add_runs(p, text, 10, italic=italic, genera=genera)
    return [(r.text, bool(r.italic)) for r in p.runs]


def test_family_group_roman_inside_markdown_italic():
    r = _runs("Familia *Nereididae* y *Nereis diversicolor*")
    assert ("Nereididae", False) in r
    assert ("Nereis diversicolor", True) in r


def test_family_group_roman_when_base_italic():
    r = _runs("Phyllodocidae, Hesioninae y Aphroditoidea", italic=True)
    assert all(not it for t, it in r if t.endswith(("idae", "inae", "oidea")))


def test_genus_ending_ina_stays_italic():
    r = _runs("*Ophelina acuminata*")
    assert r == [("Ophelina acuminata", True)]
