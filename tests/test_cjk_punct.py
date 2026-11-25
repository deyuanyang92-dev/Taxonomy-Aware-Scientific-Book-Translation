from booklayout.builder import cjk_punct


def test_fullwidth_next_to_cjk():
    assert cjk_punct("体长 20 cm;另一方面,Palmyra 属") == "体长 20 cm；另一方面，Palmyra 属"


def test_parens_and_range():
    assert cjk_punct("触角(原文「副感触手」)。8~9 cm") == "触角（原文「副感触手」）。8–9 cm"
    assert cjk_punct("(ウミネズミ,sea mouse)。") == "（ウミネズミ，sea mouse）。"


def test_latin_untouched():
    assert cjk_punct("Mettam(1980) a, b; c") == "Mettam(1980) a, b; c"


def test_no_chapter_heading_and_page_break_before(tmp_path):
    import json
    import docx
    pages = [{"page": 1, "chapter": "X", "kind": "body", "blocks": [
        {"block_id": "a", "role": "heading", "translation": "甲", "source_page": 1},
        {"block_id": "b", "role": "heading", "translation": "乙", "source_page": 1,
         "page_break_before": True}]}]
    (tmp_path / "a.json").write_text(json.dumps({"pages": pages, "metadata": {}}), encoding="utf8")
    (tmp_path / "m.json").write_text(json.dumps({"title": "", "body_start_page": 1,
        "include_contents": False, "chapter_headings": False}), encoding="utf8")
    (tmp_path / "source_figure_audit.json").write_text(json.dumps({"figures": []}), encoding="utf8")
    out = tmp_path / "o.docx"
    from booklayout import cli
    cli.main(["build", "--aligned", str(tmp_path / "a.json"), "--metadata", str(tmp_path / "m.json"),
              "--figures", str(tmp_path), "--out", str(out)])
    out = out.with_name("o.DRAFT.docx")  # no acceptance -> draft-labelled
    assert out.exists()
    d = docx.Document(str(out))
    texts = [p.text for p in d.paragraphs if p.text.strip()]
    assert texts == ["甲", "乙"]
    assert d.paragraphs[[p.text for p in d.paragraphs].index("乙")].paragraph_format.page_break_before


def test_cjk_punct_year_parens_fullwidth_before_cjk():
    from booklayout.builder import cjk_punct
    assert cjk_punct("Pettibone(1953)指出") == "Pettibone（1953）指出"
    assert cjk_punct("腹部(Narchi, 1969)。") == "腹部（Narchi, 1969）。"


def test_markdown_chunks_bold_not_italic():
    from booklayout.builder import _markdown_chunks
    assert _markdown_chunks("**形态** — 体 *Palmyra* 属") == [
        ("形态", False, True), (" — 体 ", False, False), ("Palmyra", True, False), (" 属", False, False)]
