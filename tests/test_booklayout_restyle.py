"""T4: restyle (all styles + --style overrides), HTML style CSS, stylecheck direct-format warning."""
from __future__ import annotations

import pytest
from docx import Document
from docx.shared import Pt

from booklayout import htmlout, restyle
from booklayout.builder import apply_profile, setup
from booklayout.profile import StyleProfile
from booklayout.stylecheck import check_docx, direct_format_warnings


def _doc(tmp_path):
    prof = StyleProfile()
    apply_profile(prof)
    d = Document()
    setup(d)
    d.add_paragraph("Body text here.", style="Body")
    d.add_paragraph("Caption text here.", style="Caption")
    d.add_heading("Title", level=2)
    f = tmp_path / "in.docx"
    d.save(str(f))
    return f, prof


def test_parse_override():
    assert restyle.parse_override("Body.size=11") == ("Body", "size", 11.0)
    assert restyle.parse_override("Heading 2.before=12") == ("Heading 2", "before", 12.0)
    assert restyle.parse_override("Note.italic=false") == ("Note", "italic", False)
    assert restyle.parse_override("Body.align=left")[2] == "left"
    for bad in ("Body", "Body.size", "size=3", ".size=3"):
        with pytest.raises(ValueError):
            restyle.parse_override(bad)


def test_apply_overrides_validates_and_copies():
    prof = StyleProfile()
    new = restyle.apply_overrides(prof, ["Body.size=11", "Heading 3.size=13"])
    assert new.para_styles["Body"]["size"] == 11.0 and new.heading_styles["3"]["size"] == 13.0
    assert not prof.para_styles and "size" in prof.heading_styles["3"] and prof.heading_styles["3"]["size"] != 13.0
    for spec in ("Nope.size=1", "Body.nope=1", "Heading 2.nope=1", "Body.align=diagonal"):
        with pytest.raises(ValueError):
            restyle.apply_overrides(prof, [spec])


def test_restyle_changes_style_not_paragraphs(tmp_path):
    f, prof = _doc(tmp_path)
    out = tmp_path / "out.docx"
    restyle.restyle_docx(f, out, prof, ["Body.size=12", "Caption.italic=true"])
    d = Document(str(out))
    assert d.styles["Body"].font.size == Pt(12)
    assert d.styles["Caption"].font.italic is True
    body = [p for p in d.paragraphs if p.text.startswith("Body text")][0]
    assert body.style.name == "Body" and all(r.font.size is None for r in body.runs)
    assert not direct_format_warnings(str(out))
    # original untouched
    assert Document(str(f)).styles["Body"].font.size == Pt(10.5)


def test_restyle_scales_with_body_size(tmp_path):
    f, prof = _doc(tmp_path)
    out = tmp_path / "o.docx"
    restyle.restyle_docx(f, out, prof, ["Body.size=10.5"])
    base = Document(str(out)).styles["Caption"].font.size
    prof2 = StyleProfile(body_size=12.0)
    restyle.restyle_docx(f, out, prof2, [])
    d = Document(str(out))
    assert d.styles["Normal"].font.size == Pt(12)
    assert d.styles["Caption"].font.size.pt > base.pt
    apply_profile(StyleProfile())


def test_cli_restyle_bad_style_exit2(tmp_path, capsys):
    from booklayout.cli import main
    f, _ = _doc(tmp_path)
    prof = tmp_path / "p.json"
    prof.write_text("{}", encoding="utf-8")
    rc = main(["restyle", "--docx", str(f), "--profile", str(prof), "--out", str(tmp_path / "x.docx"),
               "--style", "Body.bogus=1"])
    assert rc == 2 and "unknown field" in capsys.readouterr().err
    rc = main(["restyle", "--docx", str(f), "--profile", str(prof), "--out", str(tmp_path / "x.docx"),
               "--style", "Body.size=11", "--html", str(tmp_path / "x.html")])
    assert rc == 0 and "font-size:11pt" in (tmp_path / "x.html").read_text(encoding="utf-8")


def test_html_para_css_and_class(tmp_path):
    f, prof = _doc(tmp_path)
    css = htmlout.para_css(prof)
    assert "p.s-body{font-size:10.5pt" in css and "p.s-body-cont{" in css and "p.s-caption{" in css
    assert "break-inside:avoid" in css
    out = tmp_path / "o.html"
    htmlout.docx_to_html(f, out, prof)
    text = out.read_text(encoding="utf-8")
    assert "<p class='s-body'>Body text here.</p>" in text
    assert "<p class='s-caption'>" in text
    # one style edit reaches the HTML CSS
    p2 = restyle.apply_overrides(prof, ["Body.size=13"])
    assert "p.s-body{font-size:13pt" in htmlout.para_css(p2)
    apply_profile(StyleProfile())


def test_stylecheck_direct_format_warning(tmp_path):
    d = Document()
    setup(d)
    p = d.add_paragraph("x", style="Body")
    p.add_run(" direct").font.size = Pt(14)
    p2 = d.add_paragraph("spaced", style="Body")
    p2.paragraph_format.space_after = Pt(9)
    ok = d.add_paragraph("fine", style="Body")
    ok.add_run("\t").font.size = Pt(10)
    plain = d.add_paragraph("normal para")
    plain.add_run(" big").font.size = Pt(20)
    f = tmp_path / "d.docx"
    d.save(str(f))
    w = direct_format_warnings(str(f))
    assert len(w) == 2 and "run_size" in w[0] and "space_after" in w[1]
    assert not any(check_docx(str(f)).values())  # warning only, no error key
    from booklayout.stylecheck import main as sc_main
    assert sc_main(["x", str(f)]) == 0
