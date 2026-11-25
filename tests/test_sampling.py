"""分层抽样与 Wilson 区间：确定性、分层、排除已入队段。"""
from __future__ import annotations

import pytest

from transqa import sampling as sm


def test_wilson_reference_values():
    lo, hi = sm.wilson(0, 40)
    assert lo == pytest.approx(0.0, abs=1e-6) and hi == pytest.approx(0.0876, abs=0.001)
    lo, hi = sm.wilson(5, 40)
    assert (lo, hi) == (pytest.approx(0.0546, abs=0.002), pytest.approx(0.2611, abs=0.002))


def test_wilson_empty_sample_is_whole_interval_and_bounds_are_clamped():
    assert sm.wilson(0, 0) == (0.0, 1.0)
    lo, hi = sm.wilson(40, 40)
    assert 0.0 <= lo < hi <= 1.0 and sm.wilson(0, 40)[0] >= 0.0


def test_draw_is_deterministic_stratified_and_respects_exclude():
    paras = [{"page": p, "para": 0, "text": "t", "stratum": s} for p, s in enumerate(["key"] * 15 + ["caption"] * 3)]
    a = sm.draw(paras, 10, 1119, {(0, 0)})
    b = sm.draw(paras, 10, 1119, {(0, 0)})
    assert a == b and sum(x["stratum"] == "key" for x in a) == 10 and sum(x["stratum"] == "caption" for x in a) == 3
    assert (0, 0) not in {(x["page"], x["para"]) for x in a}


def test_draw_differs_by_seed_and_never_repeats_a_paragraph():
    paras = [{"page": p, "para": 0, "text": "t", "stratum": "key"} for p in range(50)]
    a, b = sm.draw(paras, 10, 1, set()), sm.draw(paras, 10, 2, set())
    assert a != b and len({(x["page"], x["para"]) for x in a}) == 10


def test_draw_is_independent_of_input_order_and_of_other_strata():
    key = [{"page": p, "para": 0, "text": "t", "stratum": "key"} for p in range(30)]
    cap = [{"page": 100 + p, "para": 0, "text": "t", "stratum": "caption"} for p in range(30)]
    a = sm.draw(key + cap, 5, 7, set())
    b = sm.draw(list(reversed(cap + key)), 5, 7, set())
    c = sm.draw(key, 5, 7, set())
    assert a == b and [x for x in a if x["stratum"] == "key"] == c


def test_draw_ignores_paragraphs_without_a_known_stratum():
    paras = [{"page": 1, "para": 0, "text": "t", "stratum": None}, {"page": 2, "para": 0, "text": "t", "stratum": "x"}]
    assert sm.draw(paras, 10, 1, set()) == []


def test_paragraphs_assign_strata_and_skip_references():
    pg = {1: "Fig. 1. Dorsal view.\n\n1(2) Proboscis with tooth …… 2\n\nLength 1 2 3 4 5 6 mm.\n\n"
             "FAUVEL, P., 1923. Faune de France."}
    s = {p["para"]: p["stratum"] for p in sm.paragraphs(pg, "en")}
    assert s[0] == "caption" and s[1] == "key" and s[2] == "numeric" and 3 not in s


def test_paragraphs_figure_word_is_a_caption_and_para_index_counts_skipped_paragraphs():
    pg = {4: "<!-- PDF p.4 | x -->\n\nFAUVEL, P., 1923. Faune de France.\n\nFigure 2. Anterior end, dorsal view.\n\n"
             "Body slender, with many segments and long dorsal cirri."}
    got = sm.paragraphs(pg, "en")
    assert [(p["page"], p["para"], p["stratum"]) for p in got] == [(4, 1, "caption"), (4, 2, "description")]
    assert got[0]["text"].startswith("Figure 2.")


def test_numeric_beats_other_strata_and_needs_five_numbers():
    # 图号本身也是数字：「Fig. 4. … 1, 2, 3, 4」共 5 个 → numeric；「Fig. 4. … 1, 2, 3」共 4 个 → caption
    pg = {1: "Fig. 4. Lengths 1, 2, 3, 4 mm.\n\nFig. 4. Lengths 1, 2, 3 mm."}
    assert [p["stratum"] for p in sm.paragraphs(pg, "en")] == ["numeric", "caption"]


def test_strata_constant():
    assert sm.STRATA == ("numeric", "key", "caption", "description")
