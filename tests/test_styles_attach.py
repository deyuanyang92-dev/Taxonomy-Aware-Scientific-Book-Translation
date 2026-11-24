"""Italic cue and sidecar attach of measured typography to aligned blocks (pure)."""
from booklayout import styles


def test_italic_from_word_slants():
    r = {"label": "text", "x_height_pt": 5.0, "stroke_rel": 0.1,
         "words": [{"text": "a", "slant": 12.0}, {"text": "b", "slant": 11.0}, {"text": "c", "slant": 13.0}]}
    styles.annotate_book([r])
    assert r["italic"] is True


def test_upright_not_italic():
    r = {"label": "text", "x_height_pt": 5.0, "stroke_rel": 0.1,
         "words": [{"text": "a", "slant": 0.5}, {"text": "b", "slant": -1.0}, {"text": "c", "slant": 1.0}]}
    styles.annotate_book([r])
    assert r["italic"] is False


def test_attach_matches_same_page_by_text_and_keeps_style():
    aligned = [{"page": 47, "blocks": [{"block_id": "p47-b0", "text": "Género Iberoleptus Ver. 2026"}]}]
    styled = {47: [
        {"block_id": 0, "label": "text", "text": "Otro bloque distinto", "bold": False, "italic": False},
        {"block_id": 1, "label": "paragraph_title", "text": "Género Iberoleptus, ver 2026", "bold": True,
         "italic": False, "heading_level": 1, "x_height_pt": 7.9, "outlier": False},
    ]}
    res = styles.attach_aligned(aligned, styled)
    assert res["p47-b0"]["layout_block_id"] == 1
    assert res["p47-b0"]["bold"] is True and res["p47-b0"]["heading_level"] == 1


def test_attach_rejects_low_similarity_and_other_pages():
    aligned = [{"page": 47, "blocks": [{"block_id": "p47-b0", "text": "completely unrelated sentence here"}]},
               {"page": 99, "blocks": [{"block_id": "p99-b0", "text": "x"}]}]
    styled = {47: [{"block_id": 0, "label": "text", "text": "zzz qqq"}]}
    assert styles.attach_aligned(aligned, styled) == {}


def test_mixed_block_keeps_bold_line_index():
    r = {"label": "content", "x_height_pt": 4.5, "stroke_rel": 0.11,
         "line_stroke_rel": [0.23, 0.11, 0.11, 0.11, 0.105], "words": []}
    styles.annotate_book([r])
    assert r["bold_line_idx"] == [0]
    assert r["bold"] is False  # 1 of 5 lines: block is not bold, heading line is recorded


def test_heading_lines_levels_from_bold_line_xheight():
    recs = [{"label": "paragraph_title", "x_height_pt": 4.1, "stroke_rel": 0.11, "line_stroke_rel": [0.23, 0.11, 0.11],
             "line_xh_pt": [4.56, 4.1, 4.1], "words": []},
            {"label": "figure_title", "x_height_pt": 6.9, "stroke_rel": 0.2, "line_stroke_rel": [0.2],
             "line_xh_pt": [6.9], "words": []},
            {"label": "text", "x_height_pt": 5.0, "stroke_rel": 0.11, "line_stroke_rel": [0.11, 0.11],
             "line_xh_pt": [5.0, 5.0], "words": []}]
    styles.annotate_book(recs)
    assert [h["level"] for h in recs[0]["heading_lines"]] == [2]  # 4.56 below the 6.9 bold cluster
    assert [h["level"] for h in recs[1]["heading_lines"]] == [1]
    assert recs[2]["heading_lines"] == []  # body block never yields heading levels


def test_noise_bold_lines_ignored_for_levels():
    recs = [{"label": "text", "x_height_pt": 5.0, "stroke_rel": 0.11, "line_stroke_rel": [0.11] * 5,
             "line_xh_pt": [5.0] * 5, "words": []},
            {"label": "text", "x_height_pt": 5.0, "stroke_rel": 0.11, "line_stroke_rel": [0.4, 0.11],
             "line_xh_pt": [0.24, 5.0], "words": []}]
    thr = styles.annotate_book(recs)
    assert 0.24 not in thr["bold_line_clusters_pt"]
    assert recs[1]["heading_lines"] == []


def test_masthead_in_text_block_gets_no_heading_level():
    recs = [{"label": "text", "x_height_pt": 6.5, "stroke_rel": 0.2, "line_stroke_rel": [0.2],
             "line_xh_pt": [6.48], "words": []},
            {"label": "paragraph_title", "x_height_pt": 5.8, "stroke_rel": 0.2, "line_stroke_rel": [0.2],
             "line_xh_pt": [5.8], "words": []}]
    styles.annotate_book(recs)
    assert recs[0]["heading_lines"] == []
    assert recs[1]["heading_lines"] == []  # single paragraph_title line has no bold-line cluster context
