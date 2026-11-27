"""HTML from a finished DOCX.

The DOCX is the single source of truth, so the three formats cannot drift:
every paragraph, run, figure and table of the document body is walked in order.
Heading paragraphs carry only a style reference (Heading 1-4); the CSS for them
is generated from the same StyleProfile that defines the Word styles, so one
profile edit restyles Word, PDF and HTML alike.
"""
from __future__ import annotations

import html
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

_ALIGN = {0: "left", 1: "center", 2: "right", 3: "justify"}
EMU_MM = 36000


def heading_css(profile) -> str:
    rules = []
    for level in range(1, 7):
        c = profile.heading_style(level)
        size = round(c["size"] * profile.body_size / 10.5, 2)
        rules.append(
            f"h{level}{{font-size:{size}pt;font-weight:{'bold' if c['bold'] else 'normal'};"
            f"font-style:{'italic' if c['italic'] else 'normal'};"
            f"font-variant:{'small-caps' if c['small_caps'] else 'normal'};"
            f"text-align:{c['align']};margin:{c['before']}pt 0 {c['after']}pt;color:#{str(c['color']).lstrip('#')};"
            f"line-height:1.0;break-after:avoid}}")
    return "\n".join(rules)


def style_class(name: str) -> str:
    """CSS class of a named paragraph style: 'Body Cont' -> 's-body-cont'."""
    return "s-" + name.lower().replace(" ", "-")


def para_css(profile) -> str:
    """One rule per named paragraph style, from the same profile that defines the Word styles."""
    from .builder import style_pt
    from .profile import PARA_STYLE_DEFAULTS

    rules = []
    for name in PARA_STYLE_DEFAULTS:
        c = profile.para_style(name)
        decl = [f"font-size:{style_pt(name, profile):g}pt",
                f"font-weight:{'bold' if c['bold'] else 'normal'}",
                f"font-style:{'italic' if c['italic'] else 'normal'}",
                f"text-align:{c['align']}",
                f"margin:{c['before']:g}pt 0 {c['after']:g}pt {c['left']:g}mm",
                f"text-indent:{c['first']:g}mm",
                f"line-height:{c['line']:g}"]
        if c["keep_together"]:
            decl.append("break-inside:avoid")
        if c["keep_with_next"]:
            decl.append("break-after:avoid")
        rules.append(f"p.{style_class(name)}{{{';'.join(decl)}}}")
    return "\n".join(rules)


def page_css(profile) -> str:
    return (
        f"@page{{size:{profile.page_w}mm {profile.page_h}mm;margin:{profile.margin_top}mm "
        f"{profile.margin_right}mm {profile.margin_bottom}mm {profile.margin_left}mm}}\n"
        f"body{{font-family:'{profile.body_font}','{profile.cjk_font or profile.body_font}',serif;"
        f"font-size:{profile.body_size}pt;max-width:{profile.text_w}mm;margin:0 auto;line-height:1.3}}\n"
        "p{margin:0}\nimg{max-width:100%;display:block;margin:6pt auto}\n"
        ".tl{display:flex;align-items:baseline}.tl .lead{flex:1;border-bottom:1.5px dotted #444;margin:0 .3em .25em}\n"
        "table{border-collapse:collapse;width:100%}td{vertical-align:top;padding:1pt 3pt}")


def _run_html(run, base_size) -> str:
    t = run.text
    if not t:
        return ""
    s = html.escape(t)
    f = run.font
    if f.italic:
        s = f"<i>{s}</i>"
    if f.bold:
        s = f"<b>{s}</b>"
    if f.superscript:
        s = f"<sup>{s}</sup>"
    if f.subscript:
        s = f"<sub>{s}</sub>"
    if f.size is not None and base_size and abs(f.size.pt - base_size) > 0.05:
        s = f"<span style='font-size:{f.size.pt:g}pt'>{s}</span>"
    return s


def _images(par: Paragraph, doc, out_dir: Path, counter: list[int]) -> str:
    out = []
    for blip in par._p.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        part = doc.part.related_parts[rid]
        counter[0] += 1
        ext = Path(part.partname).suffix or ".png"
        name = f"img{counter[0]:03d}{ext}"
        (out_dir / name).write_bytes(part.blob)
        w = ""
        ext_el = blip.getparent().getparent().getparent().find(qn("wp:extent"))
        if ext_el is not None:
            w = f" style='width:{int(ext_el.get('cx')) / EMU_MM:.1f}mm'"
        out.append(f"<img src='{out_dir.name}/{name}'{w} alt=''>")
    return "".join(out)


def _par_html(par: Paragraph, doc, out_dir: Path, counter: list[int]) -> str:
    style = par.style.name if par.style is not None else ""
    if style.startswith("Heading ") and style[8:].isdigit():
        lv = int(style[8:])
        return f"<h{lv}>{html.escape(par.text)}</h{lv}>" if not par.runs else \
            f"<h{lv}>{''.join(_run_html(r, None) for r in par.runs)}</h{lv}>"
    imgs = _images(par, doc, out_dir, counter)
    base = doc.styles["Normal"].font.size.pt if doc.styles["Normal"].font.size else None
    left, right, seen_tab = [], [], False
    for r in par.runs:
        # a tab run is its own run in python-docx; split the paragraph there
        if "\t" in r.text:
            a, _, b = r.text.partition("\t")
            left.append(_run_html(type("R", (), {"text": a, "font": r.font})(), base))
            right.append(_run_html(type("R", (), {"text": b, "font": r.font})(), base))
            seen_tab = True
            continue
        (right if seen_tab else left).append(_run_html(r, base))
    pf = par.paragraph_format
    from .profile import PARA_STYLE_DEFAULTS
    cls = [style_class(style)] if style in PARA_STYLE_DEFAULTS else []
    css = []
    al = pf.alignment
    if al is not None:
        css.append(f"text-align:{_ALIGN.get(int(al), 'left')}")
    if pf.left_indent:
        css.append(f"margin-left:{pf.left_indent.mm:.1f}mm")
    if pf.first_line_indent:
        css.append(f"text-indent:{pf.first_line_indent.mm:.1f}mm")
    if pf.space_before:
        css.append(f"margin-top:{pf.space_before.pt:g}pt")
    if pf.space_after:
        css.append(f"margin-bottom:{pf.space_after.pt:g}pt")
    st = f" style='{';'.join(css)}'" if css else ""
    if seen_tab:
        return f"<p class='{' '.join(['tl', *cls])}'{st}><span>{''.join(left)}</span><span class='lead'></span><span>{''.join(right)}</span></p>"
    body = "".join(left)
    if not body and not imgs:
        return ""
    cattr = f" class='{' '.join(cls)}'" if cls else ""
    return f"<p{cattr}{st}>{imgs}{body}</p>"


def docx_to_html(docx: Path, out_html: Path, profile, title: str = "") -> dict:
    doc = Document(str(docx))
    out_html = Path(out_html)
    files = out_html.with_name(out_html.stem + "_files")
    files.mkdir(parents=True, exist_ok=True)
    counter = [0]
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            h = _par_html(Paragraph(child, doc), doc, files, counter)
            if h:
                parts.append(h)
        elif child.tag == qn("w:tbl"):
            tbl = Table(child, doc)
            rows = ["<table>"]
            for row in tbl.rows:
                cells = []
                for c in row.cells:
                    cells.append("<td>" + "<br>".join(html.escape(p.text) for p in c.paragraphs) + "</td>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
            rows.append("</table>")
            parts.append("".join(rows))
    doc_html = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>\n{page_css(profile)}\n{heading_css(profile)}\n{para_css(profile)}\n</style></head>"
        "<body>\n" + "\n".join(parts) + "\n</body></html>")
    out_html.write_text(doc_html, encoding="utf-8")
    return {"html": str(out_html), "images": counter[0], "paragraphs": len(parts)}
