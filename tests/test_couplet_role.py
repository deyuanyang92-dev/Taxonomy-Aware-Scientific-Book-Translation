import docx
from booklayout.builder import couplet_para


def test_couplet_para_has_real_dot_leader_tab():
    d = docx.Document()
    b = {"couplet": {"marker": "2.", "name": "*Aphrodita*", "target": "3"}}
    p = couplet_para(d, b, "口前叶无眼柄", set())
    xml = p._p.xml
    assert 'w:leader="dot"' in xml and "w:tab/" in xml.replace(" ", "") or "<w:tab/>" in xml
    assert "2." in p.text and p.text.rstrip().endswith("3")
