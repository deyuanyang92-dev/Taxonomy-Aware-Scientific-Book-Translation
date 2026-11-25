import term_en_candidates as T


def test_pdf_text_missing_file_no_zero_pages(tmp_path):
    assert T.pdf_text(tmp_path / "nope.pdf")[1] >= 1


def test_heads_and_ngrams():
    heads = T.heads_from_glossary(["neuropodial chaetae", "notopodial chaetae", "dorsal cirrus", "ventral cirrus"])
    assert heads == {"chaetae", "cirrus"}
    c = T.ngrams("The neuropodial chaetae are simple. With a long dorsal cirrus; and hyaline chaetae.", heads)
    assert c["neuropodial chaetae"] == 1 and c["dorsal cirrus"] == 1 and c["hyaline chaetae"] == 1
    assert "the neuropodial chaetae" not in c and "with a long dorsal cirrus" not in c
    assert "chaetae" not in c
    assert "starting from chaetae" not in T.ngrams("starting from chaetae", heads)
    assert "chaetae per parapodium" not in T.ngrams("chaetae per cirrus", heads)
