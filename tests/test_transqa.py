"""transqa：共用 QA 层。含 2026-11-15 gpt-6-astra 审查的五个内存探针回归用例。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import auto_translate as at  # noqa: E402
from transqa import check_all, segments_from_pages  # noqa: E402
from transqa import languages as L  # noqa: E402

SRC = """<!-- PDF p.1 -->

Тялото късо. Четири очи. *Exogone gemmifera* Pagenstecher, 1863.

Цвят белезникав.

1(2) Хоботът със зъбче …… 3

2(1) Без зъбче …… 2. *G. limbata* Claparède

<!-- PDF p.2 -->

Дължина 2—3 mm (Vinogradov, 1949).
"""

TGT = """<!-- PDF p.1 -->

Body short. 4 eyes. *Exogone gemmifera* Pagenstecher, 1863.

Colour whitish.

1(2) Proboscis with a small tooth …… 3

2(1) Without a tooth …… 2. *G. limbata* Claparède

<!-- PDF p.2 -->

Length 2—3 mm (Vinogradov, 1949).
"""


def codes(src, tgt, sl="bg", tl="en", **kw):
    return {i.code: i for i in check_all(src, tgt, sl, tl, **kw)}


def test_clean_translation_has_no_blocking_issue():
    assert [i for i in check_all(SRC, TGT, "bg", "en") if i.blocking] == []


# ---- 五个审查探针 ----
def test_punct_only_source_segment_not_empty():
    src = "<!-- PDF p.1 -->\n\nText eins.\n\n,\n\nText zwei."
    assert "coverage.segment_empty" not in [i.code for i in check_all(src, src, "de", "de")]


def test_probe1_malformed_json_is_failure_not_empty():
    assert at.parse_json_array('[1,"unexpected"]') is None
    assert at.parse_json_array('[{"id": 1}, "junk"]') is None
    assert at.parse_json_array("[]") == []


def test_probe2_deleted_paragraph_without_numbers():
    c = codes(SRC, TGT.replace("Colour whitish.\n\n", ""))
    assert c["coverage.segment_missing"].severity == "major"


def test_probe3_added_number():
    c = codes(SRC, TGT.replace("Colour whitish.", "Colour whitish, 7 bands."))
    assert c["number.added"].severity == "major"


def test_probe4_pages_swapped():
    a, b = TGT.split("<!-- PDF p.2 -->")
    swapped = "<!-- PDF p.2 -->" + b + "\n" + a
    assert codes(SRC, swapped)["coverage.page_order"].severity == "critical"


def test_probe5_ja_to_zh_shared_han_is_not_residue():
    src = "<!-- PDF p.1 -->\n\n体は短い。\n"
    assert "script.residue" not in codes(src, "<!-- PDF p.1 -->\n\n身体短。\n", "ja", "zh-CN")
    assert "script.residue" in codes(src, "<!-- PDF p.1 -->\n\n身体は短い。\n", "ja", "zh-CN")


# ---- 其他 ----
def test_numeral_word_may_become_digit_but_unknown_language_only_info():
    assert "number.added" not in codes(SRC, TGT)            # Четири → 4
    c = codes("<!-- PDF p.1 -->\n\nX y.\n", "<!-- PDF p.1 -->\n\nX 4 y.\n", "xx", "en")
    assert c["number.added"].severity == "info" and "capability_missing" in c


def test_missing_number_is_critical():
    assert codes(SRC, TGT.replace("2—3 mm", "small"))["number.missing"].severity == "critical"


def test_cyrillic_residue_ignores_figure_labels_and_italics():
    tgt = TGT.replace("Colour whitish.", "Colour whitish (pl. IV, 1а—1г), *Тест* Тялото.")
    c = codes(SRC, tgt)
    assert "Тялото" in c["script.residue"].message and "Тест" not in c["script.residue"].message


def test_negation_risk_is_info_only():
    c = codes(SRC, TGT.replace("Without a tooth", "With a tooth"))
    assert c["meaning.negation_risk"].severity == "info"


def test_key_lead_changed_and_couplet_missing():
    assert codes(SRC, TGT.replace("…… 3", "…… 4"))["key.structure"].severity == "critical"
    assert codes(SRC, TGT.replace("2(1) Without", "2. Without"))["key.couplet_missing"].severity == "critical"


def test_key_graph_dangling_and_unpaired_in_translation():
    src = "<!-- PDF p.1 -->\n\n1(2) а …… 3\n\n2(1) б …… 3\n\n3(4) в\n\n4(3) г\n"
    tgt = "<!-- PDF p.1 -->\n\n1(2) a …… 3\n\n2(1) b …… 0\n\n3(4) c\n\n4(5) d\n"
    c = codes(src, tgt)
    assert "key.dangling" in c and "key.unpaired" in c


def test_repeated_latin_name_dropped_once_is_caught():
    src = SRC.replace("Цвят белезникав.", "Цвят белезникав, като *Exogone gemmifera*.")
    assert codes(src, TGT)["taxon.name_missing"].severity == "critical"


def test_footnote_asterisks_do_not_become_italic_taxa():
    from transqa.taxonomy import latin_names

    text = "Paraprionospio * 14. Gills absent ... *P. hoplura* (p. 253)"
    assert latin_names(text) == ["P. hoplura"]


def test_parenthesised_authority_change():
    assert "taxon.authority_changed" in codes(SRC, TGT.replace("(Vinogradov, 1949)", "(Vinogradov 1950)"))


def test_foreign_script_and_bad_terms():
    c = codes(SRC, TGT.replace("Body", "Bोdy").replace("eyes", "eyes setae"), bad_terms=["setae"])
    assert "script.foreign" in c and c["term.forbidden"].severity == "major"


def test_segments_ids_and_marker_skip():
    s = segments_from_pages(SRC)
    assert s[0].id == "p1_s1" and s[-1].id == "p2_s1" and all("<!--" not in x.text for x in s)


def test_languages_numerals_tables():
    assert L.numerals("bg")["четири"] == 4 and L.numerals("ru")["одна"] == 1 and L.numerals("en")["twenty"] == 20
    assert L.numeral_values("三つの鰓", "ja") == [3]


def test_merged_paragraphs_without_blank_line_are_minor_and_plates_ignored():
    merged = TGT.replace("Body short. 4 eyes. *Exogone gemmifera* Pagenstecher, 1863.\n\nColour",
                         "Body short. 4 eyes. *Exogone gemmifera* Pagenstecher, 1863.\nColour")
    c = codes(SRC, merged)
    assert c["coverage.segment_merged"].severity == "minor" and "coverage.segment_missing" not in c
    src = "<!-- PDF p.1 -->\n\n[图版：Таблица I]\n\nГлава: 1а.\n"
    assert "coverage.segment_missing" not in codes(src, "<!-- PDF p.1 -->\n\n[[PLATE I]]\nHead: 1а.\n")


def test_decimal_comma_equals_point():
    c = codes("<!-- PDF p.1 -->\n\nДо 33,6 %.\n", "<!-- PDF p.1 -->\n\nUp to 33.6%.\n")
    assert "number.missing" not in c and "number.added" not in c


def test_thousands_separators_equal():
    for en in ("136,000", "136 000", "136000"):
        c = codes("<!-- PDF p.1 -->\n\nОколо 136 000 екз.\n", f"<!-- PDF p.1 -->\n\nAbout {en} specimens.\n")
        assert "number.missing" not in c and "number.added" not in c, en
    assert "number.missing" not in codes("<!-- PDF p.1 -->\n\n1,2 mm\n", "<!-- PDF p.1 -->\n\n1.2 mm\n")


def test_template_round_trip_is_exact():
    from transqa.segments import render, split_template
    md = "<!-- PDF p.1 | x -->\n\n[图版：Таблица I]\nГлава: 1а.\n\nДруг абзац\nвтори ред.\n\n<!-- PDF p.2 -->\nТекст.\n"
    segs, tpl = split_template(md)
    assert render(tpl, {s.id: s.text for s in segs}) == md
    assert [s.id for s in segs] == ["p1_s1", "p1_s2", "p2_s1"] and segs[0].text == "Глава: 1а."


def test_block_classifier_and_deterministic_pass():
    from transqa.blocks import classify, deterministic, residue_left
    syn = "*Ph. tuberculata* Bobretzky, 1868, стр. 15; Зернов, 1913, стр. 220; Якубова и Маринов, 1930, стр. 86"
    assert classify(syn, "bg") == "synonymy"
    assert classify("Типов вид *Phyllodoce laminosa* Savigny, 1818", "bg") != "index"
    assert classify("През 1954 и 1960 г. бяха започнати изследвания; резултатите са публикувани.", "bg") == "free"
    assert classify("Арнольди, Л. 1948. О литорали в Черном море.", "bg") == "reference"
    names = [("Зернов", "Zernov"), ("Якубова", "Jakubova"), ("Маринов", "Marinov")]
    d = deterministic(syn, "bg", names)
    assert d == "*Ph. tuberculata* Bobretzky, 1868, p. 15; Zernov, 1913, p. 220; Jakubova and Marinov, 1930, p. 86"
    assert not residue_left(d, "bg") and residue_left("Виноградов, 1949", "bg")


def test_classifier_edge_cases_from_review():
    from transqa.blocks import classify, deterministic
    assert classify("Smith, J. 1990. A paper.\nThe body is long and the eyes are many.", "en") != "reference"
    assert classify("In 1950 and 1960 the species was found; later it disappeared.", "en") == "free"
    assert classify("Length, 12, 15 mm", "en") != "index"
    assert classify("abtensis, Leiochone, 194", "la") == "index"
    assert deterministic("S. latifolia; vgl. S. 12, Taf. IV", "de") == "S. latifolia; vgl. p. 12, pl. IV"


def test_multiline_reference_block():
    from transqa.blocks import classify
    block = "Арнольди, Л. 1948. О литорали в Черном море.\nБекман, М. 1952. Материалы.\nBellan, G. 1964. Contribution."
    assert classify(block, "bg") == "reference"


def test_toc_crosscheck_catches_genus_initial_and_page():
    from transqa.taxonomy import toc_crosscheck
    md = ("<!-- PDF p.6 | 印刷页 5 -->\n\n| Contents | Printed page |\n| --- | --- |\n"
          "| 2. Genus *Lagisca* Malmgren | 73 |\n| *I. extenuata* (Grube) | 73 |\n| *H. imbricata* (Linnaeus) | 90 |\n\n"
          "<!-- PDF p.80 | 印刷页 73 -->\n\n## 2. Genus *Lagisca* Malmgren\n\n### 1. *Lagisca extenuata* (Grube, 1840)\n\n"
          "### 1. *Harmothoe imbricata* (Linnaeus, 1767)\n")
    codes = {i.code for i in toc_crosscheck(md)}
    assert "toc.genus_initial" in codes and "toc.page" in codes
    good = md.replace("*I. extenuata*", "*L. extenuata*").replace("| 90 |", "| 73 |")
    assert toc_crosscheck(good) == []


def test_placeholder_count_mismatch_is_critical():
    src = "<!-- PDF p.1 -->\n\n[图版：Таблица I]\n\nТекст.\n\n<!-- PDF p.2 -->\n\n[图版：Таблица II]\n\nТекст.\n"
    tgt = "<!-- PDF p.1 -->\n\n[[PLATE I]]\n\nText.\n\n<!-- PDF p.2 -->\n\nText.\n"
    assert codes(src, tgt)["coverage.placeholder"].severity == "critical"


# ---------------- GitHub #12：脚注星号 vs 斜体 ----------------
def test_issue12_single_word_italic_names_are_extracted():
    from transqa.taxonomy import latin_names

    assert latin_names("Genus *Onuphis* and family *Onuphidae* occur.") == ["Onuphis", "Onuphidae"]
    assert latin_names("*Exogone gemmifera* Pagenstecher") == ["Exogone gemmifera"]
    assert latin_names("*Nereis* (*Neanthes*) *virens* subsp. *x*") == ["Nereis", "Neanthes", "virens", "x"]


def test_issue12_footnote_markers_never_open_italics():
    from transqa.taxonomy import latin_names

    # 独立星号、*1、附着在分类单元后的脚注星号，都不配对
    assert latin_names("Paraprionospio *\n14. Gills absent\nP. triglanda*\n15. other *Onuphis* here") == ["Onuphis"]
    assert latin_names("see note * and *1 then *Onuphis* done") == ["Onuphis"]
    assert latin_names("Paraprionospio * 14. Gills absent ... *P. hoplura* (p. 253)") == ["P. hoplura"]
    assert latin_names("P. triglanda* and later text *Onuphidae*") == ["Onuphidae"]


def test_issue12_italic_does_not_cross_lines_or_branches():
    from transqa.taxonomy import latin_names

    text = "1(2) Prostomium *Onuphis\n2(1) Palps absent ... *Diopatra*"
    assert latin_names(text) == ["Diopatra"]


def test_issue12_omitted_single_name_still_flagged():
    src = SRC.replace("Цвят белезникав.", "Цвят белезникав, сем. *Onuphidae*.")
    assert codes(src, TGT)["taxon.name_missing"].severity == "critical"


# ---------------- GitHub #8：作者连词归一 ----------------
def _auth(src_name, tgt_name, sl="es", tl="en"):
    s = f"<!-- PDF p.1 -->\n\n*Onuphis eremita* ({src_name}, 1989) fue citada."
    t = f"<!-- PDF p.1 -->\n\n*Onuphis eremita* ({tgt_name}, 1989) was cited."
    return {i.code for i in check_all(s, t, sl, tl)}


def test_issue8_spanish_y_equals_and():
    assert "taxon.authority_changed" not in _auth("Jamieson y Rouse", "Jamieson and Rouse")


def test_issue8_other_conjunctions_normalised():
    for src_c, tgt_c in [("et", "&"), ("und", "and"), ("e", "and"), ("&", "and"), ("y", "&")]:
        assert "taxon.authority_changed" not in _auth(f"Rouse {src_c} Pleijel", f"Rouse {tgt_c} Pleijel"), src_c


def test_issue8_changed_surname_or_year_still_flagged():
    assert "taxon.authority_changed" in _auth("Jamieson y Rouse", "Jamieson and Fauchald")
    s = "<!-- PDF p.1 -->\n\n(Rouse y Pleijel, 1989)"
    t = "<!-- PDF p.1 -->\n\n(Rouse and Pleijel, 1990)"
    assert "taxon.authority_changed" in {i.code for i in check_all(s, t, "es", "en")}


# ---------------- GitHub #5：实体检查按目标语言 ----------------
def test_issue5_chinese_names_only_for_chinese_targets():
    from transqa.languages import wants_chinese_names

    assert wants_chinese_names("zh") and wants_chinese_names("zh-CN") and wants_chinese_names("ZH-tw")
    assert not any(wants_chinese_names(x) for x in ("en", "es", "ja", "de", "", "und"))


def test_issue5_gate_entities_drops_chinese_requirements_for_english_target():
    from transqa.languages import gate_entities

    res = [{"surface": "Onuphidae", "canonical": "Onuphidae", "zh": "欧努菲虫科", "status": "已核", "type": "taxon"}]
    assert gate_entities(res, "en") == []          # 西→英：Onuphidae 保留拉丁名，不要求 欧努菲虫科
    assert gate_entities(res, "es") == []
    assert gate_entities(res, "zh") == res
    assert gate_entities(res, "zh-CN") == res


# ---------------- GitHub #10：数字检查跨页对齐 + 页眉页脚 ----------------
def _pages(*texts):
    return "\n\n".join(f"<!-- PDF p.{i} -->\n\n{t}" for i, t in enumerate(texts, 1))


def test_issue10_number_shift_to_adjacent_page_is_alignment_warning_not_error():
    src = _pages("Se midieron 60 ejemplares.", "Longitud media 300 setas largas.", "Fin del texto.")
    tgt = _pages("60 specimens were measured. Mean length 300", "setas long. Nothing else.", "End of text.")
    got = check_all(src, tgt, "es", "en")
    assert not [i for i in got if i.code in ("number.missing", "number.added")]
    shift = [i for i in got if i.code == "number.page_shift"]
    assert shift and all(not i.blocking for i in shift)
    assert shift[0].evidence["numbers"] and "src_context" in shift[0].evidence and "tgt_context" in shift[0].evidence


def test_issue10_real_missing_number_still_critical():
    src = _pages("Se midieron 60 ejemplares.", "Fin.")
    tgt = _pages("Specimens were measured.", "End.")
    assert "number.missing" in {i.code for i in check_all(src, tgt, "es", "en")}


def test_issue10_strict_numbers_not_matched_across_pages():
    # 年份、检索表编号、带单位的测量值：不允许借相邻页抵消
    src = _pages("Rouse, 1989 es citado.", "Otra cosa.")
    tgt = _pages("Rouse is cited.", "Other thing, 1989.")
    got = {i.code for i in check_all(src, tgt, "es", "en")}
    assert "number.missing" in got and "number.added" in got
    src = _pages("Longitud 12 mm.", "Otra cosa.")
    tgt = _pages("Length.", "Other thing 12 mm.")
    got = {i.code for i in check_all(src, tgt, "es", "en")}
    assert "number.missing" in got


def test_issue10_running_header_and_folio_excluded():
    src = _pages("16 FAUNA IBÉRICA\n\nTexto del cuerpo.", "FAUNA IBÉRICA 17\n\nOtro texto.", "18\n\nTercero.")
    tgt = _pages("Body text.", "Other text.", "Third.")
    got = check_all(src, tgt, "es", "en")
    assert not [i for i in got if i.code.startswith("number.")]


# ---------------- GitHub #17：OCR 词粘连 / 跨页残片 / 标点粘连 ----------------
def _wj(tgt, sl="es", tl="en"):
    return check_all(_pages(*[x for x in ["x"] * len(tgt)]), _pages(*tgt), sl, tl)


def _codes17(tgt):
    return [i for i in _wj(tgt) if i.code.startswith("text.")]


def test_issue17_stopword_join_detected():
    got = _codes17(["Specimens deposited inthe museum and also ofthe collection."])
    assert [i.code for i in got].count("text.word_join") >= 1
    assert all(i.severity == "major" for i in got if i.code == "text.word_join")


def test_issue17_camelcase_institution_join_detected():
    got = _codes17(["Held at UniversityOxford and the MuseoNacional."])
    assert "text.word_join" in {i.code for i in got}


def test_issue17_scientific_names_and_valid_camelcase_not_flagged():
    ok = ["The *Onuphis eremitaRouse* and McDonald, DeLong, GenBank and PubMed; Diopatra neapolitana Delle Chiaje."]
    assert _codes17(ok) == []


def test_issue17_punctuation_join_detected_but_abbreviations_ok():
    got = _codes17(["Rouse,Pleijel and also the sample.Another sample, e.g. mm, et al. Fig.3, 3.5 mm, www.example.com."])
    pj = [i for i in got if i.code == "text.punct_join"]
    assert len(pj) == 1 and pj[0].severity == "minor"
    assert _codes17(["Normal text, with e.g. i.e. et al. cf. sp. nov. var. and Fig. 3."]) == []


def test_issue17_cross_page_hyphen_and_orphan_fragment():
    got = _codes17(["The worm has long seg-", "ments on each side."])
    assert "text.page_hyphen" in {i.code for i in got}
    got = _codes17(["Palps are present and the prosto", "mium is short. More text follows here."])
    assert "text.orphan_fragment" in {i.code for i in got}
    assert _codes17(["The worm is long.", "The next page starts normally."]) == []
    assert _codes17(["It was found in", "the sand of the beach."]) == []


def test_issue17_duplicated_connective_across_pages():
    got = _codes17(["The animals live in sand and", "and mud in shallow water."])
    assert "text.duplicate_connective" in {i.code for i in got}
    assert _codes17(["The animals live in sand and", "mud in shallow water."]) == []


def test_issue17_no_checks_for_chinese_target():
    s = _pages("x")
    t = _pages("标本保存于UniversityOxford,Rouse。")
    assert not [i for i in check_all(s, t, "es", "zh") if i.code.startswith("text.")]


def test_numbers_date_order_is_not_a_difference():
    from transqa.core import numbers
    assert numbers('10. 3. 60; (4 Exemplare)') == numbers('3/10/60; (4 copies)')
    assert numbers('29. 12. 59') != numbers('2059')
    assert numbers('Salinität 30.9 und 12.5 m')['30.9'] == 1


def test_numbers_ocr_comma_date():
    from transqa.core import numbers
    assert numbers('10, 3. 60; (2 Exemplare)') == numbers('10. 3. 60; (2 copies)')


def test_number_missing_allows_target_numeral_word():
    from transqa import check_all
    src = '<!-- PDF p.1 -->\n\nSie tragen 10 Paar Elytren und Borsten.\n'
    ok = '<!-- PDF p.1 -->\n\n它们有十对鞘翅和刚毛。\n'
    bad = '<!-- PDF p.1 -->\n\n它们有鞘翅和刚毛。\n'
    codes = lambda t: [i.code for i in check_all(src, t, 'de', 'zh', 'taxonomy')]  # noqa: E731
    assert 'number.missing' not in codes(ok)
    assert 'number.missing' in codes(bad)


def test_numbers_comma_list_is_not_decimal():
    from transqa.core import numbers
    assert numbers('第2,4,5,7体節') == numbers('2nd, 4th, 5th, 7th')
    assert numbers('Salinität 33,6')['33.6'] == 1


def test_cjk_numeral_compounds():
    from transqa.languages import numeral_values
    assert numeral_values('十五对和二十三节，两个，十', 'zh') == [15, 23, 2, 10]


def test_english_ordinal_words_count_as_numerals():
    from transqa.languages import numeral_values
    assert numeral_values('the Third scale, fourth segment and 2 setae', 'en') == [3, 4]
