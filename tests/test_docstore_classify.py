"""docstore.classify：外文（非英非中）资料的语言、kind、key 初判。

起因（2026-11-15）：Hartmann-Schröder 德文论文 19 份全被判成 lang=en、kind=英文原著，
key 取题名前几个词（Hartmann_Schr_der_Die_2），同一作者的多份论文无法区分。
"""
from pathlib import Path

from docstore.classify import guess, guess_lang


def test_german_title_is_de():
    g = guess(Path("Hartmann-Schröder, 1965- Die Polychaeten des sublitorals.pdf"))
    assert g["lang"] == "de"
    assert g["kind"] == "外文原著"


def test_german_without_umlaut():
    assert guess_lang("Zur Kenntnis des Eulitorals der australischen Kusten unter besonderer") == "de"


def test_english_title_stays_en():
    g = guess(Path("Hartmann-Schröder, 1998-Remarks on Tibiana and description of species Eunice.pdf"))
    assert g["lang"] == "en"
    assert g["kind"] == "英文原著"


def test_french_and_latin_markers():
    assert guess_lang("Les Annélides polychètes des côtes de France") == "fr"
    assert guess_lang("Polychaeta associated with Antipatharia") == "en"


def test_author_year_key():
    g = guess(Path("Hartmann-Schröder, 1965- Die Polychaeten des sublitorals.pdf"))
    assert g["key"] == "HartmannSchroder1965_Polychaeten_Sublitorals"
    assert g["authors"] == "Hartmann-Schröder"
    assert g["year"] == "1965"


def test_author_year_key_two_authors():
    g = guess(Path("Hartmann-Schröder & Zibrowius, 1998-Polychaeta associated with Antipatharia.pdf"))
    assert g["key"] == "HartmannSchroder1998_Polychaeta_Associated"


def test_same_author_year_differs_by_title():
    a = guess(Path("Hartmann-Schroder, 1989-Teil_2.pdf"))["key"]
    b = guess(Path("Hartmann-Schroder, 1989-Zur Kenntnis des Eulitorals der australischen Kusten (Teil 14).pdf"))["key"]
    assert a != b


def test_chinese_unchanged():
    g = guess(Path("中国动物志 环节动物门 多毛纲.pdf"))
    assert g["lang"] == "zh"


def test_author_year_without_title():
    assert guess(Path("Amoureux, 1973.pdf"))["key"] == "Amoureux1973"
    assert guess(Path("Fauvel, 1923a.pdf"))["key"] == "Fauvel1923a"
    assert guess(Path("Day & Hutchings, 1979.pdf"))["key"] == "Day1979"
