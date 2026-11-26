from booklayout.gtranslate import Translator, mask_names, unmask


def test_mask_and_restore_binomial():
    masked, table = mask_names("Los individuos de Syllis prolifera y S. gracilis viven", frozenset({"Syllis"}))
    assert "Syllis" not in masked and "prolifera" not in masked
    assert "S. gracilis" not in masked
    restored, ok = unmask(masked, table)
    assert ok and restored == "Los individuos de Syllis prolifera y S. gracilis viven"


def test_unmask_flags_lost_token():
    masked, table = mask_names("Syllis prolifera", frozenset({"Syllis"}))
    _, ok = unmask("lost", table)
    assert not ok


def test_join_continuation_across_pages():
    from booklayout.gtranslate import join_continuations
    d = {"pages": [
        {"page": 1, "blocks": [{"role": "body", "text": "El prostomio es bien", "translation": "x"}]},
        {"page": 2, "blocks": [{"role": "body", "text": "desarrollado y semicircular.", "translation": "y"},
                               {"role": "body", "text": "Otro.", "translation": "z"}]}]}
    assert join_continuations(d) == 1
    assert d["pages"][0]["blocks"][0]["text"] == "El prostomio es bien desarrollado y semicircular."
    assert len(d["pages"][1]["blocks"]) == 1


def test_legend_tail_joins_caption():
    from booklayout.gtranslate import join_continuations
    d = {"pages": [{"page": 49, "blocks": [
        {"role": "caption", "text": "Fig. 12. Ejemplar y seda", "translation": ""},
        {"role": "body", "text": "simple dorsal (F) de Neopetitia.", "translation": ""},
        {"role": "body", "text": "Otro parrafo.", "translation": ""}]}]}
    join_continuations(d)
    assert [b["text"] for b in d["pages"][0]["blocks"]] == ["Fig. 12. Ejemplar y seda simple dorsal (F) de Neopetitia.", "Otro parrafo."]


def test_join_chain_when_middle_page_is_emptied():
    from booklayout.gtranslate import join_continuations
    d = {"pages": [
        {"page": 1, "blocks": [{"role": "body", "text": "El prostomio es", "translation": ""}]},
        {"page": 2, "blocks": [{"role": "body", "text": "bien desarrollado y", "translation": ""}]},
        {"page": 3, "blocks": [{"role": "body", "text": "semicircular.", "translation": ""}]}]}
    assert join_continuations(d) == 2
    assert d["pages"][0]["blocks"][0]["text"] == "El prostomio es bien desarrollado y semicircular."


def test_zh_punct_makes_mixed_parens_fullwidth():
    from booklayout.gtranslate import zh_punct
    assert zh_punct("Fauvel (1923a、1932 等）、哈特曼") == "Fauvel（1923a、1932 等）、哈特曼"
    assert zh_punct("摩尔 (1906, 1908)，此外") == "摩尔（1906, 1908），此外"
    assert zh_punct("see (Fig. 2) here") == "see (Fig. 2) here"


def test_plan_keeps_leader_and_page():
    t = Translator.__new__(Translator)
    plan = Translator.plan(t, "Familia Syllidae ..... 11\n12")
    assert ("tr", "Familia Syllidae") in plan
    assert ("keep", " ..... 11") in plan
    assert ("keep", "12") in plan


def test_rank_name_masked():
    masked, table = mask_names("Familia SYLLIDAE Grube, 1850", frozenset())
    assert "SYLLIDAE" not in masked and masked.startswith("Familia ")
    assert unmask(masked, table) == ("Familia SYLLIDAE Grube, 1850", True)


def test_use_translation_as_source_restores_key_targets():
    from booklayout.gtranslate import use_translation_as_source
    d = {"pages": [{"page": 1, "blocks": [
        {"role": "key", "text": "- Cirros ventrales presentes .....", "translation": "• Cirros ventrales presentes ..... 2"},
        {"role": "body", "text": "Igual.", "translation": "Igual."},
        {"role": "body", "text": "Solo OCR.", "translation": ""}]}]}
    assert use_translation_as_source(d) == 1
    b = d["pages"][0]["blocks"][0]
    assert b["text"].endswith("..... 2") and b["text_ocr"].endswith(".....")
    assert d["pages"][0]["blocks"][2]["text"] == "Solo OCR."


def test_glossary_replaces_google_default_with_yiku_name():
    """#68: Google renders "chaetae" as 毛壳; the yiku HARD name must win, and only when enabled."""
    class G:
        @staticmethod
        def term_count(en, term):
            return en.lower().count(term.lower())

        @staticmethod
        def replace_google_terms(zh, hard, probe):
            out = []
            for en, z in hard:
                g = probe(en)
                if g in zh and g != z:
                    zh = zh.replace(g, z)
                    out.append(f"{en}: {g}→{z}")
            return zh, out

        @staticmethod
        def apply_fixes(zh, en, fixes):
            return zh, []

    class Goog:
        @staticmethod
        def term(en):
            return {"chaetae": "毛壳"}[en]

    t = Translator.__new__(Translator)
    t.g, t.google, t.hard, t.fixes, t.glossary_applied = G, Goog, [("chaetae", "刚毛")], [], {}
    assert t.apply_glossary("体节具毛壳。", "Segments bear chaetae.") == "体节具刚毛。"
    assert t.glossary_applied
    t.hard = []  # no --glossary: output untouched
    assert t.apply_glossary("体节具毛壳。", "Segments bear chaetae.") == "体节具毛壳。"


def test_zh_punct_drops_italic_stars_around_pure_chinese():
    from booklayout.gtranslate import zh_punct
    assert zh_punct("Vinther *等人* 2008，*Nereis* 属") == "Vinther 等人 2008，*Nereis* 属"


def test_zh_caption_label_is_fixed_not_machine_translated():
    """#69: "**Fig. 3.1:** text" must keep a caption label ("图 3.1：") in Chinese output."""
    t = Translator.__new__(Translator)
    t.tl, t.genera = "zh-CN", frozenset()
    assert t.plan("**Fig. 3.1:** Stratigraphic distribution of fossils.") == [
        ("keep", "**图 3.1：** "), ("tr", "Stratigraphic distribution of fossils.")]
    assert t.plan("Fig. 12. Ejemplar y seda simple")[0] == ("keep", "图 12： ")


def test_italic_fossil_name_masked_even_if_genus_not_in_worms():
    m, table = mask_names("A, *Phragmochaeta canicularis,* MGUH31365. B, *Canadia spinosa,* USNM", frozenset())
    assert "Phragmochaeta" not in m and "Canadia" not in m
    out, ok = unmask(m, table)
    assert ok and out == "A, *Phragmochaeta canicularis,* MGUH31365. B, *Canadia spinosa,* USNM"


def test_join_when_next_page_starts_with_paren_or_year():
    from booklayout.gtranslate import join_continuations
    for head in ("(Butterfield and Harvey 2012). More.", "2004, Parry et al. 2015b). More."):
        d = {"pages": [{"page": 1, "blocks": [{"role": "body", "text": "spines and chaetae"}]},
                       {"page": 2, "blocks": [{"role": "body", "text": head}]}]}
        assert join_continuations(d) == 1


def test_section_number_is_not_a_continuation():
    from booklayout.structure import starts_continuation
    assert not starts_continuation("3.2 Soft-bodied annelid fossils")
    assert starts_continuation("2004, Parry") and starts_continuation("(Butterfield 1990)")


def test_comma_tail_joins_capital_species_name_on_next_page():
    from booklayout.gtranslate import join_continuations
    d = {"pages": [{"page": 1, "blocks": [{"role": "body", "text": "such as *Wiwaxia corrugata,*"}]},
                   {"page": 2, "blocks": [{"role": "body", "text": "*Halkieria evangelista* and more."}]}]}
    assert join_continuations(d) == 1


def test_credit_line_after_caption_joins_the_caption():
    from booklayout.gtranslate import join_continuations
    d = {"pages": [{"page": 1, "blocks": [{"role": "caption", "text": "**Fig. 3.4:** Jaws."},
                                           {"role": "body", "text": "Modified from Paxton (2009)."}]}]}
    assert join_continuations(d) == 1 and len(d["pages"][0]["blocks"]) == 1
