"""taxoformat：属名/种加词斜体，科名/命名人/sp. 正体；检索表与图注同样处理。"""
from __future__ import annotations

import taxoformat as tf


def fmt(text: str) -> str:
    lex = tf.build_lexicon([text])
    return tf.format_text(text, lex)[0]


def test_binomial_and_bare_genus_italic() -> None:
    src = ("Opisthodonta morena Langerhans, 1879 is a polychaete of the family Syllidae "
           "(Eusyllinae). The genus Opisthodonta is known from the Mediterranean.")
    out = fmt(src)
    assert "*Opisthodonta morena* Langerhans, 1879" in out
    assert "family Syllidae (Eusyllinae)" in out
    assert "The genus *Opisthodonta*" in out
    assert "*Syllidae*" not in out
    assert "*Eusyllinae*" not in out


def test_abbreviation_and_cf() -> None:
    src = ("Opisthodonta morena is the type species. O. morena was compared with "
           "Opisthodonta cf. morena and Opisthodonta sp. n. Within Lagisca, L. hubrechti is similar.")
    out = fmt(src)
    assert "*O. morena*" in out
    assert "*Opisthodonta* cf. *morena*" in out
    assert "*Opisthodonta* sp. n." in out
    assert "*L. hubrechti*" in out
    assert "*cf.*" not in out


def test_key_line_italic_names_roman_numbers() -> None:
    src = "3. Opisthodonta morena Langerhans, 1879 ..... 4\n4'. Procerastea hydrozoicola sp. n. ..... 5"
    out = fmt(src)
    assert "3. *Opisthodonta morena* Langerhans, 1879 ..... 4" in out
    assert "4'. *Procerastea hydrozoicola* sp. n. ..... 5" in out


def test_existing_italics_untouched() -> None:
    src = "The species *Opisthodonta morena* is common."
    out, n = tf.format_text(src, tf.build_lexicon([src]))
    assert out == src
    assert n == 0


def test_caption_italic() -> None:
    src = "Fig. 4-6. Opisthodonta pterochaeta Southern, 1914. 4, anterior end."
    out = fmt(src)
    assert "Fig. 4-6. *Opisthodonta pterochaeta* Southern, 1914." in out


def test_uppercase_title_genus_and_species() -> None:
    src = ("Opisthodonta morena (type species).\n"
           "OPISTHODONTA MORENA LANGERHANS\nOPISTHODONTA LANGERHANS, 1879")
    out = fmt(src)
    assert "*OPISTHODONTA MORENA* LANGERHANS" in out
    assert "*OPISTHODONTA* LANGERHANS, 1879" in out


def test_trinomial_and_subgenus() -> None:
    src = ("Opisthodonta morena morena and Opisthodonta morena morena; "
           "Opisthodonta (Opisthodonta) morena.")
    out = fmt(src)
    assert "*Opisthodonta morena morena*" in out
    assert "*Opisthodonta* (*Opisthodonta*) *morena*" in out


def test_subspecies_autonym_fully_italic() -> None:
    out = fmt("Opisthodonta morena morena is the nominate subspecies.")
    assert "*Opisthodonta morena morena* is the nominate subspecies." in out


def test_variety_rank_word_roman_epithet_italic() -> None:
    out = fmt("Opisthodonta morena var. morena var. nov. and Opisthodonta morena subsp. morena.")
    assert "*Opisthodonta morena* var. *morena* var. nov." in out
    assert "*Opisthodonta morena* subsp. *morena*" in out
    assert fmt("*Opisthodonta morena* var. morena") == "*Opisthodonta morena* var. *morena*"


def test_stop_words_not_swallowed() -> None:
    src = "Opisthodonta morena is common. Opisthodonta with long setae; Opisthodonta from the Red Sea."
    out = fmt(src)
    assert "*Opisthodonta* with" in out
    assert "*Opisthodonta* from" in out


def test_family_group_roman() -> None:
    src = "Polychaeta: Syllidae, Eusyllinae, Nereididae, Polynoidae."
    out = fmt(src)
    assert "*" not in out


def test_new_species_abbreviation_keeps_rank_words_roman() -> None:
    src = "O. n. sp. and O. n. gen. and O. sp. n. and P. gen. n."
    out = fmt(src)
    assert "*O.* n. sp." in out
    assert "*O.* n. gen." in out
    assert "*O.* sp. n." in out
    assert "*P.* gen. n." in out
    assert "*n.*" not in out
    assert "*sp.*" not in out
    assert "*gen.*" not in out


def test_line_start_footnote_asterisk_does_not_break_italics() -> None:
    src = "* ABSTRACT: Three new species are described: *Lagisca zibrowii* (Polynoidae)."
    out, n = tf.format_text(src, tf.build_lexicon([src]))
    assert out == "\\* ABSTRACT: Three new species are described: *Lagisca zibrowii* (Polynoidae)."
    assert n == 0
    assert "**" not in out


def test_unknown_epithet_still_italic_but_english_word_not() -> None:
    src = "Syllis longifilis EHLERS and Leanira it is common and Onuphis cannot be placed."
    out = fmt(src)
    assert "*Syllis longifilis* EHLERS" in out
    assert "*Leanira* it" in out
    assert "*Leanira it*" not in out
    assert "*Onuphis* cannot" in out


def test_index_page_star_and_escaped_italic_closer() -> None:
    # 1996 索引：源文 "192*, 606 (Halosydna)" 的页码星号是字面星号；
    # 模型输出 *Halosydna\* 把收尾星号误转义。两者都要修正，不能拼成 **Halosydna。
    src = "halleziana, *Procerastea* 191, 192*, 606 (*Halosydna\\*) 68"
    out = fmt(src)
    assert out == "halleziana, *Procerastea* 191, 192\\*, 606 (*Halosydna*) 68"
    assert "**" not in out


def test_escaped_cross_line_star_not_reformatted() -> None:
    # 1979 稿：Google 把 *B. clavata* 拆成两页，转义星号跨空行；
    # 不能被当成斜体开头重新配对，也不能把 B. 与 clavata 拼成缩写双名。
    src = "with \\*B.\n\nclavata\\* in shape."
    out, n = tf.format_text(src, tf.build_lexicon([src]))
    assert out == src
    assert n == 0


def test_existing_italic_genus_completes_roman_epithet() -> None:
    src = "*Syllis* longifilis EHLERS and *Leanira* it."
    out = fmt(src)
    assert "*Syllis longifilis* EHLERS" in out
    assert "*Leanira* it" in out
    assert "*Leanira it*" not in out
