"""Issue #7/#13: generic display-rectangle figure extraction from a PDF."""
from __future__ import annotations

import json

import fitz
import pytest

from booklayout import cli, pdffigures


def _make_pdf(path, pages=4):
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False)
    pix.set_rect(pix.irect, (255, 255, 255))  # white embedded image
    png = pix.tobytes("png")
    logo = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
    logo.set_rect(logo.irect, (10, 10, 200))
    for n in range(1, pages + 1):
        page = doc.new_page(width=420, height=600)
        page.insert_text((50, 40), f"Body text of page {n}", fontsize=10)
        page.insert_image(fitz.Rect(300, 540, 380, 590), pixmap=logo)  # same logo every page
        if n in (2, 3):
            # black composition behind a white image, as in Fauna Iberica p.17
            page.draw_rect(fitz.Rect(40, 80, 380, 330), color=None, fill=(0, 0, 0))
            page.insert_image(fitz.Rect(60, 100, 360, 300), stream=png)
            page.insert_text((60, 350), f"Figure {n - 1}. Caption of figure {n - 1}.", fontsize=9)
    doc.save(str(path))


@pytest.fixture()
def pdf(tmp_path):
    p = tmp_path / "book.pdf"
    _make_pdf(p)
    return p


def test_crop_keeps_page_composition_not_embedded_image_only(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=100)
    sci = [f for f in mf["figures"] if not f.get("furniture")]
    assert len(sci) == 2
    pix = fitz.Pixmap(str(tmp_path / "o" / sci[0]["crop"]))
    # the embedded image is white; the crop covers it exactly, so it is white,
    # while a crop widened to the black rectangle would contain black.  Check
    # the display rectangle is the image's (300x200 pt at 100 dpi).
    assert abs(pix.width - 300 / 72 * 100) <= 2 and abs(pix.height - 200 / 72 * 100) <= 2
    assert sci[0]["bbox_pt"] == [60.0, 100.0, 360.0, 300.0]


def test_manifest_links_caption_and_flags_repeated_logo_as_furniture(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=100)
    pdffigures.write_outputs(mf, tmp_path / "o", "cmd")
    assert mf["audit"]["furniture_figures"] == 4
    sci = [f for f in mf["figures"] if not f["furniture"]]
    assert [f["source_label"] for f in sci] == ["1", "2"]
    assert all(f["caption_text"].startswith("Figure") for f in sci)
    assert len({f["crop_sha256"] for f in sci}) == 1 or len(sci) == 2
    audit = json.loads((tmp_path / "o" / "source_figure_audit.json").read_text())
    assert {f["source_label"] for f in audit["figures"]} == {"1", "2"}
    assert all(f["crop"].startswith("source_figure_crops/") for f in audit["figures"])
    full = json.loads((tmp_path / "o" / "figures_manifest.json").read_text())
    assert full["pdf_sha256"] and full["command"] == "cmd" and full["tool"]


def test_duplicate_content_and_missing_expected_labels_are_reported(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=100)
    a = pdffigures.audit_manifest(mf, expected_labels=["1", "2", "3"])
    assert a["problems"]["missing_labels"] == ["3"]
    assert not a["ok"]
    assert a["problems"]["duplicate_content_on_few_pages"]  # same image on two pages


def test_low_resolution_flagged(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=20)
    a = pdffigures.audit_manifest(mf)
    assert a["problems"]["low_resolution"]


def test_map_to_translation_pairs_by_label_and_lists_unresolved(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=100)
    blocks = [{"role": "caption", "block_id": "b1", "translation": "Figura 1. Leyenda"},
              {"role": "caption", "block_id": "b9", "translation": "Fig. 3. other"}]
    res = pdffigures.map_to_translation(mf, blocks)
    assert res["placements"] == {"b1": ["p0002_01"]}
    assert res["unresolved"][0]["figure"] == "p0003_01"
    assert res["unresolved"][0]["reason"] == "no_caption_block"


def test_fit_check_flags_big_downscale(pdf, tmp_path):
    mf = pdffigures.extract_figures(pdf, tmp_path / "o", dpi=100)
    mf["figures"][0]["crop_px"] = [4000, 4000]
    assert pdffigures.fit_check(mf)


def test_cli_extract_exit_code_and_help(pdf, tmp_path, capsys):
    rc = cli.main(["figures", "extract", "--pdf", str(pdf), "--out", str(tmp_path / "o"), "--dpi", "100"])
    out = capsys.readouterr().out
    assert "scientific=2" in out
    assert rc == 1  # duplicate-content image on two pages needs a human look
