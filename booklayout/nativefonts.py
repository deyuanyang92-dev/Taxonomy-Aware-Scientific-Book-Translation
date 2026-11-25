"""Read italic/bold/size straight from a native PDF's font data (no image, no model).

Per page -> lines -> tokens with (italic, bold, size_pt). Use only when
pdfkind says the page is 'native'; for scan+ocr layers see layer_trust().
"""
import re
import fitz

_IT = re.compile(r'(ital|obl|slant|kursiv|-it$|-it[,-]|oblique)', re.I)
_BD = re.compile(r'(bold|black|heavy|semibold|demi|-bd|-bd[,-]|extrabold)', re.I)


def span_style(span):
    fl, fn = span['flags'], span['font']
    return bool(fl & 2) or bool(_IT.search(fn)), bool(fl & 16) or bool(_BD.search(fn))


def page_tokens(page):
    """[{bbox, text, italic, bold, size, font}] per whitespace token; italic/bold by char majority."""
    out = []
    for b in page.get_text('dict')['blocks']:
        for ln in b.get('lines', []):
            toks, cur = [], []
            for sp in ln['spans']:
                it, bd = span_style(sp)
                for ch in sp['text']:
                    if ch.isspace():
                        if cur:
                            toks.append(cur)
                            cur = []
                    else:
                        cur.append((ch, it, bd, sp['size'], sp['font']))
            if cur:
                toks.append(cur)
            for tk in toks:
                n = len(tk)
                out.append(dict(
                    text=''.join(c[0] for c in tk),
                    italic=sum(c[1] for c in tk) > n / 2,
                    bold=sum(c[2] for c in tk) > n / 2,
                    size=round(sum(c[3] for c in tk) / n, 2),
                    font=tk[0][4], line_bbox=ln['bbox']))
    return out


def layer_trust(page):
    """For scan+ocr pages: font names that OCR software writes. Return font list; caller must
    verify against image evidence before trusting italic/bold from such a layer."""
    return sorted({f[3] for f in page.get_fonts()})
