#!/usr/bin/env python3
"""DeepSeek-optimized DOCX/PDF book builder.

Builds an aligned translation as a typeset book: front matter, contents,
body, figures, identification keys, references, appendix and a re-paginated
index. Two passes: the first PDF supplies the source-page -> output-page map
used by the contents and index.

Initial port from the Vol. 48 task-level builder, generalized to accept any
aligned JSON and book metadata. Marked DeepSeek-optimized for later review.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.image.image import Image as DocxImage

BODY_FONT = "Garamond"
TEXT_W = 134.0  # mm
PAGE_W, PAGE_H = 170.0, 240.0
LEADER_RE = re.compile(r"\s*(?:\.\s*){3,}\s*")
FIG_RE = re.compile(r"\bFig(?:s)?\.\s*(\d+[′']?)")


@dataclass
class BookMeta:
    """Book-level metadata; everything edition-specific lives here."""

    title: str = "Untitled"
    volume: str = ""
    subtitle: str = ""
    edition: str = ""
    publisher: str = ""
    notes: str = ""
    running_left: str = ""
    running_right: str = ""
    contents_title: str = "CONTENTS"
    index_title: str = "ALPHABETICAL INDEX OF TAXONOMIC NAMES"
    abstract_page: int | None = None
    abstract_cut: str = ""
    include_front_matter: bool = False
    authors_title: str = "AUTHORS"
    authors: list[tuple[str, str]] = field(default_factory=list)
    contributions_title: str = "CONTRIBUTIONS"
    contributions: list[tuple[str, str]] = field(default_factory=list)
    license_note: str = ""
    chapter_titles: dict[str, str] = field(default_factory=dict)
    body_start_page: int = 1
    folio_offset: int = 3
    skip_after_page: int | None = None
    index_chapter: str = ""
    index_intro_prefix: str = "Only the scientific names"
    skip_headings: list[str] = field(default_factory=list)
    entry_prefixes: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: Path) -> "BookMeta":
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = dict(raw)
        data["authors"] = [tuple(x) for x in data.get("authors", [])]
        data["contributions"] = [tuple(x) for x in data.get("contributions", [])]
        return cls(**data)

    def display(self, chapter: str, source_title: str) -> str:
        return self.chapter_titles.get(chapter, source_title or chapter)


@dataclass
class BookPaths:
    aligned: Path
    figures_dir: Path
    translation: Path | None = None


def clean_text(s: str) -> str:
    s = re.sub(r'[\u01a4\u0530-\u058f]', '', s)
    s = s.replace('\u3000', ' ').replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def load_aligned(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_genus_set(data: dict) -> set[str]:
    names: set[str] = set()
    for p in data['pages']:
        for b in p['blocks']:
            t = b.get('text', '')
            m = re.match(r'^(?:Familia|Subfamilia|G[eé]nero|Subg[eé]nero)\s+([A-Z][a-z]{2,})', t)
            if m:
                names.add(m.group(1))
            m = re.match(r'^([A-Z][a-z]{2,})\s+[a-z(]', t)
            if m:
                names.add(m.group(1))
    names -= {'The', 'This', 'These', 'Their', 'With', 'From', 'Only', 'Both', 'Each', 'Body', 'Tubes'}
    return names


def add_runs(par, text: str, size: float, bold: bool = False, italic: bool = False,
             color: RGBColor | None = None, genera: set[str] | None = None):
    text = clean_text(text)
    if not text:
        return
    pieces: list[tuple[str, bool]] = []
    if genera and not italic:
        names = sorted(genera, key=len, reverse=True)
        rx = re.compile(r'(?<![A-Za-z])(' + '|'.join(map(re.escape, names)) + r')\s+([a-z][a-z\-]{1,})(?:\s+([a-z][a-z\-]{1,}))?')
        pos = 0
        for m in rx.finditer(text):
            ep = (m.group(2) or '').lower().strip('.')
            if ep in {'sp', 'spp', 'cf', 'aff', 'indet', 'nov', 'n'}:
                continue
            if m.start() > pos:
                pieces.append((text[pos:m.start()], False))
            pieces.append((m.group(0), True))
            pos = m.end()
        if pos < len(text):
            pieces.append((text[pos:], False))
    if not pieces:
        pieces = [(text, italic)]
    for chunk, ital in pieces:
        run = par.add_run(chunk)
        run.font.name = BODY_FONT
        run._element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)
        run.font.size = Pt(size)
        run.bold = bold
        run.italic = ital
        if color is not None:
            run.font.color.rgb = color


def setup(doc: Any):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(PAGE_W), Mm(PAGE_H)
    sec.top_margin, sec.bottom_margin = Mm(20), Mm(19)
    sec.left_margin, sec.right_margin = Mm(18), Mm(18)
    sec.header_distance, sec.footer_distance = Mm(9), Mm(10)
    sec.different_first_page_header_footer = True
    st = doc.styles['Normal']
    st.font.name = BODY_FONT
    st.font.size = Pt(10.5)
    st._element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0


def set_header_footer(sec, meta: BookMeta):
    hdr = sec.header
    hp = hdr.paragraphs[0]
    hp.text = ''
    hp.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
    r = hp.add_run(meta.running_left)
    r.font.name, r.font.size, r.italic = BODY_FONT, Pt(8), True
    r._element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)
    r2 = hp.add_run('\t' + meta.running_right)
    r2.font.name, r2.font.size, r2.italic = BODY_FONT, Pt(8), True
    r2._element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)
    ft = sec.footer
    fp = ft.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    def fld_run(kind=None, instr=None):
        r = fp.add_run()
        r.font.name, r.font.size = BODY_FONT, Pt(9)
        if kind:
            e = OxmlElement('w:fldChar')
            e.set(qn('w:fldCharType'), kind)
            r._r.append(e)
        elif instr is not None:
            e = OxmlElement('w:instrText')
            e.set(qn('xml:space'), 'preserve')
            e.text = instr
            r._r.append(e)
        return r
    fld_run('begin')
    fld_run(instr=' PAGE ')
    fld_run('separate')
    fp.add_run('1').font.size = Pt(9)
    fld_run('end')


def para(doc, text='', size=10.5, bold=False, italic=False, align=None, first=0.0,
         left=0.0, before=0.0, after=0.0, keep=False, genera=None, color=None,
         line=1.0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = line
    pf.first_line_indent = Mm(first)
    pf.left_indent = Mm(left)
    pf.keep_with_next = keep
    pf.widow_control = True
    if align is not None:
        p.alignment = align
    if text:
        add_runs(p, text, size, bold, italic, color, genera)
    return p


def heading(doc, text, level, genera, chapter_start=False):
    if chapter_start:
        doc.add_page_break()
    sizes = {1: 15, 2: 12, 3: 10.8}
    before = {1: 0, 2: 14, 3: 10}[level]
    after = {1: 10, 2: 7, 3: 4}[level]
    p = para(doc, text, size=sizes[level], bold=True, before=before, after=after,
             keep=True, genera=genera, line=1.0)
    if level == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p.runs:
            r.font.small_caps = True
    return p


def tabbed(doc, left, right, size, left_indent=5.0, genera=None, bold_left=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Mm(left_indent)
    pf.first_line_indent = Mm(-left_indent)
    pf.space_before, pf.space_after = Pt(0), Pt(0)
    pf.line_spacing = 1.0
    pf.tab_stops.add_tab_stop(Mm(TEXT_W - left_indent), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    add_runs(p, left, size, bold=bold_left, genera=genera)
    p.add_run('\t')
    add_runs(p, right, size, genera=genera)
    return p


def key_para(doc, text, genera):
    text = clean_text(text)
    m = LEADER_RE.search(text)
    if m and text[m.end():].strip():
        left = text[:m.start()].strip()
        right = text[m.end():].strip()
        if len(left) > 92:
            return para(doc, left + ' ' + right, size=9.5, left=5.0, first=-5.0, line=1.0, genera=genera)
        return tabbed(doc, left, right, 9.5, 5.0, genera)
    return para(doc, text, size=9.5, left=5.0, first=-5.0, line=1.0)


def image_para(doc, path: Path, max_w=118.0, max_h=150.0):
    try:
        im = DocxImage.from_file(str(path))
        w_mm = im.width / 36000.0
        h_mm = im.height / 36000.0
    except Exception:
        w_mm = h_mm = 0
    if w_mm and h_mm:
        if h_mm > max_h:
            w_mm *= max_h / h_mm
            h_mm = max_h
        if w_mm > max_w:
            h_mm *= max_w / w_mm
            w_mm = max_w
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Mm(w_mm or max_w), height=Mm(h_mm) if h_mm else None)
    return p


def caption(doc, text, genera):
    return para(doc, text, size=8.8, italic=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                after=6, line=1.0, genera=genera)


def raw_pages(translation: Path) -> dict[int, str]:
    text = translation.read_text(encoding="utf-8")
    marks = list(re.finditer(r'<!--\s*PDF p\.\s*(\d+)[^>]*-->', text))
    return {int(m.group(1)): text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
            for i, m in enumerate(marks)}


def front_matter(doc, data, genera, page_map, meta: BookMeta, translation: Path | None):
    if meta.title:
        para(doc, meta.title, size=18, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, before=30, after=4)
        if meta.volume:
            para(doc, meta.volume, size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=30)
        if meta.subtitle:
            para(doc, meta.subtitle, size=24, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12, genera=genera)
        if meta.edition:
            para(doc, meta.edition, size=13, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=40)
        if meta.publisher:
            para(doc, meta.publisher, size=10, align=WD_ALIGN_PARAGRAPH.CENTER, after=30)
        if meta.notes:
            para(doc, meta.notes, size=8.5, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        doc.add_page_break()

    if meta.include_front_matter:
        if meta.abstract_page and translation:
            raw = raw_pages(translation)
            abstract = clean_text(raw.get(meta.abstract_page, ""))
            if meta.abstract_cut:
                dup = abstract.find(meta.abstract_cut, 10)
                if dup > 0:
                    abstract = abstract[:dup].strip()
            if abstract:
                para(doc, "ABSTRACT", size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=8)
                para(doc, abstract, size=10, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first=5, line=1.05, genera=genera)
                doc.add_page_break()
        if meta.authors:
            para(doc, meta.authors_title, size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
            for a, t in meta.authors:
                para(doc, a, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, before=4, genera=genera)
                para(doc, t, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
            doc.add_page_break()
        if meta.contributions:
            para(doc, meta.contributions_title, size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=8)
            for a, t in meta.contributions:
                para(doc, a, size=9.5, before=3)
                para(doc, t, size=9.5, italic=True, left=4, after=2, genera=genera)
        if meta.license_note:
            para(doc, meta.license_note, size=8, italic=True, before=14, align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # contents
    doc.add_page_break()
    para(doc, meta.contents_title, size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    seen = set()
    for p in data["pages"]:
        if p["page"] < meta.body_start_page:
            continue
        if p["chapter"] in seen:
            continue
        seen.add(p["chapter"])
        source_title = chapter_title(p, meta)
        title = meta.display(p["chapter"], source_title)
        printed = p["page"] - meta.folio_offset
        out_page = page_map.get(str(printed), "")
        par = doc.add_paragraph()
        par.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        par.paragraph_format.space_before = Pt(3)
        add_runs(par, title, 10.5, bold=True, genera=genera)
        par.add_run("\t")
        add_runs(par, str(out_page), 10.5)
    doc.add_page_break()


def chapter_title(page: dict, meta: BookMeta) -> str:
    for b in page["blocks"]:
        if b["role"] == "heading" and b.get("level") == 1 and b.get("translation"):
            return clean_text(b["translation"])
    return page["chapter"]


def iter_pages(data, meta: BookMeta):
    for p in data["pages"]:
        if p["page"] < meta.body_start_page:
            continue
        yield p


def render_body(doc, data, genera, figs, page_map, meta: BookMeta, figs_dir: Path):
    current_chapter = None
    for p in iter_pages(data, meta):
        if meta.skip_after_page is not None and p["page"] >= meta.skip_after_page:
            continue
        ch = p["chapter"]
        is_index = ch == meta.index_chapter or (not meta.index_chapter and "index" in ch.lower())
        if is_index:
            current_chapter = ch
            continue
        first_page = ch != current_chapter
        if first_page:
            current_chapter = ch
            source_title = chapter_title(p, meta)
            title = meta.display(ch, source_title)
            heading(doc, title, 1, genera, chapter_start=True)
        page_figs = figs.get(p["page"], [])
        caps = [b for b in p["blocks"] if b["role"] == "caption"]
        first_y = min([b.get("y0", 999) for b in p["blocks"] if b["role"] != "caption"], default=999)
        cap_first = any(b.get("y0", 999) < first_y for b in caps)
        placed: set[int] = set()
        if cap_first:
            for b in caps:
                place_figure(doc, b, page_figs, genera, figs_dir=figs_dir)
                placed.add(id(b))
        prev_body = None
        for b in p["blocks"]:
            role = b["role"]
            text = clean_text(b.get("translation") or "")
            if role == "caption":
                if id(b) not in placed:
                    place_figure(doc, b, page_figs, genera, figs_dir=figs_dir)
                prev_body = None
                continue
            if not text:
                continue
            if p["kind"] == "index" and text.upper().startswith("ALPHABETICAL INDEX"):
                continue
            if role == "heading":
                skip = first_page and (
                    clean_text(text).lower() in {clean_text(title).lower(), clean_text(source_title).lower()}
                    or any(clean_text(text).lower().startswith(clean_text(x).lower()) for x in meta.skip_headings)
                )
                if skip:
                    continue
                level = b.get("level", 2)
                heading(doc, text, min(level, 3), genera)
                prev_body = None
            elif role == "body":
                # merge a page-split sentence
                if prev_body is not None and can_join(prev_body[0], text):
                    joined = join_texts(prev_body[0], text)
                    prev_body[1].clear()
                    add_runs(prev_body[1], joined, 10.5, genera=genera)
                    prev_body = (joined, prev_body[1])
                else:
                    par = para(doc, text, size=10.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                               first=5, line=1.02, genera=genera)
                    prev_body = (text, par)
            elif role == "citation":
                para(doc, text, size=9.2, left=4, first=-4, before=1, line=1.0, genera=genera)
                prev_body = None
            elif role == "key":
                key_para(doc, text, genera)
                prev_body = None
            elif role == "ref":
                para(doc, text, size=8.8, left=4, first=-4, after=2.5, line=0.98, genera=genera)
                prev_body = None
            elif role == "entry":
                for prefix in meta.entry_prefixes:
                    text = re.sub(prefix, "", text, count=1, flags=re.I)
                if not text:
                    continue
                size = 9.2 if p["kind"] in ("appendix",) else 10.2
                para(doc, text, size=size, left=4, first=-4, after=2.0, line=1.0, genera=genera)
                prev_body = None
            elif role == "index":
                continue
            prev_body = prev_body if role == "body" else None
    render_index(doc, data, genera, page_map, meta)


def can_join(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a.endswith('-'):
        return b[:1].islower()
    if re.search(r'[.!?:;”’)]$', a):
        return False
    return b[:1].islower() or b[:1] in '([“‘'


def join_texts(a: str, b: str) -> str:
    if a.endswith('-'):
        return a[:-1] + b
    return a + ' ' + b


def place_figure(doc, cap_block, page_figs, genera, figs_dir: Path):
    text = clean_text(cap_block.get('translation') or cap_block.get('text') or '')
    label = None
    m = FIG_RE.search(text)
    if m:
        label = m.group(1).replace('’', '′')
    fig = None
    for f in page_figs:
        if label and f['source_label'].replace('’', '′') == label:
            fig = f
            break
    if fig is None and page_figs:
        fig = page_figs[0]
    if fig:
        path = figs_dir / fig['crop']
        if path.exists():
            image_para(doc, path)
    if text:
        caption(doc, text, genera)


def render_index(doc, data, genera, page_map, meta: BookMeta):
    entries = []
    raw_intro = ''
    for p in data['pages']:
        if p['kind'] != 'index':
            continue
        for b in p['blocks']:
            if not b.get('translation'):
                continue
            if b['role'] != 'index':
                if b['translation'].upper().startswith('ALPHABETICAL INDEX'):
                    raw_intro = clean_text(b['translation'])
                continue
            entries.append(clean_text(b['translation']))
    if not entries:
        return
    intro = ""
    if raw_intro:
        if meta.index_intro_prefix:
            m = re.search(r"(" + re.escape(meta.index_intro_prefix) + r".*?)(?:Page\b|SERIES|$)", raw_intro, re.I | re.S)
            intro = m.group(1).strip() if m else raw_intro[:400]
        else:
            intro = raw_intro[:400]
    doc.add_page_break()
    para(doc, meta.index_title, size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
    if intro:
        para(doc, intro, size=8.8, italic=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8)
    sec = doc.add_section(WD_SECTION.CONTINUOUS)
    sec.page_width, sec.page_height = Mm(PAGE_W), Mm(PAGE_H)
    sec.top_margin, sec.bottom_margin = Mm(20), Mm(19)
    sec.left_margin, sec.right_margin = Mm(18), Mm(18)
    cols = sec._sectPr.xpath('./w:cols')
    if cols:
        cols[0].set(qn('w:num'), '2')
        cols[0].set(qn('w:space'), '360')
    for text in entries:
        m = LEADER_RE.search(text)
        if not m:
            m2 = re.match(r'^(.*?)\s+((?:\d{1,3}(?:,\s*)?)+)$', text)
            if m2:
                left, right = m2.group(1).strip(), m2.group(2).strip()
                right = remap_refs(right, page_map)
                p = doc.add_paragraph()
                p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.tab_stops.add_tab_stop(Mm(62), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
                add_runs(p, left, 8.6, genera=genera)
                p.add_run('\t')
                add_runs(p, right, 8.6)
                continue
        if m:
            left = text[:m.start()].strip()
            right = text[m.end():].strip()
            right = remap_refs(right, page_map)
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Mm(0)
            pf.space_before, pf.space_after = Pt(0), Pt(0)
            pf.line_spacing = 1.0
            pf.tab_stops.add_tab_stop(Mm(62), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            add_runs(p, left, 8.6, genera=genera)
            p.add_run('\t')
            add_runs(p, right, 8.6)
        else:
            para(doc, text, size=8.6, line=1.0, genera=genera)


def remap_refs(right: str, page_map: dict[str, int | str]) -> str:
    def repl(m):
        n = int(m.group(0))
        return str(page_map.get(str(n), n))
    return re.sub(r'\b\d{1,3}\b', repl, right)


def build(out_docx: Path, page_map: dict[str, int], paths: BookPaths, meta: BookMeta) -> dict:
    data = load_aligned(paths.aligned)
    genera = build_genus_set(data)
    figs: dict[int, list[dict]] = {}
    audit_path = paths.figures_dir / "source_figure_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for f in audit.get("figures", []):
            figs.setdefault(int(f["source_pdf_page"]), []).append(f)
    doc = Document()
    setup(doc)
    set_header_footer(doc.sections[0], meta)
    front_matter(doc, data, genera, page_map, meta, paths.translation)
    render_body(doc, data, genera, figs, page_map, meta, paths.figures_dir)
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))
    return data


def make_page_map(pdf: Path, data: dict, meta: BookMeta) -> dict[str, int]:
    import fitz

    doc = fitz.open(pdf)

    def norm(t):
        t = re.sub(r"-\s+", "", t)
        return re.sub(r"\s+", " ", t)

    texts = [norm(p.get_text("text")) for p in doc]
    lines = [[norm(line).strip().upper() for line in p.get_text("text").splitlines() if line.strip()] for p in doc]
    page_map: dict[str, int] = {}
    last = 0
    for p in data["pages"]:
        if p["page"] < meta.body_start_page:
            continue
        heads, bodies, anys = [], [], []
        for b in p["blocks"]:
            t = clean_text(b.get("translation") or "")
            if b["role"] == "heading" and len(t) >= 24:
                heads.append(norm(t)[:60])
            elif b["role"] in ("body", "heading") and len(t) >= 35:
                bodies.append(norm(t)[:60])
            elif len(t) >= 15:
                anys.append(norm(t)[:50])
        cands = sorted(set(heads), key=len, reverse=True) + bodies + anys
        found = None
        for snippet in cands:
            for i in range(last, min(len(texts), last + 12)):
                if snippet in texts[i]:
                    found = i
                    break
            if found is None:
                for i in range(max(0, last - 2), len(texts)):
                    if snippet in texts[i]:
                        found = i
                        break
            if found is not None:
                break
        if found is not None:
            page_map[str(p["page"] - meta.folio_offset)] = found + 1
            last = found
    # Chapter headings are more reliable than running text for contents/index.
    prev = None
    for p in data["pages"]:
        if p["page"] < meta.body_start_page or p["chapter"] == prev:
            continue
        prev = p["chapter"]
        title = meta.index_title if p["chapter"] == meta.index_chapter else meta.display(
            p["chapter"], p["chapter"]
        )
        key = title.upper()[:34]
        for i in range(5, len(lines)):
            if any(line.startswith(key) for line in lines[i]):
                page_map[str(p["page"] - meta.folio_offset)] = i + 1
                break
    # Fill gaps monotonically from neighbouring mapped source pages.
    keys = sorted(int(k) for k in page_map)
    if keys:
        for k in range(keys[0], keys[-1] + 1):
            if str(k) in page_map:
                continue
            lo = max((x for x in keys if x < k), default=None)
            hi = min((x for x in keys if x > k), default=None)
            if lo is not None and hi is not None and hi > lo:
                v = page_map[str(lo)] + (k - lo) * (page_map[str(hi)] - page_map[str(lo)]) / (hi - lo)
                page_map[str(k)] = int(round(v))
            elif lo is not None:
                page_map[str(k)] = page_map[str(lo)] + (k - lo)
            elif hi is not None:
                page_map[str(k)] = max(1, page_map[str(hi)] - (hi - k))
    return page_map
