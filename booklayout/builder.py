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
from copy import deepcopy
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_BREAK, WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.image.image import Image as DocxImage
from docx.text.run import Run

from booklayout.english import is_english_word, worms_genera
from booklayout.profile import StyleProfile

BODY_FONT = "Garamond"
# 中文版把 eastAsia 字体设为宋体（Garamond 无汉字，Word 会随机回落）；英文版保持不变。
CJK_FONT = os.environ.get("BOOKLAYOUT_CJK_FONT", BODY_FONT)
_CJK = re.compile(r"[⺀-鿿＀-￯]")
TEXT_W = 134.0  # mm
PAGE_W, PAGE_H = 170.0, 240.0
# Page design lives in booklayout/profile.py (issue #27); the defaults there
# equal the constants above, so output is unchanged unless a profile is applied.
PROFILE = StyleProfile()


def apply_profile(profile: StyleProfile) -> None:
    """Make ``profile`` the active page design (module-level, per process)."""
    global PROFILE, BODY_FONT, CJK_FONT, TEXT_W, PAGE_W, PAGE_H
    profile.validate()
    PROFILE = profile
    BODY_FONT = profile.body_font
    CJK_FONT = profile.cjk_font or os.environ.get("BOOKLAYOUT_CJK_FONT", profile.body_font)
    TEXT_W, PAGE_W, PAGE_H = profile.text_w, profile.page_w, profile.page_h

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
FIG_RE = re.compile(r"(?:\bFigs?\.|图)\s*(\d+[′']?)")


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
    include_contents: bool = True
    # Source-only reproduction (OCR of the original, no translation): the
    # book's own cover, title and contents pages are printed instead of
    # synthesized ones.
    title_page: bool = True  # False: no title page made from title/volume
    contents_in_place: bool = False  # print role "index" contents lines where they stand
    contents_indent_prefixes: list[str] = field(default_factory=list)  # e.g. ["Género"]
    own_pages: list[int] = field(default_factory=list)  # source pages that start a new page and are followed by one
    centered_pages: list[int] = field(default_factory=list)  # source pages set centred (cover, title)
    front_pages: list[int] = field(default_factory=list)  # title/copyright/board/author pages typeset line by line (frontmatter.py)
    # Source pages printed as the scan itself (cover photo, logo plates that OCR
    # cannot reproduce): figs_dir/source_pages/pNNNN.png, one full page each.
    image_pages: list[int] = field(default_factory=list)
    authors_title: str = "AUTHORS"
    authors: list[tuple[str, str]] = field(default_factory=list)
    contributions_title: str = "CONTRIBUTIONS"
    contributions: list[tuple[str, str]] = field(default_factory=list)
    license_note: str = ""
    chapter_titles: dict[str, str] = field(default_factory=dict)
    body_start_page: int = 1
    folio_offset: int = 3
    # Folio footer.  folio_start: number printed on output page 1 (Vol. 25: the scan
    # lacks 3 leading pages, so pdf page 1 prints as 4).  folio_first_page: first source
    # page that carries a footer; the own pages before it print none (a section break
    # separates them).  0 = footer from page 2 on, as before.
    folio_start: int = 1
    folio_first_page: int = 0
    folio_bold: bool = True  # page number bold (Vol. 25 source: regular)
    footer_italic: bool = True  # running text italic unless it carries <i> markup
    # When the source starts a chapter part-way down a page, insert the
    # chapter title at its real position instead of moving it to page top.
    heading_in_flow: bool = False
    # False: no synthesized chapter title (excerpts/trials whose pages carry no chapter heading).
    chapter_headings: bool = True
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
    if PROFILE.lang_east_asia.lower().startswith("zh"):
        s = cjk_punct(s)
    return s.strip()


_CJKP = r'[\u3040-\u30ff\u3400-\u9fff\uff00-\uffef\u3000-\u303f]'
_FW = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}


def cjk_punct(s: str) -> str:
    """Chinese text: ASCII punctuation touching CJK becomes full-width; spaces beside it go."""
    s = re.sub(rf'(?:(?<={_CJKP})|(?<={_CJKP}\s))\s*([,;:?!])\s*|\s*([,;:?!])\s*(?={_CJKP})',
               lambda m: _FW[m.group(1) or m.group(2)], s)
    s = re.sub(rf'\s*\((?=\s*{_CJKP})\s*', '（', s)
    s = re.sub(rf'(?<={_CJKP})\s*\(', '（', s)
    s = re.sub(rf'(?<={_CJKP})\s*\)', '）', s)
    s = re.sub(r'（([^（）]*?)\)', r'（\1）', s)
    # 「Pettibone(1953)指出」「(Narchi, 1969)。」：括号后接汉字或中文标点时也用全角，
    # 与同段「（原文「…」）」一致，避免半角/全角括号混排。
    s = re.sub(rf'\(([^()（）]*?)\)(?=\s*{_CJKP})', r'（\1）', s)
    s = re.sub(r'(?<=\d)\s*~\s*(?=\d)', '–', s)
    return s


def _no_dup_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def load_aligned(path: Path) -> dict:
    """Duplicate keys at any level are an error: last-one-wins would silently drop data on write-back."""
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_dup_pairs)


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
                for m in re.finditer(
                        r'\b(?:[Ff]amilia|[Ss]ubfamilia|[Gg]énero|[Gg]enero|'
                        r'[Ss]ubgénero|[Ss]ubgenero|[Gg]enus|[Ss]ubgenus)'
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
            m = re.match(r'^([A-Z][a-z]{2,})\s+([a-z(][^\s]*)', t)
            if m:
                second = m.group(2).lower().strip(',.;:()')
                if second not in FUNCTION_WORDS and not is_english_word(second) \
                        and second not in SPANISH_STOP:
                    names.add(m.group(1))
    names -= {'The', 'This', 'These', 'Their', 'With', 'From', 'Only', 'Both', 'Each', 'Body', 'Tubes'}
    return names


def _markdown_chunks(text: str) -> list[tuple[str, bool, bool]]:
    """Split translated text into (chunk, italic, bold) pieces.

    ``*x*`` is italic (genus names); ``**x**`` is bold (run-in headings such
    as 形态 / 分布).  Printing the markers literally is a layout defect
    (``*Arabella*``), so they are consumed here.  Unpaired asterisks left by a
    split aligner are dropped.
    """
    chunks: list[tuple[str, bool, bool]] = []
    pos = 0
    for m in re.finditer(r'(\*{1,2})([^*]+)\*{1,2}', text):
        if m.start() > pos:
            chunks.append((text[pos:m.start()], False, False))
        two = len(m.group(1)) == 2
        chunks.append((m.group(2), not two, two))
        pos = m.end()
    if pos < len(text):
        chunks.append((text[pos:], False, False))
    return [(c.replace('*', ''), it, bd) for c, it, bd in chunks if c.replace('*', '')]


# Zoological convention (ICZN governs only the names; typography is custom): names above genus rank (family-group
# -oidea/-idae/-inae/-ini) are set roman; only genus- and species-group names
# are italic.  Applied to every emitted run so no caller can print one in italic.
_FAMILY_GROUP_RX = re.compile(r"\b[A-Z][a-z]{2,}(?:oidea|idae|inae|ini)\b")


def _roman_family_group(pieces: list[tuple[str, bool, bool]]) -> list[tuple[str, bool, bool]]:
    out: list[tuple[str, bool, bool]] = []
    for chunk, ital, bd in pieces:
        pos = 0
        for m in _FAMILY_GROUP_RX.finditer(chunk):
            if m.start() > pos:
                out.append((chunk[pos:m.start()], ital, bd))
            out.append((m.group(0), False, bd))
            pos = m.end()
        out.append((chunk[pos:], ital, bd)) if pos else out.append((chunk, ital, bd))
    return [p for p in out if p[0]]


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
    if re.search(r"</?su[pb]>", text):
        # the source carries HTML for ordinals and formulae ("3<sup>rd</sup>"): real super/subscript runs
        for part in re.split(r"(<su[pb]>.*?</su[pb]>)", text):
            m = re.match(r"<(su[pb])>(.*?)</su[pb]>$", part)
            if not m:
                first = len(par.runs)
                add_runs(par, re.sub(r"</?su[pb]>", "", part), size, bold, italic, color, genera, invert)
                if len(par.runs) > first:  # clean_text trims the ends; the glue to the tag is real
                    par.runs[first].text = part[: len(part) - len(part.lstrip())] + par.runs[first].text
                    par.runs[-1].text += part[len(part.rstrip()):]
                continue
            first = len(par.runs)
            add_runs(par, m.group(2), size, bold, italic, color, None, invert)
            for run in par.runs[first:]:
                if m.group(1) == "sup":
                    run.font.superscript = True
                else:
                    run.font.subscript = True
        return
    pieces: list[tuple[str, bool, bool]] = []
    for chunk, md_italic, md_bold in _markdown_chunks(text):
        if md_bold:
            pieces.append((chunk, italic, True))
            continue
        if md_italic:
            # 译者有时把连词也圈进星号（「*Audouin and* Milne Edwards」），
            # 连词移到斜体之外；整条书名/刊名仍保持斜体。
            m = re.match(r'^(.*\S)\s+(and|y|e|et|or|&)$', chunk)
            if m:
                pieces.append((m.group(1), True, bold))
                pieces.append((" " + m.group(2), italic, bold))
            else:
                pieces.append((chunk, (not italic) if invert else True, bold))
            continue
        if not genera:
            pieces.append((chunk, italic, bold))
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
                pieces.append((chunk[pos:m.start()], italic, bold))
            pieces.append((name, (not italic) if invert else True, bold))
            pos = end
        if pos < len(chunk):
            pieces.append((chunk[pos:], italic, bold))
    if not pieces:
        pieces = [(text.replace('*', ''), italic, bold)]
    pieces = _roman_family_group(pieces)
    for chunk, ital, bd in pieces:
        run = par.add_run(chunk)
        run.font.name = BODY_FONT
        run._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
        # Word needs the eastAsia hint on a run that actually contains CJK
        # text (the translator's Chinese name); without it the run may fall
        # back to the Latin font and render boxes/missing glyphs.
        if _CJK.search(chunk):
            run._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
        if size is not None:
            run.font.size = Pt(size)
        run.bold = bd
        run.italic = ital
        if color is not None:
            run.font.color.rgb = color


def setup(doc: Any):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(PAGE_W), Mm(PAGE_H)
    sec.top_margin, sec.bottom_margin = Mm(PROFILE.margin_top), Mm(PROFILE.margin_bottom)
    sec.left_margin, sec.right_margin = Mm(PROFILE.margin_left), Mm(PROFILE.margin_right)
    sec.header_distance, sec.footer_distance = Mm(PROFILE.header_distance), Mm(PROFILE.footer_distance)
    sec.different_first_page_header_footer = True
    st = doc.styles['Normal']
    st.font.name = BODY_FONT
    st.font.size = Pt(PROFILE.body_size)
    st._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0
    define_heading_styles(doc)
    # Justified text without hyphenation produces rivers and huge word gaps,
    # especially around long taxonomic names and citations.
    rpr = st._element.get_or_add_rPr()
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), PROFILE.lang)
    lang.set(qn("w:eastAsia"), PROFILE.lang_east_asia)
    rpr.append(lang)
    settings = doc.settings.element
    anchor = settings.find(qn("w:compat"))
    index = list(settings).index(anchor) if anchor is not None else len(settings)
    for tag, value in (
        ("w:autoHyphenation", "true" if PROFILE.hyphenation else "false"),
        ("w:consecutiveHyphenLimit", "2"),
        ("w:hyphenationZone", "357"),
    ):
        element = OxmlElement(tag)
        element.set(qn("w:val"), value)
        settings.insert(index, element)
        index += 1


def _page_field(par, size: float, bold: bool = False) -> None:
    def fld(kind=None, instr=None, text=None):
        r = par.add_run(text) if text else par.add_run()
        r.font.name, r.font.size, r.bold = BODY_FONT, Pt(size), bold
        if kind:
            e = OxmlElement('w:fldChar')
            e.set(qn('w:fldCharType'), kind)
            r._r.append(e)
        elif instr is not None:
            e = OxmlElement('w:instrText')
            e.set(qn('xml:space'), 'preserve')
            e.text = instr
            r._r.append(e)
    fld('begin')
    fld(instr=' PAGE ')
    fld('separate')
    fld(text='1')
    fld('end')


def _rule_above(par, color: str = "808080", sz: int = 4) -> None:
    pPr = par._p.get_or_add_pPr()
    bdr = OxmlElement('w:pBdr')
    top = OxmlElement('w:top')
    for k, v in (('w:val', 'single'), ('w:sz', str(sz)), ('w:space', '4'), ('w:color', color)):
        top.set(qn(k), v)
    bdr.append(top)
    pPr.insert_element_before(
        bdr, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
        "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi",
        "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
        "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
        "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
        "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def _clear_style_tabs(par) -> None:
    """Cancel the tab stops a paragraph inherits from its style.

    Word's Header/Footer styles carry a centre tab at 3.25 in and a right tab at
    6.5 in; on a text block narrower than 6.5 in the first TAB lands on the centre
    stop, so the right-hand footer item printed mid-page (Vol. 25, H8)."""
    st = par.style
    while st is not None:
        for ts in st.paragraph_format.tab_stops:
            par.paragraph_format.tab_stops.add_tab_stop(ts.position, WD_TAB_ALIGNMENT.CLEAR)
        st = st.base_style


_MARK = re.compile(r"(<i>.*?</i>)")


def _folio_footer(sec, meta: BookMeta, doc: Any) -> None:
    """Ruled footer, odd/even mirrored: even = page + running_right, odd = running_left + page."""
    doc.settings.odd_and_even_pages_header_footer = True
    size = PROFILE.footer_size - 1
    for ft, page_first in ((sec.even_page_footer, True), (sec.footer, False)):
        ft.is_linked_to_previous = False
        fp = ft.paragraphs[0]
        for r in list(fp.runs):
            r._r.getparent().remove(r._r)
        _clear_style_tabs(fp)
        fp.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
        _rule_above(fp)
        def text(s: str):
            # "<i>ANNELIDA POLYCHAETA</i> I": only the marked part italic; no markup: footer_italic
            marked = "<i>" in s
            for part in _MARK.split(s):
                if not part:
                    continue
                ital = part.startswith("<i>") if marked else meta.footer_italic
                part = part[3:-4] if part.startswith("<i>") else part
                r = fp.add_run(part)
                r.font.name, r.font.size, r.italic = BODY_FONT, Pt(size), ital
                r._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
                if _CJK.search(part):  # 纯英文串不设 eastAsia 提示，否则 Word 标点变全角
                    r._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
        if page_first:
            _page_field(fp, size, bold=meta.folio_bold)
            text('\t' + meta.running_right)
        else:
            text(meta.running_left + '\t')
            _page_field(fp, size, bold=meta.folio_bold)


def _blank_header_footer(sec) -> None:
    """Own, empty header and footers: the front pages before folio_first_page print none."""
    for hf in (sec.header, sec.even_page_header, sec.first_page_header,
               sec.footer, sec.even_page_footer, sec.first_page_footer):
        hf.is_linked_to_previous = False
        for p in hf.paragraphs:
            for r in list(p.runs):
                r._r.getparent().remove(r._r)


def _set_folio_start(sec, start: int) -> None:
    sp = sec._sectPr
    for old in sp.findall(qn('w:pgNumType')):
        sp.remove(old)
    if start == 1:
        return
    pg = OxmlElement('w:pgNumType')
    pg.set(qn('w:start'), str(start))
    sp.insert_element_before(pg, 'w:cols', 'w:formProt', 'w:vAlign', 'w:noEndnote', 'w:titlePg',
                             'w:textDirection', 'w:bidi', 'w:rtlGutter', 'w:docGrid',
                             'w:printerSettings', 'w:sectPrChange')


def start_folio_section(doc: Any, meta: BookMeta) -> None:
    """New page and section where the source starts printing footers; numbering continues."""
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    _set_folio_start(sec, 1)  # the clone carries pgNumType start: drop it, or numbering restarts
    sec.different_first_page_header_footer = False
    for hf in (sec.header, sec.even_page_header, sec.footer, sec.even_page_footer):
        hf.is_linked_to_previous = False  # a linked part resolves to the blank front definition
    set_header_footer(sec, meta, doc)


def set_header_footer(sec, meta: BookMeta, doc: Any = None):
    if PROFILE.footer_style == "folio" and doc is not None:
        sec.header.is_linked_to_previous = False
        sec.header.paragraphs[0].text = ''
        _folio_footer(sec, meta, doc)
        return
    hdr = sec.header
    hp = hdr.paragraphs[0]
    hp.text = ''
    _clear_style_tabs(hp)
    hp.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
    r = hp.add_run(re.sub(r"</?i>", "", meta.running_left))
    r.font.name, r.font.size, r.italic = BODY_FONT, Pt(PROFILE.header_size), True
    r._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    if _CJK.search(meta.running_left):
        r._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
    r2 = hp.add_run('\t' + re.sub(r"</?i>", "", meta.running_right))
    r2.font.name, r2.font.size, r2.italic = BODY_FONT, Pt(PROFILE.header_size), True
    r2._element.rPr.rFonts.set(qn('w:eastAsia'), CJK_FONT)
    if _CJK.search(meta.running_right):
        r2._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
    ft = sec.footer
    fp = ft.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    def fld_run(kind=None, instr=None):
        r = fp.add_run()
        r.font.name, r.font.size = BODY_FONT, Pt(PROFILE.footer_size)
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


def _sz(size: float) -> float:
    """Hard-coded sizes are written for a 10.5 pt body; scale to PROFILE.body_size."""
    return round(size * PROFILE.body_size / 10.5, 2)


def para(doc, text='', size=10.5, bold=False, italic=False, align=None, first=0.0,
         left=0.0, before=0.0, after=0.0, keep=False, genera=None, color=None,
         line=1.0, invert=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    if _KEY_STATE.pop("gap", False):
        before = max(before, 7.0)  # air between a key table and what follows
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = line
    pf.first_line_indent = Mm(first)
    pf.left_indent = Mm(left)
    pf.keep_with_next = keep
    pf.widow_control = True
    if align is not None:
        p.alignment = align
    if text:
        add_runs(p, text, _sz(size), bold, italic, color, genera, invert)
    if PROFILE.lang_east_asia.lower().startswith("zh"):
        _suppress_hyphenation(p)  # CJK paragraphs: never split a Latin word at a line end
    return p


def page_break(doc) -> None:
    """Start a new page without creating an empty page after a page break."""
    if doc.paragraphs:
        last = doc.paragraphs[-1]._element
        if any(br.get(qn("w:type")) == "page" for br in last.iter(qn("w:br"))):
            return
    doc.add_page_break()


_ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
          "right": WD_ALIGN_PARAGRAPH.RIGHT}


def define_heading_styles(doc: Any, profile: Any = None) -> None:
    """(Re)write the named styles Heading 1/2/3 from ``profile.heading_styles``.

    Every heading paragraph only references its style (no direct size, spacing,
    alignment, bold or small caps), so changing one profile entry and calling
    this function again restyles every heading of that level at once --
    ``booklayout restyle`` does exactly that on a finished DOCX in well under a
    second, without re-typesetting the book.
    """
    prof = profile or PROFILE
    for level in (1, 2, 3, 4):
        cfg = prof.heading_style(level)
        st = doc.styles[f"Heading {level}"]
        st.base_style = doc.styles["Normal"]
        st.next_paragraph_style = doc.styles["Normal"]
        font = st.font
        font.name = BODY_FONT
        font.size = Pt(round(cfg["size"] * prof.body_size / 10.5, 2))
        font.bold = bool(cfg["bold"])
        font.italic = bool(cfg["italic"])
        font.small_caps = bool(cfg["small_caps"])
        font.color.rgb = RGBColor.from_string(str(cfg["color"]).upper())
        rpr = st.element.get_or_add_rPr()
        for el in rpr.findall(qn("w:color")):
            for attr in ("w:themeColor", "w:themeShade", "w:themeTint"):
                el.attrib.pop(qn(attr), None)
        rf = rpr.get_or_add_rFonts()
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            rf.attrib.pop(qn(attr), None)
        rf.set(qn("w:eastAsia"), CJK_FONT)
        pf = st.paragraph_format
        pf.space_before = Pt(cfg["before"])
        pf.space_after = Pt(cfg["after"])
        pf.line_spacing = 1.0
        pf.keep_with_next = True
        pf.keep_together = True
        pf.widow_control = True
        pf.first_line_indent = Mm(0)
        pf.left_indent = Mm(0)
        pf.alignment = _ALIGN[cfg["align"]]


def heading(doc, text, level, genera, chapter_start=False):
    """A heading paragraph: style reference only, all looks live in the style."""
    p = doc.add_paragraph(style=f"Heading {level}")
    add_runs(p, text, None, None, None, None, genera)
    if PROFILE.lang_east_asia.lower().startswith("zh"):
        _suppress_hyphenation(p)
    if chapter_start:
        # A separate page-break paragraph at the bottom of a full page creates
        # an empty page.  page_break_before on the heading itself cannot.
        p.paragraph_format.page_break_before = True
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
    _widen_glue(p, start)


# U+202F is narrow (and near zero after an italic run in LibreOffice), so
# "Aphrodita 3" printed as "Aphrodita3".  Each glue character goes into its own
# run with expanded character spacing: still unbreakable, as wide as a space.
_GLUE = " "
_GLUE_SPACING_TWIPS = 30  # +1.5 pt
# CT_RPr children that the schema puts after <w:spacing>
_RPR_AFTER_SPACING = {"w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr",
                      "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
                      "specVanish", "oMath"}


def _widen_glue(p, start: int) -> None:
    for run in list(p.runs[start:]):
        if _GLUE not in run.text or run.text == _GLUE:
            continue
        parts = re.split(f"({_GLUE})", run.text)
        run.text = parts[0]
        anchor = run._r
        for part in parts[1:]:
            if not part:
                continue
            r = deepcopy(run._r)
            for t in r.findall(qn("w:t")):
                r.remove(t)
            anchor.addnext(r)
            anchor = r
            new = Run(r, p)
            new.text = part
            if part == _GLUE:
                rpr = r.get_or_add_rPr()
                sp = OxmlElement("w:spacing")
                sp.set(qn("w:val"), str(_GLUE_SPACING_TWIPS))
                later = [c for c in rpr if c.tag.split("}")[-1] in _RPR_AFTER_SPACING]
                if later:
                    later[0].addprevious(sp)
                else:
                    rpr.append(sp)


# A key address (couplet name / target) starts with the taxon it leads to.
# Translations sometimes lack the *...* markup ("M. fragilis（第287页）",
# "Pontogenia"); italicise a leading genus, abbreviated genus + epithet or full
# binomial/trinomial.  Suprageneric names (-idae, -inae, ...) stay roman.
_ADDR_NAME = re.compile(
    r"^(?P<n>(?:[A-Z][a-z]+|[A-Z]\.)(?:\s+(?:\([A-Z][a-z]+\)\s+)?[a-z][a-z\-]{2,}){0,2})(?=$|[\s（(,，])")
_SUPRAGENERIC = re.compile(r"(?:idae|inae|oidea|ini|ida|ina)$")


def italicize_key_address(s: str) -> str:
    if not s:
        return s
    if "*" in s:
        return re.sub(r"(?<=[a-z])\*\(", "* (", s)  # "*P. macleari*(Haswell)"
    m = _ADDR_NAME.match(s.strip())
    if not m:
        return s
    n = m.group("n")
    words = n.split()
    if len(words) == 1 and (n.endswith(".") or _SUPRAGENERIC.search(n) or is_english_word(n.lower())):
        return s  # a lone "M." or a family/subfamily name
    if any(w.lower() in FUNCTION_WORDS or is_english_word(w.lower()) for w in words[1:]):
        return s
    s = s.strip()
    return f"*{n}*" + (" " if s[len(n):len(n) + 1] == "(" else "") + s[len(n):]


MIN_KEY_LEADER_MM_B = 40.0  # keep equal to cli.MIN_KEY_LEADER_MM


def wid_of(s: str, size: float) -> float:
    """Rough set width in mm (CJK = 1 em, Latin = 0.5 em)."""
    return sum(size if ord(ch) > 255 else size * 0.5 for ch in s) * 25.4 / 72


KEY_NAME_COL_MM = 70.0  # left edge of the shared taxon-name column in a key
_KEY_PAGE_REF = re.compile(r"\s+(\(p\.\s*\d+\))\s*$")
_KEY_TRAILING_NUMBER = re.compile(r"^(?P<name>.*\S)\s+(?P<target>\d{1,3}[\u2032']?(?:[-\u2013]\d{1,3})?)$")
_KEY_FIG_END = re.compile(r"(?:\bFigs?|\bfigs?|\bpp?|\bpl|\bPl)\.?$")


def split_key_target(right: str) -> tuple[str, str]:
    """Split what follows a key leader into (name, target).

    The source books set a key as columns: marker+text, a taxon-name column
    (which may carry a figure reference) and, at the right edge, the target
    (couplet number or page).  ``"O. farensis (p. 76)"`` -> name + ``(p. 76)``;
    ``"2"`` -> no name; ``"Syllis x (Fig. 63) 12"`` -> name + ``12``; a name
    with a figure reference but no page stays a name.
    """
    right = right.strip()
    m = _KEY_PAGE_REF.search(right)
    if m:
        return right[: m.start()].strip(), m.group(1)
    if re.fullmatch(r"\d{1,3}[\u2032']?(?:[-\u2013]\d{1,3})?", right):
        return "", right
    m = _KEY_TRAILING_NUMBER.match(right)
    if m and re.search(r"[^\W\d_]", m.group("name")) and not _KEY_FIG_END.search(m.group("name")):
        return m.group("name"), m.group("target")
    return right, ""


def tabbed(doc, left, right, size, left_indent=0.0, genera=None, bold_left=False,
           force_break=False, name_col_mm: float = KEY_NAME_COL_MM):
    """One key line in the source book's column layout (issue #35).

    Marker, text, wraps and alternate lines all start at the left margin (no
    first-line indent, as in the source).  Right of the text there are two
    slots: a taxon-name column at ``name_col_mm`` reached through a dot leader,
    and the target (couplet number or page) flush right.  Without a name the
    target alone takes the right tab behind the leader.  A target or name that
    does not fit moves to a new line whose leader starts at the left margin.
    """
    name, target = split_key_target(right)
    name, target = italicize_key_address(name), italicize_key_address(target)
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Mm(0)
    pf.first_line_indent = Mm(left_indent) if left_indent else None
    pf.space_before, pf.space_after = Pt(0), Pt(0)
    pf.line_spacing = 1.0
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    two_slots = bool(name and target)
    if not force_break and (name or target):
        # Estimate where the text's last line ends.  When it runs past the name
        # column the tab jumps to the right stop, the name lands flush right and
        # the target wraps (v41 p.6 couplet 1); break first so name and target
        # take their own slots on a leader-filled line.
        pt_mm = 25.4 / 72
        wid = sum(size if ord(ch) > 255 else size * 0.5 for ch in left) * pt_mm
        last = wid % TEXT_W if wid > TEXT_W else wid
        need = (name_col_mm if name else TEXT_W - wid_of(target, size) - MIN_KEY_LEADER_MM_B)
        if last > need - 40 if name else last > need:  # key-report wants a leader >= 40 mm
            force_break = True
    if name:
        pf.tab_stops.add_tab_stop(Mm(name_col_mm), WD_TAB_ALIGNMENT.LEFT, WD_TAB_LEADER.DOTS)
    if target:
        pf.tab_stops.add_tab_stop(
            Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT,
            WD_TAB_LEADER.SPACES if two_slots else WD_TAB_LEADER.DOTS)
    add_runs(p, left, size, bold=bold_left, genera=genera)
    if force_break:
        # A couplet whose leader would be shorter than MIN_KEY_LEADER_MM gets
        # the same treatment as an over-long target: the whole address moves
        # to a leader-filled line.  A two-dot leader reads as an ellipsis.
        p.add_run().add_break()
    p.add_run('\t')
    slot_start = len(p.runs)
    if name:
        add_runs(p, name, size, genera=genera)
        _atomic_target(p, slot_start)
    if target:
        if name:
            p.add_run('\t')
        target_start = len(p.runs)
        add_runs(p, target, size, genera=genera)
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


# A couplet leader shorter than this reads as an ellipsis; below it the address
# moves to a new leader-filled line.  The Imajima original sets leaders of
# about 8 mm on the same line (v2001 p.5, "Arctonoinae ....... 31").
COUPLET_MIN_LEADER_MM = MIN_KEY_LEADER_MM_B  # same floor as the key-leader gate (cli.MIN_KEY_LEADER_MM); was 8 mm -> gate FAIL on Fauna Vol21 couplet 23
COUPLET_FILL_MIN_MM = 3.0  # shorter remainders end the line without dots
_MM_PER_PT = 25.4 / 72
_FONT_CACHE: dict = {}
_HAN = f"{chr(0x3400)}-{chr(0x9FFF)}{chr(0xF900)}-{chr(0xFAFF)}"
_CJK_CLASS = f"{chr(0x3000)}-{chr(0x303F)}{_HAN}{chr(0xFF00)}-{chr(0xFFEF)}"
_NO_LINE_START = set("，。；：、）」』》？！…%")
_MEASURE_WORD = re.compile(f"(?<=[0-9])(?=[{_HAN}])")


def join_number_measure(text: str) -> str:
    """Glue a number to the Han character after it ("13对", "2对颚").

    CJK line breaking allows a break before any Han character, which printed
    "背鳞 13 / 对".  The same widened U+202F glue as key targets (see
    _widen_glue) forbids that break and keeps the usual CJK/digit gap; a
    zero-width U+2060 also forbids it but LibreOffice then drops the gap.
    """
    return _MEASURE_WORD.sub(_GLUE, text)


def _font(kind: str, size: float):
    key = (kind, size)
    if key not in _FONT_CACHE:
        font = None
        try:
            from PIL import ImageFont
            path = {"cjk": "/mnt/c/Windows/Fonts/simsun.ttc", "latin": "/mnt/c/Windows/Fonts/times.ttf",
                    "italic": "/mnt/c/Windows/Fonts/timesi.ttf"}[kind]
            font = ImageFont.truetype(path, int(round(size * 20)))  # 20x for sub-point precision
        except (ImportError, OSError):
            font = None
        _FONT_CACHE[key] = font
    return _FONT_CACHE[key]


def _char_mm(ch: str, size: float, italic: bool) -> float:
    if ch == _GLUE:
        return size * 0.25 * _MM_PER_PT
    cjk = ord(ch) > 0x2E7F
    font = _font("cjk" if cjk else ("italic" if italic else "latin"), size)
    if font is None:
        return (size if ord(ch) > 255 else size * 0.5) * _MM_PER_PT
    return float(font.getlength(ch)) / 20 * _MM_PER_PT


def text_mm(s: str, size: float) -> float:
    """Set width in mm of a short marked-up string (*italic* honoured)."""
    total, italic = 0.0, False
    for ch in s:
        if ch == "*":
            italic = not italic
            continue
        total += _char_mm(ch, size, italic)
    return total


def last_line_mm(text: str, size: float, line_w: float) -> float:
    """Width of the last line of ``text`` after greedy wrapping at ``line_w``.

    Han characters break anywhere except before closing punctuation; Latin
    words and digit runs stay whole.  Word's automatic CJK/Latin spacing
    (autoSpaceDE/DN) adds about a quarter em at each script change.
    """
    tokens: list[tuple[str, bool]] = []
    italic = False
    for part in re.split(r"(\*)", text):
        if part == "*":
            italic = not italic
            continue
        for tok in re.findall(f"[{_CJK_CLASS}]|[^{_CJK_CLASS}\\s]+|\\s+", part):
            if tokens and tok[0] in _NO_LINE_START:
                tokens[-1] = (tokens[-1][0] + tok, tokens[-1][1])
            else:
                tokens.append((tok, italic))
    gap = size * 0.25 * _MM_PER_PT
    last, prev_cjk = 0.0, None
    for tok, it in tokens:
        w = sum(_char_mm(ch, size, it) for ch in tok)
        if not tok.strip():
            last += w  # a space may hang past the margin
            continue
        cjk = ord(tok[0]) > 0x2E7F
        if prev_cjk is not None and cjk != prev_cjk:
            w += gap
        last = w if last + w > line_w and last > 0 else last + w
        prev_cjk = cjk
    return last


def couplet_para(doc, block: dict, text: str, genera, mark_mm: float = 9.0, hang_mm: float = 16.0):
    """One key couplet in the v7 template: hanging indent, marker, tab, text,
    real right tab with dot leader, [name] target flush right.

    Single right tab only (no name column): name and target are one atomic
    address.  When the text's last line leaves too little room for it, the
    address goes to its own leader-filled line.
    """
    c = block.get("couplet") or {}
    marker = (c.get("marker") or c.get("lead") or "").strip()
    right = " ".join(italicize_key_address(x) for x in (c.get("name"), c.get("target")) if x)
    size = PROFILE.body_size
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent, pf.first_line_indent = Mm(hang_mm), Mm(mark_mm - hang_mm)
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(0), 1.15
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.tab_stops.add_tab_stop(Mm(hang_mm - 0.1))
    pf.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    # Rule 7 (keyrender KR7): a lead never breaks over a page, and "n." stays
    # on the page of its "—" partner.
    pf.keep_together = True
    pf.keep_with_next = marker not in ("—", "-", "–")
    # Rules 1-2 (KR1/KR2): the marker tab must be its own run.  add_runs()
    # passes text through clean_text(), which turns a tab into a space; then
    # the text of "1." started at x=86 pt, of "—" at x=90 pt, and wrapped lines
    # at x=96 pt (Imajima keys, 2026-11-23).
    if marker:
        add_runs(p, marker, size, genera=genera)
        if not marker.isascii():  # "—": typeset by the CJK font, as in the text
            p.runs[-1]._element.rPr.rFonts.set(qn('w:hint'), 'eastAsia')
        p.add_run("\t")
    add_runs(p, join_number_measure(text), size, genera=genera)
    _widen_glue(p, 0)
    if right:
        line_w = TEXT_W - hang_mm
        room = line_w - last_line_mm(text, size, line_w)
        if room < text_mm(right, size) + COUPLET_MIN_LEADER_MM:
            # Standard key setting (Imajima original, Chinese keys): the dots
            # run on to the right margin of the text's last line, then a new
            # line of dots leads to the address.  No blank tail is left.
            if room >= COUPLET_FILL_MIN_MM:
                p.add_run("\t")
            p.add_run().add_break()
        p.add_run("\t")
        start = len(p.runs)
        add_runs(p, right, size, genera=genera)
        _atomic_target(p, start)
    _suppress_hyphenation(p)
    return p



def key_couplets(doc, text: str, genera) -> list:
    """Set a key block as hanging couplets (profile ``key_style: "couplet"``).

    Fauna Ibérica sets a key at body size: marker in a hanging indent, the
    text, a dot leader and the address ("*Neopetitia* (p. 49)" or "4") flush
    right as one unit.  The "tabs" style's separate taxon-name column split
    such an address: the name landed at the end of the text line and
    "(p. 49)" on a dot line of its own (Vol. 21 p. 47, 2026-11-25).
    """
    out = []
    for marker, body, right in parse_key_rows(text):
        name, target = split_key_target(right) if right else ("", "")
        block = {"couplet": {"marker": marker, "name": name, "target": target}}
        out.append(couplet_para(doc, block, body, genera))
    return out


_KEY_MARK = re.compile(r"^\s*(\d{1,3}[.)]|[•·*]|[-–—])\s*")
_KEY_ROW_BORDER = "D0D4DA"


def parse_key_rows(text: str) -> list[tuple[str, str, str]]:
    """Split one key block into (marker, characters, target) rows.

    Same cleaning and couplet splitting as ``key_para``; a line without a
    leader has an empty target (introductory notes keep their own row).
    """
    text = re.sub(chr(0xFFFD) + "+", " …… ", text)
    text = clean_text(text)
    text = _STRAY_DOT.sub(" ", text)
    merged = _MERGED_COUPLET.search(text)
    if merged:
        first = text[: merged.end("num")].strip()
        rest = text[merged.end():].strip()
        if first and rest:
            return parse_key_rows(first) + parse_key_rows(rest)
    m = LEADER_RE.search(text) or _SINGLE_DOT_TARGET.search(text) or _TARGET_SUFFIX.search(text)
    left, right = text, ""
    if m:
        cand_left = text[: m.start()].strip()
        cand_right = m.group(1).strip() if m.re is _TARGET_SUFFIX else text[m.end():].strip()
        if cand_left and cand_right:
            left, right = cand_left, cand_right
    mk = _KEY_MARK.match(left)
    marker, body = (mk.group(1), left[mk.end():].strip()) if mk else ("", left)
    return [(marker, body, right)]


def _cell_border(cell, bottom: tuple[str, int] | None) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for side in ("top", "left"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "nil")
        b.append(e)
    e = OxmlElement("w:bottom")
    if bottom:
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(bottom[1]))
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), bottom[0])
    else:
        e.set(qn("w:val"), "nil")
    b.append(e)
    e = OxmlElement("w:right")
    e.set(qn("w:val"), "nil")
    b.append(e)
    tcPr.append(b)


KEY_MARK_MM = 9.0
KEY_TARGET_MM = 40.0


def key_table(doc, rows: list[tuple[str, str, str]], genera, header: bool) -> None:
    """A run of key couplets as one borderless table (marker | text | target)."""
    size = _sz(9.2)
    heads = PROFILE.key_headers
    use_header = header and any(heads)
    n = len(rows) + (1 if use_header else 0)
    table = doc.add_table(rows=n, cols=3)
    table.autofit = False
    tblPr = table._tbl.tblPr
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    mar = OxmlElement("w:tblCellMar")
    for side, w in (("top", "45"), ("left", "50"), ("bottom", "45"), ("right", "50")):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:w"), w)
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    tblPr.append(mar)
    widths = (KEY_MARK_MM, TEXT_W - KEY_MARK_MM - KEY_TARGET_MM, KEY_TARGET_MM)
    for ci, w in enumerate(widths):
        table.columns[ci].width = Mm(w)  # w:gridCol: LibreOffice lays out by the grid
        for cell in table.columns[ci].cells:
            cell.width = Mm(w)
    aligns = (WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT)
    all_rows = ([tuple(heads)] if use_header else []) + list(rows)
    for ri, (a, b, c) in enumerate(all_rows):
        is_head = use_header and ri == 0
        row = table.rows[ri]
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        if is_head:
            h = OxmlElement("w:tblHeader")
            h.set(qn("w:val"), "true")
            trPr.append(h)
        for ci, txt in enumerate((a, b, c)):
            cell = row.cells[ci]
            cell.text = ""
            par = cell.paragraphs[0]
            pf = par.paragraph_format
            pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(0), 1.1
            pf.alignment = aligns[ci]
            pf.keep_together = True
            if ci == 1 and not is_head:
                pf.right_indent = Mm(2)
            if txt:
                add_runs(par, txt, size, bold=is_head or ci in (0, 2), genera=genera)
            _suppress_hyphenation(par)
            if ci == 2 and not is_head:
                _atomic_target(par, 0)
            _cell_border(cell, ("2F3B52", 8) if is_head else (_KEY_ROW_BORDER, 4))


_KEY_STATE: dict = {"rows": [], "open": False}


def key_flush(doc, genera) -> None:
    """Emit buffered key couplets as one table; a header only opens a new key."""
    rows = _KEY_STATE["rows"]
    if rows:
        key_table(doc, rows, genera, header=not _KEY_STATE["open"])
        _KEY_STATE["open"] = True
        _KEY_STATE["rows"] = []
        _KEY_STATE["gap"] = True


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
            return tabbed(doc, left, right, _sz(8.3), 0.0, genera, force_break=force)
    # Headings, introductory notes and footnotes inside a key carry no target:
    # set them ragged-right like the source, flush with the couplet markers
    # (no first-line indent, issue #35).  Justifying them would reintroduce
    # the wide word gaps the keys are meant to avoid.
    return para(doc, text, size=9.5, first=0.0, line=1.0,
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
    if meta.title and meta.title_page:
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
    if not meta.include_contents:
        return
    page_break(doc)
    para(doc, meta.contents_title, size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    if PROFILE.toc_headings:
        # entries are filled by fill_heading_contents() once the body has been rendered
        TOC_MARK.append(para(doc, "", size=2))
        return
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
    from .contents import ContentsEntry, render_contents

    render_contents(doc, [
        ContentsEntry(
            title=title,
            level=int(p.get("contents_level", 0) or 0),
            source_page=str(p["page"] - meta.folio_offset),
            output_page=str(out_page) if out_page != "" else None,
        )
        for p, title, out_page in rows
    ], genera=genera, source_label=None)


def chapter_title(page: dict, meta: BookMeta) -> str:
    for b in page["blocks"]:
        if b["role"] == "heading" and b.get("level") == 1 and b.get("translation"):
            return clean_text(b["translation"])
    return page["chapter"]


def _is_index_chapter(chapter: str, meta: BookMeta) -> bool:
    return chapter == meta.index_chapter or (not meta.index_chapter and "index" in chapter.lower())


KEY_REPAIRS: dict[str, int] = {}


def unwrap_page_lines(page):
    """Join hand-made line breaks in running text (they stretch justified lines)."""
    from copy import deepcopy
    out = deepcopy(page)
    blocks: list[dict] = []
    for b in out.get("blocks", []):
        tr = b.get("translation") or ""
        lines = [s.strip() for s in tr.split("\n") if s.strip()]
        if b.get("role") == "body" and len(lines) >= 3 and max(len(s) for s in lines) <= 80 \
                and sum(1 for s in lines if re.search(r"[。.]\s*$", s) and not re.search(r"\d{4}\)?$", s)) == 0:
            # taxon list (subfamily / tribe / genus / species): one line each, indented by rank
            for s in lines:
                rank = 0 if re.search(r"亚科|科|inae\b|idae\b", s.split()[0]) else \
                    1 if re.search(r"族|ini\b", s.split()[0]) else \
                    2 if "属" in s.split()[0] else 3
                blocks.append({"role": "taxon", "rank": rank, "translation": s})
            continue
        blocks.append(b)
        if b.get("role") in ("body", "caption", "note") and "\n" in tr:
            parts = lines
            text = parts[0] if parts else ""
            for s in parts[1:]:
                glue = "" if (ord(text[-1]) >= 0x2E80 and ord(s[0]) >= 0x2E80) else " "
                text += glue + s
            b["translation"] = text
    out["blocks"] = blocks
    return out


def iter_pages(data, meta: BookMeta):
    from .keyfix import repair_key_page
    for p in data["pages"]:
        if p["page"] < meta.body_start_page:
            continue
        p, counts = repair_key_page(p)
        if PROFILE.unwrap_lines and p["page"] not in meta.front_pages:
            p = unwrap_page_lines(p)
        for k, v in counts.items():
            KEY_REPAIRS[k] = KEY_REPAIRS.get(k, 0) + v
        yield p


from .keyfix import is_key_page  # noqa: E402


_CONTENTS_LINE = re.compile(r"^(?P<title>.*?\S)\s*(?:(?:\.\s*){2,}|…+)\s*(?P<page>[\dIVXLCivxlc]+)$")


def contents_lines(doc, text: str, genera, meta: BookMeta) -> None:
    """Source contents lines ("Género Syllis ..... 336"): title, dot leader,
    page number flush right.  Without this the builder silently dropped the
    contents of a source-only book (Fauna Ibérica 21, pp. 6-7)."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _CONTENTS_LINE.match(line)
        indent = 5 if any(line.startswith(x) for x in meta.contents_indent_prefixes) else 0
        p = para(doc, "", size=10, left=indent, after=0.5, line=1.0)
        p.paragraph_format.tab_stops.add_tab_stop(Mm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        add_runs(p, m.group("title") if m else line, _sz(10), genera=genera)
        if m:
            p.add_run("\t")
            add_runs(p, m.group("page"), _sz(10))


def render_body(doc, data, genera, figs, page_map, meta: BookMeta, figs_dir: Path,
                key_breaks: set[str] | None = None):
    current_chapter = None
    rendered_any = prev_own = False
    for p in iter_pages(data, meta):
        if meta.skip_after_page is not None and p["page"] >= meta.skip_after_page:
            continue
        if (PROFILE.word_toc and not PROFILE.toc_headings and not TOC_MARK
                and p["page"] > PROFILE.word_toc_after_page):
            # Word TOC page after the first word_toc_after_page source pages (cover etc.)
            if doc.paragraphs:
                page_break(doc)
            para(doc, PROFILE.word_toc_title, size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
            TOC_MARK.append(para(doc, "", size=2))  # its page break rides on the last entry
            rendered_any, prev_own = False, False
        img_page = p["page"] in meta.image_pages
        own = p["page"] in meta.own_pages or img_page
        if rendered_any and meta.folio_first_page > 1 and p["page"] == meta.folio_first_page:
            start_folio_section(doc, meta)
        elif rendered_any and (own or prev_own):
            page_break(doc)
        prev_own, rendered_any = own, True
        if img_page:
            scan = figs_dir / "source_pages" / f"p{p['page']:04d}.png"
            if scan.is_file():
                image_para(doc, scan, max_w=TEXT_W, max_h=PAGE_H - 40)
                continue
        n_before = len(doc.paragraphs)
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
                for candidate in (p["blocks"] if meta.chapter_headings else []):
                    try:
                        level = int(candidate.get("level", 1))
                    except (TypeError, ValueError):
                        level = 1
                    if candidate.get("role") == "heading" and level == 1:
                        pending_heading = id(candidate)
                        break
                if pending_heading is None and meta.chapter_headings:
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
            if role != "key" and _KEY_STATE["rows"]:
                key_flush(doc, genera)
            if role not in ("key", "index"):
                _KEY_STATE["open"] = False
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
            if role == "figure_group":
                render_figure_group(doc, b, figs_dir)
                prev_body = None
                continue
            if role in GENERIC_ROLES:
                render_generic_block(doc, b, genera)
                prev_body = None
                continue
            if not text:
                continue
            if p["page"] in meta.front_pages and role in ("body", "heading", "note", "citation"):
                from .frontmatter import front_block
                front_block(doc, p["page"], b, text, genera, {
                    "centred": p["page"] in meta.centered_pages,
                    "half_title": all("\n" not in (x.get("translation") or "") and len((x.get("translation") or "").split()) <= 3
                                      for x in p["blocks"]) and len(p["blocks"]) <= 3,
                    "first": b is p["blocks"][0]})
                prev_body = None
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
                    if PROFILE.heading_levels == "taxon":
                        from .headings import taxon_level
                        level = taxon_level(text, level)
                    level = min(level, 4 if PROFILE.heading_levels == "taxon" else 3)
                    from .headings import toc_title
                    TOC_ROWS.append((level, toc_title(text)))
                    heading(doc, text, level, genera,
                            chapter_start=bool(b.get("page_break_before")))
                prev_body = None
            elif role == "note":
                # note_italic=False: set exactly like a caption (roman, ragged-right,
                # no indent) so notes and captions look the same.
                roman = not PROFILE.note_italic
                para(doc, text, size=9.5, italic=PROFILE.note_italic,
                     align=WD_ALIGN_PARAGRAPH.LEFT if roman else WD_ALIGN_PARAGRAPH.JUSTIFY,
                     first=0 if roman else 5, before=4, after=4, genera=genera)
                prev_body = None
            elif role == "body":
                # merge a page-split sentence
                if prev_body is not None and can_join(prev_body[0], text):
                    joined = join_texts(prev_body[0], text)
                    prev_body[1].clear()
                    add_runs(prev_body[1], joined, _sz(10.5), genera=genera)
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
                para(doc, text, size=9.2, left=4, first=-4, before=PROFILE.citation_before, line=1.0, genera=genera)
                prev_body = None
            elif role == "key":
                if PROFILE.key_style == "table" and is_key_page(p):
                    _KEY_STATE["rows"].extend(parse_key_rows(text))
                elif PROFILE.key_style == "couplet":
                    key_couplets(doc, text, genera)
                else:
                    key_para(doc, text, genera, key_breaks)
                prev_body = None
            elif role == "couplet":
                couplet_para(doc, b, text, genera)
                prev_body = None
            elif role == "ref":
                para(doc, text, size=7.6, left=4, first=-4, after=1.5, line=0.95, genera=genera)
                prev_body = None
            elif role == "entry":
                for prefix in meta.entry_prefixes:
                    text = re.sub(prefix, "", text, count=1, flags=re.I)
                if not text:
                    continue
                size = 9.2 if p["kind"] in ("appendix",) else 10.2
                para(doc, text, size=size, left=4, first=-4, after=2.0, line=1.0, genera=genera)
                prev_body = None
            elif role == "taxon":
                para(doc, text, size=10, align=WD_ALIGN_PARAGRAPH.LEFT, left=4.5 * int(b.get("rank", 0)),
                     before=_taxon_gap(text, int(b.get("rank", 0))), after=0.4, keep=True, genera=genera)
                prev_body = None
            elif role == "index":
                if meta.contents_in_place:
                    contents_lines(doc, text, genera, meta)
                continue
            prev_body = prev_body if role == "body" else None
        key_flush(doc, genera)
        if p["page"] in meta.centered_pages:
            for par in doc.paragraphs[n_before:]:
                pf = par.paragraph_format
                pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pf.first_line_indent = pf.left_indent = Mm(0)
    render_index(doc, data, genera, page_map, meta)


GENERIC_ROLES = frozenset({"table", "list", "quote", "box", "footnote"})


def render_figure_group(doc, b: dict, figs_dir: Path) -> None:
    """Caption-less pictures (publisher logos) set side by side on one centred line.

    ``figures``: list of {"crop": path relative to --figures (or absolute), "height_mm": 16};
    ``gap_mm`` between pictures.  A missing file is skipped (check reports figures).
    """
    from PIL import Image
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)
    gap = float(b.get("gap_mm", 14))
    first = True
    for f in b.get("figures", []):
        path = Path(f.get("crop", ""))
        if not path.is_absolute():
            path = figs_dir / path
        if not path.is_file():
            continue
        with Image.open(path) as im:
            w, h = im.size
        h_mm = float(f.get("height_mm", 16))
        if not first:
            p.add_run(chr(0x2003) * max(1, round(gap / 4)))
        p.add_run().add_picture(str(path), width=Mm(h_mm * w / h), height=Mm(h_mm))
        first = False


def _cell_text(cell: Any) -> tuple[str, int]:
    """A table cell is a string or {"text": ..., "colspan": n}."""
    if isinstance(cell, dict):
        return clean_text(str(cell.get("translation") or cell.get("text") or "")), int(cell.get("colspan", 1))
    return clean_text(str(cell or "")), 1


def render_generic_block(doc, b: dict, genera) -> None:
    """Generic block model (issue #27): table, list, quote, box, footnote.

    Table: ``rows`` = list of rows, a cell is text or {"text", "colspan"};
    ``header_rows`` (default 1) repeat on every page.  List: ``items`` plus
    optional ``ordered``.  All text comes from ``translation`` (or ``text``).
    """
    role = b["role"]
    size = PROFILE.body_size
    text = clean_text(b.get("translation") or b.get("text") or "")
    if role == "table":
        rows = b["rows"]
        ncols = max(sum(_cell_text(c)[1] for c in r) for r in rows)
        table = doc.add_table(rows=len(rows), cols=ncols)
        if b.get("grid", True):
            table.style = "Table Grid"
        tsize = float(b.get("size") or (size - 1.5))
        widths = b.get("col_widths_mm")
        if b.get("tight"):
            mar = OxmlElement("w:tblCellMar")
            for side in ("left", "right"):
                e = OxmlElement(f"w:{side}")
                e.set(qn("w:w"), "40")
                e.set(qn("w:type"), "dxa")
                mar.append(e)
            table._tbl.tblPr.append(mar)
        if widths:
            table.autofit = False
            for ci, w in enumerate(widths):
                for cell in table.columns[ci].cells:
                    cell.width = Mm(w)
        header_rows = int(b.get("header_rows", 1))
        for ri, row in enumerate(rows):
            ci = 0
            for cell in row:
                txt, span = _cell_text(cell)
                c = table.cell(ri, ci)
                if span > 1:
                    c = c.merge(table.cell(ri, ci + span - 1))
                c.text = ""
                add_runs(c.paragraphs[0], txt, tsize, bold=ri < header_rows, genera=genera)
                c.paragraphs[0].paragraph_format.space_after = Pt(0)
                ci += span
            if ri < header_rows:
                trpr = table.rows[ri]._tr.get_or_add_trPr()
                hdr = OxmlElement("w:tblHeader")
                hdr.set(qn("w:val"), "true")
                trpr.append(hdr)
            cant = OxmlElement("w:cantSplit")
            table.rows[ri]._tr.get_or_add_trPr().append(cant)
        if text:
            para(doc, text, size=size - 1.5, italic=True, before=2, after=6, genera=genera)
        else:
            para(doc, "", after=4)
    elif role == "list":
        for i, item in enumerate(b["items"], 1):
            label = f"{i}. " if b.get("ordered") else "\u2022 "
            para(doc, label + clean_text(str(item)), size=size, left=6, first=-4, after=1,
                 genera=genera)
    elif role == "quote":
        para(doc, text, size=size - 0.5, italic=True, left=8, before=3, after=3,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY, genera=genera)
    elif role == "box":
        p = para(doc, text, size=size - 0.5, left=3, before=4, after=4, genera=genera)
        ppr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        for side in ("top", "left", "bottom", "right"):
            e = OxmlElement(f"w:{side}")
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), "4")
            e.set(qn("w:space"), "4")
            bdr.append(e)
        ppr.append(bdr)
    elif role == "footnote":
        para(doc, text, size=size - 2, before=1, after=1, genera=genera)


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
    if fig is None:
        # no label match: the first figure of the page not yet placed (never reuse one)
        fig = next((f for f in page_figs if not f.get('_placed')), None)
    if fig is not None:
        fig['_placed'] = True
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
    sec.top_margin, sec.bottom_margin = Mm(PROFILE.margin_top), Mm(PROFILE.margin_bottom)
    sec.left_margin, sec.right_margin = Mm(PROFILE.margin_left), Mm(PROFILE.margin_right)
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


TOC_ROWS: list[tuple[int, str]] = []
TOC_MARK: list = []


def _fld(par, kind: str | None = None, instr: str | None = None, first: bool = False):
    from docx.oxml import OxmlElement

    def run():
        r = OxmlElement("w:r")
        (par._p.insert(1 if par._p.pPr is not None else 0, r) if first else par._p.append(r))
        return r
    els = []
    if kind == "begin":
        r = run(); c = OxmlElement("w:fldChar"); c.set(qn("w:fldCharType"), "begin"); r.append(c)
        r2 = OxmlElement("w:r"); t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve")
        t.text = instr; r2.append(t); r.addnext(r2)
        r3 = OxmlElement("w:r"); c3 = OxmlElement("w:fldChar"); c3.set(qn("w:fldCharType"), "separate")
        r3.append(c3); r2.addnext(r3)
    elif kind == "end":
        r = run(); c = OxmlElement("w:fldChar"); c.set(qn("w:fldCharType"), "end"); r.append(c)
    return els


def _wrap_toc_field(pars, depth: int) -> None:
    """Make the rendered contents a real Word TOC field over Heading 1..depth.

    The entries stay as the field's cached result (so PDF/LibreOffice and a Word
    that does not refresh fields show the same list); Word's "Update field"
    rebuilds it from the outline levels of the Heading styles.
    """
    if not pars:
        return
    _fld(pars[0], "begin", f' TOC \\o "1-{max(1, depth)}" \\h \\z \\u ', first=True)
    _fld(pars[-1], "end")


def _taxon_gap(text: str, rank: int) -> float:
    """Space before a checklist line (pt): a blank gap before each Orden, none between its families
    (Fauna Ibérica Vol. 25 pp. 13-16); other rank lines (Género X) keep the small gap."""
    t = text.lstrip()
    if re.match(r"(?:Orden|Order)\b", t):
        return 9.0
    if re.match(r"(?:Superfamilia|Familia|Subfamilia|Suborden)\b", t):
        return 0.0
    return 2.0 if rank == 0 else 0.0


def fill_heading_contents(doc, genera, page_map) -> None:
    """Heading contents: one entry per heading of level <= toc_depth, in document order.

    The entries are rendered at the end of the document, then moved in front of
    the marker paragraph that front_matter left under the contents title.
    """
    from .contents import ContentsEntry, render_contents

    marker = TOC_MARK[0]
    entries = []
    # the shallowest heading present is the contents' top level (a book whose first
    # headings are level 2 must not indent every entry)
    top = min((lv for lv, _ in TOC_ROWS if lv <= PROFILE.toc_depth), default=1)
    for i, (lv, tx) in enumerate(TOC_ROWS):
        if lv > PROFILE.toc_depth:
            continue
        pg = page_map.get(f"head:{i}")
        entries.append(ContentsEntry(title=" ".join(tx.split()), level=lv - top,
                                     output_page=str(pg) if pg else "0"))
    pars = render_contents(doc, entries, size=9.5, genera=genera, source_label=None)
    _wrap_toc_field(pars, PROFILE.toc_depth)
    if PROFILE.word_toc and not PROFILE.toc_headings and pars:
        # break inside the last entry: a separate break paragraph would strand a blank page
        # when the list exactly fills its page
        pars[-1].add_run().add_break(WD_BREAK.PAGE)
    for p in pars:
        marker._p.addprevious(p._p)
    marker._p.getparent().remove(marker._p)


def build(out_docx: Path, page_map: dict[str, int], paths: BookPaths, meta: BookMeta,
          key_breaks: set[str] | None = None) -> dict:
    data = load_aligned(paths.aligned)
    if PROFILE.promote_captions:
        from .headings import promote_captions
        promote_captions(data)
    genera = build_genus_set(data)
    figs: dict[int, list[dict]] = {}
    audit_path = paths.figures_dir / "source_figure_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for f in audit.get("figures", []):
            figs.setdefault(int(f["source_pdf_page"]), []).append(f)
    doc = Document()
    setup(doc)
    if meta.folio_first_page > 1:
        _blank_header_footer(doc.sections[0])
    else:
        set_header_footer(doc.sections[0], meta, doc)
    _set_folio_start(doc.sections[0], meta.folio_start)
    TOC_ROWS.clear()
    TOC_MARK.clear()
    front_matter(doc, data, genera, page_map, meta, paths.translation)
    render_body(doc, data, genera, figs, page_map, meta, paths.figures_dir, key_breaks)
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    if (PROFILE.toc_headings or PROFILE.word_toc) and TOC_MARK:
        fill_heading_contents(doc, genera, page_map)
        out_docx.with_suffix(".toc.json").write_text(
            json.dumps([[lv, tx] for lv, tx in TOC_ROWS], ensure_ascii=False), encoding="utf-8")
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
    toc = pdf.with_suffix(".toc.json")
    if (PROFILE.toc_headings or PROFILE.word_toc) and toc.exists():
        rows = json.loads(toc.read_text(encoding="utf-8"))
        # contents pages carry dot leaders; body search starts after the last of them
        raw = [p.get_text("text") for p in doc]
        first_body = 0
        started = False
        for i, t in enumerate(raw):
            leaders = len(re.findall(r"\.{8,}", t)) >= 3
            if leaders:
                started = True
                first_body = i + 1
            elif started:
                break  # only the consecutive run of contents pages; key lines also have leaders
        cursor = first_body
        squashed = [re.sub(r"\s+", "", t) for t in texts]
        for n, (_lv, tx) in enumerate(rows):
            key = re.sub(r"\s+", "", norm(clean_text(tx)))[:24]
            if not key:
                continue
            for i in range(cursor, len(texts)):
                if key in squashed[i]:
                    page_map[f"head:{n}"] = i + 1
                    cursor = i
                    break
    return page_map
