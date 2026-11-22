"""日文静默错误规则：只对 lang=ja 生效，语种未知不动。"""
from __future__ import annotations

from pathlib import Path

import pytest

from docstore.lexicon import Fixer

RULES = Path(__file__).resolve().parent.parent / "docstore" / "rules" / "ocr_fix.toml"


@pytest.fixture(scope="module")
def fx() -> Fixer:
    return Fixer(RULES)


CASES = [
    ("被囊鉤状剛毛", "被嚢鉤状剛毛", "ja_sac_simplified"),
    ("鳃は11～13対あり", "鰓は11～13対あり", "ja_gill_simplified"),
    ("is inflata (区154)/前口葉", "is inflata (図154)/前口葉", "ja_fig_ku"),
    ("11”.疣足は複剛毛束", "11'.疣足は複剛毛束", "ja_key_prime_quote"),
]


@pytest.mark.parametrize("src,want,rule", CASES)
def test_ja_rules_fire(fx: Fixer, src: str, want: str, rule: str):
    out, ch = fx.apply(src, lang="ja")
    assert want in out
    assert rule in {c["rule"] for c in ch}


@pytest.mark.parametrize("src,_w,rule", CASES)
@pytest.mark.parametrize("lang", [None, "zh", "en"])
def test_ja_rules_skip_other_langs(fx: Fixer, src: str, _w: str, rule: str, lang):
    _, ch = fx.apply(src, lang=lang)
    assert rule not in {c["rule"] for c in ch}


def test_ja_rules_leave_correct_text(fx: Fixer):
    s = "鰓は11対．被嚢鉤状剛毛（図13）．区域は広い．第10”と記す"
    assert fx.apply(s, lang="ja")[0] == s
