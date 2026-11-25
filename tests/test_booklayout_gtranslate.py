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
