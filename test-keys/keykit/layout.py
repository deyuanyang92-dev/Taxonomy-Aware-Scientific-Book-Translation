"""排版：照 proto/tabtest.py build_table 已验证方案（两列无框固定布局表；不得改表格属性）。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from .ir import Couplet, KeyIR, Lead
from .profile import Profile

WJOIN = "\u2060"  # U+2060 WORD JOINER

PT_MM = 0.3528
_BIN = re.compile(r"[A-Z][a-z]+(?:[ \xa0][a-z]{3,})?")
_HIGHER = ("idae", "inae", "oidea", "ini")


def est_width_mm(text: str, size: float) -> float:
    w = 0.0
    for ch in text:
        w += size if ord(ch) > 0x2E7F else 0.5 * size
    return w * PT_MM


def mark_texts(c: Couplet, k0: int, profile: Profile) -> list[str]:
    """各分支编号文本。k0 为本偶句首条在全表的 0 起序号（serial/number 用）。"""
    n = len(c.leads)
    sl = profile.second_lead
    out: list[str] = []
    for i in range(n):
        if sl == "serial":
            partner = k0 + (1 - i if n == 2 else 0)
            out.append(f"{k0 + i + 1} ({partner + 1})." if n == 2 else f"{k0 + i + 1}.")
        elif sl == "number":
            out.append(f"{k0 + i + 1}.")
        elif i == 0:
            out.append(f"{c.num} ({c.backref})." if sl == "backref" and c.backref else f"{c.num}.")
        elif sl == "prime":
            out.append(f"{c.num}'" + "'" * (i - 1) + ".")
        else:
            out.append("—")
    return out


def md_parts(s: str) -> list[tuple[str, bool]]:
    """源文里的 markdown 斜体 *x* -> (x, True)，去掉星号。"""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in re.finditer(r"\*([^*]+)\*", s):
        if m.start() > pos:
            out.append((s[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], False))
    return out or [("", False)]


def dest_parts(ld: Lead, profile: Profile) -> list[tuple[str, bool]]:
    """去向 runs：(文本, 是否斜体)。"""
    if ld.kind == "taxon":
        parts: list[tuple[str, bool]] = []
        if profile.dest_zh_name and ld.name_zh:
            # 中文名与学名不拆行：半角空格 + U+2060。不用 NBSP：LibreOffice 按前字取宋体，NBSP 宽一整字（实测 10pt vs 5pt）
            parts.append((ld.name_zh + " " + WJOIN, False))
        m = _BIN.search(ld.target) if "*" not in ld.target else None
        if "*" in ld.target:
            parts.extend(md_parts(ld.target))
        elif m:
            first = m.group(0).split()[0].split("\xa0")[0]
            ital = not first.endswith(_HIGHER)
            if ld.target[: m.start()]:
                parts.append((ld.target[: m.start()], False))
            parts.append((m.group(0), ital))
            if ld.target[m.end():]:
                parts.append((ld.target[m.end():], False))
        else:
            parts.append((ld.target, False))
    else:
        parts = [(ld.target, False)]
    if ld.fig:
        # 图号内部禁断：LibreOffice 会在「图」与数字之间断行（2026-11-23 样张），用 U+2060 字连接符粘住
        fig = WJOIN.join(ld.fig)
        if profile.figref == "before":
            parts.insert(0, (fig + "\xa0", False))
        else:
            parts.append((WJOIN + fig, False))
    return parts


def dest_text(ld: Lead, profile: Profile) -> str:
    return "".join(t for t, _ in dest_parts(ld, profile))


def channel_mm(irs: list[KeyIR], profile: Profile) -> float:
    """去向通道宽 RIGHT（全表统一，L8）：去向估宽的第 80 百分位 + 4mm，限在 [15mm, 0.4 * 正文列宽]。

    取百分位而非最大值：一两个特长去向（学名 + 图号）会把通道撑宽，全表正文过早折行、右侧大片留白
    （2026-11-23 Imajima 样张）。超出通道的分支由 lead_right_mm 单独加宽右缩进。
    """
    mw = mark_width_mm(irs, profile)
    body_w = profile.text_w_mm - mw
    ws = sorted(est_width_mm(dest_text(ld, profile), profile.font_size)
                for ir in irs for c in ir.couplets for ld in c.leads)
    if not ws:
        return 15.0
    p80 = ws[min(len(ws) - 1, int(0.8 * len(ws)))]
    return max(15.0, min(p80 + 4.0, 0.4 * body_w))


def lead_right_mm(ld: Lead, profile: Profile, channel: float) -> float:
    """单条分支的右缩进：通常 = 通道宽；去向比通道宽时加宽到能放下去向，保证去向不折行（L3 优先于 L8）。"""
    return max(channel, est_width_mm(dest_text(ld, profile), profile.font_size) + 4.0)


def mark_width_mm(irs: list[KeyIR], profile: Profile) -> float:
    longest = 1
    for ir in irs:
        k0 = 0
        for c in ir.couplets:
            for m in mark_texts(c, k0, profile):
                longest = max(longest, len(m))
            k0 += len(c.leads)
    return max(8.0, longest * 0.55 * profile.font_size * PT_MM + 2.0)


def _runs(p, parts: list[tuple[str, bool]], profile: Profile, bold: bool = False) -> None:
    for s, ital in parts:
        r = p.add_run(s)
        r.font.size = Pt(profile.font_size)
        r.font.name = profile.latin_font
        r.font.italic = ital or None
        r.font.bold = bold or None
        rf = r._element.rPr.rFonts
        rf.set(qn("w:eastAsia"), profile.cjk_font)


def _table(doc, irs_ir: KeyIR, profile: Profile, mark_w: float, right: float, breaks: set[int] | None = None,
           k_start: int = 0) -> None:
    text_w = profile.text_w_mm
    body_w = text_w - mark_w
    t = doc.add_table(rows=0, cols=2)
    t.autofit = False
    tblPr = t._tbl.tblPr
    if tblPr.find(qn("w:tblLayout")) is None:
        lay = OxmlElement("w:tblLayout")
        lay.set(qn("w:type"), "fixed")
        tblPr.append(lay)
    mar = OxmlElement("w:tblCellMar")
    for side in ("left", "right", "top", "bottom"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:w"), "0")
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    tblPr.append(mar)
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), "0")
    ind.set(qn("w:type"), "dxa")
    tblPr.append(ind)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), (mark_w, body_w), strict=True):
        gc.set(qn("w:w"), str(int(w / 25.4 * 1440)))
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int(text_w / 25.4 * 1440)))
    tw.set(qn("w:type"), "dxa")
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblPr.append(tw)
    k0 = k_start
    for c in irs_ir.couplets:
        marks = mark_texts(c, k0, profile)
        k0 += len(c.leads)
        for i, (ld, mk) in enumerate(zip(c.leads, marks, strict=True)):
            row = t.add_row()
            trPr = row._tr.get_or_add_trPr()
            trPr.append(OxmlElement("w:cantSplit"))
            for cell, w in zip(row.cells, (mark_w, body_w), strict=True):
                cell.width = Mm(w)
            keep = i < len(c.leads) - 1  # L6：同偶句两行不拆页
            p0 = row.cells[0].paragraphs[0]
            p0.paragraph_format.space_after = Pt(2)
            p0.paragraph_format.keep_with_next = keep
            _runs(p0, [(mk, False)], profile)
            p = row.cells[1].paragraphs[0]
            pf = p.paragraph_format
            pf.right_indent = Mm(lead_right_mm(ld, profile, right) if profile.overflow == "wrap" else 0)
            pf.space_after = Pt(2)
            pf.keep_with_next = keep
            pf.tab_stops.add_tab_stop(Mm(body_w), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            if breaks and (k0 - len(c.leads) + i) in breaks:
                # L5(B)：点线填满本行，下一行点线接去向（第一遍量出点线过短的分支才这样排）
                _runs(p, md_parts(ld.text) + [("\t\n\t", False)] + dest_parts(ld, profile), profile)
            else:
                _runs(p, md_parts(ld.text) + [("\t", False)] + dest_parts(ld, profile), profile)


def render_docx(irs: list[KeyIR], profile: Profile, out: Path,
                breaks: dict[int, set[int]] | None = None,
                page_before: dict[int, set[int]] | None = None) -> Path:
    """breaks: {表序号: {表内分支平铺序号}}，这些分支按 L5(B) 排（fill 模式第二遍用）。

    page_before: {表序号: {偶句序号(0 起)}}，在这些偶句前拆表并分页（L6 第二遍用；LibreOffice
    不认表格行间的 keep_with_next，2026-11-23 keys_2007 偶句 13 实测跨页）。
    """
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm((210 - profile.text_w_mm) / 2)
    st = doc.styles["Normal"]
    st.font.size = Pt(profile.font_size)
    st.font.name = profile.latin_font
    st.element.rPr.rFonts.set(qn("w:eastAsia"), profile.cjk_font)
    mark_w = mark_width_mm(irs, profile)
    right = channel_mm(irs, profile)
    for ki, ir in enumerate(irs):
        hp = doc.add_paragraph()
        hp.paragraph_format.keep_with_next = True
        hp.paragraph_format.space_before = Pt(12)
        hp.paragraph_format.space_after = Pt(4)
        _runs(hp, [(ir.heading, False)], profile, bold=True)
        cuts = sorted(i for i in (page_before or {}).get(ki, set()) if 0 < i < len(ir.couplets))
        k = 0
        for a, b in zip([0, *cuts], [*cuts, len(ir.couplets)], strict=True):
            if a:  # 空段落自身分页（1pt、无段距），避免表格正好写满一页时多出空白页
                bp = doc.add_paragraph()
                bp.paragraph_format.page_break_before = True
                bp.paragraph_format.space_before = bp.paragraph_format.space_after = Pt(0)
                bp.paragraph_format.line_spacing = Pt(1)
                bp.add_run("").font.size = Pt(1)
            part = KeyIR(heading=ir.heading, couplets=ir.couplets[a:b], lang=ir.lang, source_style=ir.source_style)
            _table(doc, part, profile, mark_w, right, (breaks or {}).get(ki), k_start=k)
            k += sum(len(c.leads) for c in part.couplets)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def to_pdf(docx: Path) -> Path:
    docx = Path(docx)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
        check=True, capture_output=True, timeout=300,
    )
    return docx.with_suffix(".pdf")
