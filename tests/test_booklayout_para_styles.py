"""T3 (design 2026-11-26 C): every non-heading role is a named paragraph style.

Paragraphs only reference the style; size/spacing live in the style so a profile
change (``para_styles``) or a Word style edit restyles the whole book.
"""
from __future__ import annotations

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

import booklayout.builder as bld
from booklayout.builder import setup, spara, style_pt
from booklayout.profile import PARA_FIELDS, PARA_STYLE_DEFAULTS, StyleProfile


@pytest.fixture(autouse=True)
def _restore_profile():
    old = bld.PROFILE
    yield
    bld.apply_profile(old)


def _doc(profile: StyleProfile | None = None):
    if profile is not None:
        bld.apply_profile(profile)
    doc = Document()
    setup(doc)
    return doc


def test_defaults_are_valid_and_cover_roles() -> None:
    StyleProfile().validate()
    for name, cfg in PARA_STYLE_DEFAULTS.items():
        assert set(cfg) <= PARA_FIELDS, name
    for need in ("Body", "Body Cont", "Note", "Citation", "Ref", "Entry", "Taxon", "Caption", "Key",
                 "Key Couplet", "Key Table", "List Item", "Quote", "Box Text", "Footnote Text",
                 "Table Note", "Index", "Section Title"):
        assert need in PARA_STYLE_DEFAULTS


def test_bad_style_name_or_field_rejected() -> None:
    with pytest.raises(ValueError):
        StyleProfile(para_styles={"Nope": {"size": 9}}).validate()
    with pytest.raises(ValueError):
        StyleProfile(para_styles={"Body": {"colour": 1}}).validate()
    with pytest.raises(ValueError):
        StyleProfile(para_styles={"Body": {"align": "diagonal"}}).validate()


def test_para_style_merges_profile_override() -> None:
    p = StyleProfile(para_styles={"Body": {"first": 7.5}}, citation_before=3.0)
    assert p.para_style("Body")["first"] == 7.5
    assert p.para_style("Body")["size"] == 10.5
    assert p.para_style("Citation")["before"] == 3.0


def test_define_styles_creates_every_style() -> None:
    doc = _doc()
    names = {s.name for s in doc.styles}
    assert set(PARA_STYLE_DEFAULTS) <= names
    body = doc.styles["Body"]
    assert body.font.size == Pt(10.5)
    assert body.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert doc.styles["Caption"].font.bold is False  # python-docx template colour/bold reset


def test_paragraph_references_style_without_direct_size() -> None:
    doc = _doc()
    p = spara(doc, "Plain *Nereis virens* text.", "Body")
    assert p.style.name == "Body"
    assert all(r.font.size is None for r in p.runs)
    assert p.paragraph_format.first_line_indent is None
    assert p.paragraph_format.space_before is None
    n = spara(doc, "A note.", "Note")
    assert n.style.name == "Note"
    assert all(r.italic is not True or r.text.strip() for r in n.runs)
    assert all(r.font.size is None for r in n.runs)


def test_override_only_when_it_differs_from_style() -> None:
    doc = _doc()
    t = spara(doc, "Order X", "Taxon", left=9.0, before=3.0)
    assert t.paragraph_format.left_indent.mm == pytest.approx(9.0, abs=0.01)
    assert t.paragraph_format.space_before.pt == pytest.approx(3.0, abs=0.01)
    plain = spara(doc, "Order Y", "Taxon", left=0.0, before=0.0)
    assert plain.paragraph_format.left_indent is None
    assert plain.paragraph_format.space_before is None


def test_restyle_by_profile_changes_style_not_paragraphs() -> None:
    prof = StyleProfile(para_styles={"Body": {"size": 12.0, "first": 8.0}})
    doc = _doc(prof)
    p = spara(doc, "Text.", "Body")
    assert doc.styles["Body"].font.size == Pt(12.0)
    assert doc.styles["Body"].paragraph_format.first_line_indent.mm == pytest.approx(8.0, abs=0.01)
    assert p.runs[0].font.size is None


def test_body_size_scales_styles() -> None:
    doc = _doc(StyleProfile(body_size=11.0))
    assert doc.styles["Body"].font.size == Pt(11.0)
    assert style_pt("Ref") == pytest.approx(round(7.6 * 11.0 / 10.5, 2))


def test_size_follows_body_matches_legacy_double_scale() -> None:
    # old: para(size=body_size - 0.5) scaled again by _sz()
    prof = StyleProfile(body_size=11.0)
    bld.apply_profile(prof)
    assert style_pt("Quote") == pytest.approx(round((11.0 - 0.5) * 11.0 / 10.5, 2))
    assert style_pt("Footnote Text") == pytest.approx(round((11.0 - 2) * 11.0 / 10.5, 2))
    default = StyleProfile()
    bld.apply_profile(default)
    assert style_pt("Quote") == pytest.approx(10.0)


def test_bare_document_gets_styles_on_demand() -> None:
    doc = Document()
    p = spara(doc, "Text.", "Citation")
    assert p.style.name == "Citation"
    assert doc.styles["Citation"].paragraph_format.left_indent.mm == pytest.approx(4.0, abs=0.01)


def test_inverted_italic_stays_direct() -> None:
    doc = _doc()
    p = spara(doc, "Note with *Nereis virens* inside.", "Note", invert=True)
    # the note style is italic: plain text inherits it, the scientific name is set roman directly
    assert [r.italic for r in p.runs if "Nereis" in r.text] == [False]
    assert all(r.italic is None for r in p.runs if "Nereis" not in r.text)


def test_key_heading_uses_style() -> None:
    from booklayout import keymodel as km

    doc = _doc()
    key = km.parse_key_text("Key to genera of Fooidae\n1. Eyes present ........ 2\n• Eyes absent ........ Alpha (p. 1)\n")[0]
    paras = km.render_key(doc, key)
    assert paras[0].style.name == "Key Heading"
    assert paras[1].style.name == "Key"
