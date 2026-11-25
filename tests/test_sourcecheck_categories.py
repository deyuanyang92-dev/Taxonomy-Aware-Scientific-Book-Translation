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


def _cat(**kw):
    items = [_it(**kw)]
    sc.categorize(items, LEX, furniture=[__import__("re").compile(r"^(\d{1,4}\s+)?ANNELIDA\ POLYCHAETA\ I(\s+\d{1,4})?$")])
    return items[0]["category"], items[0]["blocking"]


def test_ocr_near_miss_positive():
    for s, o in [("Cossuripa", "Cossurida"), ("FIABELLIGERIDA", "FLABELLIGERIDA"),
                 ("uncinigero", "uncinígero"), ("sepiada", "septada"), ("Terehélidos", "Terebélidos"),
                 ("parapodicl", "parapodial"), ("ORCOYEÉN", "ORCOYEN"), ("Inn", "lnn"), ("Ins", "lns¹"),
                 ("vcur", "vcvr²"), ("dcor", "dcvr"), ("Ínbs", "lnbs"), ("19884", "1988a")]:
        assert _cat(type="review", source=s, output=o) == ("ocr_near_miss", False), (s, o)


def test_accent_only_single_letter_conflict():
    assert _cat(type="conflict", source="Á", output="A") == ("ocr_near_miss", False)


def test_page_number_noise():
    for s, o in [("Je", "293"), ("AS", "422")]:
        assert _cat(type="output_error", source=s, output=o) == ("ocr_noise", False)


def test_running_head_glue():
    assert _cat(type="review", source="lleANNELIDA POLYCHAETA 1", output="lle") == ("ocr_noise", False)


def test_faithful_name_suspect():
    for w in ("taxon", "palolo"):
        assert _cat(type="name_suspect", source=w, output=w) == ("faithful", False)


def test_must_stay_blocking():
    cases = [("review", "ent", "em"), ("review", "ndbl de", "dg"), ("conflict", "D", "I"), ("conflict", "E", "F"),
             ("output_error", "34D", "34I"), ("output_error", "f", "β"), ("conflict", "ce", "de"),
             ("output_error", "e", "we"), ("missing", "texto perdido", ""), ("missing", "ab", "")]
    for t, s, o in cases:
        assert _cat(type=t, source=s, output=o) == ("text", True), (t, s, o)


def test_translated_report_checks_numbers_and_names_only():
    from booklayout.sourcecheck import Lexicon, SrcLine, SrcTok, translated_report

    def tok(t, page, line):
        return SrcTok(t, page, line, 95.0, (0, 0, 1, 1))

    toks = [tok("figs.", 1, 1), tok("168A", 1, 1), tok("Haplosyllis", 1, 2), tok("1997", 1, 2)]
    lines = [SrcLine(1, i, "x", 95.0, (0, 0, 1, 1)) for i in range(3)]
    lex = Lexicon(words=frozenset({"figs"}), names=frozenset({"haplosyllis", "annelida"}))
    ok = translated_report(toks, lines, ["figs", "168A", "Haplosyllis", "1997", "extra"], lex, 60.0)
    assert ok["ok"] and ok["mode"] == "translated"
    bad = translated_report(toks, lines, ["168A", "Haplosyllis"], lex, 60.0)
    assert [i["src"] for i in bad["items"]] == ["1997"]
