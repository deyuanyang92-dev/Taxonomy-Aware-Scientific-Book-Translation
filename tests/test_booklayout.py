from __future__ import annotations

import base64
import json
from pathlib import Path

import fitz
from docx import Document

from booklayout.builder import BookMeta, BookPaths, build, make_page_map
from booklayout.cli import main

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
    assert out.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["blocks"] == 5
    assert payload["figures"] == 1
    assert payload["chapters"] == ["Introduction", "Family Testidae"]


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
