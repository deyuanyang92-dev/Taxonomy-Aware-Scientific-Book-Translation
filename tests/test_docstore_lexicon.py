"""lexicon.Fixer 的近似词查找：与逐词全表扫描结果一致，且规模大时不会拖垮一页 OCR。"""

import random
import time
from pathlib import Path

import pytest

from docstore import open_store, textify
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


def test_fixer_at_sign_is_e():
    fx = Fixer(Path(__file__).resolve().parents[1] / "docstore" / "rules" / "ocr_fix.toml")
    out, ch = fx.apply("Eurytho@ complanata (PALLAS 1766), mail a@b.", english=True)
    assert out.startswith("Eurythoe complanata") and any(c["rule"] == "at_sign_for_e" for c in ch)


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


# ---- 英文页：不得把人名/属名/普通英文词改成词表里的近似词（Harrison1992_MAI_Annelida 实例）----
# 词表里混有从 OCR 文本、散文行里抓来的「大写词+小写词」短语（"Bailey and"、"The bone is" 等）。


def _en_fixer(tmp_path, latin, chinese="", **extra):
    rules = tmp_path / "en.toml"
    body = "[latin]\nmax_distance = 2\nbuiltin = [%s]\n" % ", ".join(f'"{x}"' for x in latin)
    body += '[chinese]\nmax_distance = 0\nbuiltin = []\n' + chinese
    rules.write_text(body, encoding="utf-8")
    return Fixer(rules)


@pytest.mark.parametrize(
    "text, vocab",
    [
        # 引文里的作者名（Boilly -> Bailey，Friedman -> Freeman 的真实案例）
        ("in Magelona papillicornis (Boilly and Wissocq, 1977). The", ["Bailey and", "Magelona papilliorni"]),
        ("as shown by Friedman and Weiss (1980) in", ["Freeman and", "Freeman and Weiss"]),
        ("(Golding and Yuwono, 1994)", ["Coding and"]),
        # 句中大写的人名/属名、学名里的小写种名
        ("studied by Fischer in the", ["Fisher in the"]),
        ("lives with Dinophilus gyrociliatus in", ["Dinophilus gyroliliatus"]),
        ("Haementeria depressa is a leech", ["Haementerian depress"]),
        ("see Phragmatopoma lapidosa and", ["Phramatopoma lapidosa and"]),
        # 句首的普通英文词、普通短语
        ("The body is long. Their cilia", ["The bone is", "The cilia"]),
        ("complex structures and", ["Comple structures"]),
        ("Sabellaria spinulosa, Sabellaria", ["Sabellaridae spinulosa"]),
    ],
)
def test_english_page_never_fuzzy_edits_names_or_prose(tmp_path, text, vocab):
    fx = _en_fixer(tmp_path, vocab)
    out, ch = fx.apply(text)
    assert out == text, (out, ch)
    assert not [c for c in ch if c["rule"] == "latin_edit_distance"]


def test_english_page_keeps_hyphen_join_inside_known_name(tmp_path):
    fx = _en_fixer(tmp_path, ["Nereis marina", "Amphitrite ornata"])
    out, ch = fx.apply("on Nereis ma-\nrina and Amphitrite ornata here")
    assert "Nereis marina and" in out and "Amphitrite ornata" in out
    assert [c["rule"] for c in ch] == ["latin_dehyphen"]
    # 连字号断行但合并后不在词表里：不动
    out2, _ = fx.apply("on Nereis ba-\nrina here")
    assert out2 == "on Nereis ba-\nrina here"


def test_english_page_still_applies_fixed_regex_and_replace_rules(tmp_path):
    rules = tmp_path / "r.toml"
    rules.write_text(
        '[latin]\nmax_distance = 2\nbuiltin = ["Bailey and"]\n[chinese]\nmax_distance = 0\n'
        '[[regex_rules]]\nname = "pm"\npattern = "(?<=\\\\d) pm\\\\b"\nreplace = " µm"\n',
        encoding="utf-8",
    )
    out, ch = Fixer(rules).apply("fibers 10 pm wide (Boilly and Wissocq, 1977)")
    assert out == "fibers 10 µm wide (Boilly and Wissocq, 1977)"
    assert [c["rule"] for c in ch] == ["pm"]


def test_language_switch_autodetect_and_explicit(tmp_path):
    fx = _en_fixer(tmp_path, ["Lopadorhynchus brevis"])
    typo = "see Lopadorhynthus brevis."
    assert fx.apply(typo)[0] == typo                                   # 纯英文页：自动判英文，不纠
    assert fx.apply(typo, english=False)[0] == "see Lopadorhynchus brevis."   # 显式关掉英文保守模式
    cjk = "，环带沙虫，Lopadorhynthus brevis，单钩鳃裂虫。" * 3
    assert "Lopadorhynchus brevis" in fx.apply(cjk)[0]                 # 中文页：保持原行为
    assert "Lopadorhynchus" not in fx.apply(cjk, english=True)[0]      # 显式英文


def test_textify_consensus_rebuild_leaves_english_names_alone(tmp_path, monkeypatch):
    from docstore.store import make_version

    st = open_store(tmp_path / "libx")
    key, _ = st.register(None, key="Harrison_test", status="原件缺失")
    st.update_doc(key, lang="en")
    raw = "Cross-striated (Boilly and Wissocq, 1977) in Magelona papillicornis."
    st.put_version(key, 1, make_version(raw, "ocr", producer="tesseract", conf=0.7))
    monkeypatch.setattr(textify, "_FIXER", _en_fixer(tmp_path, ["Bailey and", "Magelona papilliorni"]))
    out = textify.consensus(st, key, pages=[1], by="pytest")
    assert out["recomputed"] == 1
    assert st.page(key, 1)["text"] == raw

