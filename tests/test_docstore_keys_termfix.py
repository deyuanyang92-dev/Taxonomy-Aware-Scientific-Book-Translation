"""终点文本固定错字（区→図）必须写进 terminals，而不只是版式栏位。"""
from __future__ import annotations

from docstore import keys


def test_fix_term_applies_to_stored_terminals():
    gr = keys.default_grammar()
    assert gr.fix_term("Aphrodita macroculata Imajima (区5)") == "Aphrodita macroculata Imajima (図5)"
    assert gr.fix_term("区域 abc") == "区域 abc"  # 后无数字不改
