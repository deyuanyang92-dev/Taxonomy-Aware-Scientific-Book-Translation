"""段落对齐检测器（纯函数部分）：引文闸口按整页核对，伪引文丢弃。"""
from __future__ import annotations

import pytest

from transqa import aligner as al


def test_gate_drops_fake_quote_keeps_real_one():
    raw = [{"para": 0, "type": "omitted", "quote": "背剛毛は足刺状で多数", "reason": "r"},
           {"para": 0, "type": "omitted", "quote": "原文にない文章です", "reason": "r"}]
    kept, dropped = al.gate_items(raw, 3, "体は細長い。背剛毛は足刺状で多数ある。", "Body slender.")
    assert [k.quote for k in kept] == ["背剛毛は足刺状で多数"] and dropped[0]["drop_reason"]
    assert kept[0].page == 3 and kept[0].type == "omitted"


def test_gate_normalizes_fullwidth_and_whitespace():
    kept, _ = al.gate_items([{"para": 0, "type": "omitted", "quote": "体節数は 12 以上", "reason": "r"}],
                            1, "体節数は１２以上である。", "Segments.")
    assert len(kept) == 1


def test_gate_drops_short_quote_and_unknown_type():
    kept, dropped = al.gate_items([{"para": 0, "type": "omitted", "quote": "体は", "reason": "r"},
                                   {"para": 0, "type": "wrong", "quote": "xxxxxxxxxx", "reason": "r"}],
                                  1, "体は細い", "x")
    assert kept == [] and len(dropped) == 2 and all(d["drop_reason"] for d in dropped)


def test_gate_added_checks_target_page_not_paragraph_index():
    src, tgt = "a\n\nb", "x\n\ny\n\nThe type material has been lost.\n\nz"     # 段落数不等
    kept, _ = al.gate_items([{"para": 1, "type": "added", "quote": "The type material has been lost.",
                              "reason": "r"}], 1, src, tgt)
    assert len(kept) == 1


def test_gate_omitted_quote_must_be_in_source_not_target_and_vice_versa():
    src, tgt = "体は細長い。背剛毛は足刺状で多数ある。", "Body slender. The type material has been lost."
    kept, dropped = al.gate_items(
        [{"para": 0, "type": "omitted", "quote": "The type material has been lost.", "reason": "r"},
         {"para": 0, "type": "added", "quote": "背剛毛は足刺状で多数", "reason": "r"}], 1, src, tgt)
    assert kept == [] and len(dropped) == 2


def test_gate_tolerates_malformed_entries():
    kept, dropped = al.gate_items(["junk", {"type": "omitted"}, {"para": "x", "type": "omitted", "quote": "体は細長い。"}],
                                  1, "体は細長い。", "x")
    assert len(kept) == 1 and kept[0].para == -1 and len(dropped) == 2


def test_split_paras_drops_page_marker_and_blank_paragraphs():
    t = "<!-- PDF p.3 | x -->\n\nFirst para\nsecond line.\n\n\n  \n\nSecond para."
    assert al.split_paras(t) == ["First para\nsecond line.", "Second para."]


def test_build_user_numbers_paragraphs_in_both_blocks():
    u = al.build_user(["a", "b"], ["x"])
    assert u == "SOURCE:\n[0] a\n[1] b\n\nTARGET:\n[0] x"


def test_system_prompt_is_language_parametrised_and_digest_tracks_template():
    s = al.system_prompt("ja", "en")
    assert "Japanese taxonomic source text" in s and "{SL}" not in s and "omitted" in s and "added" in s
    assert "Bulgarian" in al.system_prompt("bg", "en")
    import hashlib
    assert al.PROMPT_DIGEST == hashlib.sha1(al.SYSTEM_PROMPT.encode("utf-8")).hexdigest()


@pytest.mark.parametrize('reason', [
    'This is present in English as parapodia sub-biramous, notopodia vestigial, so not omitted — skip.',
    'Present in English as Distribution—Tohoku, Hokkaido, so not omitted.',
    'the English does contain the full segment list, so not a true omission.',
    'which is rendered; this is actually present; no omission here.',
])
def test_gate_drops_items_whose_own_reason_says_nothing_is_omitted(reason):
    """clean2 实测：10 条对齐项里 4 条的 reason 自己写着「并没遗漏」，仍进了人工队列。"""
    src = '疣足は亜二叉型で背足枝は発育不全である。'
    kept, dropped = al.gate_items([{'para': 0, 'type': 'omitted', 'quote': '疣足は亜二叉型で背足枝は発育不全',
                                         'reason': reason}], 7, src, 'Parapodia sub-biramous.')
    assert kept == []
    assert dropped[0]['drop_reason'].startswith('模型自述')


def test_gate_keeps_item_whose_reason_merely_contains_not_stated():
    src = '列は個体によって異なる。'
    kept, _ = al.gate_items([{'para': 0, 'type': 'omitted', 'quote': '列は個体によって異なる',
                                   'reason': 'The arrangement varies among individuals, which is not stated as such '
                                             'in the English; the English omits the identification.'}], 7, src, 'x')
    assert len(kept) == 1


def test_unparseable_or_infinite_para_becomes_minus_one_not_a_crash():
    """评审 M-6：模型写 "para": Infinity（json.loads 得 float('inf')）时 int() 抛 OverflowError，对齐阶段永久崩溃。"""
    raw = [{"para": float("inf"), "type": "omitted", "quote": "背剛毛は足刺状で多数", "reason": "r"},
           {"para": float("nan"), "type": "omitted", "quote": "背剛毛は足刺状で多数", "reason": "r"}]
    kept, _ = al.gate_items(raw, 3, "体は細長い。背剛毛は足刺状で多数ある。", "Body slender.")
    assert [k.para for k in kept] == [-1, -1]
