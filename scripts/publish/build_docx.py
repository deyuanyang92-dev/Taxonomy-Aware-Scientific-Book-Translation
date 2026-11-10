#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 译文/*.md 汇编为 Word（.docx）——A4 书籍版式。

用法: python build_docx.py
输出: Rouse2022_Annelida_中文全译本.docx

版式要点
  · A4，天头 2.5 / 地脚 2.5 / 订口 3.0 / 切口 3.0 → 行宽 15 cm
  · 章首页上方留白 3.5 cm；章号小字 + 章名大字 + 英文名斜体 + 细线 + 元信息
  · 正文宋体 10.5 pt / 行距 1.45 / 段后 7 pt / 首行 2 字符
  · 三线表；图注悬挂缩进；页眉书名 + 当前章名（STYLEREF）
  · 前置部分不编页码，正文自 1 起；目录为真域，页码自动
"""
import glob, json, os, re, sys
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 书目录（脚本在 脚本/ 下）
ZH = os.path.join(BASE, '译文')

# ─────────── 版式常量 ───────────
PAGE_W, PAGE_H = Cm(21.0), Cm(29.7)
M_TOP = M_BOT = Cm(2.5)
M_LEFT = M_RIGHT = Cm(3.0)
HEADER_D, FOOTER_D = Cm(1.5), Cm(1.6)

BODY_SIZE = 10.5
BODY_LINE = 1.45
BODY_AFTER = 7
FONT_SONG, FONT_HEI, FONT_EN = '宋体', '黑体', 'Times New Roman'
INK = RGBColor(0, 0, 0)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0x80, 0x80, 0x80)

BOOK_TITLE = '环节动物 Annelida　中文全译本'

# 插图
FIG_DIR = os.path.join(BASE, '图库')
FIG_MAX_W = 15.0     # cm，等于版心宽
FIG_MAX_H = 17.0     # cm，留出图注与页眉页脚的空间
FIGS = {}
_fig_idx = os.path.join(FIG_DIR, '_index.json')
if os.path.exists(_fig_idx):
    import json as _json
    FIGS = _json.load(open(_fig_idx, encoding='utf-8'))


# ─────────── 基础工具 ───────────
def set_run(run, cn=FONT_SONG, en=FONT_EN, size=BODY_SIZE, bold=False,
            italic=False, color=None, spacing=None):
    run.font.name = en
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts'); rPr.append(rFonts)
    rFonts.set(qn('w:eastAsia'), cn)
    if '\u3000' in run.text:   # 全角空格在 Word 编辑标记下显示 □（yzz-zh 规范）
        run.text = run.text.replace('\u3000', '  ')
    if re.search(r'[\u3400-\u9fff\U00020000-\U0002ffff\u3000-\u303f\uff00-\uffef]', run.text) or (run.text.strip() in ('—', '——') and re.search(r'[\u3400-\u9fff]', getattr(run._parent, 'text', ''))):
        rFonts.set(qn('w:hint'), 'eastAsia')
    if spacing:  # 字符间距（twips）——章号「第 1 章」拉开才有书感
        sp = OxmlElement('w:spacing'); sp.set(qn('w:val'), str(spacing)); rPr.append(sp)
    return run


def _ind(p, first=None, left=None, hanging=None):
    pPr = p._element.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind'); pPr.append(ind)
    if first:
        ind.set(qn('w:firstLineChars'), str(int(first * 100)))
    if left:
        ind.set(qn('w:leftChars'), str(int(left * 100)))
    if hanging:
        ind.set(qn('w:hangingChars'), str(int(hanging * 100)))


def para(doc, text='', size=BODY_SIZE, cn=FONT_SONG, bold=False, italic=False,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY, first=2, left=0, hanging=0,
         before=0, after=BODY_AFTER, line=BODY_LINE, color=None,
         keep_next=False, style=None, spacing=None, page_break=False, keep_lines=False):
    p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
    if page_break:
        p.paragraph_format.page_break_before = True
    if keep_lines:
        p.paragraph_format.keep_together = True
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.widow_control = True
    if keep_next:
        pf.keep_with_next = True
    if first or left or hanging:
        _ind(p, first, left, hanging)
    for seg in re.split(r'(\*\*[^*]+\*\*|\*[^*]+\*)', text):
        if not seg:
            continue
        if seg.startswith('**') and seg.endswith('**'):
            set_run(p.add_run(seg[2:-2]), cn, size=size, bold=True,
                    italic=italic, color=color, spacing=spacing)
        elif seg.startswith('*') and seg.endswith('*') and len(seg) > 2:
            set_run(p.add_run(seg[1:-1]), cn, size=size, bold=bold,
                    italic=True, color=color, spacing=spacing)
        else:
            set_run(p.add_run(seg), cn, size=size, bold=bold,
                    italic=italic, color=color, spacing=spacing)
    return p


def rule(doc, width_cm=4.0, before=6, after=6, color='808080', sz=6):
    """居中的短横线（用段落下边框实现，比字符可靠）。"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = 1
    set_run(p.add_run(' '), size=1)
    pPr = p._element.get_or_add_pPr()
    bdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), str(sz))
    bottom.set(qn('w:space'), '0')
    bottom.set(qn('w:color'), color)
    bdr.append(bottom)
    pPr.append(bdr)
    ind = OxmlElement('w:ind')
    twips = int(width_cm / 2.54 * 1440 / 2)
    ind.set(qn('w:left'), str(twips)); ind.set(qn('w:right'), str(twips))
    pPr.append(ind)
    return p


def field(p, instr, placeholder='1'):
    """在段落里插入域。"""
    r1 = p.add_run(); f1 = OxmlElement('w:fldChar'); f1.set(qn('w:fldCharType'), 'begin'); r1._r.append(f1)
    r2 = p.add_run(); it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve')
    it.text = instr; r2._r.append(it)
    r3 = p.add_run(); f3 = OxmlElement('w:fldChar'); f3.set(qn('w:fldCharType'), 'separate'); r3._r.append(f3)
    r4 = p.add_run(placeholder)
    r5 = p.add_run(); f5 = OxmlElement('w:fldChar'); f5.set(qn('w:fldCharType'), 'end'); r5._r.append(f5)
    return r4


def page_restart(sec, start=1):
    """本节页码从 start 重新起算。"""
    sectPr = sec._sectPr
    for old in sectPr.findall(qn('w:pgNumType')):
        sectPr.remove(old)
    t = OxmlElement('w:pgNumType'); t.set(qn('w:start'), str(start))
    sectPr.append(t)


def setup_section(sec):
    sec.page_width, sec.page_height = PAGE_W, PAGE_H
    sec.top_margin, sec.bottom_margin = M_TOP, M_BOT
    sec.left_margin, sec.right_margin = M_LEFT, M_RIGHT
    sec.header_distance, sec.footer_distance = HEADER_D, FOOTER_D


# ─────────── 样式 ───────────
def style_doc(doc):
    n = doc.styles['Normal']
    n.font.name = FONT_EN
    n.font.size = Pt(BODY_SIZE)
    n.element.rPr.rFonts.set(qn('w:eastAsia'), FONT_SONG)
    pf = n.paragraph_format
    pf.line_spacing = BODY_LINE
    pf.space_after = Pt(BODY_AFTER)
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for i, sz in ((1, 24), (2, 12.5), (3, 10.5)):
        st = doc.styles['Heading %d' % i]
        st.font.name = FONT_EN
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.color.rgb = INK
        st.font.italic = False
        st.element.rPr.rFonts.set(qn('w:eastAsia'), FONT_HEI)
        st.paragraph_format.space_before = Pt(0)
        st.paragraph_format.space_after = Pt(0)
        st.paragraph_format.line_spacing = 1.25
        st.paragraph_format.keep_with_next = True


# ─────────── 三线表 ───────────
def _cell_border(cell, **edges):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn('w:tcBorders'))
    if borders is None:
        borders = OxmlElement('w:tcBorders'); tcPr.append(borders)
    for edge, (val, sz) in edges.items():
        el = borders.find(qn('w:' + edge))
        if el is None:
            el = OxmlElement('w:' + edge); borders.append(el)
        el.set(qn('w:val'), val)
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), '000000')


def three_line_table(doc, rows):
    ncol = max(len(r) for r in rows)
    tbl = doc.add_table(rows=len(rows), cols=ncol)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tblPr = tbl._tbl.tblPr
    # 固定列宽：按各列最长内容的字数分配，避免第三列被挤成窄条
    widths = []
    for ci in range(ncol):
        col = [(r[ci] if ci < len(r) else '') for r in rows]
        w = max(len(c) for c in col)
        widths.append(w)
    total = sum(widths) or 1
    AVAIL = 15.0                       # 版心宽度 cm
    widths = [max(1.4, AVAIL * w / total) for w in widths]
    scale = AVAIL / sum(widths)
    widths = [w * scale for w in widths]

    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed'); tblPr.append(layout)
    # 去掉默认全框线
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement('w:' + edge)
        if edge in ('top', 'bottom'):
            el.set(qn('w:val'), 'single'); el.set(qn('w:sz'), '12')
        else:
            el.set(qn('w:val'), 'none'); el.set(qn('w:sz'), '0')
        el.set(qn('w:space'), '0'); el.set(qn('w:color'), '000000')
        borders.append(el)
    tblPr.append(borders)
    # 表头行跨页重复；各行不跨页拆开
    for ri, tr in enumerate(tbl.rows):
        trPr = tr._tr.get_or_add_trPr()
        trPr.append(OxmlElement('w:cantSplit'))
        if ri == 0:
            trPr.append(OxmlElement('w:tblHeader'))
    for ri, row in enumerate(rows):
        for ci in range(ncol):
            cell = tbl.cell(ri, ci)
            cell.width = Cm(widths[ci])
            cell.text = ''
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(2.5)
            p.paragraph_format.space_after = Pt(2.5)
            p.paragraph_format.line_spacing = 1.2
            txt = (row[ci] if ci < len(row) else '').replace('**', '')
            for k, seg in enumerate(re.split(r'\*([^*]+)\*', txt)):   # 奇数段为 *斜体*
                if seg:
                    set_run(p.add_run(seg), size=8.5, bold=(ri == 0), italic=(k % 2 == 1))
            if ri == 0:                      # 表头下细线
                _cell_border(cell, bottom=('single', 6))
    # 表格整体宽度锁定
    for ci, w in enumerate(widths):
        for cell in tbl.columns[ci].cells:
            cell.width = Cm(w)
    return tbl


# ─────────── 章首页 ───────────
def chapter_opener(doc, raw_title, orig=''):
    m = re.match(r'^第\s*(\d+)\s*章[\s　]*(.*)$', raw_title)
    if m:
        num, name = m.group(1), m.group(2).strip()
    else:
        num, name = '', raw_title
    if num:
        para(doc, '第 %s 章' % num, size=11, cn=FONT_HEI,
             align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=96, after=10,
             line=1.0, spacing=60)
    # 套 Heading 1 —— 目录域靠它收录，缺了就「未找到目录项」
    # 中文章名后直接接原书标题（如「沙蚕科 NEREIDIDAE BLAINVILLE, 1818」）；章名本身是拉丁名的只排原标题
    has_cn = re.search(r'[\u3400-\u9fff\U00020000-\U0002ffff]', name)
    p = para(doc, name if has_cn or not orig else '', size=24, cn=FONT_HEI, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=18, line=1.15,
             keep_next=True, style='Heading 1')
    if orig:
        for k, seg in enumerate(re.split(r'\*([^*]+)\*', ('  ' if has_cn else '') + orig)):
            if seg:
                set_run(p.add_run(seg), cn=FONT_HEI, size=15 if has_cn else 20, bold=not has_cn,
                        italic=(k % 2 == 1))


def chapter_meta(doc, lines):
    for t in lines:
        t = t.lstrip('>').strip()
        para(doc, t, size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER, first=0,
             before=0, after=1, line=1.25, color=GRAY)


# ─────────── md 渲染 ───────────
def place_figure(doc, label):
    """按图号插入图库中的插图，宽度依版心与高度上限自适应。"""
    meta = FIGS.get(label)
    if not meta:
        return None
    path = os.path.join(FIG_DIR, meta['file'])
    if not os.path.exists(path):
        return None
    ratio = meta['ratio']
    w = FIG_MAX_W
    if w / ratio > FIG_MAX_H:          # 太高的图按高度回算宽度
        w = FIG_MAX_H * ratio
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = Pt(12)
    pf.space_after = Pt(3)
    pf.line_spacing = 1.0
    pf.first_line_indent = Pt(0)
    pf.keep_with_next = True           # 图与图注不分页
    p.add_run().add_picture(path, width=Cm(w))
    return p


_FD = os.path.join(BASE, '_fig_defer.json')
FIG_DEFER = json.load(open(_FD, encoding='utf-8')) if os.path.exists(_FD) else {}
FIG_CAP = re.compile(r'^\*\*图\s*(\d+\.\d+)\*\*')


def place_figures_near_refs(lines):
    """把章末「图版说明」里的图注行移到正文首次引用该图的段落之后（学原书：图在被描述处附近）。
    引用识别：段落中「图」字之后、到右括号或句号之前出现的「N.M」（如「图 12.1a, 12.2b–d」）。
    没被引用的图仍留在章末。"""
    caps = {}
    for k, ln in enumerate(lines):
        m = FIG_CAP.match(ln.strip())
        if m:
            caps[m.group(1)] = k
    if not caps:
        return lines
    first_ref = {}
    for k, ln in enumerate(lines):
        t = ln.strip()
        if not t or t.startswith(('#', '**图', '|', '>')) or k in caps.values():
            continue
        for seg in re.findall(r'图\s*([^）)。；]*)', t):
            for lab in re.findall(r'(?<![\d.])(\d+\.\d+)(?![\d])', seg):
                if lab in caps and lab not in first_ref:
                    first_ref[lab] = k
    moved = {lab: lines[caps[lab]] for lab in first_ref}
    # 浮动：若上一遍渲染显示该图前留下页底空白，则让其后若干字的正文先排（_fig_defer.json，由 fig_defer.py 量得）
    defer = FIG_DEFER
    for lab, k in list(first_ref.items()):
        need = defer.get(lab, 0)
        j = k
        while need > 0 and j + 1 < len(lines):
            nxt = lines[j + 1].strip()
            if nxt.startswith('# ') or nxt.startswith('|'):
                break                      # 不越过章标题和表格；可越过小节标题与其他图注（同原书：图落在下一页页首）
            j += 1
            if nxt and not nxt.startswith(('>', '**图', '#')):
                need -= len(nxt)
        first_ref[lab] = j
    after = {}
    for lab, k in sorted(first_ref.items(), key=lambda x: (x[1], [int(v) for v in x[0].split('.')])):
        after.setdefault(k, []).append(moved[lab])
    out = []
    skip = {caps[lab] for lab in first_ref}
    for k, ln in enumerate(lines):
        if k in skip:
            continue
        out.append(ln)
        for cap in after.get(k, []):
            out += ['', cap, '']
    # 图全部移走后，章末「图版说明」标题不再保留
    if len(first_ref) == len(caps):
        idx = [k for k, ln in enumerate(out) if ln.strip() == '## 图版说明']
        for k in reversed(idx):
            del out[k]
    return out


def render_md(doc, md, first_chapter=False):
    lines = md.replace('\r\n', '\n').split('\n')
    lines = place_figures_near_refs(lines)
    is_refs = bool(lines) and '参考文献' in lines[0]
    is_index = bool(lines) and '索引' in lines[0]
    index_cols = False
    i, n = 0, len(lines)
    opener_open = False        # 章首信息块尚未结束
    while i < n:
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1; continue

        # 表格
        if ln.lstrip().startswith('|'):
            block = []
            while i < n and lines[i].lstrip().startswith('|'):
                block.append(lines[i]); i += 1
            rows = [[c.strip() for c in r.strip().strip('|').split('|')] for r in block
                    if not re.match(r'^\|[\s:|-]+\|$', r.strip())]
            if rows:
                para(doc, '', size=6, first=0, before=0, after=3)   # 表前留白
                three_line_table(doc, rows)
                para(doc, '', size=6, first=0, before=0, after=6)   # 表后留白
            continue

        # 章标题
        if ln.startswith('# '):
            body = doc.element.body
            n0 = len(body)
            tail_sect = n0 and body[n0 - 1].tag.endswith('sectPr')   # 新段插在 sectPr 之前
            orig = ''
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].startswith('## ') and re.match(r'^[*A-Z]', lines[j][3:].strip()):
                orig = lines[j][3:].strip().split(' · ')[0].strip()
                lines[j] = ''          # 已并入章名，不再单独成行
            chapter_opener(doc, ln[2:].strip(), orig)
            if not first_chapter:
                # 用段前分页，不用单独的分页段：后者在整页图之后会溢出成空白页
                first_p = body[n0 - 1] if tail_sect else body[n0]
                from docx.text.paragraph import Paragraph
                Paragraph(first_p, doc._body).paragraph_format.page_break_before = True
            opener_open = True
            i += 1; continue

        # 章首英文名：紧随 # 的纯拉丁 ## 行 → 并入章首，不作节标题
        if (opener_open and ln.startswith('## ')
                and re.match(r"^[\sA-Za-z*,.()'’\-]+$", ln[3:].strip())):
            para(doc, ln[3:].strip(), size=12, cn=FONT_SONG, italic=True,
                 align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=4, after=8,
                 line=1.2, color=GRAY, keep_next=True)
            i += 1; continue

        # DOI / 原书页码行一律不排出（在章首之外出现时也跳过）
        if ln.startswith('> ') and ('DOI' in ln or '原书 PDF' in ln):
            i += 1; continue

        # 章首元信息块（> 连续行）
        if opener_open and ln.startswith('> '):
            buf = []
            while i < n and lines[i].startswith('> '):
                buf.append(lines[i]); i += 1
            # DOI 与原书页码不排出（用户 2026-11-09），只留在 md 供核对
            opener_open = False
            continue

        # 章首分隔线
        if opener_open and re.match(r'^---+$', ln.strip()):
            opener_open = False
            i += 1; continue
        if re.match(r'^---+$', ln.strip()):
            i += 1; continue

        # 索引：字母小标题 + 双栏小字条目
        if is_index and ln.startswith('## '):
            if not index_cols:        # 从第一个字母起分两栏（连续分节，页码接排）
                sec = doc.add_section(WD_SECTION.CONTINUOUS)
                sp = sec._sectPr
                for old in sp.findall(qn('w:pgNumType')):
                    sp.remove(old)
                cols = sp.find(qn('w:cols'))
                if cols is None:
                    cols = OxmlElement('w:cols'); sp.append(cols)
                cols.set(qn('w:num'), '2'); cols.set(qn('w:space'), '500')
                index_cols = True
            para(doc, ln[3:].strip(), size=10.5, cn=FONT_HEI, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                 first=0, before=8, after=2, line=1.1, keep_next=True)
            i += 1; continue
        if is_index and '\t' in ln:
            name, pp = ln.split('\t', 1)
            para(doc, name.strip() + '  ' + pp.strip(), size=8, align=WD_ALIGN_PARAGRAPH.LEFT,
                 first=0, left=1.5, hanging=1.5, before=0, after=0.5, line=1.1)
            i += 1; continue

        # 小节
        if ln.startswith('## '):
            opener_open = False
            para(doc, ln[3:].strip(), size=12.5, cn=FONT_HEI, bold=True,
                 align=WD_ALIGN_PARAGRAPH.LEFT, first=0, before=20, after=6,
                 line=1.25, keep_next=True, style='Heading 2')
            i += 1; continue
        if ln.startswith('### '):
            para(doc, ln[4:].strip(), size=10.5, cn=FONT_HEI, bold=True,
                 align=WD_ALIGN_PARAGRAPH.LEFT, first=0, before=14, after=5,
                 line=1.25, keep_next=True, style='Heading 3')
            i += 1; continue

        # 引文
        if ln.startswith('> '):
            para(doc, ln[2:].strip(), size=8.5, align=WD_ALIGN_PARAGRAPH.LEFT,
                 first=0, left=1, before=2, after=2, line=1.3, color=GRAY)
            i += 1; continue

        # 列表
        if ln.startswith('- '):
            para(doc, '·　' + ln[2:].strip(), align=WD_ALIGN_PARAGRAPH.LEFT,
                 first=0, left=1.6, hanging=1.0, before=0, after=4, line=1.4)
            i += 1; continue

        # 表标题：**表 1.1** 说明…… → 居中于表格之上
        if re.match(r'^\*\*表\s*[\d.]+\*\*', ln.strip()):
            para(doc, ln.strip(), size=9, cn=FONT_HEI, bold=False,
                 align=WD_ALIGN_PARAGRAPH.CENTER, first=0,
                 before=8, after=4, line=1.3, keep_next=True)
            i += 1; continue
        # 图注（**图 56.1**　说明…）：先插图，再排图注
        m = re.match(r'^\*\*(图版|图)\s*([\d.]+)\*\*', ln.strip())
        if m:
            place_figure(doc, ('P' if m.group(1) == '图版' else '') + m.group(2))
            # 图注段内不分页：避免两三行图注续排成孤页
            para(doc, ln.strip(), size=9.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                 first=0, left=3.4, hanging=3.4, before=7, after=10, line=1.4,
                 keep_lines=True)
            i += 1; continue

        if is_refs:   # 参考文献：照录英文，小字号、悬挂缩进、左对齐（不两端对齐，免得长网址撑开字距）
            para(doc, ln.strip(), size=8.5, cn=FONT_SONG, align=WD_ALIGN_PARAGRAPH.LEFT,
                 first=0, left=2, hanging=2, before=0, after=2.5, line=1.15)
        else:
            para(doc, ln.strip())
        i += 1


# ─────────── 前置部分 ───────────
def cover(doc):
    para(doc, '', size=10, first=0, before=0, after=0)
    para(doc, '', size=10, first=0, before=150, after=0, line=1)
    para(doc, '环节动物', size=44, cn=FONT_HEI, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=14,
         line=1.1, spacing=120)
    para(doc, 'ANNELIDA', size=15, cn=FONT_SONG,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=26,
         line=1.0, color=GRAY, spacing=180)
    rule(doc, width_cm=5.2, before=0, after=22, color='404040', sz=8)
    para(doc, 'Greg W. Rouse　Fredrik Pleijel　Ekin Tilic', size=11.5,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=6)
    para(doc, 'Oxford University Press · 2022', size=10,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=0, color=GRAY)
    para(doc, '', size=10, first=0, before=0, after=150, line=1)
    rule(doc, width_cm=3.2, before=0, after=16, color='A6A6A6', sz=4)
    para(doc, '中 文 全 译 本', size=13, cn=FONT_HEI, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=10, spacing=80)
    para(doc, '正文 79 章　·　附录 4 种', size=9.5,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=4, color=GRAY)
    para(doc, '仅供个人学习与研究使用', size=8.5,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=0, after=0, color=LIGHT)


def preface(doc, texts):
    # 段前分页（不用分页段：上一页正好排满时分页段会溢出成空白页）
    para(doc, '译　序', page_break=True, size=18, cn=FONT_HEI, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=40, after=22, spacing=100)
    for t in texts:
        para(doc, t, before=0, after=9, line=1.55)
    for t in PREFACE_SIGN:
        para(doc, t, align=WD_ALIGN_PARAGRAPH.RIGHT, first=0, before=0, after=2, line=1.4)
    para(doc, '凡　例', page_break=True, size=18, cn=FONT_HEI, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=20, after=14, spacing=100)
    for t in NOTES:   # 凡例需排在一页内
        para(doc, t, size=10, before=0, after=4, line=1.4)


def toc(doc, entries):
    """静态目录：章号 + 章名 ……页码，制表位点线引导。entries = [(label, pageno)]"""
    para(doc, '目　录', page_break=True, size=18, cn=FONT_HEI, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, first=0, before=30, after=16, spacing=100)
    for label, pg in entries:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(4)
        pf.line_spacing = 1.0
        pf.first_line_indent = Pt(0)
        pf.left_indent = Pt(0)
        # 右对齐制表位 + 点线引导，撑满版心 15 cm
        pPr = p._element.get_or_add_pPr()
        tabs = OxmlElement('w:tabs')
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'right')
        tab.set(qn('w:leader'), 'dot')
        tab.set(qn('w:pos'), str(int(15.0 / 2.54 * 1440)))
        tabs.append(tab); pPr.append(tabs)
        for k, seg in enumerate(re.split(r'\*([^*]+)\*', label)):   # 奇数段为属名，斜体
            if seg:
                set_run(p.add_run(seg), size=9.2, italic=(k % 2 == 1))
        set_run(p.add_run('\t'), size=9.2)
        set_run(p.add_run(str(pg) if pg != '' else '—'), size=9.2)


def header_footer(sec, with_header):
    if with_header:
        hp = sec.header.paragraphs[0]
        hp.text = ''
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(hp.add_run(BOOK_TITLE), size=8.5, color=GRAY)
        pPr = hp._element.get_or_add_pPr()
        bdr = OxmlElement('w:pBdr')
        b = OxmlElement('w:bottom')
        b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), '4')
        b.set(qn('w:space'), '4'); b.set(qn('w:color'), 'BFBFBF')
        bdr.append(b); pPr.append(bdr)
    fp = sec.footer.paragraphs[0]
    fp.text = ''
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if with_header:
        set_run(field(fp, ' PAGE ', '1'), size=9, color=GRAY)


# ─────────── 主流程 ───────────
def main():
    files = sorted(glob.glob(os.path.join(ZH, 'ch*.md')))
    apps = sorted(glob.glob(os.path.join(ZH, '附录*.md')))
    if not files:
        print('没有可汇编的章节'); return 1

    # 两遍编译：第一遍marker页 → Word 量页 → 第二遍写入真实页码
    toc_data = load_toc_pages()
    entries = []
    for f in files + apps:
        first = open(f, encoding='utf-8').readline().strip()
        label = toc_label(first)
        # JSON 的键是 Heading 1 的文本：去掉「第 N 章」与 markdown 星号
        h1 = first.lstrip('#').strip()
        h1 = re.sub(r'^第\s*\d+\s*章[\s　]*', '', h1).replace('*', '').strip()
        pg = toc_data.get(h1, '')
        if pg == '':   # 章名段落现含原标题：按前缀匹配（不分大小写）
            pg = next((v for k, v in toc_data.items()
                       if k.lower().startswith(h1.lower() + ' ') or k.lower() == h1.lower()), '')
        en = toc_original(f)
        lab = label.replace('*', '')
        # 目录：中文在前、原文在后；章名本身就是拉丁名的只写一次
        if en and en.replace('*', '').lower() not in lab.lower():
            lab = lab + ' ' + en
        elif en:
            lab = re.sub(re.escape(en.replace('*', '')), en, lab)   # 拉丁属名保持斜体标记
        entries.append((lab, pg))

    doc = Document()
    style_doc(doc)

    sec1 = doc.sections[0]
    setup_section(sec1)
    header_footer(sec1, with_header=False)

    cover(doc)
    preface(doc, PREFACE)
    toc(doc, entries)

    sec2 = doc.add_section(WD_SECTION.NEW_PAGE)
    setup_section(sec2)
    page_restart(sec2, 1)
    sec2.header.is_linked_to_previous = False
    sec2.footer.is_linked_to_previous = False
    header_footer(sec2, with_header=True)

    for k, f in enumerate(files + apps):
        render_md(doc, open(f, encoding='utf-8').read(), first_chapter=(k == 0))

    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(BASE, '发布', '草稿.docx')
    tmp = out + '.part'
    doc.save(tmp)
    try:
        os.replace(tmp, out)
    except PermissionError:
        import datetime
        alt = os.path.join(BASE, '发布/草稿_%s.docx'
                           % datetime.datetime.now().strftime('%m%d_%H%M'))
        try:
            os.replace(tmp, alt); out = alt
            print('※ 目标文件被占用，已写入:', os.path.basename(alt))
        except PermissionError:
            print('※ 无法写入（文件被占用）：', tmp)
    print('已生成:', os.path.basename(out), '｜章:', len(files), '｜附录:', len(apps))
    return 0


APP_EN = {'术语表': 'Glossary', '彩图版': 'Plates', '参考文献': 'References', '索引': 'Index'}


def toc_original(md_path):
    """章的原文名：取 md 第一个「## 」行（原书章名 + 命名人），去掉命名人与年份，改为常规大小写。"""
    lines = open(md_path, encoding='utf-8').read().split('\n')[:8]
    first = lines[0]
    if first.startswith('# 附录'):
        return next((v for k, v in APP_EN.items() if k in first), '')
    sub = next((l[3:].strip() for l in lines[1:] if l.startswith('## ')), '')
    if not sub or not re.match(r'[*A-Za-z]', sub):
        return 'Anatomy' if '解剖学' in first else ''
    sub = sub.split(' · ')[0].strip()
    italic = sub.startswith('*')
    # 带命名人与年份的（如「NEPHTYIDAE GRUBE, 1850」「TRICHOBRANCHIDAE MALMGREN 1866」）：类群名即第一个词
    name = sub.split()[0] if re.search(r'\d{4}\s*$', sub) else sub
    name = name.replace('*', '').strip()
    if name.isupper():
        w = name.lower().split()
        name = ' '.join([w[0].capitalize()] + w[1:])
    return f'*{name}*' if italic else name


def toc_label(first_line):
    """把「# 第 1 章　绪论与系统学」整理成目录条目「1　绪论与系统学」。"""
    t = first_line.lstrip('#').strip()
    m = re.match(r'^第\s*(\d+)\s*章[\s　]*(.*)$', t)
    if m:
        return '%s　%s' % (m.group(1), m.group(2))
    m = re.match(r'^附录\s*([A-Z])[\s　]*(.*)$', t)
    if m:
        return '附录 %s　%s' % (m.group(1), m.group(2))
    return t.replace('　', ' ')


def load_toc_pages():
    """读 _toc_pages.json（由 collect_pages.py 用 Word 量得）。缺失则返回空 → 目录页码占位 0。"""
    p = os.path.join(BASE, '_toc_pages.json')
    if os.path.exists(p):
        import json
        return json.load(open(p, encoding='utf-8'))
    return {}


def _load_preface_config():
    """译序正文与署名读自同目录可选文件 preface_config.json（不入库，含个人联系方式）。
    格式见 preface_config.example.json；文件不存在时两段均为空列表。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'preface_config.json')
    if not os.path.exists(p):
        return [], []
    with open(p, encoding='utf-8') as f:
        cfg = json.load(f)
    return list(cfg.get('preface', [])), list(cfg.get('preface_sign', []))


PREFACE, PREFACE_SIGN = _load_preface_config()

NOTES = [
    '本书是 Greg W. Rouse、Fredrik Pleijel 与 Ekin Tilic 合著《Annelida》（Oxford University Press, 2022；DOI: 10.1093/oso/9780199692309.001.0001）的中文全译本。原书正文 79 章，逐一对应环节动物各高级阶元与科级类群；本译本按章编译，章序与原书一致，仅第 2 章（解剖学）因篇幅较长析为两部分。',
    '各章结构依原书分为导言、形态与生理、自然史、系统学四部分，章末附该章图版的分图说明。原书插图 155 幅、彩色图版 16 版均按原图收录。',
    '学名处理原则：拉丁学名一律照原书保留（属名、种名斜体），不改为现行有效名。科名首次出现时写作「中文名（拉丁名）」，其后用中文；属名、种名只在每章首次出现时于拉丁名前加注中文名（如「白毛虫属 *Pilargis*」「小头虫 *Capitella capitata*」），其后仍用拉丁名。',
    '中文名的依据依次为：《中国动物志》多毛纲叶须虫目卷（吴宝铃等，1997）、沙蚕目卷（孙瑞平、杨德渐，2004）、缨鳃虫目卷（孙瑞平、杨德渐，2014），以及星虫动物门、螠虫动物门卷；杨德渐、孙瑞平《中国近海多毛环节动物》（1988）；刘瑞玉主编《中国海洋生物名录》（2008）。各书说法不一时，以正式记述该类群的志书为准（如竹节虫科 Maldanidae 依杨德渐、孙瑞平 1988 与名录，而不取叶须虫目卷分类总表中顺带列出的「节节虫科」）；名录、志书均未收录的，参考专门研究该类群的学位论文（如王跃云、孙悦、王伟娜等）；以上来源均未收录的，依 WoRMS 的有效名、模式属和学名词源暂拟中文名，每章首次出现时注「暂定名」。分类地位变动的类群（如亚科升为科）沿用原有中文名。',
    '体例上须说明一处：原书目名作 -ida（如 Phyllodocida 叶须虫目），《中国动物志》叶须虫目卷目名作 -morpha（如 Phyllodocemorpha）。本译本**章序从原书，译名从动物志**，故同一阶元在层级称呼上略有出入，非译名不一。',
    '形态术语先从志书用字，志书未用的依全国科学技术名词审定委员会《动物学名词》（第 2 版，2021），二者不同处在附录术语表中注明。有三处关键辨别：**触手（antenna）** 为上皮细胞突起、具单一神经、受脑控制，位于口前叶背面或前缘；**触角（palp）** 由脑与围咽神经环两条神经支配，更敏感，主司感觉与捕食；围口节的 cirrus 才是**触须**。三者互不替代。疣足依结构分**双叶型**、**单叶型**、**亚双叶型**；疣足内部较粗的刚毛称**足刺**（内刚毛）；疣足上的叶状附器称**舌叶**（ligule）。专用术语首次出现时附英文原词。',
    '原文中个别交叉引用与图号有误、或经 OCR 后文字残损之处，译文一律照录并加注「原文如此」或「原书如此」，不作径改；凡属明显的排印讹误而文意可辨者，随文订正。原书参考文献照录英文原文，列为附录 C，不作翻译。一切分类学判断请以英文原书及所引原始文献为准。',
]

if __name__ == '__main__':
    sys.exit(main())
