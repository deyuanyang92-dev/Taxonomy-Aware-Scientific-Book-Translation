import ocr_score as m


def test_selftest_gate():
    assert m.selftest()


def test_cer_hand_computed():
    assert m.cer('abcd', 'abxd') == 0.25
    assert m.cer('abcd', '') == 1.0
    assert m.cer('', '') == 0.0


def test_raw_keeps_space_norm_drops():
    s = m.score_page('多毛 類', '多毛類')
    assert s['cer_norm'] == 0.0 and s['cer_raw'] == 0.25


def test_old_glyph_not_folded():
    assert m.score_page('區', '区')['cer_norm'] == 1.0


def test_len_ratio_and_recall():
    s = m.score_page('ゴカイ科12AB', 'ゴカイ')
    assert s['len_ratio'] < 0.85
    assert s['recall']['kana'] == 1.0 and s['recall']['digit'] == 0.0
    assert s['recall']['latin'] == 0.0
