"""Regression tests for the Fauna Iberica Vol. 21 delivery defects (2026-11-23).

Screenshots: (1) key couplets lost / targets stranded, (2) caption with hand-made
line breaks stretched by justification, (3) taxon lists scattered by tabs.
"""
from __future__ import annotations

from docx import Document

from booklayout import builder
from booklayout.keyfix import is_key_page, is_target_only, repair_key_page
from booklayout.profile import StyleProfile


def _page():
    return {"page": 276, "blocks": [
        {"role": "heading", "level": 2, "translation": "Clave de especies"},
        {"role": "key", "translation": "1. Cirros dorsales largos. Exogone verugera"},
        {"role": "index", "translation": "2. Sin cirros dorsales"},
        {"role": "index", "translation": "P. papillosa (p. 278)"},
        {"role": "index", "translation": "3. Con cirros dorsales"},
        {"role": "index", "translation": "S. gracilis (p. 280)"},
    ]}


def test_untagged_couplet_lines_under_key_heading_are_restored():
    page = {"page": 451, "blocks": [
        {"role": "heading", "level": 2, "translation": "物种检索表"},
        {"role": "body", "translation": "1. 触手锤形。钻孔器具"},
        {"role": "body", "translation": "15-30枚齿.....P. balleziana（第453页）"},
        {"role": "key", "translation": "• 触手圆柱形 ..... ."},
        {"role": "body", "translation": "P. nematodes（第456页）"},
        {"role": "body", "translation": "已知该属有五个物种，" + "其中两个存在于我们的海岸。" * 20},
    ]}
    fixed, c = repair_key_page(page)
    got = [b["translation"] for b in fixed["blocks"]]
    assert len(got) == 4 and got[1].startswith("1. 触手锤形。钻孔器具 15-30") and "balleziana" in got[1]
    assert got[2].endswith("P. nematodes（第456页）") and "..... ." not in got[2]
    assert fixed["blocks"][3]["role"] == "body"


def test_html_sup_sub_become_real_runs_not_literal_tags():
    doc = Document()
    p = doc.add_paragraph()
    builder.add_runs(p, "from the 3<sup>rd</sup> chaetiger, H<sub>2</sub>O", 10)
    assert "<" not in p.text and p.text == "from the 3rd chaetiger, H2O"
    assert [r.text for r in p.runs if r.font.superscript] == ["rd"]
    assert [r.text for r in p.runs if r.font.subscript] == ["2"]


def test_target_only_detection():
    assert is_target_only("P. papillosa (p. 278)")
    assert not is_target_only("背须长（第278页）")


def test_repair_restores_dropped_couplets():
    page = _page()
    assert is_key_page(page)
    fixed, counts = repair_key_page(page)
    assert counts["index_to_key"] == 2 and counts["targets_merged"] == 2
    assert counts["orphan_targets"] == 0
    assert all(b["role"] != "index" for b in fixed["blocks"])
    assert "P. papillosa (p. 278)" in fixed["blocks"][2]["translation"]
    assert page["blocks"][2]["role"] == "index"  # input untouched


def test_unwrap_joins_hand_breaks_only_in_running_text():
    page = {"page": 1, "blocks": [
        {"role": "caption", "translation": "背简单型刚毛（E）\n及针毛（F），\nAnoplosyllis edentula\n（A和C）。"},
        {"role": "key", "translation": "1. a\nb"},
    ]}
    out = builder.unwrap_page_lines(page)
    assert "\n" not in out["blocks"][0]["translation"]
    assert "Anoplosyllis edentula" in out["blocks"][0]["translation"]
    assert "\n" in out["blocks"][1]["translation"]


def test_profile_key_style_validation():
    import pytest
    with pytest.raises(ValueError):
        StyleProfile(key_style="grid").validate()
    with pytest.raises(ValueError):
        StyleProfile(key_style="table", key_headers=["a"]).validate()


def test_key_table_one_row_per_couplet():
    rows = builder.parse_key_rows("1. Cirros largos ..... P. papillosa (p. 278)")
    assert len(rows) == 1
    marker, body, right = rows[0]
    assert marker.startswith("1") and "papillosa" in right
    doc = Document()
    builder.key_table(doc, rows, set(), ["", "", ""])
    t = doc.tables[0]
    assert len(t.rows) == 1 and len(t.columns) == 3


def test_taxon_list_becomes_ranked_lines_not_a_justified_run_on():
    lst = "OPHIODROMINAE亚科 Pleijel, 1998\nGyptini族 Pleijel, 1998\nGyptis属 Marion, 1874\nGyptis rosea (Malm, 1874)"
    out = builder.unwrap_page_lines({"page": 1, "blocks": [{"role": "body", "translation": lst}]})
    got = [(b["role"], b["rank"]) for b in out["blocks"]]
    assert got == [("taxon", 0), ("taxon", 1), ("taxon", 2), ("taxon", 3)]


def test_thin_strip_plate_is_found_by_lenient_fallback():
    import numpy as np
    import cv2
    from booklayout.scanfigures import find_figures
    g = np.full((1400, 980), 255, np.uint8)
    for y in (300, 500, 700):  # outline strips: big bbox, thin and low ink, < 15 mm high
        cv2.rectangle(g, (200, y), (700, y + 46), 0, 2)
    assert find_figures(g, 150) == []
    assert len(find_figures(g, 150, lenient=True)) == 3


def test_caption_continuation_joins_english_with_space_chinese_without():
    from booklayout.headings import promote_captions
    d = {"pages": [{"page": 1, "blocks": [
        {"role": "body", "text": "Fig. 1. x", "translation": "Fig. 1. Anterior regeneration of"},
        {"role": "body", "label": "vision_footnote", "text": "a", "translation": "a fragment"},
    ]}]}
    promote_captions(d)
    assert d["pages"][0]["blocks"][0]["translation"] == "Fig. 1. Anterior regeneration of a fragment"


def test_stray_panel_labels_flagged_and_dropped():
    from booklayout.headings import drop_stray_labels, promote_captions, stray_label_blocks
    blk = lambda t, tr=None, role="body": {"role": role, "text": t, "translation": tr or t}
    data = {"pages": [{"page": 1, "blocks": [blk("D"), blk("Fig. 2. Parte anterior (A)", "图2。前部（A）"),
                                              blk("E"), blk("posteriores (E)", "后部（E）"), blk("Texto largo normal.")]}]}
    assert [s["text"] for s in stray_label_blocks(data)] == ["D", "E"]
    promote_captions(data)
    assert not stray_label_blocks(data)
    bl = data["pages"][0]["blocks"]
    assert [b["role"] for b in bl] == ["caption", "body"] and "后部" in bl[0]["translation"]
    assert drop_stray_labels(data) == 0
    # a lowercase body block NOT preceded by plate letters stays a body block (v36 p54: "der, 1977)")
    d2 = {"pages": [{"page": 2, "blocks": [blk("Fig. 3. Region (A)", "图3。区域（A）"), blk("der, 1977), y se ha", "der, 1977)，已")]}]}
    promote_captions(d2)
    assert [b["role"] for b in d2["pages"][0]["blocks"]] == ["caption", "body"]


def test_check_ignores_page_gaps_and_index_pages():
    from booklayout.keymarkers import lost_marker_pages
    from booklayout.structure import uncertain_boundaries
    body = lambda t: {"role": "body", "translation": t, "text": t}
    data = {"pages": [
        {"page": 14, "chapter": "v", "blocks": [body("an unfinished sentence without end")]},
        {"page": 25, "chapter": "v", "blocks": [body("Another paragraph starts here.")]},
        {"page": 26, "chapter": "v", "blocks": [body("Third paragraph starts here.")]},
    ]}
    # 14 -> 25 is a sampling gap; 25 -> 26 ends with a full stop
    assert uncertain_boundaries(data) == []
    data["pages"][1]["blocks"] = [body("unfinished again without end")]
    assert [f["page"] for f in uncertain_boundaries(data)] == [25]  # consecutive pages still flagged
    idx = {"pages": [{"page": 549, "blocks": [
        {"role": "index", "text": f"name{i}, Genus ..... {i}, 5{i}", "translation": f"name{i}, Genus ..... {i}, 5{i}"} for i in range(6)]}]}
    assert lost_marker_pages(idx) == []
