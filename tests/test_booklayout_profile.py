"""Issue #27: style profile and generic block model."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from docx import Document

from booklayout import builder
from booklayout.profile import StyleProfile, validate_aligned


@pytest.fixture(autouse=True)
def _restore():
    yield
    builder.apply_profile(StyleProfile())


def aligned(extra: list[dict] | None = None) -> dict:
    blocks = [{"block_id": "h", "role": "heading", "level": 1, "translation": "Chapter"},
              {"block_id": "b", "role": "body", "translation": "Plain body text."}]
    return {"pages": [{"page": 1, "chapter": "C", "kind": "body", "blocks": blocks + (extra or [])}]}


def build_doc(tmp: Path, data: dict, profile: StyleProfile | None, name: str) -> Path:
    ap = tmp / f"{name}.json"
    ap.write_text(json.dumps(data), encoding="utf-8")
    fig = tmp / "figs"
    fig.mkdir(exist_ok=True)
    (fig / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")
    builder.apply_profile(profile or StyleProfile())
    out = tmp / f"{name}.docx"
    builder.build(out, {}, builder.BookPaths(ap, fig), builder.BookMeta(title="T"))
    return out


def parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in ("word/document.xml", "word/styles.xml", "word/settings.xml")}


def test_default_profile_matches_historical_constants() -> None:
    p = StyleProfile()
    assert (p.page_w, p.page_h, p.text_w, p.body_font, p.body_size) == (170.0, 240.0, 134.0, "Garamond", 10.5)
    assert (p.margin_top, p.margin_bottom, p.margin_left, p.margin_right) == (20, 19, 18, 18)


def test_default_profile_output_identical_and_geometry(tmp_path) -> None:
    a = build_doc(tmp_path, aligned(), None, "a")
    b = build_doc(tmp_path, aligned(), StyleProfile(), "b")
    assert parts(a) == parts(b)
    sec = Document(str(a)).sections[0]
    assert round(sec.page_width.mm) == 170 and round(sec.left_margin.mm) == 18


def test_custom_profile_changes_page_font_and_is_hashed(tmp_path) -> None:
    prof = StyleProfile(name="a5", page_w=148, page_h=210, margin_left=15, margin_right=15,
                        body_font="Times New Roman", cjk_font="SimSun", body_size=11)
    out = build_doc(tmp_path, aligned(), prof, "c")
    doc = Document(str(out))
    assert round(doc.sections[0].page_width.mm) == 148
    assert doc.styles["Normal"].font.name == "Times New Roman"
    assert prof.sha256() != StyleProfile().sha256()
    assert prof.text_w == 118


def test_profile_from_toml_and_rejects_unknown(tmp_path) -> None:
    f = tmp_path / "p.toml"
    f.write_text('name = "x"\npage_w = 150.0\n', encoding="utf-8")
    assert StyleProfile.from_file(f).page_w == 150.0
    f.write_text("nope = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        StyleProfile.from_file(f)
    with pytest.raises(ValueError):
        StyleProfile(margin_left=90, margin_right=90).validate()


def test_legacy_aligned_valid_and_bad_detected() -> None:
    assert validate_aligned(aligned()) == []
    bad = aligned([{"block_id": "t", "role": "table"}, {"role": "wat", "translation": "x"}])
    errs = validate_aligned(bad)
    assert any("table needs" in e for e in errs) and any("unknown role" in e for e in errs)


def test_generic_blocks_render(tmp_path) -> None:
    extra = [
        {"block_id": "t1", "role": "table", "header_rows": 1, "translation": "Table 1. Sizes.",
         "rows": [["Taxon", {"text": "Length", "colspan": 2}], ["A", "1", "2"]]},
        {"block_id": "l1", "role": "list", "items": ["one", "two"], "ordered": True},
        {"block_id": "q1", "role": "quote", "translation": "A quotation."},
        {"block_id": "x1", "role": "box", "translation": "Boxed note."},
        {"block_id": "f1", "role": "footnote", "translation": "Footnote text."},
    ]
    out = build_doc(tmp_path, aligned(extra), None, "g")
    doc = Document(str(out))
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert t.cell(0, 1).text == "Length" and t.cell(1, 2).text == "2"
    xml = parts(out)["word/document.xml"].decode()
    assert "w:tblHeader" in xml and "w:pBdr" in xml
    texts = [p.text for p in doc.paragraphs]
    assert "1. one" in texts and "A quotation." in texts and "Footnote text." in texts


def test_cli_profile_and_report_hash(tmp_path) -> None:
    from booklayout.cli import main
    assert main(["profile"]) == 0
    f = tmp_path / "p.json"
    f.write_text(json.dumps(StyleProfile(name="n").to_dict()), encoding="utf-8")
    assert main(["profile", "--validate", str(f)]) == 0
    ap = tmp_path / "a.json"
    ap.write_text(json.dumps(aligned()), encoding="utf-8")
    assert main(["validate-aligned", "--aligned", str(ap)]) == 0
    fig = tmp_path / "figs"
    fig.mkdir()
    (fig / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")
    rep = tmp_path / "r.json"
    assert main(["build", "--aligned", str(ap), "--figures", str(fig), "--profile", str(f),
                 "--out", str(tmp_path / "o.docx"), "--report", str(rep)]) == 0
    assert json.loads(rep.read_text())["profile_sha256"] == StyleProfile(name="n").sha256()
