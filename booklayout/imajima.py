#!/usr/bin/env python3
"""Imajima 三卷原书版式（profile）渲染器——booklayout 的一个版式子模块。

为什么单独一个模块：六本交付书的版式由 `builder.py` 的默认值决定，不能动；
本模块只服务 Imajima 日文志书的版式复刻，复用 `builder` 的 add_runs / para /
clean_text / BookMeta / 图裁剪查找，不复制排版逻辑。

版式依据全部来自原书实测（见 日本-imajima/排版/原书排版分析_20261118.md）：
  页面 162 × 254 mm；版心 126 × 212（左 18 / 右 18 / 上 20 / 下 22）
  正文 10 pt / 固定行距 14 pt；首行缩进 2 字
  概述页（科、亚科の解説）**单栏通栏**
  种记述页：图注块（Fig.N / 属名+命名人 / 种名+命名人 / 和名，居中）
            → 文献引证行 → **双栏正文**（每栏 65.7 mm、栏间 10.5）
            → 图（通栏）+ 图说明
  检索表：通栏、10 pt、条目号缩进 9 mm、折行悬挂 16 mm、点线铺到右版口
  页码在**外角**，无书眉

用法：
    python -m booklayout.imajima --aligned <aligned.json> --figures <figures 目录> \\
        --out <out.docx> [--pages 5-24] [--metadata <metadata.json>]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from booklayout.builder import BookMeta, add_runs, clean_text


@dataclass(frozen=True)
class Layout:
    page_w: float = 162.0
    page_h: float = 254.0
    margin_l: float = 10.0
    margin_r: float = 10.0
    margin_t: float = 20.0
    margin_b: float = 22.0
    body_pt: float = 10.0
    lead_pt: float = 14.0
    indent_pt: float = 20.0      # 首行缩进 2 字
    key_pt: float = 10.0
    key_mark_mm: float = 9.0     # 条目号缩进
    key_hang_mm: float = 16.0    # 折行悬挂
    key_min_leader_mm: float = 12.0
    caption_pt: float = 10.0     # 图注块
    kana_pt: float = 12.0        # 和名
    legend_pt: float = 8.0       # 图说明 a: b: c:
    citation_pt: float = 8.5
    ref_pt: float = 8.5
    folio_pt: float = 8.0
    column_gap_mm: float = 10.5

    @property
    def text_w(self) -> float:
        return self.page_w - self.margin_l - self.margin_r


LAYOUT = Layout()
_CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")


def _font(run, size: float, bold: bool = False, italic: bool = False) -> None:
    run.font.name = "Garamond"
    run.font.size = Pt(size)
    run.bold, run.italic = bold, italic
    rpr = run._element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:eastAsia"), "宋体")
    if _CJK.search(run.text or ""):
        rpr.rFonts.set(qn("w:hint"), "eastAsia")


def setup(doc, layout: Layout) -> None:
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(layout.page_w), Mm(layout.page_h)
    sec.left_margin, sec.right_margin = Mm(layout.margin_l), Mm(layout.margin_r)
    sec.top_margin, sec.bottom_margin = Mm(layout.margin_t), Mm(layout.margin_b)
    sec.header_distance, sec.footer_distance = Mm(10), Mm(12)
    st = doc.styles["Normal"]
    st.font.name = "Garamond"
    st.font.size = Pt(layout.body_pt)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = st.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = Pt(layout.lead_pt)
    ppr = st.element.get_or_add_pPr()
    # Word 默认允许行末标点悬出版口 3.6 mm；原书没有这种外悬。
    for tag, val in (("w:overflowPunct", "0"), ("w:kinsoku", "1"),
                     ("w:autoSpaceDE", "1"), ("w:autoSpaceDN", "1")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        ppr.append(el)
    doc.settings.odd_and_even_pages_header_footer = True
    for footer in (sec.footer, sec.even_page_footer):
        footer.is_linked_to_previous = False


def _folio(par, align):
    par.alignment = align

    def fld(kind=None, instr=None):
        r = par.add_run()
        _font(r, LAYOUT.folio_pt)
        if kind:
            e = OxmlElement("w:fldChar")
            e.set(qn("w:fldCharType"), kind)
            r._r.append(e)
        elif instr:
            e = OxmlElement("w:instrText")
            e.set(qn("xml:space"), "preserve")
            e.text = instr
            r._r.append(e)

    fld("begin"); fld(instr=" PAGE "); fld("separate")
    _font(par.add_run("1"), LAYOUT.folio_pt); fld("end")


def footer_outer(sec) -> None:
    _folio(sec.footer.paragraphs[0], WD_ALIGN_PARAGRAPH.RIGHT)
    _folio(sec.even_page_footer.paragraphs[0], WD_ALIGN_PARAGRAPH.LEFT)


def para(doc, text: str = "", *, size: float | None = None, bold: bool = False,
         italic: bool = False, align=None, first: float = 0.0, left: float = 0.0,
         before: float = 0.0, after: float = 0.0, hang: float = 0.0,
         keep: bool = False, line: float | None = None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = Pt(line) if line else Pt(LAYOUT.lead_pt)
    pf.first_line_indent = Pt(first)
    pf.left_indent = Pt(left)
    if hang:
        pf.first_line_indent = Pt(-hang)
    pf.keep_with_next = keep
    if align is not None:
        p.alignment = align
    if text:
        add_runs(p, text, size if size is not None else LAYOUT.body_pt, bold, italic)
    return p


# ---- 检索表 ----
LEADER = re.compile(r"\s*(?:…+|\.{3,}|·{3,})\s*")


def key_line(doc, text: str) -> None:
    m = LEADER.search(text)
    if not m:
        para(doc, text, size=LAYOUT.key_pt,
             first=LAYOUT.key_mark_mm * 72 / 25.4,
             align=WD_ALIGN_PARAGRAPH.LEFT)
        return
    left = LEADER.sub("", text[:m.start()]).strip()
    right = re.sub(r"[…\.·]{2,}", "　", text[m.end():]).strip()
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Mm(LAYOUT.key_hang_mm)
    pf.first_line_indent = Mm(LAYOUT.key_mark_mm - LAYOUT.key_hang_mm)
    pf.line_spacing = Pt(LAYOUT.lead_pt)
    pf.tab_stops.add_tab_stop(Mm(LAYOUT.text_w - 1.0), WD_TAB_ALIGNMENT.RIGHT,
                              WD_TAB_LEADER.DOTS)
    add_runs(p, left, LAYOUT.key_pt)
    width = sum(LAYOUT.key_pt if (_CJK.match(c) or c in "，。；：、（）") else LAYOUT.key_pt * 0.5
                for c in left)
    room = LAYOUT.text_w * 72 / 25.4 - LAYOUT.key_hang_mm * 72 / 25.4 - width
    if room < LAYOUT.key_min_leader_mm * 72 / 25.4:
        p.add_run().add_break()
    p.add_run("\t")
    if right:
        start = len(p.runs)
        add_runs(p, right, LAYOUT.key_pt)
        for r in p.runs[start:]:
            r.text = r.text.replace(" ", "\u202f")


# ---- 图 ----
def picture(doc, path: Path, max_w: float | None = None, max_h: float = 132.0) -> None:
    from docx.image.image import Image as DocxImage
    max_w = max_w or LAYOUT.text_w
    try:
        im = DocxImage.from_file(str(path))
        w, h = im.width / 36000.0, im.height / 36000.0
    except Exception:
        return
    if not w or not h:
        return
    if h > max_h:
        w, h = w * max_h / h, max_h
    if w > max_w:
        h, w = h * max_w / w, max_w
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.0
    p.add_run().add_picture(str(path), width=Mm(w))


# ---- 分栏 ----
def _set_cols(section, num: int, gap_mm: float) -> None:
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:cols")):
        sect_pr.remove(old)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), str(num))
    if num > 1:
        cols.set(qn("w:space"), str(int(gap_mm * 56.7)))
        cols.set(qn("w:equalWidth"), "1")
    sect_pr.append(cols)


class ColumnFlow:
    """把连续正文放进双栏 section，出栏后自动恢复单栏。"""

    def __init__(self, doc, layout: Layout):
        self.doc, self.layout, self.on = doc, layout, False

    def start(self) -> None:
        if self.on:
            return
        sec = self.doc.add_section(WD_SECTION.CONTINUOUS)
        _set_cols(sec, 2, self.layout.column_gap_mm)
        # 新 section 的页边距必须显式写，否则 Word 继承默认 25.4 mm
        sec.left_margin, sec.right_margin = Mm(self.layout.margin_l), Mm(self.layout.margin_r)
        sec.top_margin, sec.bottom_margin = Mm(self.layout.margin_t), Mm(self.layout.margin_b)
        self.on = True

    def stop(self) -> None:
        if not self.on:
            return
        sec = self.doc.add_section(WD_SECTION.CONTINUOUS)
        _set_cols(sec, 1, self.layout.column_gap_mm)
        sec.left_margin, sec.right_margin = Mm(self.layout.margin_l), Mm(self.layout.margin_r)
        sec.top_margin, sec.bottom_margin = Mm(self.layout.margin_t), Mm(self.layout.margin_b)
        self.on = False


# ---- 种记述块 ----
FIG_ONLY = re.compile(r"^Fig\.?\s*(\d+)\s*$", re.I)
GENUS_LINE = re.compile(r"^[A-Z][a-z]+(\s+[A-Z][a-z]+)?,?\s+[A-Z][\w.\-]+.*,\s*\d{4}\s*$")
SPECIES_LINE = re.compile(r"^[A-Z][a-z]+\s+[a-z][a-z\-]+.*$")
KANA = re.compile(r"^[\u30a0-\u30ffー・\s]+$")


def _species_block(blocks, i):
    """从 caption「Fig.N」起，识别 属名行 / 种名行 / 和名 三行。"""
    if not FIG_ONLY.match(clean_text(blocks[i].get("translation") or "")):
        return None
    j, names = i + 1, []
    while j < len(blocks) and len(names) < 3:
        b = blocks[j]
        t = clean_text(b.get("translation") or "")
        if not t:
            j += 1
            continue
        if KANA.match(t) or t.startswith("日名"):
            names.append(("kana", j))
            j += 1
            break
        if GENUS_LINE.match(t) or SPECIES_LINE.match(t):
            names.append(("name", j))
            j += 1
            continue
        break
    return names if len(names) >= 2 else None


def species_caption(doc, fig_label: str, genus: str, species: str, kana: str | None) -> None:
    """原书图注块：Fig.N / 属名+命名人 / 种名+命名人 / 和名，四行居中。"""
    para(doc, fig_label, size=LAYOUT.caption_pt, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=8, after=0, keep=True)
    para(doc, genus, size=LAYOUT.caption_pt, align=WD_ALIGN_PARAGRAPH.CENTER,
         after=0, keep=True)
    para(doc, species, size=LAYOUT.caption_pt, align=WD_ALIGN_PARAGRAPH.CENTER,
         after=0, keep=True)
    if kana:
        para(doc, kana, size=LAYOUT.kana_pt, align=WD_ALIGN_PARAGRAPH.CENTER,
             before=2, after=6, keep=True)


def render(doc, data, meta: BookMeta, figs_by_page, layout: Layout,
           page_from: int, page_to: int) -> dict:
    stats = {"pages": 0, "keys": 0, "figs": 0, "species": 0, "body": 0}
    flow = ColumnFlow(doc, layout)
    state = {"latin": ""}

    def body_para(text):
        legend = re.match(r"^[a-z]\s*[:：]", text)
        para(doc, text, size=layout.legend_pt if legend else None,
             first=0 if legend else layout.indent_pt,
             align=WD_ALIGN_PARAGRAPH.LEFT if legend else WD_ALIGN_PARAGRAPH.JUSTIFY)
        stats["body"] += 1

    def heading_para(text, level):
        if level <= 2:
            flow.stop()
            m = re.match(r"^(.*?)[\s　]*([A-Z][a-z]+idae|[A-Z][a-z]+inae)(.*)$", text)
            if m and m.group(1).strip() and m.group(2):
                para(doc, m.group(1).strip(), size=17, bold=True,
                     align=WD_ALIGN_PARAGRAPH.CENTER, before=10, after=2,
                     keep=True, line=22)
                para(doc, (m.group(2) + m.group(3)).strip(), size=10, italic=True,
                     align=WD_ALIGN_PARAGRAPH.CENTER, after=12, keep=True)
                state["latin"] = (m.group(2) + m.group(3)).strip()
            else:
                para(doc, text, size=12, bold=True,
                     align=WD_ALIGN_PARAGRAPH.CENTER, before=10, after=6,
                     keep=True, line=16)
        else:
            para(doc, text, size=layout.kana_pt,
                 align=WD_ALIGN_PARAGRAPH.CENTER, before=2, after=4, keep=True)

    for p in data["pages"]:
        pn = int(p["page"])
        if not (page_from <= pn <= page_to):
            continue
        stats["pages"] += 1
        blocks = p["blocks"]
        crops = list(figs_by_page.get(pn, []))
        si = next((k for k in range(len(blocks)) if _species_block(blocks, k)), None)
        if si is not None:
            # 种记述页：图注块在页顶 → 文献引证 → 双栏正文 → 图在页脚
            flow.stop()
            spec = _species_block(blocks, si)
            names = [clean_text(blocks[j].get("translation") or "") for _, j in spec]
            consumed = {si} | {j for _, j in spec}
            # 属名行在源页里常排在 Fig.N 之前，原书排在 Fig.N 之后
            genus = ""
            if si > 0:
                prev = clean_text(blocks[si - 1].get("translation") or "")
                if prev and re.search(r",\s*(?:18|19|20)\d{2}\s*$", prev) and len(prev) < 60:
                    genus = prev
                    consumed.add(si - 1)
            species = names[0] if names else ""
            kana = names[1] if len(names) > 1 else None
            if not genus and len(names) > 1:
                genus, species, kana = names[0], names[1], names[2] if len(names) > 2 else None
            species_caption(doc, clean_text(blocks[si].get("translation") or ""),
                            genus, species, kana)
            stats["species"] += 1
            nxt = max(consumed) + 1
            if nxt < len(blocks):
                t = clean_text(blocks[nxt].get("translation") or "")
                if t and (blocks[nxt].get("role") in ("ref", "citation")
                          or re.match(r"^[A-Z][a-z]+ [a-z].*[:：]", t)):
                    para(doc, t, size=layout.citation_pt, before=2, after=4,
                         align=WD_ALIGN_PARAGRAPH.LEFT)
                    consumed.add(nxt)
            flow.start()
            for k, b in enumerate(blocks):
                if k in consumed:
                    continue
                text = clean_text(b.get("translation") or "")
                if not text or b.get("role") in ("caption", "ref"):
                    continue
                body_para(text)
            flow.stop()
            while crops:
                picture(doc, crops.pop(0))
                stats["figs"] += 1
            continue
        for b in blocks:
            role = b.get("role") or "body"
            text = clean_text(b.get("translation") or "")
            if not text:
                continue
            if role == "key":
                flow.stop()
                key_line(doc, text)
                stats["keys"] += 1
            elif role == "heading":
                heading_para(text, int(b.get("level") or 1))
            elif role == "caption":
                flow.stop()
                if crops:
                    picture(doc, crops.pop(0))
                    stats["figs"] += 1
                para(doc, text, size=10.0, before=3, after=2, keep=True)
            elif role == "ref":
                para(doc, text, size=layout.ref_pt, left=4.0, hang=4.0,
                     align=WD_ALIGN_PARAGRAPH.LEFT)
            elif role == "index":
                # 图内标注词的 OCR 残行，原书不是正文
                para(doc, text, size=8.0, align=WD_ALIGN_PARAGRAPH.LEFT)
            else:
                # 科名下方已排过拉丁科名，正文里重复的一行丢掉
                if (text.strip() == state.get("latin")
                        and len(text.strip()) < 40):
                    continue
                body_para(text)
        flow.stop()
        while crops:
            picture(doc, crops.pop(0))
            stats["figs"] += 1
    flow.stop()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Imajima 原书版式（booklayout 子模块）")
    ap.add_argument("--aligned", type=Path, required=True)
    ap.add_argument("--figures", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pages", help="源页范围，如 5-24")
    ap.add_argument("--metadata", type=Path)
    args = ap.parse_args()

    data = json.loads(args.aligned.read_text(encoding="utf-8"))
    meta = BookMeta()
    if args.metadata:
        meta = BookMeta.from_json(args.metadata)
    audit = json.loads((args.figures / "source_figure_audit.json").read_text(encoding="utf-8"))
    figs_by_page: dict[int, list[Path]] = {}
    for f in audit["figures"]:
        p = args.figures / f["crop"]
        if p.exists():
            figs_by_page.setdefault(int(f["source_pdf_page"]), []).append(p)

    lo, hi = 1, 10**6
    if args.pages:
        a, _, bb = args.pages.partition("-")
        lo = int(a)
        hi = int(bb or a)

    doc = Document()
    setup(doc, LAYOUT)
    footer_outer(doc.sections[0])
    stats = render(doc, data, meta, figs_by_page, LAYOUT, lo, hi)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.out)
    print(f"{args.out}  {stats}")


if __name__ == "__main__":
    main()
