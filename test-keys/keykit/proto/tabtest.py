"""样张：验证「右缩进 + 越界右对齐点线制表位」在 Word / LibreOffice 下是否生效。

用法: python3 tabtest.py OUT_DIR
产物: OUT_DIR/tabtest.docx
"""
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

TEXT_W = 150.0   # 版心宽 mm
MARK = 9.0       # 编号区宽
HANG = 12.0      # 正文起点
RIGHT = 38.0     # 去向通道宽（右缩进）

LEADS = [
    ("1.", "口前叶具触角", "2"),
    ("—", "口前叶无触角，具 1 对眼点", "3"),
    ("2 (1).", "背须长于背舌叶的 2 倍，表面具环纹，在体中段尤为明显；口前叶具 2 对呈梯形排列的黑色眼点", "格裂虫属 Brania"),
    ("—", "背须短小或退化，长度小于背舌叶的 1.5 倍；口前叶无眼，或仅具 1 对退化眼点，咽齿位于咽前端", "4"),
    ("3 (1).", "背须长于背舌叶，表面具环纹，体中段明显；口前叶具 2 对眼点，前对较大，后对较小呈梯形排", "Exogone"),
    ("—", "Dorsal cirri much longer than dorsal lobe, annulated throughout; prostomium with two pairs of eyes in trapezoid", "Sphaerosyllis erinaceus"),
    ("4 (2).", "Ventral fascicle with 1-4 heterogomph falcigers, blade length/width ratio below 3; pharynx with cone-shaped tooth near the anterior margin of", "Exogone naidina Ørsted, 1845"),
    ("—", "腹刚毛束具 5–10 根异齿镰状复型刚毛", "5"),
]


def set_compat(doc, mode: int) -> None:
    st = doc.settings.element
    comp = st.find(qn("w:compat"))
    if comp is None:
        comp = st.makeelement(qn("w:compat"), {})
        st.append(comp)
    for cs in comp.findall(qn("w:compatSetting")):
        if cs.get(qn("w:name")) == "compatibilityMode":
            comp.remove(cs)
    cs = comp.makeelement(qn("w:compatSetting"), {qn("w:name"): "compatibilityMode",
                          qn("w:uri"): "http://schemas.microsoft.com/office/word", qn("w:val"): str(mode)})
    comp.append(cs)


def build(out: Path, name: str = "tabtest", hang: float = HANG, compat: int = 0) -> Path:
    HANG = hang
    doc = Document()
    if compat:
        set_compat(doc, compat)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(30)
    for mark, text, dest in LEADS:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent, pf.first_line_indent = Mm(HANG), Mm(-HANG)
        pf.right_indent = Mm(RIGHT)
        pf.space_after = Pt(2)
        pf.tab_stops.add_tab_stop(Mm(HANG))
        # 越界制表位：位置以左缩进为原点? Word 制表位位置相对段落左边距(页边)而非缩进
        pf.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        for s in (mark + "\t", text, "\t", dest):
            r = p.add_run(s)
            r.font.size = Pt(10)
            r.font.name = "Times New Roman"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")
    path = out / f"{name}.docx"
    doc.save(str(path))
    return path


def build_table(out: Path, name: str = "tbl", mark_w: float = 14.0) -> Path:
    """两列无框表：编号列 + 正文列；正文段落左缩进 0，右缩进 = 去向通道，越界制表位到单元格右缘。"""
    from docx.oxml import OxmlElement
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(30)
    body_w = TEXT_W - mark_w
    t = doc.add_table(rows=0, cols=2)
    t.autofit = False
    tblPr = t._tbl.tblPr
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
    mar = OxmlElement("w:tblCellMar")
    for side in ("left", "right", "top", "bottom"):
        e = OxmlElement(f"w:{side}"); e.set(qn("w:w"), "0"); e.set(qn("w:type"), "dxa"); mar.append(e)
    tblPr.append(mar)
    ind = OxmlElement("w:tblInd"); ind.set(qn("w:w"), "0"); ind.set(qn("w:type"), "dxa"); tblPr.append(ind)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), (mark_w, body_w)):
        gc.set(qn("w:w"), str(int(w / 25.4 * 1440)))
    tw = OxmlElement("w:tblW"); tw.set(qn("w:w"), str(int(TEXT_W / 25.4 * 1440))); tw.set(qn("w:type"), "dxa")
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblPr.append(tw)
    for mark, text, dest in LEADS:
        row = t.add_row()
        trPr = row._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit"); trPr.append(cs)
        for cell, w in zip(row.cells, (mark_w, body_w)):
            cell.width = Mm(w)
        def runs(p, parts):
            for s in parts:
                r = p.add_run(s)
                r.font.size = Pt(10)
                r.font.name = "Times New Roman"
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")
        p0 = row.cells[0].paragraphs[0]
        p0.paragraph_format.space_after = Pt(2)
        runs(p0, [mark])
        p = row.cells[1].paragraphs[0]
        pf = p.paragraph_format
        pf.right_indent = Mm(RIGHT)
        pf.space_after = Pt(2)
        pf.tab_stops.add_tab_stop(Mm(body_w), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        runs(p, [text, "\t", dest])
    path = out / f"{name}.docx"
    doc.save(str(path))
    return path


if __name__ == "__main__":
    o = Path(sys.argv[1])
    o.mkdir(parents=True, exist_ok=True)
    print(build(o))
    print(build(o, "h20", hang=20.0))
    print(build(o, "c15", compat=15))
    print(build_table(o))
