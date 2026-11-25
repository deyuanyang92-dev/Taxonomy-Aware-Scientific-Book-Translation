"""落实前护栏：空 new、new 含源语言文字、极性词互换须有原文引文。"""
from __future__ import annotations

from transqa import guardrails as g

PAIRS = [("present", "absent"), ("anterior", "posterior"), ("more than", "fewer than")]


def test_blocks_empty_new():
    assert g.check_edit("x y", "  ", "src", sl="ja", tl="en", polarity=[])


def test_blocks_source_script_in_new():
    assert "源语言" in g.check_edit("setae", "setae 刚毛", "背剛毛", sl="ja", tl="en", polarity=[])


def test_blocks_polarity_swap_without_quote():
    assert g.check_edit("eyes present", "eyes absent", "眼あり", sl="ja", tl="en", polarity=PAIRS)


def test_blocks_polarity_swap_with_quote_not_in_source():
    assert g.check_edit("eyes present", "eyes absent", "眼あり", sl="ja", tl="en", polarity=PAIRS, quote="眼なし")


def test_allows_polarity_swap_with_verbatim_source_quote():
    assert g.check_edit("eyes present", "eyes absent", "眼なし。", sl="ja", tl="en", polarity=PAIRS,
                        quote="眼なし") is None


def test_quote_match_ignores_whitespace_and_width():
    assert g.check_edit("eyes present", "eyes absent", "眼 なし。", sl="ja", tl="en", polarity=PAIRS,
                        quote="眼なし") is None


def test_multiword_pair_and_reverse_direction_blocked():
    assert g.check_edit("fewer than 5 eyes", "more than 5 eyes", "x", sl="ja", tl="en", polarity=PAIRS)


def test_swap_inside_longer_text_with_other_occurrence_blocked():
    assert g.check_edit("anterior and anterior", "anterior and posterior", "x", sl="ja", tl="en", polarity=PAIRS)


def test_non_polarity_change_passes():
    assert g.check_edit("eyes present", "eyes well developed", "x", sl="ja", tl="en", polarity=PAIRS) is None


def test_polarity_rule_skipped_when_no_list_for_pair():
    assert g.load_polarity("xx", "yy") == [] and g.check_edit(
        "a present", "a absent", "s", sl="xx", tl="yy", polarity=[]) is None


def test_source_script_rule_skipped_for_non_latin_target_and_latin_source():
    assert g.check_edit("a", "b 刚毛", "s", sl="ja", tl="zh", polarity=[]) is None      # tl 非拉丁文字
    assert g.check_edit("a", "b ö", "s", sl="de", tl="en", polarity=[]) is None         # sl 为拉丁文字，无从区分


def test_load_polarity_reads_ja_en_file():
    pairs = g.load_polarity("ja", "en")
    assert ("present", "absent") in pairs and ("more than", "fewer than") in pairs
    assert all(not a.startswith("#") for a, _ in pairs)


# 合成句（结构取自 40 页验收里的真实错改 p.286，句子本身是自编的，书稿原文不入库）：
# 两遍 check 与复核一致把整句里的 lobe alpha / lobe beta 互换并自动落实。原文是 甲葉…乙葉…，
# 译文原本就译错、改动换成另一种错。单处极性互换的规则拦不住它（互换了 4 处，词也不在极性表里）。
P286_OLD = ("lobe alpha a short triangle, lobe beta semicircular; later segments gradually larger, "
            "lobe alpha becoming longer and lobe beta approximately triangular")
P286_NEW = ("lobe beta a short triangle, lobe alpha semicircular; later segments gradually larger, "
            "lobe beta becoming longer and lobe alpha approximately triangular")
P286_SRC = "甲葉は短い三角形，乙葉は半円形，以降の体節は漸次大きくなって甲葉は更に長くなり，乙葉は略三角形になる"


def test_blocks_pure_word_permutation_even_with_a_verbatim_source_quote():
    why = g.check_edit(P286_OLD, P286_NEW, P286_SRC, sl="ja", tl="en", polarity=PAIRS, quote="甲葉は短い三角形")
    assert why and "互换" in why


def test_blocks_two_word_swap_even_without_polarity_list():
    assert g.check_edit("left and right", "right and left", "x", sl="ja", tl="en", polarity=[])


def test_still_allows_edits_that_change_words_or_only_punctuation():
    assert g.check_edit("a short triangle", "a short, triangle", "x", sl="ja", tl="en", polarity=[]) is None
    assert g.check_edit("postbranchial setae", "postchaetal lobes", "x", sl="ja", tl="en", polarity=[]) is None


# 合成句（结构取自 40 页验收里的真实错改 p.14，句子本身是自编的）：改动在句末追加
# "; arrangement of scales varies among individuals"，而该页译文开头已有同一句——自动落实后同一句话出现两次。
P14_OLD = "Scales ranging from pale to dark, highly variable, without spines or marginal fringe papillae."
P14_NEW = ("Scales ranging from pale to dark, highly variable, without spines or marginal fringe "
           "papillae; arrangement of scales varies among individuals.")
P14_TGT = ("length 3–6 cm, with 55–85 segments. Arrangement of scales varies among individuals. "
           + P14_OLD + " Head pentagonal.")


def test_blocks_pure_insertion_that_duplicates_text_already_on_the_target_page():
    why = g.check_edit(P14_OLD, P14_NEW, "x", sl="ja", tl="en", polarity=[], tgt_text=P14_TGT)
    assert why and "已有" in why


def test_allows_pure_insertion_that_is_new_to_the_target_page():
    assert g.check_edit(P14_OLD, P14_NEW, "x", sl="ja", tl="en", polarity=[], tgt_text=P14_OLD) is None
    assert g.check_edit(P14_OLD, P14_NEW, "x", sl="ja", tl="en", polarity=[]) is None   # 没给页文：不判


def test_short_insertion_found_elsewhere_is_not_blocked():
    old, new = "Palps long, eyes absent.", "Palps long, eyes of the type absent."
    assert g.check_edit(old, new, "x", sl="ja", tl="en", polarity=[], tgt_text="of the type") is None


def test_load_polarity_finds_list_in_installed_skill_layout(tmp_path):
    """安装到技能目录后 md/tsv 在根下（没有 skill/ 层）：pitfalls/ 也要能读到，否则规则 3 静默失效。"""
    (tmp_path / "pitfalls").mkdir()
    (tmp_path / "pitfalls" / "ja-en.polarity.tsv").write_text("# c\nnotopodium\tneuropodium\n", encoding="utf-8")
    assert g.load_polarity("ja", "en", root=tmp_path) == [("notopodium", "neuropodium")]
    (tmp_path / "skill" / "pitfalls").mkdir(parents=True)
    (tmp_path / "skill" / "pitfalls" / "ja-en.polarity.tsv").write_text("a\tb\n", encoding="utf-8")
    assert g.load_polarity("ja", "en", root=tmp_path) == [("a", "b")]      # 仓库布局优先
