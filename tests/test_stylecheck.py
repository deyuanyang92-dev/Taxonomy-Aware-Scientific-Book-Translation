from docx import Document

from booklayout.stylecheck import check_docx


def _build(tmp_path, build):
    d = Document()
    build(d)
    f = tmp_path / "t.docx"
    d.save(str(f))
    return check_docx(str(f))


def test_clean_doc_passes(tmp_path):
    def b(d):
        p = d.add_paragraph()
        p.add_run("形态").bold = True
        p.add_run("：体长 5 mm（Pettibone, 1953）。")
    assert not any(_build(tmp_path, b).values())


def test_italic_cjk_and_halfwidth_paren_flagged(tmp_path):
    def b(d):
        p = d.add_paragraph()
        p.add_run("形态").italic = True
        d.add_paragraph("见 (Narchi, 1969)的研究")
        d.add_paragraph("")
    res = _build(tmp_path, b)
    assert res["italic_cjk"] and res["label_not_bold"]
    assert res["halfwidth_paren_before_cjk"] and res["blank_paragraph"]
