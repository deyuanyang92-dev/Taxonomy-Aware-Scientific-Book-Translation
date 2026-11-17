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
import os
import re
import unicodedata
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

from booklayout.english import (
    FAMILY_RUN,
    is_english_word,
    is_family_group,
    worms_genera,
    worms_higher_taxa,
)

BODY_FONT = "Garamond"
# 中文版把 eastAsia 字体设为宋体（Garamond 无汉字，Word 会随机回落）；英文版保持不变。
CJK_FONT = os.environ.get("BOOKLAYOUT_CJK_FONT", BODY_FONT)
_CJK = re.compile(r"[⺀-鿿＀-￯]")
# 中英共用的标点（点线、破折号、弯引号等）：只有所在段落含中文时才按东亚字体排。
# 英文段落里给它们加 eastAsia hint，Word 会把 , . ( ) 显示成全角（yzz zh check）。
_SHARED_PUNCT = re.compile(r"[…—―·×÷∶‘’“”]")
TEXT_W = 134.0  # mm
PAGE_W, PAGE_H = 170.0, 240.0

# 属名后跟这些词时不是种加词：「Rouse y Fauchald」「Torrea and」被整段排成斜体，
# 根因是 build_genus_set 把段首作者名当成属名、add_runs 又把连词当种加词。
FUNCTION_WORDS = {"and", "or", "of", "the", "in", "with", "from", "between", "to",
                  "for", "on", "by", "as", "y", "e", "de", "del", "en", "con",
                  "et", "al", "与", "和", "及"}

# 属名后跟这些词时不是种加词，只把属名排斜体（sp. 正体是通行做法）。
SKIP_EPITHETS = {"sp", "spp", "cf", "aff", "indet", "nov", "n"}

# 原文是西班牙文；全段扫描「大写词 + 小写词」时用它挡掉 Los individuos 这类词组。
SPANISH_STOP = {"los", "las", "el", "la", "un", "una", "unos", "unas", "del", "al",
                "para", "por", "según", "entre", "sobre", "con", "sin", "sus", "su",
                "este", "esta", "estos", "estas", "como", "donde", "cuando", "más",
                "pero", "otra", "otro", "fig", "figs", "tabla", "lámina", "láminas",
                "clave", "género", "especie", "especies", "material", "ejemplares"}

# Dot leaders reach the builder in three forms: the source's spaced dots
# (". . . ."), a run of periods ("......"), and the ellipsis that the key
# aligner writes ("…").  Missing the third form made every identification-key
# line fall through to a plain paragraph: the target stayed inline instead of
# being pulled to the right margin with leaders.
LEADER_RE = re.compile(r"\s*(?:(?:\.\s*){2,}|…+|�+)\s*")
# OCR sometimes leaves a single dot before a couplet number ("... setigers . 8").
_SINGLE_DOT_TARGET = re.compile(r"\s+\.\s+(?=\d{1,3}\s*$)")
# Some translated key lines lost their leader entirely and end with a plain
# species/family target such as "L. collaris (p. 136)".
_TARGET_SUFFIX = re.compile(
    r"\s+((?:[A-Z][A-Za-z.-]*)(?:\s+[a-z][a-z.-]*)?\s*\(p\.\s*\d+\))\s*$"
)
_STRAY_DOT = re.compile(
    r"\s+\.(?=[A-Z][A-Za-z.-]*(?:\s+[a-z][a-z.-]*)?\s*\(p\.\s*\d+\)\s*$)"
)
# Two key couplets caught in one block: the first ends with a dot leader and a
# couplet number, and the next couplet number starts right after it
# ("… lobe …… 5 3. Collar completely surrounding …").  Upstream line joining
# once produced this, and the builder then set the whole remainder as one
# right-aligned target, leaving a 1 mm leader and the second couplet glued to
# the first.  Split it here so stale aligned data cannot reproduce the defect.
_MERGED_COUPLET = re.compile(r"(?:[.…]\s*)+(?P<num>\d{1,3})\s+(?=\d{1,3}[.)]\s)")
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
    translator: str = ""
    translator_preface_title: str = "TRANSLATOR'S PREFACE"
    translator_preface: str = ""
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
    # When the source starts a chapter part-way down a page, insert the
    # chapter title at its real position instead of moving it to page top.
    heading_in_flow: bool = False
    skip_after_page: int | None = None
    index_chapter: str = ""
    index_intro_prefix: str = "Only the scientific names"
    skip_headings: list[str] = field(default_factory=list)
    entry_prefixes: list[str] = field(default_factory=list)
    # Source indexes contain occasional misprints (wrong genus, missing letter).
    # Each pair corrects the printed entry; readers must be able to find the
    # name that the cited pages actually carry.  An optional third element
    # records the evidence printed in the end-of-book correction list.
    index_entry_fixes: list[tuple[str, ...]] = field(default_factory=list)
    corrections_title: str = "CORRECTIONS TO THE ORIGINAL"
    corrections_intro: str = (
        "The source index contains a few misprints. Corrected entries are "
        "marked † in the index; each correction and the evidence for it "
        "are listed below."
    )

    @classmethod
    def from_json(cls, path: Path) -> "BookMeta":
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = dict(raw)
        data["authors"] = [tuple(x) for x in data.get("authors", [])]
        data["contributions"] = [tuple(x) for x in data.get("contributions", [])]
        data["index_entry_fixes"] = [tuple(x) for x in data.get("index_entry_fixes", [])]
        return cls(**data)

    def display(self, chapter: str, source_title: str) -> str:
        return self.chapter_titles.get(chapter, source_title or chapter)


@dataclass
class BookPaths:
    aligned: Path
    figures_dir: Path
    translation: Path | None = None


def clean_text(s: str) -> str:
    # python-docx rejects XML-incompatible control characters outright.
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    s = re.sub(r'[\u01a4\u0530-\u058f]', '', s)
    # OCR leader runs are occasionally encoded as U+FFFD; leaving them in
    # prints a row of black replacement glyphs in keys and body text.
    s = s.replace('\ufffd', ' ')
    s = s.replace('\u3000', ' ').replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def load_aligned(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_genus_set(data: dict) -> set[str]:
    """属名集合：WoRMS Annelida 名单与书内实际出现的词取交集，再加译者的星号标记。

    只用段首/全书「大写词 + 小写词」会漏掉正文里只出现一次的属名
    （Notomastus latericeus），而全段扫描不加过滤又会收进 Los、Abundantes
    这类西语普通词。WoRMS 缓存（与 scripts/taxoformat.py 同一个库）给出可信
    属名，书内出现过的才保留。缓存不存在时退回段首启发式。
    """
    texts: list[str] = []
    names: set[str] = set()
    for p in data['pages']:
        for b in p['blocks']:
            for t in (b.get('text', ''), b.get('translation', '') or ''):
                if not t:
                    continue
                texts.append(t)
                # 「El género Elicodasia Laubier y Ramos, 1973」「genus Apomatus」
                # 这类阶元标签是可靠的属名来源，标签常在句中出现，不能只查段首。
                # Familia/Subfamilia 不能算：科名和亚科名正体，不是属名。
                for m in re.finditer(
                        r'\b(?:[Gg]énero|[Gg]enero|[Ss]ubgénero|[Ss]ubgenero|'
                        r'[Gg]enus|[Ss]ubgenus)'
                        r'\s+([A-Z][a-z]{2,})', t):
                    names.add(m.group(1))
    words = set(re.findall(r'\b[A-Z][a-z]{2,}\b', '\n'.join(texts)))
    # 译者的星号标记：*Genus* 与 *Genus epithet*（书内新属不一定在 WoRMS 里）。
    for t in texts:
        for m in re.finditer(r'\*\s*([A-Z][a-z]{2,})(?:\s+[a-z][a-z\-]+)?\s*\*', t):
            names.add(m.group(1))
    worms = worms_genera()
    if worms:
        names |= worms & words
    else:
        # 缓存缺失时退回段首「属名 + 小写词」启发式（会混入普通词语，故只在
        # 没有 WoRMS 名单时使用）。
        for t in texts:
            mm = re.match(r'^([A-Z][a-z]{2,})\s+([a-z(][^\s]*)', t)
            if mm:
                second = mm.group(2).lower().strip(',.;:()')
                if second not in FUNCTION_WORDS and not is_english_word(second) \
                        and second not in SPANISH_STOP:
                    names.add(mm.group(1))
    # 科级及以上阶元正体（ICZN 惯例，用户 2026-11-17 定）：译者把科名也标了
    # 星号（原书科名就排斜体），阶元标签补进来的也可能带科名，全部移出属名集合。
    higher = worms_higher_taxa()
    names = {n for n in names
             if n not in higher and not (is_family_group(n) and n not in worms)}
    names -= {'The', 'This', 'These', 'Their', 'With', 'From', 'Only', 'Both', 'Each', 'Body', 'Tubes'}
    return names


def _markdown_chunks(text: str) -> list[tuple[str, bool]]:
    """Split translated text into plain and *italic* chunks.

    The translation pass marks genus names with Markdown asterisks.  Printing
    them literally is a layout defect (``*Arabella*``), so the markers are
    consumed here.  Unpaired asterisks left by a split aligner are dropped.
    """
    chunks: list[tuple[str, bool]] = []
    pos = 0
    for m in re.finditer(r'\*{1,2}([^*]+)\*{1,2}', text):
        if m.start() > pos:
            chunks.append((text[pos:m.start()], False))
        chunks.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        chunks.append((text[pos:], False))
    return [(c.replace('*', ''), it) for c, it in chunks if c.replace('*', '')]


_HIGHER_RX: re.Pattern[str] | None = None


def _higher_rx() -> re.Pattern[str]:
    """科级词尾 + WoRMS 阶元名（目、纲、门），用于把阶元名移出斜体。"""
    global _HIGHER_RX
    if _HIGHER_RX is None:
        names = sorted(worms_higher_taxa(), key=len, reverse=True)
        pattern = FAMILY_RUN.pattern
        if names:
            pattern += r"|\b(?:" + "|".join(map(re.escape, names)) + r")\b"
        _HIGHER_RX = re.compile(pattern)
    return _HIGHER_RX


def _family_roman(chunk: str) -> list[tuple[str, bool]]:
    """Split an italic chunk so ICZN family-group names come out roman.

    The Spanish original prints family names in italic (Vol. 45 author list,
    ITC Garamond Light Italic) and the translation marks them with asterisks
    too.  The English edition follows the zoological convention instead:
    only genus and species-group names are italic (user 2026-11-17).
    """
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for m in _higher_rx().finditer(chunk):
        if m.start() > pos:
            pieces.append((chunk[pos:m.start()], True))
        pieces.append((m.group(0), False))
        pos = m.end()
    if pos < len(chunk):
        pieces.append((chunk[pos:], True))
    return pieces


def add_runs(par, text: str, size: float, bold: bool = False, italic: bool = False,
             color: RGBColor | None = None, genera: set[str] | None = None,
             invert: bool = False):
    """Emit runs.  ``invert`` sets the taxon names opposite to the base style
    (kept for styles that print captions in italic); the Fauna Ibérica
    delivery uses roman captions with italic names, see ``caption``.
    """
    text = clean_text(text)
    if not text:
        return
    pieces: list[tuple[str, bool]] = []
    for chunk, md_italic in _markdown_chunks(text):
        if md_italic:
            # 译者照原书把科名也标了星号；科级及以上阶元正体，移出斜体。
            if _higher_rx().search(chunk):
                pieces.extend(_family_roman(chunk))
                continue
            # 译者有时把连词也圈进星号（「*Audouin and* Milne Edwards」），
            # 连词移到斜体之外；整条书名/刊名仍保持斜体。
            m = re.match(r'^(.*\S)\s+(and|y|e|et|or|&)$', chunk)
            if m:
                pieces.append((m.group(1), True))
                pieces.append((" " + m.group(2), italic))
            else:
                pieces.append((chunk, (not italic) if invert else True))
            continue
        if not genera:
            pieces.append((chunk, italic))
            continue
        names = sorted(genera, key=len, reverse=True)
        # 属名单独出现也排斜体（分类学惯例：属名后不带种加词时同样斜体）。
        # 「属名 + 小写词」只有小写词确实是种加词才连排斜体——英语词和虚词
        # 不是种加词，曾把「Lopadorrhynchus comprises the」整段排成斜体。
        rx = re.compile(
            r'(?<![A-Za-z])(' + '|'.join(map(re.escape, names)) + r')(?![a-z])'
            r'(?:\s+([a-z][a-z\-]{1,})(?:\s+([a-z][a-z\-]{1,}))?)?')
        pos = 0
        for m in rx.finditer(chunk):
            ep = (m.group(2) or '').lower().strip('.')
            end = m.end(1)
            name = m.group(1)
            if ep and ep not in SKIP_EPITHETS and ep not in FUNCTION_WORDS \
                    and not is_english_word(ep):
                end = m.end(2)
                name = chunk[m.start(1):end]
                third = (m.group(3) or '').lower().strip('.')
                if third and third not in FUNCTION_WORDS and third not in SKIP_EPITHETS \
                        and not is_english_word(third):
                    end = m.end(3)
                    name = chunk[m.start(1):end]
            if m.start() > pos:
                pieces.append((chunk[pos:m.start()], italic))
            pieces.append((name, (not italic) if invert else True))
            pos = end
        if pos < len(chunk):
            pieces.append((chunk[pos:], italic))
    if not pieces:
        pieces = [(text.replace('*', ''), italic)]
    # 带斜体底的段落（作者名单、题记、索引引言）里，科级及以上阶元同样正体。
    final: list[tuple[str, bool]] = []
    for chunk, ital in pieces:
        if ital and _higher_rx().search(chunk):
            final.extend(_family_roman(chunk))
        else:
            final.append((chunk, ital))
    pieces = final
    para_text = ''.join(r.text for r in par.runs) + text
    para_cjk = bool(_CJK.search(para_text))
    for chunk, ital in pieces:
        # 点线「……」单独成 run：它需要 eastAsia hint，但同一 run 里的拉丁文
        # 若也带 hint，Word 会把其中的 , . ( ) 显示成全角（yzz zh check 报
        # 「英文段落标点被设为东亚字体」）。拆开后两边各按自己的字体排。
        for sub in re.split(r'(…+)', chunk):
            if not sub:
                continue
            run = par.add_run(sub)
            run.font.name = BODY_FONT
            run._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
            if _CJK.search(sub) or (_SHARED_PUNCT.search(sub) and para_cjk):
                run._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
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
    st._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0
    # Justified text without hyphenation produces rivers and huge word gaps,
    # especially around long taxonomic names and citations.
    rpr = st._element.get_or_add_rPr()
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), "en-US")
    rpr.append(lang)
    settings = doc.settings.element
    anchor = settings.find(qn("w:compat"))
    index = list(settings).index(anchor) if anchor is not None else len(settings)
    for tag, value in (
        ("w:autoHyphenation", "true"),
        ("w:consecutiveHyphenLimit", "2"),
        ("w:hyphenationZone", "357"),
    ):
        element = OxmlElement(tag)
        element.set(qn("w:val"), value)
        settings.insert(index, element)
        index += 1


def set_header_footer(sec, meta: BookMeta):
    hdr = sec.header
    hp = hdr.paragraphs[0]
    hp.text = ''
    hp.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
    hdr_cjk = bool(_CJK.search(meta.running_left + meta.running_right))
    r = hp.add_run(meta.running_left)
    r.font.name, r.font.size, r.italic = BODY_FONT, Pt(8), True
    r._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    if _CJK.search(meta.running_left) or (_SHARED_PUNCT.search(meta.running_left) and hdr_cjk):
        r._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
    r2 = hp.add_run('\t' + meta.running_right)
    r2.font.name, r2.font.size, r2.italic = BODY_FONT, Pt(8), True
    r2._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    if _CJK.search(meta.running_right) or (_SHARED_PUNCT.search(meta.running_right) and hdr_cjk):
        r2._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
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
         line=1.0, invert=False):
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
        add_runs(p, text, size, bold, italic, color, genera, invert)
    return p


def page_break(doc) -> None:
    """Start a new page without creating an empty page after a page break."""
    if doc.paragraphs:
        last = doc.paragraphs[-1]._element
        if any(br.get(qn("w:type")) == "page" for br in last.iter(qn("w:br"))):
            return
    doc.add_page_break()


def heading(doc, text, level, genera, chapter_start=False):
    sizes = {1: 15, 2: 12, 3: 10.8}
    before = {1: 0, 2: 14, 3: 10}[level]
    after = {1: 10, 2: 7, 3: 4}[level]
    p = para(doc, text, size=sizes[level], bold=True, before=before, after=after,
             keep=True, genera=genera, line=1.0)
    if chapter_start:
        # A separate page-break paragraph at the bottom of a full page creates
        # an empty page.  page_break_before on the heading itself cannot.
        p.paragraph_format.page_break_before = True
    if level == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p.runs:
            r.font.small_caps = True
    return p


def _atomic_target(p, start: int) -> None:
    """Make every word of a key target non-breaking.

    The target is one address ("L. torquata (p. 133)"); a break inside it
    leaves "L." at the end of the couplet and "torquata (p. 133)" at the left
    margin of the next line.  The tab would then be consumed on the first
    line, so the remainder is neither flush right nor led.  Non-breaking
    spaces keep the address whole; when it does not fit, Word/LibreOffice move
    all of it to the next line and the right tab fills that line with leaders,
    which is exactly how the Spanish original sets long couplets.
    """
    for run in p.runs[start:]:
        if " " in run.text:
            # U+202F NARROW NO-BREAK SPACE, not U+00A0: both are glue in
            # Unicode line breaking, but U+00A0 shows as a degree-like mark
            # in Word and is rejected by the workspace zh-check gate, while
            # U+202F passes it and renders as an ordinary space.
            run.text = run.text.replace(" ", " ")


def tabbed(doc, left, right, size, left_indent=4.0, genera=None, bold_left=False,
           force_break=False):
    """One key line: marker indented, target flush right behind dot leaders.

    The Spanish original indents the couplet number/bullet by about 4 mm and
    returns wrapped lines to the left margin (it does *not* hang the whole
    line under the text after the marker).  The right tab at the text width
    pulls the target to the margin; a target that does not fit moves to the
    next line as a whole instead of staying inline after an ellipsis.
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Mm(0)
    pf.first_line_indent = Mm(left_indent)
    pf.space_before, pf.space_after = Pt(0), Pt(0)
    pf.line_spacing = 1.0
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.tab_stops.add_tab_stop(
        Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
    )
    add_runs(p, left, size, bold=bold_left, genera=genera)
    if force_break:
        # A couplet whose leader would be shorter than MIN_KEY_LEADER_MM gets
        # the same treatment as an over-long target: the whole address moves
        # to a leader-filled line.  A two-dot leader reads as an ellipsis.
        p.add_run().add_break()
    p.add_run('\t')
    target_start = len(p.runs)
    add_runs(p, right, size, genera=genera)
    _atomic_target(p, target_start)
    _suppress_hyphenation(p)
    return p


def key_signature(left: str, right: str) -> str:
    """Stable identity of a key couplet, shared by the builder and the audit.

    PDF extraction leaves a space after a hyphen that fell at a line break
    ("4- 5"), while the aligned text has "4-5"; remove it on both sides.
    """
    def norm(text: str) -> str:
        return re.sub(r"(?<=[A-Za-z0-9])-\s+(?=[a-z0-9])", "-", match_text(text))

    return norm(left) + "\t" + norm(right)


def key_para(doc, text, genera, key_breaks: set[str] | None = None):
    text = re.sub(r'\ufffd+', ' …… ', text)
    text = clean_text(text)
    text = _STRAY_DOT.sub(" ", text)
    merged = _MERGED_COUPLET.search(text)
    if merged:
        first = text[: merged.end("num")].strip()
        rest = text[merged.end():].strip()
        if first and rest:
            key_para(doc, first, genera, key_breaks)
            return key_para(doc, rest, genera, key_breaks)
    m = LEADER_RE.search(text)
    if m is None:
        m = _SINGLE_DOT_TARGET.search(text)
    if m is None:
        m = _TARGET_SUFFIX.search(text)
    if m:
        left = text[:m.start()].strip()
        right = m.group(1).strip() if m.re is _TARGET_SUFFIX else text[m.end():].strip()
        if left and right:
            force = key_breaks is not None and key_signature(left, right) in key_breaks
            return tabbed(doc, left, right, 9.5, 4.0, genera, force_break=force)
    # Headings, introductory notes and footnotes inside a key carry no target:
    # set them ragged-right like the source, with the same 4 mm first-line
    # indent as a couplet marker.  Justifying them would reintroduce the wide
    # word gaps the keys are meant to avoid.
    return para(doc, text, size=9.5, first=4.0, line=1.0,
                align=WD_ALIGN_PARAGRAPH.LEFT, genera=genera)


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


def _suppress_hyphenation(p) -> None:
    """Keep a short paragraph from breaking a word across lines.

    LibreOffice hyphenates "Redrawn" as "Re-drawn" in a justified caption;
    the break looks like an accidental hyphen in the printed book.  Captions
    and key lines are short enough that moving the whole word is preferable.
    """
    pPr = p._p.get_or_add_pPr()
    element = OxmlElement("w:suppressAutoHyphens")
    element.set(qn("w:val"), "true")
    # Word's schema fixes the child order inside w:pPr; appending at the end
    # after w:jc makes Word repair the document on open.
    pPr.insert_element_before(
        element,
        "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct",
        "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
        "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
        "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
        "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
        "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
    )


def caption(doc, text, genera):
    # 出版惯例（用户 2026-11-17 定）：图注正体，学名斜体。原书把整条图注排成
    # ITC Garamond Light Italic（Vol. 45 p. 30），照搬后图注与学名同色同体、没有层次。
    # 9.5 pt：8.8 pt 在 Word/LibreOffice 里明显偏小。
    # The Spanish original sets captions ragged-right beside the figure.  A
    # justified caption has to hyphenate long words ("Re-drawn") to fill the
    # measure; ragged-right keeps the caption readable and avoids those
    # accidental-looking hyphens in the printed book.
    p = para(doc, text, size=9.5, italic=False, align=WD_ALIGN_PARAGRAPH.LEFT,
             before=12, after=7, line=1.05, genera=genera)
    # A caption that splits over a page break reads as two unrelated fragments.
    p.paragraph_format.keep_together = True
    _suppress_hyphenation(p)
    return p


def raw_pages(translation: Path) -> dict[int, str]:
    text = translation.read_text(encoding="utf-8")
    marks = list(re.finditer(r'<!--\s*PDF p\.\s*(\d+)[^>]*-->', text))
    return {int(m.group(1)): text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
            for i, m in enumerate(marks)}


def _translator_preface(meta: BookMeta) -> str:
    return meta.translator_preface.strip() or (
        "An initial machine translation was produced with Google Translate and then "
        "revised with DeepSeek Flash, a non-reasoning large language model. The "
        "project's alignment and typesetting software mapped each translated block "
        "to the corresponding page of the Spanish original and placed the original "
        "figures. Taxonomic names, literature citations and figure captions were "
        "aligned with the source edition. This is a working English translation, "
        "not a critical revision of the Spanish text; remaining errors are the "
        "translator's responsibility."
    )


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
        page_break(doc)

    if meta.translator:
        para(doc, meta.translator_preface_title, size=13, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
        for paragraph in re.split(r"\n\s*\n", _translator_preface(meta)):
            paragraph = clean_text(paragraph)
            if paragraph:
                para(doc, paragraph, size=10.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                     first=5, line=1.05, after=7)
        para(doc, f"Translated by {meta.translator}.", size=10.5,
             align=WD_ALIGN_PARAGRAPH.RIGHT, before=14)
        page_break(doc)

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
                para(doc, abstract, size=10, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first=5,
                     line=1.05, genera=genera)
                page_break(doc)
        if meta.authors:
            para(doc, meta.authors_title, size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
            for a, t in meta.authors:
                para(doc, a, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, before=4, genera=genera)
                para(doc, t, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
            page_break(doc)
        if meta.contributions:
            para(doc, meta.contributions_title, size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=8)
            for a, t in meta.contributions:
                para(doc, a, size=9.5, before=3)
                para(doc, t, size=9.5, italic=True, left=4, after=2, genera=genera)
        if meta.license_note:
            para(doc, meta.license_note, size=8, italic=True, before=14, align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # contents
    page_break(doc)
    para(doc, meta.contents_title, size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    seen = set()
    rows = []
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
        rows.append((p, title, out_page))
    # The index is always rendered after every body chapter, so its contents
    # entry must come last even when the source book prints it earlier.
    rows.sort(key=lambda row: _is_index_chapter(row[0]["chapter"], meta))
    for p, title, out_page in rows:
        par = doc.add_paragraph()
        par.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        par.paragraph_format.space_before = Pt(3)
        add_runs(par, title, 10.5, bold=True, genera=genera)
        par.add_run("\t")
        add_runs(par, str(out_page), 10.5)


def chapter_title(page: dict, meta: BookMeta) -> str:
    for b in page["blocks"]:
        if b["role"] == "heading" and b.get("level") == 1 and b.get("translation"):
            return clean_text(b["translation"])
    return page["chapter"]


def _is_index_chapter(chapter: str, meta: BookMeta) -> bool:
    return chapter == meta.index_chapter or (not meta.index_chapter and "index" in chapter.lower())


def iter_pages(data, meta: BookMeta):
    for p in data["pages"]:
        if p["page"] < meta.body_start_page:
            continue
        yield p


def render_body(doc, data, genera, figs, page_map, meta: BookMeta, figs_dir: Path,
                key_breaks: set[str] | None = None):
    current_chapter = None
    for p in iter_pages(data, meta):
        if meta.skip_after_page is not None and p["page"] >= meta.skip_after_page:
            continue
        ch = p["chapter"]
        is_index = _is_index_chapter(ch, meta)
        if is_index:
            current_chapter = ch
            continue
        first_page = ch != current_chapter
        synthetic_heading = False
        pending_heading = None
        if first_page:
            current_chapter = ch
            source_title = chapter_title(p, meta)
            title = meta.display(ch, source_title)
            in_flow = meta.heading_in_flow and any(
                b.get("role") == "heading" and b.get("level") == 1 for b in p["blocks"])
            if in_flow:
                synthetic_heading = False
            else:
                # A source page can hold the tail of the previous chapter
                # before the new chapter heading.  Put the heading where the
                # source heading sits, not above that tail.
                for candidate in p["blocks"]:
                    try:
                        level = int(candidate.get("level", 1))
                    except (TypeError, ValueError):
                        level = 1
                    if candidate.get("role") == "heading" and level == 1:
                        pending_heading = id(candidate)
                        break
                if pending_heading is None:
                    heading(doc, title, 1, genera, chapter_start=True)
                    synthetic_heading = True
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
            if pending_heading is not None and id(b) == pending_heading:
                heading(doc, title, 1, genera, chapter_start=True)
                synthetic_heading = True
                prev_body = None
                continue
            if role == "caption":
                if id(b) not in placed:
                    place_figure(doc, b, page_figs, genera, figs_dir=figs_dir)
                prev_body = None
                continue
            if not text:
                continue
            if p["kind"] == "index" and text.upper().startswith("ALPHABETICAL INDEX"):
                continue
            if role in {"heading", "body"}:
                ack = re.match(r'^(Acknowledg(?:e)?ments)\b[\s.:\-—]*(.*)$',
                               text, re.I | re.S)
                if ack:
                    heading(doc, ack.group(1).upper(), 2, genera)
                    text = ack.group(2).strip()
                    role = "body"
                    if not text:
                        prev_body = None
                        continue
            if role == "heading":
                skip = first_page and synthetic_heading and (
                    clean_text(text).lower() in {clean_text(title).lower(), clean_text(source_title).lower()}
                    or any(clean_text(text).lower().startswith(clean_text(x).lower()) for x in meta.skip_headings)
                )
                if skip:
                    continue
                if len(re.findall(r"[A-Za-z]{2,}", text)) > 20:
                    # A source call-out or boxed note was often tagged as a
                    # heading by the aligner.  Typesetting it as a chapter
                    # heading turns it into a huge all-caps block.
                    para(doc, text, size=9.5, italic=True,
                         align=WD_ALIGN_PARAGRAPH.JUSTIFY, first=5,
                         before=4, after=4, genera=genera)
                else:
                    level = b.get("level", 2)
                    try:
                        level = int(level)
                    except (TypeError, ValueError):
                        level = 2
                    heading(doc, text, min(level, 3), genera)
                prev_body = None
            elif role == "note":
                para(doc, text, size=9.5, italic=True,
                     align=WD_ALIGN_PARAGRAPH.JUSTIFY, first=5,
                     before=4, after=4, genera=genera)
                prev_body = None
            elif role == "body":
                # merge a page-split sentence
                if prev_body is not None and can_join(prev_body[0], text):
                    joined = join_texts(prev_body[0], text)
                    prev_body[1].clear()
                    add_runs(prev_body[1], joined, 10.5, genera=genera)
                    prev_body = (joined, prev_body[1])
                else:
                    # A lower-case opening is a paragraph continued after an
                    # intervening figure or caption; indenting it would print
                    # a paragraph break in the middle of a sentence.
                    first = 0 if text[:1].islower() else 5
                    par = para(doc, text, size=10.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                               first=first, line=1.02, genera=genera)
                    prev_body = (text, par)
            elif role == "citation":
                para(doc, text, size=9.2, left=4, first=-4, before=1, line=1.0, genera=genera)
                prev_body = None
            elif role == "key":
                key_para(doc, text, genera, key_breaks)
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
    # Never fall back to the Spanish source here: the English edition must
    # omit an untranslated caption rather than print source-language text.
    text = clean_text(cap_block.get('translation') or '')
    # OCR often appends the panel letters of the illustration as body text.
    text = re.sub(r'(?:\s+(?:[A-Z]|[A-Z][–-][A-Z])){2,}\s*$', '', text).rstrip()
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


def index_fixes(meta: BookMeta):
    """(old, new, evidence) for each declared source-index misprint."""
    for item in meta.index_entry_fixes:
        old, new = item[0], item[1]
        note = item[2] if len(item) > 2 else ""
        yield old, new, note


def apply_index_fixes(text: str, meta: BookMeta) -> tuple[str, bool]:
    """Correct source-index misprints; also report whether any was applied."""
    fixed = False
    for old, new, _note in index_fixes(meta):
        if old in text and old != new:
            fixed = True
        text = text.replace(old, new)
    return text, fixed


def index_entry_key(text: str) -> str:
    """Compare index rows without their dot leaders or spacing."""
    # Leaders arrive both as "......" and as ". . . ."; strip the spaced form.
    key = re.sub(r"(?:\.\s*){2,}", " ", text)
    return re.sub(r"\s+", " ", key).strip().lower()


def render_index(doc, data, genera, page_map, meta: BookMeta):
    entries = []
    seen_entries: set[str] = set()
    raw_intro = ''
    for p in data['pages']:
        if p['kind'] != 'index':
            continue
        for b in p['blocks']:
            if not b.get('translation'):
                continue
            if b['role'] != 'index':
                if 'ALPHABETICAL INDEX' in b['translation'].upper():
                    raw_intro = clean_text(b['translation'])
                continue
            text, fixed = apply_index_fixes(clean_text(b['translation']), meta)
            # An editorial fix can make two source variants identical; compare
            # without the dot leaders and print the entry once.
            key = index_entry_key(text)
            if key and key not in seen_entries:
                seen_entries.add(key)
                entries.append((text, fixed))
    if not entries:
        return
    printed_pages: dict[int, dict] = {}
    block_rows = []
    word_pages: dict[str, set[int]] = {}
    for p in data["pages"]:
        printed = p["page"] - meta.folio_offset
        printed_pages.setdefault(printed, p)
        if p.get("kind") == "index":
            continue
        for b in p["blocks"]:
            block_id = str(b.get("block_id") or "")
            text = unicodedata.normalize(
                "NFKC", clean_text(b.get("translation") or "")
            ).lower().replace("-", "")
            if not block_id or not text:
                continue
            block_rows.append((printed, b.get("y0") or 0, block_id, text))
            for word in set(re.findall(r"[^\W\d_]{4,}", text)):
                word_pages.setdefault(word, set()).add(printed)
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
    for text, fixed in entries:
        m = LEADER_RE.search(text)
        if not m:
            m2 = re.match(r'^(.*?)\s+((?:\d{1,3}(?:,\s*)?)+)$', text)
            if m2:
                left, right = m2.group(1).strip(), m2.group(2).strip()
                right = remap_refs(right, page_map, left, printed_pages,
                                   block_rows, word_pages)
                p = doc.add_paragraph()
                p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.tab_stops.add_tab_stop(Mm(62), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
                add_runs(p, left, 8.6, genera=genera)
                if fixed:
                    p.add_run('†')
                p.add_run('\t')
                add_runs(p, right, 8.6)
                continue
        if m:
            left = text[:m.start()].strip()
            right = text[m.end():].strip()
            right = remap_refs(right, page_map, left, printed_pages,
                               block_rows, word_pages)
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Mm(0)
            pf.space_before, pf.space_after = Pt(0), Pt(0)
            pf.line_spacing = 1.0
            pf.tab_stops.add_tab_stop(Mm(62), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            add_runs(p, left, 8.6, genera=genera)
            if fixed:
                p.add_run('†')
            p.add_run('\t')
            add_runs(p, right, 8.6)
        else:
            para(doc, text + ('†' if fixed else ''), size=8.6, line=1.0,
                 genera=genera)
    render_corrections(doc, meta, genera)


def render_corrections(doc, meta: BookMeta, genera=None):
    """End-of-book list of the source misprints corrected in the index."""
    fixes = list(index_fixes(meta))
    if not fixes:
        return
    doc.add_page_break()
    para(doc, meta.corrections_title, size=13, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
    if meta.corrections_intro:
        para(doc, meta.corrections_intro, size=8.8, italic=True,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8)
    for old, new, note in fixes:
        old_clean = old.strip('()')
        new_clean = new.strip('()')
        line = f"† Index entry “{old_clean}” corrected to “{new_clean}”."
        if note:
            line += " " + note
        para(doc, line, size=8.8, left=4, first=-4, after=3, line=1.0,
             genera=genera)


def remap_refs(right: str, page_map: dict[str, int | str],
               left: str = "", printed_pages: dict[int, dict] | None = None,
               block_rows: list[tuple[int, float, str, str]] | None = None,
               word_pages: dict[str, set[int]] | None = None) -> str:
    """Map source page numbers to this edition's pages.

    A source page can straddle two PDF pages, and the source index itself is
    occasionally off by a few pages.  Prefer the block that contains the cited
    name, first on the printed source page and then on the nearest page that
    has every name word; fall back to the numeric map.
    """
    # Join hyphenated names before tokenizing: the block text is normalized the
    # same way, so "saint-hilaire" must match as one word, not "saint"+"hilaire".
    words = re.findall(r"[^\W\d_]{4,}", left.lower().replace("-", ""))

    def contains_all(text: str) -> bool:
        return all(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)

    def repl(m):
        n = int(m.group(0))
        if words and printed_pages is not None:
            page = printed_pages.get(n)
            if page is not None:
                # A page's TYPE SPECIES citation can name the taxon before its
                # heading is printed on the next PDF page; prefer the heading or
                # entry block so the index points at the treatment, not the
                # citation that precedes it.
                rank = {"heading": 0, "entry": 1, "body": 2}
                for b in sorted(page["blocks"], key=lambda b: (
                        rank.get(b.get("role"), 3), b.get("y0") or 0)):
                    text = unicodedata.normalize(
                        "NFKC", clean_text(b.get("translation") or "")
                    ).lower().replace("-", "")
                    if contains_all(text):
                        block_page = page_map.get("block:" + str(b.get("block_id") or ""))
                        if block_page:
                            return str(block_page)
            if block_rows and word_pages:
                candidates = None
                for word in words:
                    hits = word_pages.get(word, set())
                    candidates = hits if candidates is None else candidates & hits
                    if not candidates:
                        break
                for nearest in sorted(candidates or (), key=lambda x: (abs(x - n), x)):
                    for printed, _y0, block_id, text in block_rows:
                        if printed == nearest and contains_all(text):
                            block_page = page_map.get("block:" + block_id)
                            if block_page:
                                return str(block_page)
        return str(page_map.get(str(n), n))
    return re.sub(r'\b\d{1,3}\b', repl, right)


def build(out_docx: Path, page_map: dict[str, int], paths: BookPaths, meta: BookMeta,
          key_breaks: set[str] | None = None) -> dict:
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
    render_body(doc, data, genera, figs, page_map, meta, paths.figures_dir, key_breaks)
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))
    return data


def match_text(t: str) -> str:
    """Normalize printed and aligned text to the same comparison form.

    PDF extraction keeps typographic ligatures (ﬂ, ﬁ) and italic markup in the
    aligned data marks names with asterisks; neither may hide a match.
    """
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\xad", "").replace("‑", "-")
    t = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", t)
    t = t.replace("*", "").replace("…", " ")
    t = re.sub(r"[�.]{4,}", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def make_page_map(pdf: Path, data: dict, meta: BookMeta) -> dict[str, int]:
    import fitz

    doc = fitz.open(pdf)
    norm = match_text

    def snippet(t):
        value = norm(t).replace("*", "")
        value = re.sub(r"^[•\d.,;:)\s]+", "", value)
        return value[:60]

    texts = [norm(p.get_text("text")) for p in doc]
    lines = [[norm(line).strip().upper() for line in p.get_text("text").splitlines() if line.strip()] for p in doc]
    page_map: dict[str, int] = {}
    # The appendix reprints source descriptions; searching its pages for body
    # snippets would map an early chapter to the appendix page.
    appendix_page = next(
        (i for i, page_lines in enumerate(lines)
         if any("APPENDIX 1" in line or line == "ANNEX" for line in page_lines[:5])),
        len(texts),
    )
    appendix_source = min(
        (p["page"] for p in data["pages"] if p["chapter"].startswith("Appendix")),
        default=10 ** 9,
    )
    bib_page = next(
        (i for i, page_lines in enumerate(lines)
         if any(line == "BIBLIOGRAPHY" for line in page_lines[:5])),
        len(texts),
    )
    body_search_end = min(appendix_page, bib_page)
    last = 0
    for p in data["pages"]:
        if p["page"] < meta.body_start_page or p["page"] >= appendix_source:
            continue
        heads, bodies, anys = [], [], []
        for b in p["blocks"]:
            t = clean_text(b.get("translation") or "")
            if b["role"] == "heading" and len(t) >= 24:
                heads.append(snippet(t))
            elif b["role"] in ("body", "heading") and len(t) >= 35:
                bodies.append(snippet(t))
            elif len(t) >= 15:
                anys.append(snippet(t))
        cands = sorted({c for c in heads if len(c) >= 18}, key=len, reverse=True)
        cands += [c for c in bodies if len(c) >= 25]
        cands += [c for c in anys if len(c) >= 15]
        found = None
        for snippet_text in cands:
            for i in range(last, min(len(texts), last + 12, body_search_end)):
                if snippet_text in texts[i]:
                    found = i
                    break
            if found is None:
                for i in range(max(0, last - 2), min(len(texts), last + 25, body_search_end)):
                    if snippet_text in texts[i]:
                        found = i
                        break
            if found is not None:
                break
        if found is not None:
            page_map[str(p["page"] - meta.folio_offset)] = found + 1
            last = found
    # Chapter headings are more reliable than running text for contents/index.
    # The contents page repeats every chapter title next to its page number;
    # matching there would map a chapter to the number printed in the contents.
    # Only the contents page repeats chapter titles.  The index title appears
    # as a running head on every index page; skipping those would make the
    # index chapter unmappable.
    front_marks = {meta.contents_title.upper()}
    skip_pages = {
        i for i, page_lines in enumerate(lines)
        if any(mark in line for line in page_lines[:4] for mark in front_marks)
    }
    prev = None
    chapter_starts: list[tuple[int, int, int | None]] = []
    for p in data["pages"]:
        if p["page"] < meta.body_start_page or p["chapter"] == prev:
            continue
        prev = p["chapter"]
        chapter_starts.append(
            (p["page"], p["page"] - meta.folio_offset,
             page_map.get(str(p["page"] - meta.folio_offset)))
        )
        title = meta.index_title if p["chapter"] == meta.index_chapter else meta.display(
            p["chapter"], p["chapter"]
        )
        keys = [title.upper()[:34]]
        short = re.split(r"[（(]", title.upper())[0].strip()[:34]
        if short and short not in keys:
            keys.append(short)
        for i in range(4, len(lines)):
            if i in skip_pages:
                continue
            def heading_match(line: str, key: str) -> bool:
                if not line.startswith(key):
                    return False
                # "BIBLIOGRAPHY. The Central Service..." is prose, not the
                # chapter heading; a heading continues with a space or is exact.
                return len(line) == len(key) or line[len(key)] not in ".,;:"

            if any(heading_match(line, key) for key in keys for line in lines[i][:4]):
                page_map[str(p["page"] - meta.folio_offset)] = i + 1
                break
    # A body snippet can also occur in the appendix, which maps a later page of
    # a chapter to the appendix.  Chapter headings give the true start; reject
    # mappings far outside that chapter's page range.
    for idx, (src, printed, out) in enumerate(chapter_starts):
        # The chapter-heading pass runs after the first pass, so read the
        # corrected start page here rather than the pre-pass snapshot.
        out = page_map.get(str(printed), out)
        if out is None:
            continue
        next_src = (chapter_starts[idx + 1][0]
                    if idx + 1 < len(chapter_starts) else 10 ** 9)
        for p in data["pages"]:
            if not (src <= p["page"] < next_src):
                continue
            key = str(p["page"] - meta.folio_offset)
            expected = out + (p["page"] - src)
            cur = page_map.get(key)
            # A direct text match is stronger evidence than the chapter's
            # one-source-page-per-PDF-page assumption; only fill gaps.
            if cur is None:
                page_map[key] = expected
    # The appendix is typeset denser than the Spanish source, so its PDF pages
    # do not advance one-for-one with source pages.  Locate the appendix start,
    # then match each page by its own text; the one-for-one estimate is only a
    # fallback for pages whose text cannot be found.
    appendix_pages_data = [p for p in data["pages"]
                           if p["page"] >= meta.body_start_page
                           and p["chapter"].startswith("Appendix")]
    if appendix_pages_data:
        first_src = min(p["page"] for p in appendix_pages_data)
        needle = ""
        for p in appendix_pages_data:
            for b in p["blocks"]:
                if b["role"] in ("entry", "heading", "body"):
                    needle = norm(clean_text(b.get("translation") or ""))[:60]
                    if len(needle) >= 20:
                        break
            if len(needle) >= 20:
                break
        # Appendix entries often reprint main-text passages, so the earliest
        # occurrence of the needle can be a body page.  The printed appendix
        # heading is the reliable floor; without it, take the last occurrence.
        detected = appendix_page < len(texts)
        floor = appendix_page if detected else 0
        hit = None
        if len(needle) >= 20:
            if detected:
                hit = next((i for i in range(floor, len(texts))
                            if needle in texts[i]), None)
            else:
                hit = next((i for i in range(len(texts) - 1, -1, -1)
                            if needle in texts[i]), None)
        if hit is not None:
            base = hit + 1
        elif detected:
            base = floor + 1
        else:
            base = None
        if base is not None:
            cursor = base - 1
            for p in appendix_pages_data:
                key = str(p["page"] - meta.folio_offset)
                cands = []
                for b in p["blocks"]:
                    t = norm(clean_text(b.get("translation") or ""))
                    if b["role"] in ("entry", "heading", "body") and len(t) >= 25:
                        cands.append(t[:60])
                found = None
                for snippet_text in cands:
                    for i in range(max(floor, cursor - 2), min(len(texts), cursor + 9)):
                        if snippet_text in texts[i]:
                            found = i
                            break
                    if found is not None:
                        break
                if found is not None:
                    page_map[key] = found + 1
                    cursor = found
                elif key not in page_map:
                    page_map[key] = base + (p["page"] - first_src)
    # Fill gaps monotonically from neighbouring mapped source pages.
    mapped_keys = sorted(int(k) for k in page_map)
    if mapped_keys:
        for k in range(mapped_keys[0], mapped_keys[-1] + 1):
            if str(k) in page_map:
                continue
            lo = max((x for x in mapped_keys if x < k), default=None)
            hi = min((x for x in mapped_keys if x > k), default=None)
            if lo is not None and hi is not None and hi > lo:
                v = page_map[str(lo)] + (k - lo) * (page_map[str(hi)] - page_map[str(lo)]) / (hi - lo)
                page_map[str(k)] = int(round(v))
            elif lo is not None:
                page_map[str(k)] = page_map[str(lo)] + (k - lo)
            elif hi is not None:
                page_map[str(k)] = max(1, page_map[str(hi)] - (hi - k))
    # A source page can straddle two PDF pages, so an index entry that points
    # at the source page may land before the name it cites.  Record the page
    # where each block's own text starts; the index uses it to correct such
    # references without guessing page numbers.
    for p in data["pages"]:
        start = page_map.get(str(p["page"] - meta.folio_offset))
        if start is None:
            continue
        for b in p["blocks"]:
            block_id = b.get("block_id")
            t = norm(clean_text(b.get("translation") or ""))
            if not block_id or len(t) < 20:
                continue
            snippet_text = t[:60]
            for i in range(max(0, start - 2), min(len(texts), start + 3)):
                if snippet_text in texts[i]:
                    page_map["block:" + block_id] = i + 1
                    break
    return page_map
