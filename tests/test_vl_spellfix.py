import json
import sys
from pathlib import Path

from docstore import spellfix as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vl_spellfix as cli  # noqa: E402


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


def test_cli_inplace_backs_up_and_keeps_text_raw(tmp_path):
    d = tmp_path / "book"
    d.mkdir()
    p = d / "aligned.json"
    al = {"pages": [{"page": 1, "blocks": [{"role": "body", "text": "el farigeo largo y el faringeo corto, faringeo, faringeo"},
                                           {"role": "ref", "text": "Hartmann-Schröder 1996"}]}]}
    p.write_text(json.dumps(al), encoding="utf-8")
    tess = tmp_path / "t"
    (tess / "book").mkdir(parents=True)
    (tess / "book" / "t0001_L.txt").write_text("el faringeo largo\n", encoding="utf-8")
    assert cli.main([str(p), "--inplace", "--tess-root", str(tess), "--worms", "", "--lang", "", "--out", str(tmp_path / "o")]) == 0
    out = json.loads(p.read_text(encoding="utf-8"))
    b = out["pages"][0]["blocks"]
    assert b[0]["text"] == "el faringeo largo y el faringeo corto, faringeo, faringeo" and b[0]["text_raw"].startswith("el farigeo")
    assert b[1]["text"] == "Hartmann-Schröder 1996"  # ref 块不动
    assert json.loads((d / "aligned.pre_spellfix.json").read_text(encoding="utf-8")) == al


def test_index_blocks_suggest_only_but_key_prose_fixed(tmp_path):
    d = tmp_path / "book"
    d.mkdir()
    p = d / "aligned.json"
    body = " faringeo, faringeo, faringeo"
    al = {"pages": [{"page": 1, "blocks": [
        {"role": "index", "text": "el farigeo" + body}, {"role": "key", "text": "(farnigeo) ....." + body},
        {"role": "key", "text": "el farlngeo ..... 5" + body}]}]}
    p.write_text(json.dumps(al), encoding="utf-8")
    tess = tmp_path / "t"
    (tess / "book").mkdir(parents=True)
    (tess / "book" / "t0001_L.txt").write_text("el faringeo\n", encoding="utf-8")
    cli.main([str(p), "--inplace", "--tess-root", str(tess), "--worms", "", "--lang", "", "--extra-words", "", "--out", str(tmp_path / "o")])
    b = json.loads(p.read_text(encoding="utf-8"))["pages"][0]["blocks"]
    assert "farigeo" in b[0]["text"] and "farnigeo" in b[1]["text"] and "farlngeo" not in b[2]["text"]


def test_gender_swap_and_known_name_guards():
    assert sf.gender_swap("pseudoespinigeros", "pseudoespinigeras") and not sf.gender_swap("faringe", "faringeo")
    lex = sf.Lexicon({}, {}, {"nephtys": {"rathkei"}})
    assert lex.is_known_name("rathkei") and not lex.is_known_name("ratbkei")


def test_two_engines_same_genus_misread_fixed_only_for_letter_substitution():
    lex = _lex()
    assert sf.fix_text("Paraeblersia", sf.Lexicon({}, {"paraehlersia": "Paraehlersia"}, {}), {"paraeblersia"})[0] == "Paraehlersia"
    assert sf.fix_text("Lopadorhynchus", sf.Lexicon({}, {"lopadorrhynchus": "Lopadorrhynchus"}, {}), {"lopadorhynchus"})[0] == "Lopadorhynchus"
    assert lex
