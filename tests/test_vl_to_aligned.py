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


def _pg(*blocks):
    return {"pages": [{"page": 46, "blocks": [dict(y0=i, **b) for i, b in enumerate(blocks)]}]}


def test_refine_toc_lines_without_lead_are_index_not_key():
    """Vol. 21 p6：目录「Género Neopetitia ..... 49」有引导点和页码，但不是检索表条目。"""
    al = _pg({"role": "index", "label": "content", "text": "Familia Syllidae ..... 11\nGénero Neopetitia ..... 49",
              "translation": "Familia Syllidae ..... 11\nGénero Neopetitia ..... 49"})
    assert [b["role"] for b in V.refine(al)["pages"][0]["blocks"]] == ["index", "index"]


def test_refine_key_title_line_is_heading():
    """Vol. 21 p47：表题「Clave de géneros」与条目同块，单独成标题。"""
    t = "Clave de géneros\n1. Faringe armada ..... 2\n• Faringe inerme ..... 11"
    al = _pg({"role": "body", "label": "text", "text": t, "translation": t})
    b = V.refine(al)["pages"][0]["blocks"]
    assert [(x["role"], x["text"]) for x in b][0] == ("heading", "Clave de géneros")
    assert [x["role"] for x in b[1:]] == ["key", "key"]


def test_refine_folds_split_key_target_back_into_couplet():
    """Vol. 21 p46：目标「Autolytinae (p. 447)」被 VL 拆成下一块正文。"""
    t = "1. Sin cirros ventrales (posiblemente fusionados a los lóbulos parapodiales) ..."
    al = _pg({"role": "body", "label": "text", "text": t, "translation": t},
             {"role": "body", "label": "text", "text": "Autolytinae (p. 447)", "translation": "Autolytinae (p. 447)"},
             {"role": "body", "label": "text", "text": "Cuerpo de talla pequeña.", "translation": "Cuerpo de talla pequeña."})
    b = V.refine(al)["pages"][0]["blocks"]
    assert len(b) == 2 and b[0]["role"] == "key"
    assert b[0]["text"].endswith("parapodiales) ..... Autolytinae (p. 447)")
    assert b[0]["translation"] == b[0]["text"]


def test_source_only_copies_text_and_loads_docstore_layout(tmp_path):
    rec = {"page": 3, "pruned_result": {"width": 100, "height": 100, "parsing_res_list": [
        {"block_label": "text", "block_content": "Hola", "block_bbox": "[1, 2, 50, 20]"}]}}
    (tmp_path / "p0003.json").write_text(__import__("json").dumps(rec), encoding="utf-8")
    assert list(V.layout_files(tmp_path)) == [3]
    assert V.load_pruned(tmp_path / "p0003.json")["parsing_res_list"][0]["block_content"] == "Hola"
    al = V.source_only({"pages": [{"page": 3, "blocks": [{"role": "body", "label": "text", "text": "Hola", "y0": 2}]}]})
    assert al["pages"][0]["blocks"][0]["translation"] == "Hola"
    assert al["pages"][0]["blocks"][0]["block_id"] == "p003_b00"
    assert V.parse_pages("1-3,7") == {1, 2, 3, 7}


def test_latex_superscripts_become_ordinals_or_sup():
    from vl_to_aligned import fix_latex_superscripts
    assert fix_latex_superscripts("la Dra. M $ ^{a} $ Ángeles Ramos") == "la Dra. M" + chr(0xAA) + " Ángeles Ramos"
    assert fix_latex_superscripts("M\\textsuperscript{a} Ángeles") == "M" + chr(0xAA) + " Ángeles"
    assert fix_latex_superscripts("10 $ ^{3} $ células") == "10<sup>3</sup> células"


def test_merge_caption_columns_joins_three_column_caption():
    from vl_to_aligned import merge_caption_columns
    bl = [
        {"role": "caption", "text": "Ancestro común", "translation": "Ancestro común", "y0": 510},
        {"role": "body", "text": "Fig. 1. Cladograma", "translation": "Fig. 1. Cladograma", "y0": 565},
        {"role": "body", "text": "cerebroideos\nhacia", "translation": "cerebroideos\nhacia", "y0": 564},
        {"role": "body", "text": "segmentos 15: ventosa", "translation": "segmentos 15: ventosa", "y0": 565},
        {"role": "body", "text": "que aparezcan en grupos", "translation": "que aparezcan en grupos", "y0": 935},
    ]
    out = merge_caption_columns(bl)
    assert [b["role"] for b in out] == ["caption", "body"]
    assert out[0]["text"] == "Fig. 1. Cladograma cerebroideos hacia segmentos 15: ventosa"
    assert out[1]["text"].startswith("que aparezcan")
