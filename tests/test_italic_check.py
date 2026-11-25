"""italic_check：误斜体（作者名、夹英文词的学名、汉字）、图注学名应正体、图注整条斜体。

依据：原书 Fauna Ibérica Vol. 45 p. 30 图注整条为 ITCGaramondStd-LtIta（斜体），
其中的学名 Alciopa reynaudii 为 ITCGaramondStd-Lt（正体）。
"""
from __future__ import annotations

import taxoformat as tf
from docx import Document

import italic_check as ic

LEX = tf.Lexicon(
    frozenset({"Nereis", "Torrea", "Alciopa"}),
    frozenset({("Nereis", "pelagica"), ("Alciopa", "reynaudii")}),
    frozenset(),
    frozenset(),
)


def _kinds(text: str, caption_names: str = "roman") -> list[str]:
    return [f.kind for f in ic.check_markdown("t.md", text, caption_names)]


def test_author_name_italic_flagged() -> None:
    assert ic.classify("*Rouse and Fauchald*", LEX, False, "roman") == "italic.author"
    assert ic.classify("*Rouse, 1997*", LEX, False, "roman") == "italic.author"
    assert ic.classify("*Rouse et al.*", LEX, False, "roman") == "italic.author"


def test_taxon_plus_english_word_is_mixed() -> None:
    assert ic.classify("*Torrea and*", LEX, False, "roman") == "italic.mixed"


def test_binomial_italic_in_body_is_fine() -> None:
    assert ic.classify("*Nereis pelagica*", LEX, False, "roman") == "italic.other"


def test_caption_names_italic_is_the_default() -> None:
    # 出版惯例：图注正体、学名斜体（用户 2026-11-17 定）。
    assert ic.classify("*Nereis pelagica*", LEX, True, "italic") == "italic.other"
    assert ic.classify("*Nereis pelagica*", LEX, True, "roman") == "caption.name_roman"


def test_cjk_italic_is_critical() -> None:
    assert ic.classify("*整条说明*", LEX, False, "roman") == "italic.cjk"


def test_family_italic_is_a_major_finding() -> None:
    # 原书科名排斜体（Vol. 45 p. 7 作者名单），但英文版按动物命名法惯例：
    # 只有属名、种名斜体，科级及以上阶元正体（用户 2026-11-17 定）。
    assert ic.classify("*Chrysopetalidae*", LEX, False, "roman") == "italic.higher_taxon"
    assert ic.LEVELS["italic.higher_taxon"] == "major"
    assert "italic.higher_taxon" in ic.FIXABLE


def test_family_italic_is_fixed_to_roman(tmp_path) -> None:
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    par = doc.add_paragraph()
    par.add_run("Families ")
    run = par.add_run("Lumbrineridae, Oenonidae")
    run.italic = True
    doc.save(str(src))
    findings = ic.fix_docx(src, out)
    assert findings and findings[0].kind == "italic.higher_taxon"
    fixed = Document(str(out)).paragraphs[0]
    assert all(not r.italic for r in fixed.runs if r.text.strip())


def test_family_run_keeps_neighbouring_italic_text() -> None:
    assert ic._split_higher("see Lumbrineridae now") == [
        ("see ", True), ("Lumbrineridae", False), (" now", True)]


def test_markdown_reports_author_italic() -> None:
    text = ("Nereis pelagica Smith, 1900.\n"
            "如 *Rouse and Fauchald* 所述，见 *Nereis pelagica*。\n"
            "Fig. 3. Specimen of *Nereis pelagica* from the Atlantic.\n")
    assert "italic.author" in _kinds(text)


def test_markdown_flags_whole_italic_caption() -> None:
    text = ("Fig. 7. *Specimen of Nereis pelagica from the Canary Islands, eastern Atlantic "
            "Ocean, collected at 1200 m depth.*\n")
    assert "caption.allitalic" in _kinds(text)


def test_markdown_clean_caption_has_no_major_finding() -> None:
    text = "Nereis pelagica Smith, 1900.\nFig. 2. Specimen of Nereis pelagica from the Atlantic.\n"
    major = [f for f in ic.check_markdown("t.md", text) if f.level in ("critical", "major")]
    assert major == []


def test_docx_detects_all_italic_caption_and_author_italic(tmp_path) -> None:
    doc = Document()
    doc.add_paragraph("Nereis pelagica Smith, 1900.")
    cap = doc.add_paragraph()
    cap.add_run("Fig. 4. Specimen of Nereis pelagica from the Atlantic.").italic = True
    body = doc.add_paragraph()
    body.add_run(" as noted by ")
    body.add_run("Rouse and").italic = True
    body.add_run(" Fauchald, 1997.")
    path = tmp_path / "book.docx"
    doc.save(path)
    kinds = [f.kind for f in ic.check_docx(path)]
    assert "caption.allitalic" in kinds
    assert "italic.author" in kinds


def test_docx_caption_roman_with_italic_name_passes(tmp_path) -> None:
    doc = Document()
    doc.add_paragraph("Nereis pelagica Smith, 1900.")
    cap = doc.add_paragraph()
    cap.add_run("Fig. 4. Specimen of ")
    cap.add_run("Nereis pelagica").italic = True
    cap.add_run(" from the Atlantic.")
    path = tmp_path / "book.docx"
    doc.save(path)
    assert [f for f in ic.check_docx(path) if f.level in ("critical", "major")] == []


def test_docx_fig_number_roman_species_italic_not_allitalic(tmp_path) -> None:
    """图N 正体 + 学名斜体：不得报 caption.allitalic。"""
    doc = Document()
    cap = doc.add_paragraph()
    cap.add_run("图3 ")
    cap.add_run("Australaugeneria michaelseni").italic = True
    path = tmp_path / "fig.docx"
    doc.save(path)
    kinds = [f.kind for f in ic.check_docx(path) if f.level in ("critical", "major")]
    assert "caption.allitalic" not in kinds


def test_fix_docx_makes_caption_roman_and_names_italic(tmp_path) -> None:
    doc = Document()
    doc.add_paragraph("Nereis pelagica Smith, 1900.")
    cap = doc.add_paragraph()
    cap.add_run("Fig. 4. Specimen of Nereis pelagica from the Atlantic.").italic = True
    src = tmp_path / "in.docx"
    out = tmp_path / "out.docx"
    doc.save(src)
    ic.fix_docx(src, out)
    runs = [(r.text, bool(r.italic)) for r in Document(out).paragraphs[1].runs if r.text.strip()]
    assert ("Nereis pelagica", True) in runs
    assert any("Atlantic" in t and not it for t, it in runs)


def test_genus_prefix_of_family_name_is_not_a_name() -> None:
    """Spio 是属名，Spionidae 是科名；属名匹配不得咬进科名（2009 en 图 5 误报）。"""
    lex = tf.Lexicon(frozenset({"Spio"}), frozenset(), frozenset(), frozenset())
    assert ic._names_in("Fig. 5 Body parts of Spionidae", lex) == []
    assert ic._names_in("Fig. 5 Spio filicornis", lex) == ["Spio filicornis"]
