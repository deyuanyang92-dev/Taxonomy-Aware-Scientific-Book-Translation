"""taxostyle：原文/译文逐 token 体例比对（#34），以及渲染后 DOCX/PDF 的体例审计（#20）。"""
from __future__ import annotations

import json

import fitz
import pytest
import taxoformat as tf
import taxostyle as ts
from docx import Document

LEX = tf.Lexicon(
    frozenset({"Nereis", "Alciopa"}),
    frozenset({("Nereis", "pelagica")}),
    frozenset(),
    frozenset(),
)


def codes(issues: list[ts.StyleIssue]) -> list[str]:
    return [i.code for i in issues]


def cmp(src: str, tgt: str, **kw) -> list[ts.StyleIssue]:
    return ts.compare_block(src, tgt, LEX, where="p1/b1", **kw)


def test_source_italic_translation_roman() -> None:
    iss = cmp("*Nereis pelagica* is common", "Nereis pelagica 很常见")
    assert codes(iss) == ["source_italic_translation_roman"]
    assert iss[0].token == "Nereis pelagica" and iss[0].expected == "italic"
    assert iss[0].severity == "error"


def test_family_italic_in_translation_is_error_even_if_source_italic() -> None:
    iss = cmp("*Nereididae* are worms", "*Nereididae* 是蠕虫")
    assert codes(iss) == ["translation_italic_expected_roman"]
    assert iss[0].rank == "family"


def test_family_roman_ok_and_source_family_italic_only_info() -> None:
    iss = cmp("*Nereididae* are worms", "Nereididae 是蠕虫")
    assert all(i.severity == "info" for i in iss)
    assert codes(iss) == ["source_family_italic_accepted"]


def test_qualifiers_roman_pass() -> None:
    assert cmp("*Nereis* sp.", "*Nereis* sp.") == []
    assert cmp("*Nereis* cf. *pelagica*", "*Nereis* cf. *pelagica*") == []


def test_qualifier_italic_error() -> None:
    iss = cmp("*Nereis* sp.", "*Nereis sp.*")
    assert "translation_italic_expected_roman" in codes(iss)
    assert any(i.token == "sp." and i.rank == "qualifier" for i in iss)


def test_authority_italic_error() -> None:
    iss = cmp("Rouse and Fauchald, 1997", "*Rouse and Fauchald, 1997*")
    assert codes(iss) == ["translation_italic_expected_roman"]
    assert iss[0].rank == "authority"


def test_name_followed_by_roman_authority_ok() -> None:
    assert cmp("*Nereis pelagica* Linnaeus, 1758", "*Nereis pelagica* Linnaeus, 1758") == []


def test_genus_prefix_of_longer_word_not_matched() -> None:
    lex = tf.Lexicon(frozenset({"Nereid"}), frozenset(), frozenset(), frozenset())
    assert ts.compare_block("Nereididae", "Nereididae", lex, where="x") == []


def test_unclassified_capitalised_goes_to_review() -> None:
    iss = cmp("text", "*Zorgus* 是新属")
    assert codes(iss) == ["unclassified_capitalised"]
    assert iss[0].severity == "info"


def test_reference_role_skipped() -> None:
    iss = ts.compare_block("*Nereis pelagica* in Journal", "Nereis pelagica in 期刊",
                           LEX, where="x", role="ref")
    assert iss == []


def test_italic_book_title_not_flagged() -> None:
    assert cmp("see Fauna Iberica", "见 *Fauna Ibérica* 一书") == []


def test_compare_aligned_and_report(tmp_path) -> None:
    aligned = {"pages": [{"page": 7, "blocks": [
        {"block_id": "b1", "role": "body", "text": "*Nereis pelagica* here",
         "translation": "Nereis pelagica 在此"},
        {"block_id": "b2", "role": "body", "text": "plain", "translation": "普通"},
    ]}]}
    p = tmp_path / "a.json"
    p.write_text(json.dumps(aligned), encoding="utf-8")
    rep = ts.compare_aligned(p, LEX)
    assert rep["ok"] is False and rep["errors"] == 1
    row = rep["issues"][0]
    assert row["page"] == 7 and row["block_id"] == "b1"
    assert {"token", "rank", "observed", "expected", "evidence", "code"} <= set(row)


def test_cli_compare_exit_code(tmp_path) -> None:
    aligned = {"pages": [{"page": 1, "blocks": [
        {"block_id": "b1", "role": "body", "text": "*Nereis pelagica*", "translation": "Nereis pelagica"}]}]}
    p = tmp_path / "a.json"
    p.write_text(json.dumps(aligned), encoding="utf-8")
    out = tmp_path / "r.json"
    assert ts.main(["compare", str(p), "--report", str(out), "--no-worms", "--genera", "Nereis"]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False


# ------------------------------------------------------------ rendered DOCX


def _docx(tmp_path, runs: list[tuple[str, bool]]):
    d = Document()
    par = d.add_paragraph()
    for t, it in runs:
        par.add_run(t).italic = it
    p = tmp_path / "x.docx"
    d.save(str(p))
    return p


def test_docx_audit_clean(tmp_path) -> None:
    p = _docx(tmp_path, [("Nereis", True), (" sp. 与 ", False), ("Nereis pelagica", True), (" Linnaeus, 1758", False)])
    assert ts.audit_docx(p, LEX)["ok"] is True


def test_docx_audit_detects_roman_name_and_italic_qualifier(tmp_path) -> None:
    p = _docx(tmp_path, [("Nereis pelagica", False), (" 和 ", False), ("Alciopa sp.", True)])
    rep = ts.audit_docx(p, LEX)
    got = {i["code"] for i in rep["issues"]}
    assert {"name_roman", "qualifier_italic"} <= got
    assert rep["ok"] is False


def test_docx_audit_includes_tables(tmp_path) -> None:
    d = Document()
    t = d.add_table(rows=1, cols=1)
    t.cell(0, 0).paragraphs[0].add_run("Nereididae").italic = True
    p = tmp_path / "t.docx"
    d.save(str(p))
    rep = ts.audit_docx(p, LEX)
    assert [i["code"] for i in rep["issues"]] == ["higher_taxon_italic"]


# ------------------------------------------------------------- rendered PDF


def _pdf(tmp_path, parts: list[tuple[str, str]]):
    doc = fitz.open()
    page = doc.new_page()
    x = 72
    for text, font in parts:
        page.insert_text((x, 100), text, fontname=font, fontsize=11)
        x += fitz.get_text_length(text, fontname=font, fontsize=11) + 3
    p = tmp_path / "x.pdf"
    doc.save(str(p))
    return p


def test_pdf_audit_clean_and_bad(tmp_path) -> None:
    good = _pdf(tmp_path, [("Nereis ", "tiit"), ("sp.", "tiro")])
    assert ts.audit_pdf(good, LEX)["ok"] is True
    bad_dir = tmp_path / "b"
    bad_dir.mkdir()
    bad = _pdf(bad_dir, [("Nereis ", "tiro"), ("sp.", "tiit")])
    rep = ts.audit_pdf(bad, LEX)
    assert {i["code"] for i in rep["issues"]} >= {"name_roman", "qualifier_italic"}
    assert rep["issues"][0]["page"] == 1


@pytest.mark.parametrize("name", ["TimesNewRomanPS-ItalicMT", "ITCGaramondStd-LtIta", "Arial-ItalicMT",
                                  "Foo-Oblique"])
def test_italic_font_names(name) -> None:
    assert ts.font_is_italic(name, 0)


def test_roman_font_names() -> None:
    assert not ts.font_is_italic("TimesNewRomanPSMT", 0)
    assert not ts.font_is_italic("ITCGaramondStd-Lt", 0)
    assert ts.font_is_italic("Anything", 2)


# ------------------------------------------------------------- 接线


def test_italic_check_rendered_subcommand(tmp_path) -> None:
    import italic_check

    p = _docx(tmp_path, [("Alciopa sp.", True)])
    assert italic_check.main(["rendered", str(p), "--no-worms", "--report", str(tmp_path / "r.json")]) in (0, 1)
    assert (tmp_path / "r.json").exists()


def test_booklayout_gate_blocks_on_style_report(tmp_path) -> None:
    from booklayout import cli

    ok = {"ok": True}
    for n in ("qa", "check"):
        (tmp_path / f"{n}.json").write_text(json.dumps(ok), encoding="utf-8")
    (tmp_path / "key.json").write_text(json.dumps({"breaks": [], "defects": []}), encoding="utf-8")
    (tmp_path / "style.json").write_text(json.dumps({"ok": False, "errors": 3}), encoding="utf-8")
    base = ["gate", "--qa", str(tmp_path / "qa.json"), "--check", str(tmp_path / "check.json"),
            "--key-report", str(tmp_path / "key.json")]
    assert cli.main(base) == 0
    assert cli.main([*base, "--style-report", str(tmp_path / "style.json")]) == 1
