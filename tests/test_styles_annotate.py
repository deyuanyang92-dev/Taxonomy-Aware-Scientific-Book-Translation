"""Book-level annotation: outlier guard, bold cue, heading level clustering (pure, no PDF)."""
from booklayout import styles


def _b(label, xh=None, sr=None):
    return {"label": label, "x_height_pt": xh, "stroke_rel": sr}


def test_outlier_header_is_flagged_and_not_text_body():
    recs = [_b("text", 5.0, 0.11)] * 5 + [_b("header", 15.8, 0.04)]
    styles.annotate_book(recs)
    assert recs[-1]["outlier"] is True
    assert recs[-1]["bold"] is False


def test_bold_cue_from_stroke_ratio():
    recs = [_b("text", 5.0, 0.10)] * 5 + [_b("paragraph_title", 5.8, 0.18), _b("text", 5.0, 0.10)]
    thr = styles.annotate_book(recs)
    assert recs[5]["bold"] is True
    assert recs[6]["bold"] is False
    assert thr["status"] == "unverified"


def test_heading_levels_by_size_clusters():
    recs = [_b("text", 5.0, 0.1)] * 3 + [
        _b("doc_title", 7.9, 0.15), _b("paragraph_title", 5.8, 0.17),
        _b("paragraph_title", 5.85, 0.17), _b("paragraph_title", 6.9, 0.2)]
    styles.annotate_book(recs)
    lv = [r["heading_level"] for r in recs if r["label"] in styles.HEADING_LABELS]
    assert lv[0] == 1          # 7.9 pt doc_title -> level 1
    assert lv[1] == lv[2]      # 5.8 and 5.85 merge into one cluster
    assert lv[3] == 2          # 6.9 pt between doc_title and 5.8 cluster
    assert lv[1] == 3


def test_contents_page_regular_serif_lines_not_bold():
    # book body median ~0.105 from other pages; page 6 (contents) lines sit at ~0.135 all over:
    # no line is bold relative to its own page, so none may be flagged.
    body = [{"page": 9, "label": "text", "x_height_pt": 5.0, "stroke_rel": 0.105,
             "line_stroke_rel": [0.105] * 6, "line_xh_pt": [5.0] * 6, "words": []} for _ in range(3)]
    toc = {"page": 6, "label": "content", "x_height_pt": 5.0, "stroke_rel": 0.135,
           "line_stroke_rel": [0.136, 0.143, 0.148, 0.135, 0.141, 0.135], "line_xh_pt": [7.9, 6.7, 6.5, 4.8, 5.0, 5.0],
           "words": []}
    styles.annotate_book(body + [toc])
    assert toc["bold_line_idx"] == []
    assert toc["bold"] is False


def test_heading_line_bold_relative_to_its_own_page():
    # p47-like page: one heading line at 0.235 among regular lines at ~0.11 is bold.
    recs = [{"page": 47, "label": "content", "x_height_pt": 4.3, "stroke_rel": 0.12,
             "line_stroke_rel": [0.235, 0.118, 0.118, 0.111, 0.111, 0.111],
             "line_xh_pt": [4.56, 4.08, 4.08, 4.32, 4.32, 4.32], "words": []}]
    styles.annotate_book(recs)
    assert recs[0]["bold_line_idx"] == [0]


def test_content_block_bold_line_gets_heading_level():
    # mixed content block (e.g. key couplet heading inside a content block) keeps its bold heading line level
    recs = [{"page": 1, "label": "paragraph_title", "x_height_pt": 6.9, "stroke_rel": 0.2, "line_stroke_rel": [0.2],
             "line_xh_pt": [6.9], "words": []},
            {"page": 47, "label": "content", "x_height_pt": 4.3, "stroke_rel": 0.12,
             "line_stroke_rel": [0.235, 0.118, 0.118, 0.111, 0.111, 0.111],
             "line_xh_pt": [4.56, 4.08, 4.08, 4.32, 4.32, 4.32], "words": []}]
    styles.annotate_book(recs)
    assert [h["level"] for h in recs[1]["heading_lines"]] == [2]


def test_figure_panel_letter_is_not_a_heading_line():
    recs = [{"page": 14, "label": "figure_title", "text": "A", "x_height_pt": 6.5, "stroke_rel": 0.2,
             "line_stroke_rel": [0.2], "line_xh_pt": [6.48], "words": []},
            {"page": 14, "label": "figure_title", "text": "B", "x_height_pt": 7.2, "stroke_rel": 0.2,
             "line_stroke_rel": [0.2], "line_xh_pt": [7.2], "words": []}]
    styles.annotate_book(recs)
    assert recs[0]["heading_lines"] == [] and recs[1]["heading_lines"] == []


def test_plain_entry_block_gets_no_heading_level_without_style_cue():
    # p48 false positive: a regular-type synonym line in a paragraph_title block is not a heading
    recs = [{"page": 48, "label": "paragraph_title", "text": "Petitia amphophthalma Siewing, 1956. Vie Milieu",
             "x_height_pt": 6.24, "stroke_rel": 0.11, "line_stroke_rel": [0.11], "line_xh_pt": [6.24], "words": []},
            {"page": 48, "label": "paragraph_title", "text": "ÍNDICE", "x_height_pt": 7.92, "stroke_rel": 0.11,
             "line_stroke_rel": [0.11], "line_xh_pt": [7.92], "words": []}]
    styles.annotate_book(recs)
    assert recs[0]["heading_level"] is None
    assert recs[1]["heading_level"] is not None
