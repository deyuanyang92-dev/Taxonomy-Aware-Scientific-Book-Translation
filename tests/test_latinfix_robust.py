"""#22：字体/编码鲁棒的拉丁文错字修正（normalize、同形字、多语混淆表、保护表、复核队列、可复现）。"""
import json
from collections import Counter

from docstore import latinfix as lf


def test_fullwidth_and_ligature_normalized_not_typo():
    new, ch = lf.normalize("Länge １９ ｍｍ, ﬁne ﬂat­ word​")
    assert new == "Länge 19 mm, fine flat word"
    assert {r for r, _, _ in ch} <= {"norm.fullwidth", "norm.ligature", "norm.invisible"}
    assert {"norm.fullwidth", "norm.ligature", "norm.invisible"} == {r for r, _, _ in ch}


def test_fullwidth_in_chinese_context_untouched():
    s = "样本Ａ１组"
    assert lf.normalize(s)[0] == s


def test_micro_sign_not_turned_into_greek_mu():
    assert lf.normalize("50 µm")[0] == "50 µm"


def test_homoglyph_cyrillic_a_in_latin_word_reported():
    word = "Nаture"  # Cyrillic а
    new, ch = lf.normalize(word)
    assert new == "Nature"
    assert ch == [("norm.homoglyph", word, "Nature")]


def test_homoglyph_pure_cyrillic_word_kept():
    assert lf.normalize("Привет")[0] == "Привет"


def test_nfd_recomposed():
    nfd = "Küste"
    assert lf.normalize(nfd)[0] == "Küste"


def test_spanish_accent_only_with_corpus_evidence():
    vocab = Counter({"comunmente": 1, "comúnmente": 40})
    new, ch = lf.fix_vocab("se halla comunmente", vocab, lang="es")
    assert new == "se halla comúnmente" and ch == [("comunmente", "comúnmente")]
    # 语料里没有重音形式：不动
    assert lf.fix_vocab("se halla comunmente", Counter({"comunmente": 1}), lang="es")[0] == "se halla comunmente"


def test_rare_valid_term_not_touched_when_not_attested():
    vocab = Counter({"mucus": 30, "mucos": 1})
    # mucos 与常见词差一字符，但 u→o 不在 es 混淆表里，不改
    assert lf.fix_vocab("mucos", vocab, lang="es")[0] == "mucos"


def test_german_kuste_needs_corpus_and_names_unchanged():
    vocab = Counter({"Kuste": 1, "Küste": 30, "glauCopsis": 1, "McIntosh": 1})
    new, _ = lf.fix_vocab("An der Kuste glauCopsis McIntosh", vocab, lang="de")
    assert new == "An der Küste glauCopsis McIntosh"
    assert lf.fix_vocab("Kuste", Counter({"Kuste": 1}), lang="de")[0] == "Kuste"


def test_protect_italics_authority_and_set():
    vocab = Counter({"Nereis": 1, "diversicolor": 1, "Muller": 1, "Müller": 40})
    text = "*Nereis diversicolor* (O. F. Muller, 1776) und Muller"
    new, ch = lf.fix_vocab(text, vocab, lang="de", protect={"Nereis"})
    assert "(O. F. Muller, 1776)" in new and "*Nereis diversicolor*" in new
    # 正文里未受保护的同一词可改
    assert new.endswith("und Müller")


def test_protect_set_blocks_replacement():
    vocab = Counter({"Kuste": 1, "Küste": 30})
    assert lf.fix_vocab("Kuste", vocab, lang="de", protect={"Kuste"})[0] == "Kuste"


def test_ambiguous_goes_to_review_queue_not_text():
    vocab = Counter({"Mahn": 1, "Mähn": 20, "Mahu": 20})
    review: list[dict] = []
    new, ch = lf.fix_vocab("er Mahn", vocab, lang="de", review=review)
    assert new == "er Mahn" and not ch
    assert review and review[0]["token"] == "Mahn" and review[0]["reason"] == "ambiguous"
    assert {c for c, _ in review[0]["candidates"]} == {"Mähn", "Mahu"}


def test_dictionary_only_flags():
    vocab = Counter({"Nereis": 2})
    review: list[dict] = []
    text = "Zelt Nereis zzqwx"
    new, ch = lf.fix_vocab(text, vocab, lang="en", review=review, dictionary={"zelt"}, protect=set())
    assert new == text and ch == []
    toks = {r["token"] for r in review}
    assert "zzqwx" in toks and "Zelt" not in toks and "Nereis" in toks  # 学名不在词典也只是复核，不替换
    assert all(r["reason"] in {"not_in_dictionary", "ambiguous"} for r in review)


def test_evidence_counts_in_detail():
    vocab = Counter({"Kuste": 1, "Küste": 30})
    detail: list[dict] = []
    lf.fix_page("Kuste", vocab, lang="de", detail=detail)
    assert detail == [{"rule": "vocab", "old": "Kuste", "new": "Küste", "n_old": 1, "n_new": 30, "lang": "de"}]


def test_deterministic():
    vocab = Counter({"Kuste": 1, "Küste": 30})
    text = "Kuste ﬁne １"
    a = lf.fix_page(text, vocab, lang="de")
    b = lf.fix_page(text, vocab, lang="de")
    assert a == b


def test_fix_page_backward_compatible_logs():
    new, log = lf.fix_page("Notopod beim & und", None)
    assert new == "Notopod beim ♂ und" and log[0][0] == "sex"


def test_learn_confusions_counts_substitutions():
    vocab = Counter({"Kuste": 1, "Küste": 9, "Muhle": 1, "Mühle": 8, "xyz": 5})
    got = lf.learn_confusions(vocab, common=5, rare=2)
    assert got[("u", "ü")] == 2


def test_cli_postfix_dry_reports_per_lang(tmp_path, monkeypatch, capsys):
    from docstore import cli, open_store
    from docstore.store import make_version

    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    st = open_store(tmp_path / "lib")
    pdf = tmp_path / "Muster, 1970-Test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    key, _ = st.register(pdf, by="pytest")
    st.update_doc(key, lang="de")
    st.put_version(key, 1, make_version("Zahl １９ und ﬁne", "ocr", producer="tesseract"))
    rq = tmp_path / "rq.jsonl"
    assert cli.main(["--root", str(st.root), "postfix", key, "--dry", "--review-out", str(rq)]) == 0
    out = capsys.readouterr().out
    assert "de" in out and "norm.fullwidth" in out
    assert st.read_page(key, 1)["producer"] == "tesseract"  # dry 不写
    assert rq.exists()
    json_lines = [json.loads(x) for x in rq.read_text().splitlines() if x]
    assert isinstance(json_lines, list)
