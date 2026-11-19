"""typo_scan：成品 DOCX/PDF 错字扫描、字体安全定点修补与闸（issue #24）。"""
from __future__ import annotations

import json
import zipfile

import fitz
import patch_release as pr
import pytest
import typo_scan as ts

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
RULES = [ts.Rule("沙蚕料", "沙蚕科", "typo-table", "high")]


def run(text: str, italic: bool = False, east: str | None = "SimSun", bold: bool = False) -> str:
    fonts = f'<w:rFonts w:eastAsia="{east}" w:ascii="Times New Roman"/>' if east else ""
    it = ("<w:i/>" if italic else "") + ("<w:b/>" if bold else "")
    return f'<w:r><w:rPr>{fonts}{it}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'


def make_docx(path, body: str, footnotes: str = "") -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>')
        if footnotes:
            z.writestr("word/footnotes.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:footnotes {W}>{footnotes}</w:footnotes>')


def yes(font, chars):
    return True


def no(font, chars):
    return False


def unknown(font, chars):
    return None


def test_split_run_table_caption_footnote_all_detected(tmp_path) -> None:
    body = (f"<w:p>{run('本沙蚕')}{run('料很常见')}</w:p>"
            f"<w:tbl><w:tr><w:tc><w:p>{run('沙蚕料')}</w:p></w:tc></w:tr></w:tbl>"
            f"<w:p><w:pPr><w:pStyle w:val=\"Caption\"/></w:pPr>{run('图1 沙蚕料')}</w:p>")
    fn = f'<w:footnote w:id="1"><w:p>{run("注：沙蚕料")}</w:p></w:footnote>'
    p = tmp_path / "a.docx"
    make_docx(p, body, fn)
    rep = ts.scan_docx(p, RULES, can_render=yes)
    hits = [t for t in rep["typos"] if t["observed"] == "沙蚕料"]
    assert len(hits) == 4
    assert {t["where"].split(":")[0] for t in hits} == {"word/document.xml", "word/footnotes.xml"}
    assert all(t["proposed"] == "沙蚕科" and t["auto"] for t in hits)
    assert "沙蚕料" in hits[0]["context"]
    assert rep["status"] == "typos" and rep["ok"] is False


def test_fix_preserves_run_formatting_and_is_idempotent(tmp_path) -> None:
    body = f"<w:p>{run('沙蚕')}{run('料', bold=True)}</w:p>"
    src, dst = tmp_path / "a.docx", tmp_path / "b.docx"
    make_docx(src, body)
    rep = ts.fix_docx(src, dst, RULES, can_render=yes)
    assert rep["applied"] == 1
    with zipfile.ZipFile(dst) as z:
        xml = z.read("word/document.xml").decode("utf8")
    assert xml.count("<w:b/>") == 1 and xml.count("SimSun") == 2  # run 与格式都保留
    assert ">料<" not in xml and ">科<" in xml and ">沙蚕<" in xml  # 只改差异那一个字，留在原 run
    again = ts.scan_docx(dst, RULES, can_render=yes)
    assert again["typos"] == [] and again["status"] == "clean" and again["ok"] is True
    assert ts.fix_docx(dst, tmp_path / "c.docx", RULES, can_render=yes)["applied"] == 0


def test_font_without_glyph_refused(tmp_path) -> None:
    p = tmp_path / "a.docx"
    make_docx(p, f"<w:p>{run('沙蚕料')}</w:p>")
    rep = ts.scan_docx(p, RULES, can_render=no)
    t = rep["typos"][0]
    assert t["auto"] is False and "字体" in t["reason"]
    out = tmp_path / "o.docx"
    fx = ts.fix_docx(p, out, RULES, can_render=no)
    assert fx["applied"] == 0 and fx["refused"] == 1 and not out.exists()


def test_unknown_font_not_applied(tmp_path) -> None:
    p = tmp_path / "a.docx"
    make_docx(p, f"<w:p>{run('沙蚕料', east=None)}</w:p>")
    t = ts.scan_docx(p, RULES, can_render=unknown)["typos"][0]
    assert t["auto"] is False and "未知" in t["reason"]


def test_scientific_name_never_proposed(tmp_path) -> None:
    p = tmp_path / "a.docx"
    make_docx(p, f"<w:p>{run('Nereis', italic=True)}{run(' Nereis Linnaeus, 1758')}</w:p>")
    rules = [ts.Rule("Nereis", "Nereid", "typo-table", "high")]
    assert ts.scan_docx(p, rules, can_render=yes)["typos"] == []


def test_builtin_rules_replacement_char_and_double_punct(tmp_path) -> None:
    p = tmp_path / "a.docx"
    make_docx(p, f"<w:p>{run('多毛类�，，很多')}</w:p>")
    rep = ts.scan_docx(p, [], can_render=yes)
    rules = {t["rule"] for t in rep["typos"]}
    assert {"replacement-char", "double-punct"} <= rules
    rc = next(t for t in rep["typos"] if t["rule"] == "replacement-char")
    assert rc["proposed"] == "" and rc["auto"] is False  # 无法确定应为何字，必须人工
    assert rep["ok"] is False


def test_read_rules_tsv(tmp_path) -> None:
    f = tmp_path / "r.tsv"
    f.write_text("# c\n沙蚕料\t沙蚕科\t常见\nteh\tthe\n", encoding="utf8")
    rules = ts.read_rules(f)
    assert [(r.old, r.new) for r in rules] == [("沙蚕料", "沙蚕科"), ("teh", "the")]


def test_ok_when_clean(tmp_path) -> None:
    p = tmp_path / "a.docx"
    make_docx(p, f"<w:p>{run('沙蚕科')}</w:p>")
    rep = ts.scan_docx(p, RULES, can_render=yes)
    assert rep["status"] == "clean" and rep["ok"] is True


# ------------------------------------------------------------------- PDF


def _pdf(tmp_path, text="the teh cat"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), text, fontsize=12)
    p = tmp_path / "a.pdf"
    doc.save(str(p))
    return p


def test_pdf_scan_reports_page_and_bbox_and_not_auto_for_ascii(tmp_path) -> None:
    p = _pdf(tmp_path)
    rep = ts.scan_pdf(p, [ts.Rule("teh", "the", "typo-table", "high")])
    t = rep["typos"][0]
    assert t["page"] == 1 and len(t["bbox"]) == 4 and t["auto"] is False
    assert "re-render" in t["reason"] or "重渲染" in t["reason"]
    assert rep["status"] == "typos"


def test_pdf_clean(tmp_path) -> None:
    rep = ts.scan_pdf(_pdf(tmp_path, "all fine"), [ts.Rule("teh", "the", "x", "high")])
    assert rep["status"] == "clean" and rep["ok"] is True and rep["unscannable"] == []


@pytest.mark.parametrize("ftype,tounicode,safe", [
    ("Type3", True, False), ("Type0", False, False), ("TrueType", False, False),
    ("Type0", True, True), ("Type1", False, True)])
def test_font_scannable(ftype, tounicode, safe) -> None:
    assert ts.font_scannable(ftype, tounicode) is safe


def test_unscannable_is_not_clean(tmp_path, monkeypatch) -> None:
    p = _pdf(tmp_path, "fine")
    monkeypatch.setattr(ts, "font_scannable", lambda t, u: False)
    rep = ts.scan_pdf(p, [])
    assert rep["status"] == "not_scannable" and rep["ok"] is False
    assert rep["unscannable"][0]["page"] == 1


# ------------------------------------------------------------------- 字体与 CLI


def test_font_can_render_ascii_and_empty() -> None:
    assert ts.font_can_render("AnyFont", "") is True
    assert ts.font_can_render("AnyFont", " ,.") is True


def test_font_can_render_unknown_font_is_none(tmp_path) -> None:
    assert ts.font_can_render("NoSuchFontXYZ", "科", font_dirs=[tmp_path]) is None


def test_cli_scan_and_fix(tmp_path) -> None:
    src = tmp_path / "a.docx"
    make_docx(src, f"<w:p>{run('沙蚕料')}</w:p>")
    rules = tmp_path / "r.tsv"
    rules.write_text("沙蚕料\t沙蚕科\n", encoding="utf8")
    rep = tmp_path / "rep.json"
    assert ts.main(["scan", str(src), "--rules", str(rules), "--report", str(rep), "--assume-fonts-ok"]) == 1
    assert json.loads(rep.read_text(encoding="utf8"))["status"] == "typos"
    out = tmp_path / "o.docx"
    assert ts.main(["fix", str(src), "--rules", str(rules), "-o", str(out), "--assume-fonts-ok"]) == 0
    assert ts.main(["scan", str(out), "--rules", str(rules), "--assume-fonts-ok"]) == 0


def test_patch_release_delegates_scan(tmp_path) -> None:
    src = tmp_path / "a.docx"
    make_docx(src, f"<w:p>{run('沙蚕料')}</w:p>")
    rules = tmp_path / "r.tsv"
    rules.write_text("沙蚕料\t沙蚕科\n", encoding="utf8")
    assert pr.main(["scan", str(src), "--rules", str(rules), "--assume-fonts-ok"]) == 1
