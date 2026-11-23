import os
import shutil
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from keykit.ir import from_imajima_json
from keykit.layout import channel_mm, mark_width_mm, render_docx, to_pdf
from keykit.profile import for_lang
from keykit.verify import verify_pdf

# 样本是书稿译文数据，不进仓库；KEYKIT_SAMPLES 指向含 keys_2001.json 的目录，否则取 test-keys/imajima_keys
J = Path(os.environ.get("KEYKIT_SAMPLES") or Path(__file__).resolve().parents[2] / "imajima_keys") / "keys_2001.json"
NEED_SAMPLE = pytest.mark.skipif(not J.exists(), reason="无 Imajima 样本（设 KEYKIT_SAMPLES）")


@NEED_SAMPLE
def test_docx_props(tmp_path):
    irs = from_imajima_json(J)
    prof = for_lang("zh", "dash")
    out = render_docx(irs, prof, tmp_path / "a.docx")
    d = Document(str(out))
    t = d.tables[0]
    pr = t._tbl.tblPr
    assert pr.find(qn("w:tblLayout")).get(qn("w:type")) == "fixed"
    assert pr.find(qn("w:tblInd")).get(qn("w:w")) == "0"
    assert all(e.get(qn("w:w")) == "0" for e in pr.find(qn("w:tblCellMar")))
    mw = mark_width_mm(irs, prof)
    grid = [int(g.get(qn("w:w"))) for g in t._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert grid[0] == int(mw / 25.4 * 1440)
    assert sum(grid) <= int(150 / 25.4 * 1440) + 2
    assert t.rows[0]._tr.trPr.find(qn("w:cantSplit")) is not None
    p = t.rows[0].cells[1].paragraphs[0]
    tabs = p.paragraph_format.tab_stops
    assert abs(tabs[0].position.mm - (150 - mw)) < 0.1
    assert abs(p.paragraph_format.right_indent.mm - channel_mm(irs, prof)) < 0.1
    assert t.rows[0].cells[1].paragraphs[0].paragraph_format.keep_with_next is True


@NEED_SAMPLE
@pytest.mark.skipif(shutil.which("soffice") is None, reason="no soffice")
def test_pdf_verify(tmp_path):
    irs = from_imajima_json(J)
    prof = for_lang("zh", "dash")
    pdf = to_pdf(render_docx(irs, prof, tmp_path / "b.docx"))
    bad = [i for i in verify_pdf(pdf, irs, prof) if i["code"] in ("L5", "L8")]
    assert not bad
