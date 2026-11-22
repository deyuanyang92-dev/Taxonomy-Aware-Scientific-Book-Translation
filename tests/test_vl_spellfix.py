from docstore import spellfix as sf


def _lex():
    lex = sf.Lexicon({}, {"ehlersia": "Ehlersia", "salvatoria": "Salvatoria", "lophelia": "Lophelia", "ophelia": "Ophelia"},
                     {"syllis": {"gracilis"}})
    for _ in range(5):
        lex.add_text("faringeo parapodo sido")
    return lex


def test_worms_unique_ocr_confusion_auto_applied():
    new, ch = sf.fix_text("Eblersia sp.", _lex(), None)
    assert new.startswith("Ehlersia") and ch[0]["why"] == "worms" and ch[0]["applied"]


def test_vol_valid_misread_name_still_checked_against_worms():
    lex = _lex()
    for _ in range(3):
        lex.add_text("Eblersia")  # VL 连续读错同一学名，词频>=2 不得自证有效
    new, _ = sf.fix_text("Eblersia", lex, None)
    assert new == "Ehlersia"


def test_non_ocr_edit_to_real_genus_is_not_auto():
    new, ch = sf.fix_text("Lophelia pertusa", _lex(), None)
    assert new == "Lophelia pertusa"  # 真有其名（珊瑚），删字候选 Ophelia 不能自动改
    assert not any(c["applied"] for c in ch)


def test_accented_spanish_word_not_treated_as_name():
    lex = _lex()
    new, _ = sf.fix_text("Hesiónidos", lex, None)
    assert new == "Hesiónidos"


def test_second_engine_required_for_dictionary_candidates():
    lex = _lex()
    assert sf.fix_text("el farigeo largo", lex, None)[0] == "el farigeo largo"
    assert sf.fix_text("el farigeo largo", lex, {"faringeo"})[0] == "el faringeo largo"


def test_second_engine_reads_same_word_blocks_fix():
    assert sf.fix_text("Salvadoria", _lex(), {"salvadoria", "salvatoria"})[0] == "Salvadoria"


def test_llm_choice_outside_candidates_is_ignored_and_dict_class_only_suggested():
    lex = _lex()
    pend: list = []
    sf.fix_text("el farigeo largo", lex, {"otra"}, None, pend)
    assert pend == [] or pend[0]["token"] == "farigeo"
    key = "farigeo|el farigeo largo"
    new, ch = sf.fix_text("el farigeo largo", lex, {"otra"}, {key: "inventada"}, None)
    assert new == "el farigeo largo"


def test_epithet_after_genus_checked_against_same_genus_only():
    lex = _lex()
    new, ch = sf.fix_text("Syllis gracilus", lex, None)
    assert new == "Syllis gracilus"  # u/i 不是典型 OCR 混淆：只进待审（交 LLM），不自动改
    assert ch[0]["cands"] == ["gracilis"] and not ch[0]["applied"]
