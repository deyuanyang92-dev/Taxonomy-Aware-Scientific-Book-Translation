"""L6 检测按全文字符位置找，不误报；page_before 拆表分页不多出空白页（2026-11-23，keys_2007 偶句 13）。"""
import shutil
from pathlib import Path

import fitz
import pytest

from keykit.ir import Couplet, KeyIR, Lead
from keykit.layout import render_docx, to_pdf
from keykit.profile import Profile
from keykit.verify import verify_pdf


def _ir() -> KeyIR:
    cs = [Couplet(num=1, leads=[Lead(text="背鳞15对，体长", target="2"), Lead(text="背鳞12对", target="Aus bus")]),
          Couplet(num=2, leads=[Lead(text="背鳞15对", target="Cus dus"), Lead(text="背鳞18对", target="Eus fus")])]
    return KeyIR(heading="检索", couplets=cs, lang="zh", source_style="dash")


@pytest.mark.skipif(shutil.which("soffice") is None, reason="无 LibreOffice")
def test_no_false_l6_and_page_before(tmp_path: Path):
    prof = Profile(second_lead="dash", overflow="wrap", figref="after", dest_zh_name=False)
    pdf = to_pdf(render_docx([_ir()], prof, tmp_path / "a.docx"))
    assert [i for i in verify_pdf(pdf, [_ir()], prof) if i["code"] == "L6"] == []
    pdf = to_pdf(render_docx([_ir()], prof, tmp_path / "b.docx", page_before={0: {1}}))
    d = fitz.open(str(pdf))
    assert d.page_count == 2
    p0, p1 = ("".join(p.get_text().split()) for p in d)
    assert "背鳞18对" in p1 and "背鳞18对" not in p0
    assert [i for i in verify_pdf(pdf, [_ir()], prof) if i["code"] == "L6"] == []
