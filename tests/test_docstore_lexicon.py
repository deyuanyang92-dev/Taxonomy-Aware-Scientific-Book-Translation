"""lexicon.Fixer 的近似词查找：与逐词全表扫描结果一致，且规模大时不会拖垮一页 OCR。"""

import random
import time

import pytest

from docstore.lexicon import Fixer, VocabIndex, _lev, _lev_bounded


def best_slow(token, vocab, max_dist):
    """原实现：对整张词表逐词算编辑距离。"""
    best = []
    for cand in vocab:
        d = _lev(token, cand)
        if d <= max_dist:
            best.append((d, cand))
    if not best:
        return None
    best.sort(key=lambda x: (x[0], x[1]))
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1]


def test_lev_bounded_matches_full_distance():
    rng = random.Random(1)
    for _ in range(2000):
        a = "".join(rng.choice("abc") for _ in range(rng.randint(0, 8)))
        b = "".join(rng.choice("abc") for _ in range(rng.randint(0, 8)))
        for k in (0, 1, 2, 3):
            d = _lev(a, b)
            assert _lev_bounded(a, b, k) == (d if d <= k else k + 1), (a, b, k)


@pytest.mark.parametrize("max_dist", [0, 1, 2, 3])
def test_vocab_index_equals_brute_force(max_dist):
    rng = random.Random(7 + max_dist)
    alphabet = "甲乙丙丁戊"
    vocab = sorted({"".join(rng.choice(alphabet) for _ in range(rng.randint(2, 7))) for _ in range(300)})
    idx = VocabIndex(vocab, max_dist, max_token_len=8)
    for _ in range(600):
        tok = "".join(rng.choice(alphabet) for _ in range(rng.randint(2, 8)))
        assert idx.best(tok) == best_slow(tok, vocab, max_dist), tok


def test_vocab_index_drops_entries_too_long_to_match():
    idx = VocabIndex(["甲乙丙", "甲" * 40], 1, max_token_len=8)
    assert "甲" * 40 not in idx.words
    assert idx.best("甲乙") == "甲乙丙"


def test_exact_member_is_returned_unchanged_and_ties_are_refused():
    idx = VocabIndex(["沙蚕", "围沙蚕"], 1, max_token_len=8)
    assert idx.best("沙蚕") == "沙蚕"
    idx2 = VocabIndex(["甲乙丙", "甲乙丁"], 1, max_token_len=8)
    assert idx2.best("甲乙戊") is None  # 两个同距离候选 -> 不改


def test_fixer_applies_known_corrections(tmp_path):
    rules = tmp_path / "r.toml"
    rules.write_text(
        '[latin]\nmax_distance = 2\nbuiltin = ["Lopadorhynchus brevis"]\n'
        '[chinese]\nmax_distance = 1\nbuiltin = ["环带沙蚕", "单钩鳃裂虫"]\n',
        encoding="utf-8",
    )
    fx = Fixer(rules)
    out, ch = fx.apply("，环带沙虫，Lopadorhynthus brevis，单钩鳃裂虫。")
    assert "环带沙蚕" in out and "Lopadorhynchus brevis" in out and "单钩鳃裂虫" in out
    assert {c["rule"] for c in ch} == {"chinese_edit_distance", "latin_edit_distance"}


def test_fixer_scales_to_large_vocab(tmp_path):
    rng = random.Random(3)
    cn = "".join(chr(0x4E00 + i) for i in range(400))
    vocab = {"".join(rng.choice(cn) for _ in range(rng.randint(2, 9))) for _ in range(60000)}
    vocab |= {"".join(rng.choice(cn) for _ in range(35)) for _ in range(20000)}  # 整行长条目
    src = tmp_path / "vocab.txt"
    src.write_text("\n".join(sorted(vocab)), encoding="utf-8")
    rules = tmp_path / "r.toml"
    rules.write_text(f'[chinese]\nmax_distance = 1\nsources = ["{src}"]\n', encoding="utf-8")
    fx = Fixer(rules)
    text = "，".join("".join(rng.choice(cn) for _ in range(rng.randint(2, 8))) for _ in range(250))
    t = time.time()
    fx.apply(text)
    assert time.time() - t < 20  # 原实现这一规模要几小时
