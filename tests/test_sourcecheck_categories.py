"""source-check 问题分类登记（category / blocking / issues.tsv / name-fixes.tsv），Vol25 p1-50 实例。"""
from booklayout import sourcecheck as sc

LEX = sc.Lexicon(words=frozenset({"familia", "incluyen", "ahora", "a", "los", "con", "vaso", "sanguíneo", "zona"}),
                 names=frozenset({"nephtyidae", "amphinomidae", "savigny", "poeobiidae", "polychaeta"}))


def _it(**kw):
    base = {"id": "x", "src_page": 1, "out_page": 1, "output": "", "box": (0, 0, 10, 10), "conf": 90.0}
    base.update(kw)
    return base


def test_ocr_misread_name_judged_output_correct():
    items = [_it(type="review", source="Nepbtyidae", output="Nephtyidae 390"),
             _it(type="review", source="Poeobíidae", output="Poeobiidae")]
    sc.categorize(items, LEX)
    assert [i["category"] for i in items] == ["name_ocr", "name_ocr"]
    assert not any(i["blocking"] for i in items)


def test_real_word_output_change_stays_blocking():
    # 成品 FAUNA 与原书 POLYCHAETA 都是真词，不是学名错字：仍要人看
    items = [_it(type="conflict", source="POLYCHAETA", output="FAUNA")]
    sc.categorize(items, LEX)
    assert items[0]["category"] == "text" and items[0]["blocking"]


def test_output_typo_of_known_name_goes_to_replace_table(tmp_path):
    items = [_it(type="output_error", source="Nephtyidae", output="Nepbtyidae", src_page=6)]
    sc.categorize(items, LEX)
    assert items[0]["category"] == "name_replace" and items[0]["blocking"]
    led, nf = sc.write_ledger({"items": items}, tmp_path / "r.json")
    assert "output_wrong\tNepbtyidae\tNephtyidae\t1\t6" in nf.read_text(encoding="utf-8")
    assert led.read_text(encoding="utf-8").count("\n") == 2


def test_missing_line_near_figure_is_figure_text():
    figs = {30: [(400, 297, 1284, 841)]}
    items = [_it(type="missing", src_page=30, source="Seno sanguíneo intestinal", box=(1231, 408, 1568, 436)),
             _it(type="missing", src_page=30, source="texto lejos", box=(200, 2000, 900, 2040))]
    sc.categorize(items, LEX, figs, dpi=300)
    assert items[0]["category"] == "figure_text" and not items[0]["blocking"]
    assert items[1]["category"] == "text" and items[1]["blocking"]


def test_moved_is_reading_order_not_blocking():
    items = [_it(type="moved", source="Antonio José Laborda")]
    sc.categorize(items, LEX)
    assert items[0]["category"] == "reading_order"
    ok, open_ = sc.verdict({"items": items}, set())
    assert ok and not open_


def test_review_page_lists_only_blocking_items():
    from booklayout import review
    rep = {"items": [{"id": "a", "type": "moved", "blocking": False}, {"id": "b", "type": "review", "blocking": True}]}
    assert [i["id"] for i in review.open_items(rep, set())] == ["b"]


def test_fuzzy_find_line_with_ocr_misread_word():
    near = "x familia amphinomidae savigny 1818 y".split()
    assert sc.fuzzy_find(["Familia", "Amphbinomidae", "Savigny,", "1818"], near, LEX) == "familia amphinomidae savigny 1818"
    assert sc.fuzzy_find(["incluyen", "abora", "a", "los"], "incluyen ahora a los".split(), LEX)
    # 真词不放宽：ahora 不能匹配 ahorro
    assert sc.fuzzy_find(["incluyen", "ahora", "a", "los"], "incluyen ahorro a los".split(), LEX) is None


def test_fuzzy_found_missing_is_ocr_noise():
    items = [_it(type="missing", source="Familia Amphbinomidae Savigny, 1818", fuzzy_output="familia amphinomidae")]
    sc.categorize(items, LEX)
    assert items[0]["category"] == "ocr_noise" and not items[0]["blocking"]
