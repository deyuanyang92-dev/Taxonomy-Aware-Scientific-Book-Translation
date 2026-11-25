"""PDF 按固定页数切块（零模型）。每个 PDF 一个子目录，块文件名带原 PDF 页码范围，附 manifest.tsv。"""
from __future__ import annotations

import re
from pathlib import Path


def volume_tag(pdf: Path) -> str:
    """从文件名取卷标：'FAUNA IBERICA（Vol.25）.pdf' → 'Vol25'；取不到用去掉非字母数字后的文件名。"""
    m = re.search(r"vol\.?\s*(\d+)", pdf.stem, re.I)
    if m:
        return f"Vol{m.group(1)}"
    return re.sub(r"[^0-9A-Za-z_-]+", "_", pdf.stem).strip("_") or "pdf"


def plan(total: int, size: int) -> list[tuple[int, int]]:
    """返回 [(起, 止)]，1 基、闭区间。"""
    if size < 1:
        raise ValueError("size 必须 >= 1")
    return [(s, min(s + size - 1, total)) for s in range(1, total + 1, size)]


def split_pdf(pdf: Path, out_root: Path, size: int = 50, tag: str | None = None, overwrite: bool = False) -> list[dict]:
    """切一个 PDF 到 out_root/<tag>/，返回每块信息。已存在且页数正确的块跳过（断点续跑）。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf))
    total = len(reader.pages)
    tag = tag or volume_tag(pdf)
    d = out_root / tag
    d.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for i, (a, b) in enumerate(plan(total, size), 1):
        f = d / f"{tag}_B{i:02d}_p{a:03d}-{b:03d}.pdf"
        status = "written"
        if f.exists() and not overwrite:
            try:
                if len(PdfReader(str(f)).pages) == b - a + 1:
                    status = "skipped"
            except Exception:
                pass
        if status == "written":
            w = PdfWriter()
            for p in range(a - 1, b):
                w.add_page(reader.pages[p])
            with open(f, "wb") as fh:
                w.write(fh)
        rows.append({"tag": tag, "block": i, "start": a, "end": b, "pages": b - a + 1, "file": f.name, "status": status})
    man = d / "manifest.tsv"
    man.write_text(
        "tag\tblock\tstart\tend\tpages\tfile\tsource\n"
        + "".join(f"{r['tag']}\t{r['block']}\t{r['start']}\t{r['end']}\t{r['pages']}\t{r['file']}\t{pdf.name}\n" for r in rows),
        encoding="utf-8",
    )
    return rows
