"""Unattended-run blockers found 2026-11-26 (speed_architecture.md §2): spa hard-coded, html without
profile, figures exit 1, OCR on native PDFs."""
from __future__ import annotations

import argparse

import fitz

from booklayout import cli, make, sourcecheck as sc


def _pdf(tmp_path, pages=3, text="Nereis diversicolor O.F. Müller, 1776 has 12 parapodia and a long body text here."):
    doc = fitz.open()
    for _ in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 100), text, fontsize=10)
    f = tmp_path / "n.pdf"
    doc.save(str(f))
    return f


def test_native_tsv_has_tesseract_format(tmp_path):
    pdf = _pdf(tmp_path)
    cache = tmp_path / "c"
    cache.mkdir()
    out = sc.native_words_tsv(pdf, [1, 2, 3], cache, 300)
    assert set(out) == {1, 2, 3}
    toks, lines = [], []
    sc.read_tsv(out[1], 1, [], toks, lines)
    assert "Nereis" in [t.text for t in toks] and "1776" in " ".join(t.text for t in toks)


def test_native_tsv_rejects_scanned_page(tmp_path):
    doc = fitz.open()
    doc.new_page()  # blank: no text layer
    f = tmp_path / "s.pdf"
    doc.save(str(f))
    c = tmp_path / "c"
    c.mkdir()
    assert sc.native_words_tsv(f, [1], c, 300) == {}


def test_native_is_per_page_mixed_book(tmp_path):
    doc = fitz.open()
    doc.new_page()  # cover without text
    pg = doc.new_page()
    pg.insert_text((72, 100), "Nereis diversicolor has 12 parapodia and a long body text here.", fontsize=10)
    f = tmp_path / "m.pdf"
    doc.save(str(f))
    c = tmp_path / "c"
    c.mkdir()
    assert set(sc.native_words_tsv(f, [1, 2], c, 300)) == {2}


def test_make_source_lang_not_spanish_for_translated():
    a = argparse.Namespace(translated=True, lang=None, dict_lang=None)
    assert make.source_lang(a) == "eng" and make.source_dict_lang(a) == "en"
    a = argparse.Namespace(translated=False, lang=None, dict_lang=None)
    assert make.source_lang(a) == "spa" and make.source_dict_lang(a) == "es"
    a = argparse.Namespace(translated=True, lang="deu", dict_lang="de")
    assert make.source_lang(a) == "deu"


def test_default_profile_is_valid(tmp_path):
    f = make._default_profile(tmp_path / "w")
    assert cli.main(["profile", "--validate", str(f)]) == 0


def test_figures_extract_lenient_exit_zero(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "Figure 1. caption", fontsize=10)
    f = tmp_path / "f.pdf"
    doc.save(str(f))
    rc = cli.main(["figures", "extract", "--pdf", str(f), "--out", str(tmp_path / "o"), "--dpi", "50", "--lenient"])
    assert rc == 0
    assert (tmp_path / "o" / "figures_manifest.json").exists()
