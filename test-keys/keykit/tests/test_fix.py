from keykit.fix import add_zh_names, check, fix_text, renumber
from keykit.ir import Couplet, KeyIR, Lead


def test_fix_text():
    assert fix_text("１２对") == "12对"
    assert fix_text("a" + chr(0x3000) + "b") == "ab"
    assert fix_text("背鳞 ......") == "背鳞......"
    assert fix_text("Exogone naidina 在").startswith("Exogone\xa0naidina")
    assert "Dorsal cirri" not in fix_text("Dorsal cirri")


def _ir():
    return KeyIR("t", [
        Couplet(1, None, [Lead("a", "jump", "5"), Lead("b", "jump", "9")]),
        Couplet(5, 1, [Lead("c", "taxon", "Exogone"), Lead("d", "jump", "9")]),
        Couplet(9, 5, [Lead("e", "taxon", "Brania x"), Lead("f", "taxon", "Brania y")]),
    ])


def test_renumber():
    ir, m = renumber(_ir())
    assert m == {1: 1, 5: 2, 9: 3}
    assert [c.num for c in ir.couplets] == [1, 2, 3]
    assert ir.couplets[0].leads[0].target == "2"
    assert ir.couplets[0].leads[1].target == "3"
    assert ir.couplets[2].backref == 2
    assert not [i for i in check(ir) if i["code"] == "S2" and i["severity"] == "critical"]


def test_check():
    ir = _ir()
    ir.couplets[0].leads[1].target = "77"
    codes = {i["code"] for i in check(ir)}
    assert "S2" in codes


def test_zh_names():
    ir, miss = add_zh_names(_ir(), lambda s: {"Exogone": "外指虫"}.get(s))
    assert ir.couplets[1].leads[0].name_zh == "外指虫"
    assert "Brania" in miss
