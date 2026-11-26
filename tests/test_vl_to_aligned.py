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


# ---- T6：aligned/2、标题层级组合、空块回退 ----
import json  # noqa: E402


def _layout(blocks, w=1000, h=1400):
    return {"pruned_result": {"width": w, "height": h, "parsing_res_list": blocks}}


def _blk(label, text, bbox):
    return {"block_label": label, "block_content": text, "block_bbox": bbox}


def _mk_dirs(tmp_path, blocks, w=1000, h=1400):
    from PIL import Image
    lay, png = tmp_path / "lay", tmp_path / "png"
    lay.mkdir()
    png.mkdir()
    (lay / "p0001.json").write_text(json.dumps(_layout(blocks, w, h)), encoding="utf-8")
    Image.new("RGB", (w, h), "white").save(png / "p0001.png")
    return lay, png


def test_number_depth_and_rule_levels():
    assert V.number_depth("1 Introduction") == 1
    assert V.number_depth("1.2 Gut") == 2
    assert V.number_depth("3.2.1. Foregut") == 3
    assert V.number_depth("General features") is None
    assert V.number_depth("2019 was a year") is None
    assert V.heading_rule_level("1.2 Gut") == (2, "number")
    assert V.heading_rule_level("CHAPTER 24 PHYLLODOCIDAE") == (1, "taxon")
    assert V.heading_rule_level("GLOSSARY") == (1, "taxon")
    assert V.heading_rule_level("Familia Syllidae Grube, 1850") == (1, "taxon")
    assert V.heading_rule_level("Género Exogone Oersted, 1845") == (2, "taxon")
    assert V.heading_rule_level("Morphology and physiology") is None  # 不能被当成双名法种名
    assert V.heading_rule_level("General features", "paragraph_title") is None
    assert V.heading_rule_level("Whatever", "doc_title") == (1, "engine")


def test_kmeans_tiers_orders_and_merges():
    t = V.kmeans_tiers([1.8, 1.82, 1.78, 1.4, 1.38, 1.42, 1.1, 1.08, 1.12], k=3)
    assert len(t) == 3 and t == sorted(t, reverse=True)
    assert len(V.kmeans_tiers([1.30, 1.31, 1.29, 1.30], k=3)) == 1  # 几乎等大：一层
    assert V.kmeans_tiers([]) == []


def _page(p, heads, body_chars=600):
    """body: 1 个正文块（框 400x300，600 字 -> 单位 sqrt(200)=14.1）；heads: [(text, w, h, label)]。"""
    bl = [{"role": "body", "label": "text", "text": "x" * body_chars, "y0": 0, "src": {"bbox": [0, 0, 400, 300]}}]
    for i, (t, w, h, lab) in enumerate(heads):
        bl.append({"role": "heading", "label": lab, "text": t, "y0": 10 + i, "level": 2,
                   "src": {"bbox": [0, 400 + 50 * i, w, 400 + 50 * i + h]}})
    return {"page": p, "blocks": bl}


def test_assign_heading_levels_combines_number_rule_and_size():
    # 单位 14.1：字数 10 的标题，框面积 = (ratio*14.1)^2 * 10
    def box(ratio, n=10):
        a = (ratio * 14.1) ** 2 * n
        return int(a ** 0.5 * 4), int(a ** 0.5 / 4)  # w=4h
    heads = [("Alpha beta", *box(1.8), "paragraph_title"), ("Gamma delta", *box(1.4), "paragraph_title"),
             ("Epsilon zeta", *box(1.1), "paragraph_title"), ("1.2 Numbered", *box(1.1), "paragraph_title"),
             ("CHAPTER 3", *box(2.5), "doc_title")]
    pages = [_page(1, heads), _page(2, heads)]
    st = V.assign_heading_levels(pages)
    lv = {b["text"]: (b["level"], b["level_source"]) for b in pages[0]["blocks"] if b["role"] == "heading"}
    assert lv["CHAPTER 3"] == (1, "taxon")
    assert lv["1.2 Numbered"] == (2, "number")
    assert [lv[k][0] for k in ("Alpha beta", "Gamma delta", "Epsilon zeta")] == [2, 3, 4]
    assert all(lv[k][1] == "font" for k in ("Alpha beta", "Gamma delta", "Epsilon zeta"))
    assert st["font"] == 6 and st["number"] == 2 and len(st["tiers"]) == 3


def test_convert_ocr_fields_levels_and_validate(tmp_path):
    from booklayout.profile import validate_aligned
    blocks = [_blk("paragraph_title", "CHAPTER 2 ANATOMY", [100, 100, 600, 160]),
              _blk("text", "word " * 120, [100, 200, 900, 400]),
              _blk("figure_title", "Fig. 1. Something", [100, 800, 900, 840]),
              _blk("header", "running head", [100, 10, 900, 40])]
    lay, png = _mk_dirs(tmp_path, blocks)
    out = tmp_path / "o"
    V.convert(lay, png, out, heading_levels="auto", tess_fallback=False)
    al = json.loads((out / "aligned.json").read_text(encoding="utf-8"))
    assert al["schema"] == "aligned/2" and al["source"]["kind"] == "scan"
    bs = al["pages"][0]["blocks"]
    assert len(bs) == 3  # header 被跳过
    h = bs[0]
    assert h["role"] == "heading" and h["level"] == 1 and h["level_source"] == "taxon"
    assert h["src"]["origin"] == "ocr" and h["src"]["label"] == "paragraph_title" and h["src"]["bbox"] == [100, 100, 600, 160]
    assert h["src"]["engine"] == "paddleocr-vl" and h["block_id"] == "p001_b00"
    assert validate_aligned(al) == []


def test_convert_flat_keeps_old_level(tmp_path):
    lay, png = _mk_dirs(tmp_path, [_blk("paragraph_title", "CHAPTER 2", [100, 100, 600, 160])])
    V.convert(lay, png, tmp_path / "o", tess_fallback=False)
    b = json.loads((tmp_path / "o" / "aligned.json").read_text(encoding="utf-8"))["pages"][0]["blocks"][0]
    assert b["level"] == 2


def test_empty_block_falls_back_to_tesseract_or_is_recorded(tmp_path, monkeypatch):
    blocks = [_blk("text", "", [100, 200, 900, 400]), _blk("text", "real text here", [100, 500, 900, 600]),
              _blk("image", "", [100, 700, 900, 900])]
    lay, png = _mk_dirs(tmp_path, blocks)
    calls = []

    def fake(im, box, lang="eng", psm=6):
        calls.append(box)
        return "filled by tesseract"
    monkeypatch.setattr(V, "tesseract_text", fake)
    out = tmp_path / "o1"
    V.convert(lay, png, out)
    pg = json.loads((out / "aligned.json").read_text(encoding="utf-8"))["pages"][0]
    assert calls == [(100, 200, 900, 400)]  # 只对文本块调用，图不调
    assert pg["blocks"][0]["text"] == "filled by tesseract"
    assert pg["blocks"][0]["src"]["empty"] is True and pg["blocks"][0]["src"]["fallback"] == "tesseract"
    assert "empty" not in pg["blocks"][1]["src"]
    # 补不出：不入块，记 empty_blocks
    monkeypatch.setattr(V, "tesseract_text", lambda *a, **k: "")
    out2 = tmp_path / "o2"
    V.convert(lay, png, out2)
    pg2 = json.loads((out2 / "aligned.json").read_text(encoding="utf-8"))["pages"][0]
    assert [b["text"] for b in pg2["blocks"]] == ["real text here"]
    assert pg2["empty_blocks"] == [{"label": "text", "bbox": [100, 200, 900, 400]}]
    # 关闭回退
    calls.clear()
    monkeypatch.setattr(V, "tesseract_text", fake)
    V.convert(lay, png, tmp_path / "o3", tess_fallback=False)
    assert calls == []


def test_tesseract_text_absent_returns_empty(monkeypatch):
    from PIL import Image
    monkeypatch.setattr(V.shutil, "which", lambda n: None)
    assert V.tesseract_text(Image.new("RGB", (50, 50), "white"), (0, 0, 50, 50)) == ""


def test_load_pruned_accepts_cached_layout_wrapper(tmp_path):
    f = tmp_path / "p0003.json"
    f.write_text(json.dumps({"layout": {"width_px": 5, "pruned_result": {"width": 5, "height": 6, "parsing_res_list": []}}}), encoding="utf-8")
    assert V.load_pruned(f)["width"] == 5


def test_structv3_wrapper_maps_tables_and_labels(tmp_path):
    import structv3_to_aligned as S3
    blocks = [_blk("doc_title", "CHAPTER 1", [100, 100, 600, 160]), _blk("table", "<table></table>", [100, 200, 900, 400]),
              _blk("table_title", "Table 1. Counts", [100, 420, 900, 450]), _blk("reference", "Smith 1999", [100, 500, 900, 530])]
    lay, png = _mk_dirs(tmp_path, blocks)
    out = tmp_path / "o"
    r = S3.convert(lay, png, out, tess_fallback=False)
    bs = json.loads((out / "aligned.json").read_text(encoding="utf-8"))["pages"][0]["blocks"]
    assert [b["role"] for b in bs] == ["heading", "caption", "ref"]
    assert bs[0]["src"]["engine"] == "pp-structurev3"
    assert len(r["figures"]) == 1 and (out / r["figures"][0]["crop"]).exists()
