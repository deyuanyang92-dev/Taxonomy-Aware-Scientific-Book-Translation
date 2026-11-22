import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vl_to_aligned as V  # noqa: E402


def test_panel_letters():
    for t in ["A", "A B", "L M N O P", "(A)", "A, B, C"]:
        assert V.is_panel_letters(t), t
    for t in ["Fig. 5. Vista dorsal", "Heteromastus filiformis (Claparède, 1864)", "Glycera"]:
        assert not V.is_panel_letters(t), t


def test_refine_drops_panels_and_splits_index():
    al = {"pages": [{"page": 1, "blocks": [
        {"role": "caption", "label": "figure_title", "text": "A B", "translation": "A B", "y0": 1},
        {"role": "caption", "label": "figure_title", "text": "Fig. 1. Vista", "translation": "图1", "y0": 2},
        {"role": "index", "label": "content", "text": "a ..... 1\nb ..... 2", "translation": "甲 ..... 1\n乙 ..... 2", "y0": 3}]}]}
    b = V.refine(al)["pages"][0]["blocks"]
    assert [x["text"] for x in b] == ["Fig. 1. Vista", "a ..... 1", "b ..... 2"]
    assert b[2]["translation"] == "乙 ..... 2"


def test_refine_marks_identification_key_lines():
    txt = "1. Cirros lanceolados ..... 2\n2. Cirros ovalados ..... E. clavigera (p. 193)"
    al = {"pages": [{"page": 1, "blocks": [{"role": "body", "label": "content", "text": txt, "translation": txt, "y0": 1}]}]}
    assert {b["role"] for b in V.refine(al)["pages"][0]["blocks"]} == {"key"}


def test_key_leader_normalised_and_body_block_becomes_key():
    al = {"pages": [{"page": 1, "blocks": [
        {"role": "body", "label": "text", "text": "4. 8 macrotubérculos.....S. amoureuxi (p. 36)", "translation": "4. 每个体节具8个大瘤突..S. amoureuxi（第36页）", "y0": 1},
        {"role": "body", "label": "text", "text": "Texto normal sin hojas.", "translation": "普通正文。", "y0": 2}]}]}
    b = V.refine(al)["pages"][0]["blocks"]
    assert b[0]["role"] == "key" and b[0]["translation"] == "4. 每个体节具8个大瘤突 ..... S. amoureuxi（第36页）"
    assert b[1]["role"] == "body"


def test_caption_continuation_merged_and_binomial_not_caption():
    al = {"pages": [{"page": 1, "blocks": [
        {"role": "caption", "label": "figure_title", "text": "Fig. 3. Vista dorsal (A),", "translation": "图3 背面（A），", "y0": 1},
        {"role": "caption", "label": "figure_title", "text": "ventral (B).", "translation": "腹面（B）。", "y0": 2},
        {"role": "caption", "label": "figure_title", "text": "Heteromastus filiformis (Claparède, 1864)", "translation": "丝异须虫", "y0": 3}]}]}
    b = V.refine(al)["pages"][0]["blocks"]
    assert len(b) == 2 and b[0]["translation"] == "图3 背面（A），腹面（B）。" and b[1]["role"] == "body"


def test_keyline_variants():
    from vl_to_aligned import KEYLINE
    assert KEYLINE.match("4. Podios posteriores con el lóbulo superior muy desarrollado..5")
    assert KEYLINE.match("Podios posteriores con el lóbulo cónico pero sin aspecto foliáceo .....7")
    assert KEYLINE.match("2. Faringe con paragnatos claros y caedizos Eunereis (p. 321)")
    assert not KEYLINE.match("Los ejemplares miden 5 mm y fueron hallados en 1990.")


def test_fix_arabic_unique_match():
    from vl_to_aligned import fix_arabic
    ar = chr(0x627) + chr(0x631)
    al = {"pages": [{"blocks": [{"text": f"Proto{ar}icia oerstedii"}, {"text": "Protoaricia oerstedi (Claparede)"}, {"text": f"zzz{ar}yy"}]}]}
    out = fix_arabic(al)
    assert out["pages"][0]["blocks"][0]["text"] == "Protoaricia oerstedii"
    assert out["arabic_unresolved"] == [f"zzz{ar}yy"]
