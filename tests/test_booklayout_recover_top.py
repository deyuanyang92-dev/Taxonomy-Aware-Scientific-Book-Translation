from booklayout.recover_top import join_lines, lines_above, recover_top
from booklayout.sourcecheck import SrcLine


def L(i, t, conf=90.0):
    return SrcLine(1, i, t, conf, (0, 0, 1, 1))


def test_lines_above_and_join_dehyphenate():
    lines = [L(0, "encontró que están compuestos de una célula sen-"), L(1, "sorial y una pequeña lente."),
             L(2, "La gran mayoría de los Sílidos llevan")]
    above = lines_above(lines, "La gran mayoría de los Sílidos llevan tres antenas")
    assert len(above) == 2
    assert join_lines(above).endswith("célula sensorial y una pequeña lente.")


def test_recover_inserts_only_after_unfinished_page():
    d = {"pages": [{"page": 1, "blocks": [{"role": "body", "text": "termina y"}]},
                   {"page": 2, "blocks": [{"role": "body", "text": "La gran mayoría de los Sílidos llevan"}]}]}
    pl = {2: [L(0, "encontró que están compuestos de una"), L(1, "La gran mayoría de los Sílidos llevan")]}
    assert len(recover_top(d, pl)) == 1
    assert d["pages"][1]["blocks"][0]["text"].startswith("encontró")
