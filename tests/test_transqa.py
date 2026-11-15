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
