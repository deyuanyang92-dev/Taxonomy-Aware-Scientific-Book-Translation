from __future__ import annotations

import base64
import json
from pathlib import Path

import fitz
import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn

from booklayout.builder import (
    BookMeta,
    BookPaths,
    apply_index_fixes,
    index_fixes,
    build,
    build_genus_set,
    index_entry_key,
    caption,
    key_para,
    key_signature,
    make_page_map,
    match_text,
    page_break,
    para,
    remap_refs,
    setup,
)
from booklayout.cli import (
    _key_breaks_from_lines,
    _key_layout_problems,
    _pdf_layout_problems,
    _reference_problems,
    _report,
    _spacing_problems,
    _text_qa,
    main,
)
from booklayout.keyalign import align_page, key_groups, page_text, source_anchor
from booklayout.normalize import (
    apply_block_edits,
    apply_page_patch,
    backfill_source,
    normalize_aligned,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def make_book(tmp_path: Path) -> tuple[Path, Path, BookMeta]:
    figs = tmp_path / "figures"
    figs.mkdir()
    (figs / "fig.png").write_bytes(PNG)
    (figs / "source_figure_audit.json").write_text(
        json.dumps({"figures": [{"source_pdf_page": 1, "source_label": "1", "crop": "fig.png"}]}),
        encoding="utf-8",
    )
    aligned = tmp_path / "aligned.json"
    aligned.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "chapter": "Introduction",
                        "kind": "chapter",
                        "blocks": [
                            {"role": "heading", "level": 1, "translation": "Introduction", "y0": 10},
                            {"role": "body", "translation": "Test body text for the book layout.", "y0": 100},
                            {"role": "caption", "translation": "Fig. 1. Test figure.", "y0": 200},
                        ],
                    },
                    {
                        "page": 2,
                        "chapter": "Family Testidae",
                        "kind": "chapter",
                        "blocks": [
                            {"role": "heading", "level": 1, "translation": "Family Testidae", "y0": 10},
                            {"role": "body", "translation": "Second chapter body.", "y0": 100},
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    meta = BookMeta(
        title="Test Book",
        subtitle="A Layout Fixture",
        chapter_titles={"Introduction": "Introduction", "Family Testidae": "Family Testidae"},
        body_start_page=1,
        folio_offset=0,
        include_front_matter=False,
    )
    return aligned, figs, meta


def test_build_creates_docx_with_contents_and_figure(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    out = tmp_path / "book.docx"
    data = build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    assert data["pages"][0]["chapter"] == "Introduction"
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "Test Book" in text
    assert "CONTENTS" in text
    assert "Test body text for the book layout." in text
    assert "Fig. 1. Test figure." in text
    assert "Second chapter body." in text
    assert len(Document(out).inline_shapes) == 1


def test_reference_check_flags_wrong_index_page(tmp_path: Path) -> None:
    """Index numbers that land on a page without the name must fail QA."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "CONTENTS")
    doc[0].insert_text((72, 100), "Family Testidae..........2")
    doc.new_page().insert_text((72, 72), "Family Testidae")
    index = doc.new_page()
    index.insert_text((72, 72), "ALPHABETICAL INDEX OF TAXONOMIC NAMES")
    index.insert_text((72, 100), "Testidae..........2")
    index.insert_text((72, 120), "Testoides zeta..........2")
    pdf = tmp_path / "refs.pdf"
    doc.save(pdf)
    meta = BookMeta(title="T", contents_title="CONTENTS",
                    index_title="ALPHABETICAL INDEX OF TAXONOMIC NAMES")
    report = _reference_problems(pdf, meta)
    assert report["page_refs_checked"] == 3
    assert [(item["entry"], item["ref"]) for item in report["wrong_page_refs"]] == [
        ("Testoides zeta", 2)
    ]


def test_contents_lists_index_after_later_chapters(tmp_path: Path) -> None:
    """The index is printed last, so its contents line must also come last."""
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"] = [
        {"page": 1, "chapter": "Chapter A", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Chapter A"},
            {"role": "body", "translation": "Chapter A body text."},
        ]},
        {"page": 2, "chapter": "Alphabetical index of taxonomic names", "kind": "index", "blocks": [
            {"role": "index", "translation": "Alpha 1"},
        ]},
        {"page": 3, "chapter": "Annex", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Annex"},
            {"role": "body", "translation": "Annex body text."},
        ]},
    ]
    aligned.write_text(json.dumps(data), encoding="utf-8")
    meta.index_chapter = "Alphabetical index of taxonomic names"
    meta.chapter_titles = {}
    out = tmp_path / "contents_order.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    toc = [p.text.split("\t")[0] for p in Document(out).paragraphs if "\t" in p.text]
    assert toc.index("Annex") < toc.index("Alphabetical index of taxonomic names")


def test_chapter_heading_follows_previous_chapter_tail(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][1]["blocks"] = [
        {"role": "body", "translation": "Tail of the introduction.", "y0": 10},
        {"role": "heading", "level": 1, "translation": "Family Testidae", "y0": 60},
        {"role": "body", "translation": "Second chapter body.", "y0": 100},
    ]
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "book.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    texts = [p.text for p in Document(out).paragraphs]
    tail = texts.index("Tail of the introduction.")
    heading_indexes = [i for i, text in enumerate(texts) if text.strip() == "Family Testidae"]
    assert heading_indexes and tail < heading_indexes[-1]
    assert tail < texts.index("Second chapter body.")


def test_build_accepts_string_heading_level(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][0]["level"] = "1"
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "book.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    assert out.exists()


def test_build_does_not_indent_lowercase_continuation(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][1]["blocks"][1]["translation"] = "second chapter body continues."
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "book.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    doc = Document(out)
    par = next(p for p in doc.paragraphs if p.text.startswith("second chapter body"))
    assert not par.paragraph_format.first_line_indent


def test_make_page_map_ignores_chapter_titles_in_front_matter(tmp_path: Path) -> None:
    data = {"pages": [
        {"page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Introduction"},
        ]},
        {"page": 2, "chapter": "Family Testidae", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Family Testidae"},
            {"role": "body", "translation": "Second chapter body text long enough to match a page."},
        ]},
    ]}
    meta = BookMeta(title="T", body_start_page=1, folio_offset=0, include_front_matter=False)
    pdf = tmp_path / "book.pdf"
    doc = fitz.open()
    front = doc.new_page()
    front.insert_text((72, 72), "LIST OF AUTHORS AND TEXTS")
    front.insert_text((72, 100), "Family Testidae")
    front.insert_text((72, 120), "Introduction")
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "Front matter filler")
    doc.new_page().insert_text((72, 72), "Introduction")
    doc.new_page().insert_text((72, 72), "FAMILY TESTIDAE")
    doc.new_page().insert_text((72, 200), "Second chapter body text long enough to match a page.")
    doc.save(pdf)
    page_map = make_page_map(pdf, data, meta)
    assert page_map["1"] == 5
    assert page_map["2"] == 6


def test_make_page_map_maps_printed_pages_to_pdf_pages(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    pdf = tmp_path / "book.pdf"
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((72, 72), "Test body text for the book layout.")
    second = doc.new_page()
    second.insert_text((72, 72), "Second chapter body.")
    doc.save(pdf)
    page_map = make_page_map(pdf, data, meta)
    assert page_map["1"] == 1
    assert page_map["2"] == 2


def test_cli_build_writes_report(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(meta.__dict__), encoding="utf-8")
    out = tmp_path / "cli.docx"
    report = tmp_path / "report.json"
    assert main([
        "build",
        "--aligned", str(aligned),
        "--figures", str(figs),
        "--metadata", str(metadata),
        "--out", str(out),
        "--report", str(report),
    ]) == 0
    out = out.with_name("cli.DRAFT.docx")  # no acceptance given -> draft-labelled
    assert out.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["blocks"] == 5
    assert payload["figures"] == 1
    assert payload["chapters"] == ["Introduction", "Family Testidae"]


def test_cli_build_rejects_figure_dir_without_audit(tmp_path: Path) -> None:
    """A wrong --figures path must not silently produce a book with no figures."""
    aligned, figs, meta = make_book(tmp_path)
    (figs / "source_figure_audit.json").unlink()
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(meta.__dict__), encoding="utf-8")
    with pytest.raises(SystemExit, match="source_figure_audit.json"):
        main([
            "build",
            "--aligned", str(aligned),
            "--figures", str(figs),
            "--metadata", str(metadata),
            "--out", str(tmp_path / "bad.docx"),
        ])


def test_cli_check_passes_complete_package(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    report = tmp_path / "check.json"
    assert main([
        "check",
        "--aligned", str(aligned),
        "--figures", str(figs),
        "--out", str(report),
    ]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["ok"] is True


def test_check_ignores_language_neutral_empty_blocks(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"].insert(
        0,
        {
            "page": 0,
            "chapter": "Front matter",
            "kind": "front",
            "blocks": [
                {"role": "body", "text": "Introducción . . . . . . . . 11", "translation": ""},
            ],
        },
    )
    data["pages"].append(
        {
            "page": 3,
            "chapter": "Appendix 1",
            "kind": "appendix",
            "blocks": [
                {"role": "entry", "text": "Genus Example Author, 1900", "translation": ""},
            ],
        }
    )
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["untranslated_blocks"] == 2
    assert payload["untranslated_content_blocks"] == 0


def test_check_flags_missing_front_matter_prose(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"].insert(
        0,
        {
            "page": 0,
            "chapter": "Front matter",
            "kind": "front",
            "blocks": [
                {"role": "body", "text": "Este volumen revisa la fauna marina.", "translation": ""},
            ],
        },
    )
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["untranslated_content_blocks"] == 1


def test_check_flags_empty_caption_on_rendered_page(tmp_path: Path) -> None:
    # The builder drops an untranslated caption and prints the figure bare,
    # so an empty caption in the printed part of the book is missing content.
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][2]["translation"] = ""
    data["pages"][0]["blocks"][2]["text"] = "Fig. 1. Cuerpo del gusano en vista lateral."
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["untranslated_content_blocks"] == 1


def test_check_ignores_empty_caption_on_skipped_page(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][2]["translation"] = ""
    data["pages"][0]["blocks"][2]["text"] = "Fig. 1. Cuerpo del gusano en vista lateral."
    aligned.write_text(json.dumps(data), encoding="utf-8")
    meta.body_start_page = 2
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({"title": "Test", "body_start_page": 2}), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--metadata", str(meta_path), "--out", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["untranslated_content_blocks"] == 0


def test_check_flags_spanish_field_label_citation(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][1]["blocks"].append(
        {"role": "citation", "text": "ESPECIE TIPO: Trochochaeta sarsi Levinsen, 1884", "translation": ""}
    )
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 1
    assert json.loads(report.read_text(encoding="utf-8"))["untranslated_content_blocks"] == 1


def test_check_flags_page_that_lost_source_text(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    source = tmp_path / "source_structure.json"
    long_text = " ".join(f"palabra{i}" for i in range(60))
    source.write_text(json.dumps({"pages": [
        {"page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "body", "text": long_text},
        ]},
    ]}), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--source", str(source), "--out", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["coverage_problems"]


def test_check_accepts_page_with_full_translation(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][1]["translation"] = " ".join(f"word{i}" for i in range(20))
    aligned.write_text(json.dumps(data), encoding="utf-8")
    source = tmp_path / "source_structure.json"
    source.write_text(json.dumps({"pages": [
        {"page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "body", "text": " ".join(f"palabra{i}" for i in range(40))},
        ]},
    ]}), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--source", str(source), "--out", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["coverage_problems"] == []


def test_check_ignores_words_moved_by_cross_page_merge(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    page = data["pages"][0]
    page["blocks"][1]["translation"] = " ".join(f"word{i}" for i in range(20))
    page["_merged_first_block_source_words"] = 50
    page["_merged_first_block_into"] = 1
    aligned.write_text(json.dumps(data), encoding="utf-8")
    source = tmp_path / "source_structure.json"
    source.write_text(json.dumps({"pages": [
        {"page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "body", "text": " ".join(f"palabra{i}" for i in range(60))},
        ]},
    ]}), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--source", str(source), "--out", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["coverage_problems"] == []


def _eff(par, attr):
    """Paragraph-format value, falling back through the named style chain (T3: formatting lives in styles)."""
    v = getattr(par.paragraph_format, attr) if attr != "alignment" else par.alignment
    st = par.style
    while v is None and st is not None:
        v = getattr(st.paragraph_format, attr) if attr != "alignment" else st.paragraph_format.alignment
        st = st.base_style
    return v


def _eff_size(run, par):
    v, st = run.font.size, par.style
    while v is None and st is not None:
        v, st = st.font.size, st.base_style
    return v


def test_caption_does_not_split_across_pages() -> None:
    doc = Document()
    p = caption(doc, "Fig. 1. A long caption that must stay in one piece.", None)
    assert _eff(p, "keep_together") is True
    assert _eff(p, "alignment") == WD_ALIGN_PARAGRAPH.LEFT
    assert p._p.pPr.find(qn("w:suppressAutoHyphens")) is not None


def test_caption_roman_with_italic_names() -> None:
    # 出版惯例：图注正体，学名斜体（用户 2026-11-17 定；原书整条图注斜体太丑）。
    doc = Document()
    p = caption(doc, "Fig. 2. Anterior region of *Nereis pelagica* in dorsal view.",
                {"Nereis"})
    runs = [(r.text, bool(r.italic)) for r in p.runs if r.text.strip()]
    assert ("Nereis pelagica", True) in runs
    assert any("Anterior" in t and not it for t, it in runs)
    assert any("dorsal view" in t and not it for t, it in runs)


def test_caption_strips_trailing_panel_letters(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][2]["translation"] = "Fig. 1. Test figure. A B"
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "panels.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "Fig. 1. Test figure." in text
    assert "Test figure. A B" not in text


def test_check_rejects_non_figure_caption(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][2]["translation"] = "Especie Tipo: Example"
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 1
    assert json.loads(report.read_text(encoding="utf-8"))["bad_captions"]


def test_page_map_ignores_repeated_appendix_body(tmp_path: Path) -> None:
    """A body snippet repeated in an appendix must not move a chapter page."""
    aligned, _figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"].append(
        {
            "page": 3,
            "chapter": "Family Testidae",
            "kind": "chapter",
            "blocks": [
                {"role": "body", "translation": "Second chapter body continued.", "y0": 100},
            ],
        }
    )
    pdf = tmp_path / "appendix.pdf"
    doc = fitz.open()
    contents = doc.new_page()
    contents.insert_text((72, 72), "CONTENTS")
    contents.insert_text((72, 92), "Family Testidae 2")
    first = doc.new_page()
    first.insert_text((72, 72), "Family Testidae")
    first.insert_text((72, 92), "Second chapter body.")
    second = doc.new_page()
    second.insert_text((72, 72), "Second chapter body continued.")
    appendix = doc.new_page()
    appendix.insert_text((72, 72), "Second chapter body continued.")
    doc.save(pdf)
    page_map = make_page_map(pdf, data, meta)
    assert page_map["3"] == 3


def test_index_ref_uses_block_page_when_source_page_straddles(tmp_path: Path) -> None:
    """An index entry must point at the page where its name is printed."""
    first = "First block text long enough to match the opening page."
    second = "Second block text long enough to continue on the next page."
    data = {"pages": [{
        "page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Introduction", "y0": 10},
            {"role": "body", "translation": first, "y0": 40, "block_id": "p1_b1"},
            {"role": "body", "translation": second, "y0": 60, "block_id": "p1_b2"},
        ],
    }]}
    meta = BookMeta(title="T", body_start_page=1, folio_offset=0, include_front_matter=False)
    pdf = tmp_path / "straddle.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Introduction")
    page.insert_text((72, 100), first)
    doc.new_page().insert_text((72, 72), second)
    doc.save(pdf)
    page_map = make_page_map(pdf, data, meta)
    assert page_map["1"] == 1
    assert page_map["block:p1_b2"] == 2
    printed_pages = {1: data["pages"][0]}
    assert remap_refs("1", page_map, "Second block", printed_pages) == "2"
    assert remap_refs("1", page_map, "Missing name", printed_pages) == "1"


def test_index_entry_fixes_correct_declared_source_errata() -> None:
    """A metadata fix changes the printed entry and drives its page lookup."""
    meta = BookMeta(index_entry_fixes=[("arietina, Apomatus", "arietina, Ditrupa")])
    assert apply_index_fixes("arietina, Apomatus  264, 431", meta) == (
        "arietina, Ditrupa  264, 431", True)
    assert apply_index_fixes("ambigua, Circeis  300", meta) == (
        "ambigua, Circeis  300", False)
    # A third element carries the evidence printed in the correction list.
    meta = BookMeta(index_entry_fixes=[
        ("arietina, Apomatus", "arietina, Ditrupa", "pp. 264, 431")])
    assert list(index_fixes(meta)) == [
        ("arietina, Apomatus", "arietina, Ditrupa", "pp. 264, 431")]
    # Two source variants can become one entry after the fix; leaders and
    # spacing must not keep the duplicate alive.
    assert index_entry_key("(saint-hilaire)..... 526") == index_entry_key("(saint-hilaire) 526")
    assert index_entry_key("(saint-hilaire) . . . . . 526") == index_entry_key("(saint-hilaire)...... 526")


def test_index_ref_prefers_heading_over_earlier_citation() -> None:
    """A TYPE SPECIES citation must not pull the index one page too early."""
    page = {"blocks": [
        {"block_id": "p1_cite", "role": "citation", "y0": 10,
         "translation": "Pseudopolydora Czerniavsky, 1881. Type species: Polydora antennata."},
        {"block_id": "p1_head", "role": "heading", "y0": 60,
         "translation": "Pseudopolydora antennata (Claparede, 1869) (fig. 102)"},
    ]}
    page_map = {"1": 5, "block:p1_cite": 5, "block:p1_head": 6}
    assert remap_refs("1", page_map, "antennata, Pseudopolydora", {1: page}) == "6"


def test_remap_folds_ligature_in_block_text() -> None:
    """An aligned entry can carry ﬂ; the index must still find its block."""
    page = {"blocks": [{
        "block_id": "p1_b1", "role": "entry", "y0": 10,
        "translation": "Nerine ﬂoroensis Saint-Joseph, 1894. Ann. Sci.",
    }]}
    page_map = {"1": 5, "block:p1_b1": 6}
    assert remap_refs("1", page_map, "(floroensis)", {1: page}) == "6"


def test_remap_joins_hyphenated_index_names() -> None:
    """A hyphenated name is one token; splitting it hid the block page."""
    page_map = {"1": 5, "block:p1_b1": 6}
    printed_pages = {1: {"blocks": [{
        "block_id": "p1_b1", "y0": 10,
        "translation": "Lumbricus saint-hilaire Delle Chiaje, 1828. Mem. Stor. Notomia.",
    }]}}
    assert remap_refs("1", page_map, "(saint-hilaire)", printed_pages) == "6"


def test_match_text_folds_ligatures_and_italic_markup() -> None:
    """Ligatures and *name* markup must not hide a page-map match."""
    assert match_text("Nerine ﬂoroensis") == "nerine floroensis"
    assert match_text("*Clymene modesta* Quatrefages") == "clymene modesta quatrefages"
    assert match_text("saint-\n   hilaire") == "sainthilaire"


def test_page_map_matches_dense_appendix_by_page_text(tmp_path: Path) -> None:
    """Appendix PDF pages must not be assumed one-for-one with source pages."""
    data = {"pages": [
        {"page": 1, "chapter": "Introduction", "kind": "chapter", "blocks": [
            {"role": "heading", "level": 1, "translation": "Introduction"},
            {"role": "body", "translation": "Introductory body text long enough to match its page."},
        ]},
    ]}
    entries = [
        "Alpha beta Author, 1900. Journal of Tests 1: 11",
        "Gamma delta Author, 1901. Journal of Tests 2: 22",
        "Epsilon zeta Author, 1902. Journal of Tests 3: 33",
        "Eta theta Author, 1903. Journal of Tests 4: 44",
    ]
    for offset, entry in enumerate(entries):
        data["pages"].append({
            "page": 2 + offset,
            "chapter": "Appendix 1. Nomenclature",
            "kind": "appendix",
            "blocks": [{"role": "entry", "translation": entry}],
        })
    meta = BookMeta(title="T", body_start_page=1, folio_offset=0, include_front_matter=False)
    pdf = tmp_path / "dense_appendix.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Introductory body text long enough to match its page.")
    appendix = doc.new_page()
    appendix.insert_text((72, 72), "APPENDIX 1. NOMENCLATURE")
    appendix.insert_text((72, 100), entries[0])
    doc.new_page().insert_text((72, 72), entries[1])
    last = doc.new_page()
    last.insert_text((72, 72), entries[2])
    last.insert_text((72, 100), entries[3])
    doc.save(pdf)
    page_map = make_page_map(pdf, data, meta)
    assert page_map["2"] == 2
    assert page_map["3"] == 3
    assert page_map["4"] == 4
    # The fourth source page is typeset on the same PDF page as the third.
    assert page_map["5"] == 4


def test_translator_preface_names_translator_and_method(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    meta.translator = "Yang Deyuan"
    out = tmp_path / "preface.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    paragraphs = [p.text for p in Document(out).paragraphs]
    text = "\n".join(paragraphs)
    assert "TRANSLATOR'S PREFACE" in paragraphs
    assert "Google Translate" in text
    assert "DeepSeek Flash" in text
    assert "Translated by Yang Deyuan." in paragraphs


def test_translator_preface_chinese_name_gets_eastasia_hint(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    meta.translator = "Yang Deyuan (杨德援)"
    out = tmp_path / "preface.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    hints = []
    for paragraph in Document(out).paragraphs:
        if "杨德援" not in paragraph.text:
            continue
        for run in paragraph.runs:
            if "杨德援" in run.text:
                fonts = run._element.rPr.rFonts
                hints.append(fonts.get(qn("w:hint")))
    assert hints and all(hint == "eastAsia" for hint in hints)


def test_caption_has_space_above_it() -> None:
    doc = Document()
    p = caption(doc, "Fig. 1. A caption.", None)
    # The Spanish original keeps at least 10.88 pt between figure and caption.
    assert _eff(p, "space_before").pt >= 10


def test_page_break_does_not_add_a_second_break() -> None:
    doc = Document()
    doc.add_paragraph("Contents")
    page_break(doc)
    page_break(doc)
    breaks = [
        br
        for p in doc.paragraphs
        for br in p._element.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br"
        )
        if br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page"
    ]
    assert len(breaks) == 1


def test_inline_acknowledgments_become_a_heading(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"].insert(
        1,
        {"role": "body", "translation": "Acknowledgments We thank the museum.", "y0": 90},
    )
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "ack.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    paragraphs = [p.text for p in Document(out).paragraphs]
    assert "ACKNOWLEDGMENTS" in paragraphs
    assert not any(p.startswith("Acknowledgments We thank") for p in paragraphs)


def test_long_heading_is_rendered_as_a_note(tmp_path: Path) -> None:
    aligned, figs, meta = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    long_note = "This is a long boxed note " * 5
    data["pages"][0]["blocks"].append(
        {"role": "heading", "level": 1, "translation": long_note, "y0": 150}
    )
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "note.docx"
    build(out, {}, BookPaths(aligned=aligned, figures_dir=figs), meta)
    match = [p for p in Document(out).paragraphs if p.text.startswith("This is a long boxed note")]
    assert len(match) == 1
    assert _eff_size(match[0].runs[0], match[0]).pt == 9.5
    assert match[0].runs[0].bold is not True


def test_check_flags_heading_and_acknowledgment_layout(tmp_path: Path) -> None:
    aligned, figs, _ = make_book(tmp_path)
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"].extend([
        {"role": "heading", "level": 1, "translation": "A long call-out " * 8},
        {"role": "body", "translation": "Acknowledgments We thank the museum."},
    ])
    aligned.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "check.json"
    assert main(["check", "--aligned", str(aligned), "--figures", str(figs),
                 "--out", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["long_headings"]
    assert payload["inline_acknowledgments"]


def test_key_para_pulls_ellipsis_target_to_right_margin() -> None:
    """Ellipsis leaders must produce the same layout as spaced/period leaders."""
    doc = Document()
    setup(doc)
    for text in (
        "1. Gills present from setiger 1 … 2",
        "• Gills present from setiger 5, simple (with a single branchial filament) … O. farensis (p. 76)",
    ):
        key_para(doc, text, set())
    for paragraph in doc.paragraphs:
        pf = paragraph.paragraph_format
        assert _eff(paragraph, "alignment") == WD_ALIGN_PARAGRAPH.LEFT
        # Issue #35: the source book has no first-line indent in keys.
        assert not pf.first_line_indent
        assert _eff(paragraph, "left_indent").mm == pytest.approx(0.0)
        stops = list(pf.tab_stops)
        assert stops[-1].alignment == WD_TAB_ALIGNMENT.RIGHT
        assert stops[-1].position.mm == pytest.approx(134.0, abs=0.01)
        # The target is a separate run after a tab, not left inline behind "…".
        assert "\t" in [r.text for r in paragraph.runs]
        assert "…" not in paragraph.text


def test_key_para_recovers_target_without_a_leader() -> None:
    """Some translated lines end with a plain species target and no leader."""
    doc = Document()
    setup(doc)
    key_para(
        doc,
        "4. Falcigerous setae with blunt hood, without mucro (fig. 42D) .E. vittata (p. 123)",
        set(),
    )
    key_para(
        doc,
        "2. Eyes reniform. Antennae reaching the anterior margin; body brown "
        "(fig. 47A) L. collaris (p. 136)",
        set(),
    )
    first, second = doc.paragraphs
    assert first.text.replace("\u202f", " ").endswith("\tE. vittata\t(p. 123)")
    assert second.text.replace("\u202f", " ").endswith("\tL. collaris\t(p. 136)")


def test_key_para_accepts_single_dot_before_couplet_number() -> None:
    """OCR occasionally leaves one dot instead of a leader run."""
    doc = Document()
    setup(doc)
    key_para(
        doc,
        "7. Dorsal crests from setigers 6 or 7 and continuing on subsequent setigers . 8",
        set(),
    )
    paragraph = doc.paragraphs[0]
    assert paragraph.runs[-2].text == "\t"
    assert paragraph.runs[-1].text == "8"


def test_key_para_keeps_long_couplet_as_one_tabbed_line() -> None:
    """A long couplet must still end at the right tab, not inline the target."""
    doc = Document()
    setup(doc)
    left = "3. Pseudocompound hooks bi-, tri- and quadricentate " * 3
    key_para(doc, left + " ......... O. anadonae (p. 69)", set())
    paragraph = doc.paragraphs[0]
    assert _eff(paragraph, "alignment") == WD_ALIGN_PARAGRAPH.LEFT
    assert paragraph.text.replace("\u202f", " ").endswith("\tO. anadonae\t(p. 69)")


def test_key_target_is_non_breaking() -> None:
    """A target address must never split between 'L.' and 'torquata'."""
    doc = Document()
    setup(doc)
    key_para(
        doc,
        "• Body coloration uniform, posterior setigers with long cirri ......... "
        "L. torquata (p. 133)",
        set(),
    )
    paragraph = doc.paragraphs[0]
    target = "".join(paragraph.text.split("\t")[-2:])
    assert " " not in target
    assert target.replace("\u202f", " ") == "L. torquata(p. 133)"
    # The workspace zh-check gate rejects U+00A0; U+202F must not leak in.
    assert " " not in target


def test_key_para_inserts_requested_break_before_target() -> None:
    """A couplet whose leader would be very short starts a new leader line."""
    doc = Document()
    setup(doc)
    left = "3. Pseudocompound hooks bi-, tri- and quadricentate"
    right = "O. anadonae (p. 69)"
    key_para(doc, left + " ......... " + right, set(),
             {key_signature(left, right)})
    paragraph = doc.paragraphs[0]
    breaks = list(paragraph._element.iter(qn("w:br")))
    assert len(breaks) == 1
    tab_index = next(i for i, run in enumerate(paragraph.runs) if run.text == "\t")
    break_run = breaks[0].getparent()
    run_index = list(paragraph._element.iter(qn("w:r"))).index(break_run)
    assert run_index < tab_index


def test_key_layout_flags_short_leader() -> None:
    words = [
        (50, 100, 62, 112, "1.", 0, 0, 0),
        (65, 100, 150, 112, "Gills", 0, 0, 1),
        (193, 100, 195, 112, ".", 0, 0, 2),
        (197, 100, 199, 112, ".", 0, 0, 3),
        (400, 100, 470, 112, "O.", 0, 0, 4),
        (473, 100, 480, 112, "(p.", 0, 0, 5),
        (482, 100, 500, 112, "1)", 0, 0, 6),
        (50, 130, 62, 142, "2.", 1, 1, 0),
        (65, 130, 150, 142, "Gills", 1, 1, 1),
        (200, 130, 203, 142, "…", 1, 1, 2),
        (400, 130, 470, 142, "O.", 1, 1, 3),
        (473, 130, 480, 142, "(p.", 1, 1, 4),
        (482, 130, 500, 142, "2)", 1, 1, 5),
    ]
    problems = _key_layout_problems(words, width=520)
    assert any(item["reason"] == "short leader" for item in problems)


def test_pdf_layout_flags_caption_word_break(tmp_path: Path) -> None:
    pdf = tmp_path / "caption.pdf"
    doc = fitz.open()
    page = doc.new_page(width=482, height=700)
    page.insert_text((51, 80), "Fig. 17. A caption that ends with Re-", fontsize=9.5)
    page.insert_text((51, 94), "drawn from an earlier figure.", fontsize=9.5)
    doc.save(pdf)
    report = _pdf_layout_problems(pdf)
    assert report["caption_word_breaks"]


def test_pdf_layout_flags_key_target_not_flush_right(tmp_path: Path) -> None:
    pdf = tmp_path / "key.pdf"
    doc = fitz.open()
    page = doc.new_page(width=482, height=700)
    page.insert_text((51, 80), "Key to species", fontsize=10)
    page.insert_text(
        (51, 100),
        "The body line runs to the right margin so the detector has a reference edge",
        fontsize=10,
    )
    page.insert_text((51, 120), "1. Gills present from setiger 1 . . . . 2", fontsize=9.5)
    page.insert_text((51, 140), "2. Gills absent . . . . 3", fontsize=9.5)
    doc.save(pdf)
    report = _pdf_layout_problems(pdf)
    assert report["key_layout"]
    assert report["key_layout"][0]["reason"] == "target not flush right"
    assert "Gills present" in report["key_layout"][0]["line"]


def test_pdf_layout_finds_blank_pages_and_tight_captions(tmp_path: Path) -> None:
    pdf = tmp_path / "layout.pdf"
    doc = fitz.open()
    doc.new_page()
    page = doc.new_page()
    page.insert_image(fitz.Rect(50, 50, 150, 150), stream=PNG)
    page.insert_text((50, 160), "Fig. 1. Test figure.")
    doc.save(pdf)
    report = _pdf_layout_problems(pdf)
    assert report["blank_pages"] == [1]
    assert report["tight_caption_gaps"][0]["page"] == 2
    assert report["tight_caption_gaps"][0]["gap_pt"] < 10


def test_text_qa_flags_key_text_inside_body() -> None:
    data = {"pages": [{"page": 1, "blocks": [
        {"block_id": "b0", "role": "body", "text": "Cuerpo alargado.",
         "translation": "Body elongate. Key to species 1. Aciculae black ……………………… S. fragilis (p. 212)"},
        {"block_id": "b1", "role": "body", "text": "Clave de especies",
         "translation": "Key to species"},
    ]}]}
    report = _text_qa(data)
    assert [item["block_id"] for item in report["key_text_in_body"]] == ["b0"]


def test_normalize_trims_page_translation_that_duplicates_next_page() -> None:
    unique = ("Nuchal organs short and arched. " * 10
              + "The hooks have a short hood (fig. 61I), a large rounded tooth. ")
    duplicated = ("Description based on Graff (1877). The internal anatomy is known "
                  "in detail and the species is widely distributed.")
    data = {"pages": [
        {"page": 1, "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "text": "x" * 300,
             "translation": unique + duplicated + " " + "more text " * 100},
        ]},
        {"page": 2, "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "text": "y" * 100,
             "translation": duplicated},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == unique.strip()
    assert any(change["rule"] == "overflow_duplicate_tail"
               for change in report["changes"])


def test_normalize_restores_acknowledgments_heading_from_shifted_page() -> None:
    prose = ("The book is illustrated with plates of original drawings and photographs "
             "taken with the scanning electron microscope, all accompanied by explanations.")
    data = {"pages": [{"page": 11, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "heading", "translation": prose},
        {"block_id": "b1", "role": "body",
         "translation": "Acknowledgments The authors wish to thank the museum staff."},
    ]}]}
    report = normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert [b["role"] for b in blocks] == ["body", "heading", "body"]
    assert blocks[0]["translation"] == prose
    assert blocks[1]["translation"] == "Acknowledgments"
    assert blocks[2]["translation"] == "The authors wish to thank the museum staff."
    assert any(change["rule"] == "acknowledgment_heading_bleed"
               for change in report["changes"])


def test_normalize_joins_paragraph_split_by_page_break() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "translation": "The body is thin and"},
        ]},
        {"page": 2, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "translation": "elongated, with many segments.",
             "text": "alargado con muchos segmentos"},
            {"block_id": "b2", "role": "body", "translation": "Next paragraph."},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "The body is thin and elongated, with many segments."
    )
    assert [b["block_id"] for b in data["pages"][1]["blocks"]] == ["b2"]
    assert data["pages"][1]["_merged_first_block_source_words"] == 4
    assert report["changed_blocks"] == 1


def test_normalize_keeps_paragraph_break_at_page_boundary() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "translation": "The body is thin and wide."},
        ]},
        {"page": 2, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "translation": "elongate setae present."},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == "The body is thin and wide."
    assert report["changed_blocks"] == 0


def test_normalize_keeps_paragraph_split_across_chapters() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "A", "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "translation": "The body is thin and"},
        ]},
        {"page": 2, "chapter": "B", "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "translation": "elongate setae present."},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][1]["blocks"][0]["translation"] == "elongate setae present."
    assert report["changed_blocks"] == 0


def test_normalize_joins_paragraph_running_over_two_page_breaks() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "translation": "The body is thin and"},
        ]},
        {"page": 2, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "translation": "flattened, with"},
        ]},
        {"page": 3, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b2", "role": "body", "translation": "many short segments."},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "The body is thin and flattened, with many short segments."
    )
    assert data["pages"][1]["blocks"] == []
    assert data["pages"][2]["blocks"] == []
    assert report["changed_blocks"] == 2


def test_normalize_does_not_carry_merge_past_following_blocks() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "translation": "The body is thin and"},
        ]},
        {"page": 2, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "translation": "flattened. Next paragraph ends here"},
            {"block_id": "b2", "role": "body", "translation": "Another paragraph starts."},
        ]},
        {"page": 3, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "b3", "role": "body", "translation": "lower-case continuation."},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "The body is thin and flattened. Next paragraph ends here"
    )
    assert data["pages"][1]["blocks"][0]["translation"] == "Another paragraph starts."
    assert data["pages"][2]["blocks"][0]["translation"] == "lower-case continuation."
    assert report["changed_blocks"] == 1


def test_patch_blocks_edits_and_removes_by_id() -> None:
    data = {"pages": [{"page": 1, "blocks": [
        {"block_id": "b0", "role": "body", "translation": "Old"},
        {"block_id": "b1", "role": "body", "translation": "Drop me"},
        {"block_id": "b2", "role": "citation", "translation": "Keep"},
    ]}]}
    report = apply_block_edits(data, {"edits": [
        {"block_id": "b0", "translation": "New"},
        {"block_id": "b1", "remove": True},
        {"block_id": "b2", "role": "body"},
        {"block_id": "missing", "translation": "x"},
    ]})
    blocks = data["pages"][0]["blocks"]
    assert [b["block_id"] for b in blocks] == ["b0", "b2"]
    assert blocks[0]["translation"] == "New"
    assert blocks[1]["role"] == "body"
    assert report == {"applied": ["b0", "b1", "b2"], "removed": ["b1"], "missing": ["missing"], "stale": [], "invalid": [], "inserted": []}


def test_backfill_source_restores_text_and_geometry() -> None:
    data = {"pages": [{"page": 2, "blocks": [
        {"block_id": "p2_b0", "role": "body", "translation": "Translated."},
        {"block_id": "p2_ack", "role": "body", "translation": "Synthetic note."},
        {"block_id": "p2_b1", "role": "heading", "translation": "Genus"},
    ]}]}
    source = {"pages": [{"page": 2, "blocks": [
        {"block_id": "p2_b0", "role": "body", "text": "Fuente.", "x0": 1.0, "y0": 2.0},
        {"block_id": "p2_b1", "role": "heading", "level": 2, "text": "Genus"},
    ]}]}
    report = backfill_source(data, source)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["text"] == "Fuente."
    assert blocks[0]["y0"] == 2.0
    assert blocks[2]["level"] == 2
    assert report["filled_blocks"] == 2
    assert report["unmatched_blocks"] == ["p2_ack"]


def test_backfill_source_keeps_existing_translation_metadata() -> None:
    data = {"pages": [{"page": 2, "blocks": [
        {"block_id": "p2_b0", "role": "body", "translation": "Kept.", "text": "Texto."},
    ]}]}
    source = {"pages": [{"page": 2, "blocks": [
        {"block_id": "p2_b0", "role": "body", "text": "Fuente."},
    ]}]}
    report = backfill_source(data, source)
    assert data["pages"][0]["blocks"][0]["text"] == "Texto."
    assert report["filled_blocks"] == 0


def test_normalize_keeps_normal_paragraph_with_shared_description_wording() -> None:
    shared = ("present, hidden by the collar. Body segments rectangular, not "
              "biannulate; glandular pads absent.")
    translation = "Membranous tube. " * 90 + shared
    data = {"pages": [
        {"page": 1, "kind": "body", "blocks": [
            {"block_id": "b0", "role": "body", "text": "x" * len(translation),
             "translation": translation},
        ]},
        {"page": 2, "kind": "body", "blocks": [
            {"block_id": "b1", "role": "body", "text": "y" * 200,
             "translation": shared + " " + "Setae limbate. " * 20},
        ]},
    ]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == translation
    assert not any(change["rule"] == "overflow_duplicate_tail"
                   for change in report["changes"])


def test_normalize_cuts_embedded_duplicate_entry_list() -> None:
    first = ("As in the other groups of holoplanktonic polychaetes, a more thorough "
             "taxonomic study of the species is required before the family can be revised. ")
    entries = [
        "Family LOPADORRHYNCHIDAE Claparède, 1870",
        "Genus Lopadorrhynchus Grube, 1855",
        "Lopadorrhynchus appendiculatus Southern, 1909",
    ]
    body = first + " ".join(entries) + " " + "Key text follows here. " * 40
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        *[{"block_id": f"e{i}", "role": "entry", "text": "x" * 40,
           "translation": text} for i, text in enumerate(entries)],
        {"block_id": "b0", "role": "body", "text": "x" * 150,
         "translation": body},
    ]}]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][-1]["translation"] == first.strip()
    assert any(change["rule"] == "embedded_duplicate_list"
               for change in report["changes"])


def test_text_qa_skips_index_pages() -> None:
    data = {"pages": [{"page": 600, "kind": "index",
                       "chapter": "Alphabetical index of taxonomic names",
                       "blocks": [
                           {"block_id": "b0", "role": "body", "text": "",
                            "translation": "Abarenicola ........ 438"},
                       ]}]}
    report = _text_qa(data)
    assert report["key_text_in_body"] == []


def test_spacing_flags_stretched_lines_and_margin_words() -> None:
    words = [
        (50, 100, 70, 112, "alpha", 0, 0, 0),
        (73, 100, 93, 112, "beta", 0, 0, 1),
        (96, 100, 125, 112, "gamma", 0, 0, 2),
        (50, 130, 70, 142, "one", 1, 1, 0),
        (180, 130, 200, 142, "two", 1, 1, 1),
        (290, 130, 310, 142, "three", 1, 1, 2),
        (325, 130, 345, 142, "four", 1, 1, 3),
        (360, 130, 380, 142, "five", 1, 1, 4),
        (395, 130, 415, 142, "six", 1, 1, 5),
        (430, 130, 450, 142, "seven", 1, 1, 6),
        (465, 130, 490, 142, "eight", 1, 1, 7),
        (400, 160, 470, 172, "over", 2, 2, 0),
    ]
    wide, overflow = _spacing_problems(words, width=482)
    assert len(wide) == 1
    assert wide[0]["gap_pt"] == 110
    assert "over" in {item["word"] for item in overflow}


def test_normalize_moves_heading_suffix_and_citation_body() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "heading", "translation": "Foo bar Smith, 1900"},
        {"block_id": "b1", "role": "citation",
         "text": "Foo bar Smith, 1900. J. X, 1: 123",
         "translation": "Foo bar Smith, 1900. J. X, 1: 123 Body starts here."},
        {"block_id": "b2", "role": "body", "translation": "More body."},
    ]}]}
    report = normalize_aligned(data)
    rules = {c["rule"] for c in report["changes"]}
    assert "citation_body_bleed" in rules
    assert data["pages"][0]["blocks"][2]["translation"].startswith("Body starts here.")


def test_normalize_heading_citation_bleed_only_for_species_heading() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "heading", "translation": "Foo bar baz qux Smith, 1900."},
        {"block_id": "b1", "role": "citation",
         "text": "bar baz qux Smith, 1900. J. X, 1: 123",
         "translation": "J. X, 1: 123"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == "Foo"
    assert data["pages"][0]["blocks"][1]["translation"].startswith("bar baz qux Smith, 1900.")


def test_normalize_keeps_citation_without_source_text() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "citation",
         "translation": "Trochochaeta Levinsen, 1884. Vidensk. Medd. Dan. Naturhist. Foren., 45: 129"},
    ]}]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["role"] == "citation"
    assert report["changed_blocks"] == 0


def test_normalize_moves_equals_type_species_tail_to_citation() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "heading", "translation": "Genus Arabella Grube, 1850"},
        {"block_id": "b1", "role": "citation",
         "translation": "Arabella Grube, 1850. Arch. Naturgesch., 16(1): 293 "
                        "Type species: Lumbriconereis quadristriata Grube, 1840"},
        {"block_id": "b2", "role": "body",
         "translation": "= Arabella iricolor (Montagu, 1804) Prostomium conical to subpyriform."},
    ]}]}
    report = normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[1]["translation"].endswith("= Arabella iricolor (Montagu, 1804)")
    assert blocks[2]["translation"] == "Prostomium conical to subpyriform."
    assert any(c["rule"] == "type_species_equals_tail" for c in report["changes"])


def test_normalize_keeps_equals_body_without_type_species_citation() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "citation",
         "translation": "Arabella Grube, 1850. Arch. Naturgesch., 16(1): 293"},
        {"block_id": "b1", "role": "body",
         "translation": "= Arabella iricolor (Montagu, 1804) Prostomium conical."},
    ]}]}
    report = normalize_aligned(data)
    assert data["pages"][0]["blocks"][1]["translation"].startswith("= Arabella")
    assert report["changed_blocks"] == 0


def test_normalize_spanish_author_conjunction_keeps_titles() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body",
         "translation": "Audouin y Milne-Edwards (1833); Ciencias Físicas y Naturales."},
    ]}]}
    normalize_aligned(data)
    text = data["pages"][0]["blocks"][0]["translation"]
    assert "Audouin and Milne-Edwards" in text
    assert "Físicas y Naturales" in text


def test_normalize_merges_lowercase_paragraph_fragment() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body", "translation": "A sentence without end"},
        {"block_id": "b1", "role": "body", "translation": "and its continuation."},
    ]}]}
    normalize_aligned(data)
    assert len(data["pages"][0]["blocks"]) == 1
    assert data["pages"][0]["blocks"][0]["translation"].endswith("and its continuation.")


def test_apply_page_patch_preserves_geometry_and_adds_caption() -> None:
    data = {"pages": [{"page": 7, "kind": "body", "chapter": "C", "blocks": [
        {"block_id": "b0", "role": "body", "translation": "Old", "x0": 12, "y0": 34},
    ]}]}
    patch = {"pages": {"7": [
        {"block_id": "b0", "role": "body", "translation": "New"},
        {"block_id": "b1", "role": "caption", "translation": "Fig. 7. New caption."},
    ]}}
    apply_page_patch(data, patch)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["x0"] == 12 and blocks[0]["y0"] == 34
    assert blocks[0]["translation"] == "New"
    assert blocks[1]["role"] == "caption"


def test_apply_page_patch_sets_heading_level_for_new_block() -> None:
    data = {"pages": [{"page": 7, "kind": "body", "chapter": "C", "blocks": [
        {"block_id": "b0", "role": "body", "translation": "Old"},
    ]}]}
    patch = {"pages": {"7": [
        {"block_id": "b2", "role": "heading", "level": 2, "translation": "Genus Example"},
    ]}}
    apply_page_patch(data, patch)
    assert data["pages"][0]["blocks"][0]["level"] == 2


def squash(text: str) -> str:
    return " ".join(text.split())


def test_keyalign_page_text_strips_running_header() -> None:
    markdown = (
        "<!-- PDF p.5 -->\n"
        "12 IBERIAN FAUNA\n"
        "1. Alpha state ......... 2\n"
        "<!-- PDF p.6 -->\n"
        "next page"
    )
    assert page_text(markdown, 5) == "1. Alpha state ......... 2"
    assert page_text(markdown, 9) == ""


def test_keyalign_source_anchor_forms() -> None:
    page_ref = source_anchor("• With gills (p. 12)")
    assert page_ref is not None and page_ref.search("with gills (p.12)")
    year = source_anchor("Smith and Jones (1900)")
    assert year is not None and year.search("Smith and Jones (1900)")
    number = source_anchor("• With simple hooded hooks ......... 7")
    assert number is not None and number.search("hooded hooks ……… 7")
    word = source_anchor("• Genus *Eranno* bifrons")
    assert word is not None and word.search("genus Eranno bifrons.")
    assert source_anchor("") is None


def test_keyalign_groups_wrapped_key_line() -> None:
    blocks = [
        {"block_id": "b0", "role": "key", "text": "1. First state without ending"},
        {"block_id": "b1", "role": "key", "text": "continues here ......... 2"},
        {"block_id": "b2", "role": "key", "text": "• Second state ......... 3"},
    ]
    groups = key_groups(blocks)
    assert [len(group) for group in groups] == [2, 1]


def test_keyalign_recuts_drifted_couplets() -> None:
    markdown = (
        "<!-- PDF p.12 -->\n"
        "ANNELIDA, POLYCHAETA V 12\n"
        "1. Alpha state with hooded hooks ......... Alpha (p. 30) "
        "• Beta state with simple hooks ......... 2\n"
        "<!-- PDF p.13 -->\n"
    )
    page = {"page": 12, "blocks": [
        {"block_id": "b0", "role": "key",
         "text": "1. Alpha state with hooded hooks ......... Alpha (p. 30)",
         "translation": "1. Wrong text"},
        {"block_id": "b1", "role": "key",
         "text": "• Beta state with simple hooks ......... 2",
         "translation": "• Wrong text"},
    ]}
    changes, messages = align_page(page, markdown)
    assert messages == []
    updated = {c["block_id"]: c["translation"] for c in changes if "translation" in c}
    assert squash(updated["b0"]) == "1. Alpha state with hooded hooks … Alpha (p. 30)"
    assert squash(updated["b1"]) == "• Beta state with simple hooks … 2"


def test_keyalign_finds_line_whose_bullet_was_lost() -> None:
    markdown = (
        "<!-- PDF p.20 -->\n"
        "1. First state ......... Target A (p. 5) • Second state ......... 2 "
        "P. serpens (p. 362) • Branchiae absent ......... 3\n"
    )
    page = {"page": 20, "blocks": [
        {"block_id": "b0", "role": "key",
         "text": "1. First state ......... Target A (p. 5)", "translation": "x"},
        {"block_id": "b1", "role": "key",
         "text": "• Second state ......... 2", "translation": "y"},
        {"block_id": "b2", "role": "key",
         "text": "P. serpens (p. 362) • Branchiae absent ......... 3",
         "translation": "z"},
    ]}
    changes, messages = align_page(page, markdown)
    assert messages == []
    updated = {c["block_id"]: c["translation"] for c in changes if "translation" in c}
    assert squash(updated["b2"]) == "• Branchiae absent … 3"


def test_keyalign_last_footnote_stops_before_heading() -> None:
    markdown = (
        "<!-- PDF p.30 -->\n"
        "1. First state ......... 2 1 Footnote continues here. "
        "Genus *Example* Smith, 1900 Example Smith, 1900. J. Zool., 12: 34\n"
    )
    page = {"page": 30, "blocks": [
        {"block_id": "b0", "role": "key", "text": "1. First state ......... 2",
         "translation": "1. First state … 2"},
        {"block_id": "b1", "role": "key", "text": "1 Footnote begins with words",
         "translation": "1 old footnote"},
        {"block_id": "b2", "role": "heading", "translation": "Genus *Example* Smith, 1900"},
        {"block_id": "b3", "role": "citation",
         "translation": "Example Smith, 1900. J. Zool., 12: 34"},
    ]}
    changes, messages = align_page(page, markdown)
    assert messages == []
    by_id = {c["block_id"]: c for c in changes}
    assert by_id["b1"]["translation"] == "1 Footnote continues here."
    assert by_id["b1"]["role"] == "note"
    assert "b2" not in by_id and "b3" not in by_id


def test_normalize_rebuilds_structural_heading_from_source() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "heading", "text": "Familia EUNICIDAE",
         "translation": "Familia EUNICIDAE ......... Body text of next paragraph"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == "Family EUNICIDAE"


def test_normalize_rebuilds_genus_entry_from_source() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Género Acromegalomma Gil and Nishi, 2017",
         "translation": "Wrong paragraph that belongs to the next block"},
    ]}]}
    normalize_aligned(data)
    text = data["pages"][0]["blocks"][0]["translation"]
    assert text.startswith("Genus *Acromegalomma* Gil and Nishi, 2017")


def test_normalize_rebuilds_citation_from_source_when_leader_contaminated() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "citation",
         "text": "Abyssoninoe Orensanz, 1990. Antarct. Res. Ser., 52: 76",
         "translation": "Abyssoninoe Orensanz, 1990 ......... Genus next"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "Abyssoninoe Orensanz, 1990. Antarct. Res. Ser., 52: 76"
    )


def test_normalize_drops_previous_target_from_key_line() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "key",
         "translation": "Lumbrineriopsis (p. 185) • With simple hooded hooks ......... 2"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"].startswith("• With simple hooded hooks")


def test_normalize_strips_leading_punctuation_after_page_break() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body", "translation": ". Next sentence starts here."},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == "Next sentence starts here."


def test_text_qa_flags_mispaired_function_word_from_page_break() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body",
         "translation": "Prostomium conical, ending posteriorly in with a short pointed end."},
    ]}]}
    report = _text_qa(data)
    assert report["function_word_pairs"][0]["pair"] == "in with"
    assert report["duplicate_paragraphs"] == []


def test_normalize_repairs_function_word_duplicated_by_page_break() -> None:
    data = {"pages": [{"page": 1, "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body",
         "translation": "Prostomium conical, ending posteriorly in with a short pointed end."},
        {"block_id": "b1", "role": "body",
         "translation": "Recent studies indicate that in in reality these are bundles."},
    ]}]}
    report = normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["translation"].endswith("ending posteriorly with a short pointed end.")
    assert "that in reality these" in blocks[1]["translation"]
    assert sum(c["rule"] == "function_word_join" for c in report["changes"]) == 2


def test_normalize_restores_heading_authority_from_source() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "heading",
         "text": "Acromegalomma lanigerum (Grube, 1846) (fig. 6)",
         "translation": "Acromegalomma lanigerum"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "Acromegalomma lanigerum (Grube, 1846) (fig. 6)"
    )


def test_normalize_merges_heading_split_over_two_lines() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "heading",
         "text": "APÉNDICE 1. NOMENCLATURA: LISTA DE SINÓNIMOS",
         "translation": "APPENDIX 1. NOMENCLATURE: LIST OF SYNONYMS"},
        {"block_id": "b1", "role": "heading", "text": "Y COMBINACIONES",
         "translation": "AND COMBINATIONS"},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert [b["block_id"] for b in blocks] == ["b0"]
    assert blocks[0]["translation"].endswith("AND COMBINATIONS")


def test_normalize_strips_next_heading_from_entry_tail() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Caobangiidae Jones, 1974. Smithson. Contrib. Zool., 175: 31",
         "translation": "Caobangiidae Jones, 1974. Smithson. Contrib. Zool., 175: 31 "
                        "Genus Acromegalomma Gil and Nishi, 2017"},
        {"block_id": "b1", "role": "heading",
         "text": "Género Acromegalomma Gil y Nishi, 2017",
         "translation": "Genus Acromegalomma Gil and Nishi, 2017"},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"].endswith("175: 31")


def test_normalize_fills_and_joins_appendix_entries() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Nereis tubicola O.F. Müller, 1776. Zool. Dan. Prodromus: 217",
         "translation": "*Nereis tubicola* O.F. Müller, 1776. Zool. Dan. Prodromus: 217"},
        {"block_id": "b1", "role": "entry",
         "text": "Onuphis filicornis Delle Chiaje, 1841. Descr. Notomia, 3: 94",
         "translation": ""},
        {"block_id": "b2", "role": "entry",
         "text": "(non Audouin y Milne-Edwards, 1833)",
         "translation": ""},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert len(blocks) == 2
    assert blocks[1]["translation"].startswith("*Onuphis filicornis*")
    assert blocks[1]["translation"].endswith("(non Audouin and Milne-Edwards, 1833)")


def test_normalize_translates_appendix_status_terms() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Alciopa vittata Hering, 1892. Sitz.ber., 101(8): 747",
         "translation": "*Alciopa vittata* Hering, 1892. Sitz.ber., 101(8): 747 "
                        "(grafía posterior incorrecta)"},
        {"block_id": "b1", "role": "entry",
         "text": "Johnstonia Quatrefages, 1866. Ann. Mag. Nat. Hist., 17(97): 21",
         "translation": "Johnstonia Quatrefages, 1866. Ann. Mag. Nat. Hist., 17(97): 21 "
                        "(colocado en la Lista Oficial de Nombres de Nivel Género, "
                        "ICZN. Opinion 1807, 1995)"},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["translation"].endswith("(incorrect subsequent spelling)")
    assert "placed on the Official List of Names at Genus Level" in blocks[1]["translation"]


def test_text_qa_flags_untranslated_appendix_status_phrase() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "translation": "*Alciopa vittata* Hering, 1892 (grafía posterior incorrecta)"},
    ]}]}
    report = _text_qa(data)
    assert report["spanish_residue"][0]["phrase"] == "grafía posterior incorrecta"


def test_text_qa_flags_entry_that_loses_a_source_year() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Labrorostratus Saint-Joseph, 1885. C.R. Hebd. Séances Acad. Sci., 101: 1510",
         "translation": "Labrorostratus Saint-Joseph, 1888"},
    ]}]}
    report = _text_qa(data)
    assert report["entry_year_missing"][0]["missing"] == ["1885"]


def test_normalize_strips_shifted_page_tail_from_appendix_entry() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Maldane glebifex Grube, 1860. Arch. Naturgesch., 26(1): 92",
         "translation": "Maldane glebifex Grube, 1860"},
        {"block_id": "b1", "role": "entry",
         "text": "Maldane glebifex var. transversi-maculata Arwidsson, 1912. Zool. Jahrb., Suppl., 15(1): 430",
         "translation": "Maldane glebifex Grube, 1860. Arch. Naturgesch., 26(1): 92 "
                        "Maldane glebifex var. transversi-maculata Arwidsson, 1912. "
                        "Zool. Jahrb., Suppl., 15(1): 430"},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[1]["translation"].startswith(
        "*Maldane glebifex* var. transversi-maculata")
    assert ": 92" not in blocks[1]["translation"]


def test_normalize_drops_next_entry_bleed_from_previous_entry() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Maldane biceps (M. Sars): Malmgren, 1865. Öfvers. K. Vetensk.-Akad. Förh., 22(2): 188",
         "translation": "*Maldane biceps* (M. Sars): Malmgren, 1865. "
                        "Öfvers. K. Vetensk.-Akad. Förh., 22(2): 188 ? Maldane consobrina Mar"},
        {"block_id": "b1", "role": "entry",
         "text": "? Maldane consobrina Marion, 1876. Rev. Sci. Nat. (Montp.), [1875], 4: 312",
         "translation": ""},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["translation"].endswith("22(2): 188")
    assert blocks[1]["translation"].startswith("? *Maldane consobrina*")


def test_report_counts_empty_appendix_entries(tmp_path: Path) -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "chapter": "Appendix 1", "blocks": [
        {"block_id": "b0", "role": "entry", "text": "Nereis tubicola Müller, 1776", "translation": ""},
    ]}]}
    report = _report(data, tmp_path)
    assert report["empty_appendix_entries"] == ["b0"]


def test_normalize_drops_wrapped_tail_already_inside_previous_entry() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Nereis coccinea Renier, 1804. Tavola Alf. Conchigl. Adriat.: xix (no publicado, obra",
         "translation": "Nereis coccinea Renier, 1804. Tavola Alf. Conchigl. Adriat.: xix "
                        "(unpublished, work suppressed by ICZN. Opinion 316, 1954 and Opinion 427, 1956)"},
        {"block_id": "b1", "role": "entry",
         "text": "suprimida ICZN. Opinion 316, 1954 y Opinion 427, 1956)",
         "translation": ""},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert len(blocks) == 1
    assert "suprimida" not in blocks[0]["translation"]


def test_normalize_rebuilds_stale_appendix_entry_from_source() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Nereis phasma Dalyell, 1853. Powers Creat. Disp. Creat., 2: 260",
         "translation": "reat. Disp. Creat., 2: 260"},
        {"block_id": "b1", "role": "entry",
         "text": "Aonidella Maciolek, 1983. Syst. Atl. Spionidae: 400 (no disponible).",
         "translation": "Aonidella Maciolek, 1989"},
        {"block_id": "b2", "role": "entry",
         "text": "Aonidella Maciolek, 1989. En: López-Jamar, Bol. Inst. Esp. Oceanogr., 5(2): 107",
         "translation": "Aonidella Maciolek, 1983. Syst. Atl. Spionidae: 400 (unavailable). "
                        "Aonidella Maciolek, 1989. In: López-Jamar, Bol. Inst. Esp. Oceanogr., 5(2): 107"},
    ]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert blocks[0]["translation"] == "*Nereis phasma* Dalyell, 1853. Powers Creat. Disp. Creat., 2: 260"
    assert blocks[1]["translation"].startswith("*Aonidella* Maciolek, 1983.")
    assert blocks[2]["translation"].startswith("*Aonidella* Maciolek, 1989. In:")


def test_normalize_keeps_doubt_mark_upright_in_entry() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "? Nereis phasma Dalyell, 1853. Powers Creat. Disp. Creat., 2: 260",
         "translation": ""},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"].startswith("? *Nereis phasma*")


def test_source_convert_keeps_status_phrase_before_rank_words() -> None:
    data = {"pages": [{"page": 1, "kind": "appendix", "blocks": [
        {"block_id": "b0", "role": "entry",
         "text": "Oficial de Nombres de Nivel Género, ICZN. Opinion 2324, 2013)",
         "translation": ""},
    ]}]}
    normalize_aligned(data)
    assert data["pages"][0]["blocks"][0]["translation"] == (
        "Official Index of Names at Genus Level, ICZN. Opinion 2324, 2013)"
    )


def test_key_para_splits_two_couplets_joined_in_one_block() -> None:
    """Upstream line joining must not glue target 5 to the next couplet."""
    doc = Document()
    setup(doc)
    key_para(
        doc,
        "• Collar of the anterior peristomial ring absent, replaced by a "
        "ventral lobe  … 5 3. Collar completely surrounding the anterior end, "
        "without a mediodorsal incision  … Pseudofabriciola (p. 226)",
        set(),
    )
    first, second = doc.paragraphs
    assert first.runs[-1].text == "5"
    assert first.runs[-2].text == "\t"
    assert second.text.replace("\u202f", " ").endswith("\tPseudofabriciola\t(p. 226)")
    assert second.text.rsplit("\t", 1)[1].replace(chr(0x202f), " ") == "(p. 226)"


def test_caption_italicises_bare_genus_but_not_sp() -> None:
    # 「Cenogenus sp.」：属名斜体，sp. 正体（分类学惯例）。
    doc = Document()
    p = caption(doc, "Fig. 39. Anterior region of Cenogenus sp. in lateral view.",
                {"Cenogenus"})
    runs = [(r.text, bool(r.italic)) for r in p.runs if r.text.strip()]
    assert ("Cenogenus", True) in runs
    assert any("sp." in t and not it for t, it in runs)


def test_caption_italicises_genus_before_author() -> None:
    # 「Apomatus Philippi, 1844」：属名斜体，作者名正体。
    doc = Document()
    p = caption(doc, "Fig. 82. Operculum of Apomatus Philippi, 1844.", {"Apomatus"})
    runs = [(r.text, bool(r.italic)) for r in p.runs if r.text.strip()]
    assert ("Apomatus", True) in runs
    assert any("Philippi" in t and not it for t, it in runs)


def test_body_genus_followed_by_english_word_italicises_genus_only() -> None:
    # 「Lopadorrhynchus comprises the」曾整段斜体：英语词不是种加词。
    doc = Document()
    p = para(doc, "So that Lopadorrhynchus comprises the subgenera.",
             genera={"Lopadorrhynchus"})
    runs = [(r.text, bool(r.italic)) for r in p.runs if r.text.strip()]
    assert ("Lopadorrhynchus", True) in runs
    assert any("comprises" in t and not it for t, it in runs)


def test_genus_set_skips_english_second_word_and_authors() -> None:
    data = {"pages": [{"blocks": [
        {"text": "Material examined. Twelve specimens."},
        {"text": "Rouse y Fauchald (1997) revised the group."},
        {"text": "Nereis pelagica Smith, 1900."},
    ]}]}
    names = build_genus_set(data)
    assert "Nereis" in names
    assert "Material" not in names
    assert "Rouse" not in names


def _key_line(text: str, block: int, leader_pt: float | None = None) -> dict:
    leaders = []
    if leader_pt is not None:
        leaders = [{"text": "……", "bbox": [0.0, 0.0, leader_pt, 10.0]}]
    return {"text": text, "block": block, "leaders": leaders}


def test_key_breaks_reads_couplet_whose_target_wrapped() -> None:
    """目标换到下一行时，构造强制断行签名（Vol. 45 Praxillura 条目）。"""
    lines = [
        _key_line("1. Body with 20-29 setigers or more (fig. 129A)..........", 0, 93.2),
        _key_line("2. Body with fewer setigers..........Praxillura (p. 335)", 1, 300.0),
        _key_line("Praxillura (p. 335)", 0, None),
        _key_line("3. Other..........Praxillura (p. 336)", 1, 300.0),
    ]
    breaks, defects = _key_breaks_from_lines(lines, page_no=308)
    assert defects and defects[0]["page"] == 308
    assert any(sig.endswith("\tpraxillura (p. 335)") for sig in breaks)


def test_key_breaks_ignores_wide_leader() -> None:
    lines = [
        _key_line("1. Short left..........Alpha (p. 1)", 0, 300.0),
        _key_line("2. Other left..........Beta (p. 2)", 1, 300.0),
    ]
    assert _key_breaks_from_lines(lines) == ([], [])


def test_key_breaks_checks_page_with_single_leader_line() -> None:
    """键页只有一行带引导点也要检查（Vol. 45 p. 308 的 Praxillura）。"""
    lines = [
        _key_line("1. Body with 20-29 setigers (fig. 129A); uncini with a single "
                  "subrostral barbula (fig. 129E)..........", 0, 93.2),
        _key_line("Praxillura (p. 335)", 0, None),
        _key_line("2. Body with fewer setigers..........Ninoe (p. 336)", 0, 300.0),
    ]
    breaks, defects = _key_breaks_from_lines(lines, page_no=308)
    assert defects and defects[0]["page"] == 308
    assert any(sig.endswith("\tpraxillura (p. 335)") for sig in breaks)
