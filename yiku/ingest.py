"""把各种格式的书读成 [(页码, 文本)]：有文本层 PDF、扫描 PDF（RapidOCR）、EPUB、DOCX、HTML、TXT/MD。"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

Pages = list[tuple[str, str]]


def _pdf(path: Path, ocr: str) -> Pages:
    import fitz  # pymupdf

    out: Pages = []
    engine = None
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, 1):
            text = page.get_text()
            if ocr == "always" or (ocr == "auto" and len(text.strip()) < 30):
                if engine is None:
                    from rapidocr_onnxruntime import RapidOCR  # 可选依赖：pip install yiku[ocr]
                    engine = RapidOCR()
                png = page.get_pixmap(dpi=200).tobytes("png")
                res, _ = engine(png)
                text = "\n".join(r[1] for r in res or [])
            out.append((str(i), text))
    return out


def _html_text(html: str | bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return soup.get_text("\n")


def _epub(path: Path) -> Pages:
    """按 OPF spine 顺序读每个 XHTML，'页码' 用文件名。"""
    with zipfile.ZipFile(path) as z:
        container = z.read("META-INF/container.xml").decode("utf8")
        opf = re.search(r'full-path="([^"]+)"', container).group(1)  # type: ignore[union-attr]
        base = opf.rsplit("/", 1)[0] + "/" if "/" in opf else ""
        o = z.read(opf).decode("utf8")
        items = dict(re.findall(r'<item[^>]*id="([^"]+)"[^>]*href="([^"]+)"', o))
        items.update({k: v for v, k in re.findall(r'<item[^>]*href="([^"]+)"[^>]*id="([^"]+)"', o)})
        spine = re.findall(r'<itemref[^>]*idref="([^"]+)"', o)
        return [(items[i], _html_text(z.read(base + items[i]))) for i in spine if i in items]


def _docx(path: Path) -> Pages:
    import docx

    d = docx.Document(str(path))
    return [("1", "\n".join(p.text for p in d.paragraphs))]


def read(path: str | Path, ocr: str = "auto") -> Pages:
    """ocr: auto（页面无文本层才 OCR）| always | never"""
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".pdf":
        return _pdf(p, ocr)
    if suf == ".epub":
        return _epub(p)
    if suf == ".docx":
        return _docx(p)
    if suf in (".html", ".htm", ".xhtml"):
        return [("1", _html_text(p.read_bytes()))]
    return [("1", p.read_text(encoding="utf8", errors="replace"))]


def join_lines(text: str) -> str:
    """去掉排版换行：英文连字符断词接回；中文行间换行删除；其余换行变空格。段落（空行）保留。"""
    text = text.replace("\f", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    paras = re.split(r"\n\s*\n", text)
    out = []
    for para in paras:
        para = re.sub(r"(?<=[　-鿿＀-￯])\n(?=[　-鿿＀-￯])", "", para)
        out.append(re.sub(r"\s*\n\s*", " ", para).strip())
    return "\n\n".join(x for x in out if x)


def full_text(pages: Pages) -> tuple[str, list[tuple[int, str]]]:
    """拼成全文，并返回 [(起始偏移, 页码)] 以便由偏移反查页码。"""
    buf, marks, pos = [], [], 0
    for pg, t in pages:
        t = join_lines(t)
        marks.append((pos, pg))
        buf.append(t)
        pos += len(t) + 2
    return "\n\n".join(buf), marks


def page_at(marks: list[tuple[int, str]], offset: int) -> str:
    pg = marks[0][1] if marks else "1"
    for start, p in marks:
        if start > offset:
            break
        pg = p
    return pg
