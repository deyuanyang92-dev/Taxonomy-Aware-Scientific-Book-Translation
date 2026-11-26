"""layout_pair / layout_gt / layout_score 纯函数测试（不依赖真 PDF 的部分 + 一个合成 PDF）。"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "bench"))
import layout_gt as G  # noqa: E402
import layout_pair as P  # noqa: E402
import layout_score as S  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "bench"))


def test_match_pages_ok_ambiguous_none():
    native = {1: "alpha bravo charlie delta echoes foxtrot golfer hotel india juliet"}
    scan = {5: "alpha bravo charlie delta echoes foxtrot golfer hotel india juliet", 6: "zulu yankee whiskey victor uniform"}
    assert P.match_pages(native, scan)[1]["status"] == "ok"
    scan2 = {5: scan[5], 6: scan[5]}
    assert P.match_pages(native, scan2)[1]["status"] == "ambiguous"
    assert P.match_pages(native, {6: scan[6]})[1]["status"] == "none"
    assert P.match_pages({1: "short"}, scan)[1]["status"] == "short"


def test_printed_page():
    assert P.printed_page("12\nTitle\nbody") == "12"
    assert P.printed_page("Title\nbody text here") == ""


def test_tsv_roundtrip(tmp_path):
    rows = [{h: "x" for h in P.HEADER}]
    P.write_tsv(rows, str(tmp_path / "a.tsv"))
    assert P.read_tsv(str(tmp_path / "a.tsv"))[0]["book"] == "x"


def test_classify_line():
    assert G.classify_line("GLOSSARY", "DanteMTStd-Regular", 24, False, False, 70, 90, 600) == ("heading", 1)
    assert G.classify_line("Systematics", "DanteMTStd-Bold", 14, True, False, 200, 215, 600) == ("heading", 2)
    assert G.classify_line("FIGURE 3 text", "DanteMTStd-Regular", 9, False, False, 200, 215, 600)[0] == "caption"
    assert G.classify_line("12", "DanteMTStd-Regular", 10, False, False, 580, 590, 600)[0] == "furniture"
    assert G.classify_line("Smith 2000", "SourceSansPro-Regular", 8.7, False, False, 200, 210, 600)[0] == "ref"
    assert G.classify_line("plain text", "DanteMTStd-Regular", 10.5, False, False, 200, 210, 600)[0] == "body"


def test_markup_and_join():
    spans = [{"text": "the ", "font": "DanteMTStd-Regular", "flags": 0},
             {"text": "Nereis virens", "font": "DanteMTStd-Italic", "flags": 2},
             {"text": " worm", "font": "DanteMTStd-Regular", "flags": 0}]
    t, itw = G._line_markup(spans)
    assert t == "the *Nereis virens* worm"
    assert itw == ["Nereis", "virens"]
    assert G.strip_markup(t) == "the Nereis virens worm"
    assert G.join_lines(["abc-", "def"]).replace(" ", "") in ("abcdef", "abc-def")


def test_reading_order_two_columns():
    mk = lambda i, x0, x1, y0, role="body": {"id": i, "role": role, "bbox_pt": [x0, y0, x1, y0 + 10]}
    bl = [mk("r2", 320, 560, 100), mk("l2", 60, 300, 200), mk("l1", 60, 300, 100), mk("r1", 320, 560, 200),
          mk("f", 60, 560, 580, "furniture"), mk("h", 60, 560, 50, "heading")]
    out = {b["id"]: b["order"] for b in G.reading_order(bl, 612)}
    assert out["h"] < out["l1"] < out["l2"] < out["r2"] < out["r1"] or out["h"] < out["l1"] < out["l2"] < out["r1"] < out["r2"]
    assert out["l2"] < min(out["r1"], out["r2"]) and out["f"] == -1


def test_affine_recovers_transform():
    rng = np.random.default_rng(0)
    pts = rng.uniform(0.05, 0.95, (40, 2))
    M = np.array([[1.02, 0.01, 0.03], [-0.01, 0.99, -0.02]])
    pairs = [(x, y, M[0, 0] * x + M[0, 1] * y + M[0, 2], M[1, 0] * x + M[1, 1] * y + M[1, 2]) for x, y in pts]
    pairs += [(0.5, 0.5, 0.9, 0.1), (0.2, 0.7, 0.1, 0.9)]  # 外点
    fit = G.fit_affine(pairs)
    assert fit is not None
    M2, ninl = fit
    assert np.allclose(M2, M, atol=1e-3) and ninl >= 40
    bb = G.apply_affine(M2, [0.1, 0.1, 0.4, 0.4])
    assert bb[0] == pytest.approx(1.02 * 0.1 + 0.01 * 0.1 + 0.03, abs=2e-3)


def test_fit_affine_too_few():
    assert G.fit_affine([(0.1, 0.1, 0.1, 0.1)]) is None


def _gt():
    return {"registration": {"status": "ok"}, "blocks": [
        {"role": "heading", "level": 1, "bbox_rel": [0.1, 0.05, 0.9, 0.1], "text": "GLOSSARY OF TERMS HERE", "order": 0, "italic_words": []},
        {"role": "body", "level": None, "bbox_rel": [0.1, 0.2, 0.45, 0.5], "text": "left column body text about annelid worms", "order": 1, "italic_words": ["annelid"]},
        {"role": "body", "level": None, "bbox_rel": [0.55, 0.2, 0.9, 0.5], "text": "right column body text about polychaete setae", "order": 2, "italic_words": []},
        {"role": "furniture", "level": None, "bbox_rel": [0.4, 0.95, 0.6, 0.98], "text": "12", "order": -1, "italic_words": []}]}


def test_score_perfect_and_swapped():
    gt = _gt()
    eng = {"engine": "x", "seconds": 1.0, "blocks": [
        {"bbox_rel": b["bbox_rel"], "role": b["role"], "level": b["level"], "text": b["text"], "order": b["order"],
         "italic_words": b["italic_words"]} for b in gt["blocks"] if b["role"] != "furniture"]}
    r = S.score_layout(gt, eng)
    assert r["block_f1"] == 1.0 and r["role_macro_f1"] == 1.0 and r["heading_level_acc"] == 1.0
    assert r["order_tau"] == 1.0 and r["cer"] == 0.0 and r["italic_f1"] == 1.0
    eng["blocks"][1]["order"], eng["blocks"][2]["order"] = 2, 1
    assert S.score_layout(gt, eng)["order_tau"] < 1.0


def test_overlap_roles_granularity_independent():
    # GT 一个大块（两段），预测拆成两个小段：块级配对不上，但角色按交叠仍应判对
    gt = {"blocks": [{"role": "body", "level": None, "bbox_rel": [0.1, 0.1, 0.5, 0.5], "text": "x" * 200, "order": 0, "italic_words": []}]}
    eng = {"blocks": [{"bbox_rel": [0.1, 0.1, 0.5, 0.3], "role": "body", "text": "x" * 100, "order": 0},
                      {"bbox_rel": [0.1, 0.3, 0.5, 0.5], "role": "caption", "text": "x" * 100, "order": 1}]}
    r = S.score_layout(gt, eng)
    assert r["cover"] == 1.0 and r["role_acc"] in (0.0, 1.0)
    eng["blocks"][1]["role"] = "body"
    assert S.score_layout(gt, eng)["role_acc"] == 1.0
    eng["blocks"] = [dict(eng["blocks"][0], role="caption")]
    assert S.score_layout(gt, eng)["role_acc"] == 0.0


def test_score_wrong_level_and_missing_block():
    gt = _gt()
    eng = {"blocks": [{"bbox_rel": [0.1, 0.05, 0.9, 0.1], "role": "heading", "level": 2, "text": "GLOSSARY OF TERMS HERE", "order": 0}]}
    r = S.score_layout(gt, eng)
    assert r["heading_level_acc"] == 0.0 and r["heading_recall"] == 1.0 and r["heading_level_strict"] == 0.0
    assert r["block_recall"] == pytest.approx(1 / 3, abs=1e-3)
    assert r["italic_f1"] == 0.0


def test_score_level_none_not_counted():
    gt = _gt()
    eng = {"blocks": [{"bbox_rel": [0.1, 0.05, 0.9, 0.1], "role": "heading", "level": None, "text": "GLOSSARY OF TERMS HERE", "order": 0}]}
    r = S.score_layout(gt, eng)
    assert r["heading_level_acc"] is None and r["heading_level_strict"] == 0.0 and r["heading_recall"] == 1.0


def test_iou_kendall_interleave():
    assert S.iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0 and S.iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0.0
    assert S.kendall_tau([1, 2, 3], [1, 2, 3]) == 1.0 and S.kendall_tau([1, 2, 3], [3, 2, 1]) == -1.0
    L = {"bbox_rel": [0.1, 0, 0.4, 0.1]}
    R = {"bbox_rel": [0.6, 0, 0.9, 0.1]}
    assert S.col_interleave([L, L, R, R]) == 0.0
    assert S.col_interleave([L, R, L, R]) > 0.5


def test_check_aspect(tmp_path):
    import layout_run as R
    from PIL import Image
    png = tmp_path / "a.png"
    Image.new("RGB", (1240, 1652)).save(png)
    R.check_aspect((1190, 1586), png)  # 一致
    with pytest.raises(RuntimeError):
        R.check_aspect((1190, 1683), png)  # mediabox 高度 -> 错位


def test_adapters_paddle_and_levels():
    import layout_adapters as A
    lay = {"width_px": 1000, "height_px": 2000, "pruned_result": {"parsing_res_list": [
        {"block_label": "doc_title", "block_bbox": [100, 100, 900, 200], "block_content": "BIG TITLE", "block_order": 1},
        {"block_label": "paragraph_title", "block_bbox": [100, 300, 500, 340], "block_content": "Sub", "block_order": 2},
        {"block_label": "text", "block_bbox": [100, 400, 500, 900], "block_content": "body", "block_order": 3},
        {"block_label": "footer", "block_bbox": [100, 1900, 500, 1950], "block_content": "f"}]}}
    e = A.paddle_blocks(lay)
    assert [b["role"] for b in e["blocks"]] == ["heading", "heading", "body", "furniture"]
    assert e["blocks"][0]["level"] == 1 and e["blocks"][1]["level"] is None
    assert e["blocks"][0]["bbox_rel"] == [0.1, 0.05, 0.9, 0.1]
    lv = A.infer_levels(e["blocks"])
    assert lv[0]["level"] < lv[1]["level"]
    assert e["blocks"][1]["level"] is None  # 原件不被改


def test_ledger_append(tmp_path):
    p = tmp_path / "L.tsv"
    S.append_ledger("eng", "set", "m", 0.5, 0, "src", "2026-11-26", path=p)
    assert p.read_text().strip().split("\t") == ["2026-11-26", "eng", "set", "m", "0.5", "0", "src"]
