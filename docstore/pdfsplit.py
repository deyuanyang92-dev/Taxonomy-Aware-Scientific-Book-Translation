"""PDF 切块（零模型）。每个 PDF 一个子目录，块文件名带原 PDF 页码范围，附 manifest.tsv。

两种模式：
- 默认：每块固定页数（plan），pypdf 原样抄页。
- 目标服务 profile（rules/split_targets.toml）：按体积/页数上限贪心装块（plan_by_size），
  可选 200 dpi 灰度无损重编码（MuPDF 渲染 → PNG/Flate → 新页，页尺寸与原页一致）。
"""
from __future__ import annotations

import io
import re
import tempfile
import tomllib
from pathlib import Path

RULES = Path(__file__).parent / "rules" / "split_targets.toml"
BLOCK_BASE_BYTES = 2000  # 每块 PDF 结构固定开销（估计）
PAGE_OVERHEAD_BYTES = 700  # 每页对象开销（估计）


def volume_tag(pdf: Path) -> str:
    """从文件名取卷标：'FAUNA IBERICA（Vol.25）.pdf' → 'Vol25'；取不到用去掉非字母数字后的文件名。"""
    m = re.search(r"vol\.?\s*(\d+)", pdf.stem, re.I)
    if m:
        return f"Vol{m.group(1)}"
    return re.sub(r"[^\w-]+", "_", pdf.stem).strip("_") or "pdf"


def plan(total: int, size: int) -> list[tuple[int, int]]:
    """返回 [(起, 止)]，1 基、闭区间。"""
    if size < 1:
        raise ValueError("size 必须 >= 1")
    return [(s, min(s + size - 1, total)) for s in range(1, total + 1, size)]


def load_profiles() -> dict[str, dict]:
    with open(RULES, "rb") as f:
        return tomllib.load(f)["profiles"]


def load_profile(name: str) -> dict:
    profs = load_profiles()
    if name not in profs:
        raise KeyError(f"未知 target {name!r}；可用：{', '.join(sorted(profs))}")
    return dict(profs[name])


def plan_by_size(
    page_bytes: list[int], max_bytes: int | None, max_pages: int | None = None, rec_pages: int | None = None
) -> list[tuple[int, int]]:
    """贪心装块。返回 [(起, 止)]，相对 page_bytes 的 1 基闭区间。
    每块页数 <= min(max_pages, rec_pages)；块体积（页字节之和 + 每块固定开销）<= max_bytes。
    单页就超 max_bytes 时该页独占一块（调用方据此标 ok=false）。None = 该项不限。"""
    caps = [x for x in (max_pages, rec_pages) if x]
    cap = min(caps) if caps else None
    if cap is not None and cap < 1:
        raise ValueError("页数上限必须 >= 1")
    out: list[tuple[int, int]] = []
    start = 1
    acc = 0
    n = len(page_bytes)
    for i in range(1, n + 1):
        b = page_bytes[i - 1]
        cnt = i - start
        if cnt > 0 and ((cap is not None and cnt >= cap) or (max_bytes is not None and acc + b > max_bytes)):
            out.append((start, i - 1))
            start, acc = i, 0
        acc += b
    if n:
        out.append((start, n))
    return out


def _render_png(doc, p: int, dpi: int) -> tuple[bytes, float, float]:
    """渲染原 PDF 第 p 页（1 基）为灰度 PNG；返回 (png, 原页宽pt, 原页高pt)。"""
    import fitz
    from PIL import Image

    page = doc[p - 1]
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    bio = io.BytesIO()
    img.save(bio, "PNG", optimize=True, dpi=(dpi, dpi))
    return bio.getvalue(), page.rect.width, page.rect.height


def _write_reencoded(block: list[tuple[bytes, float, float]], f: Path) -> None:
    import fitz

    out = fitz.open()
    for png, w, h in block:
        pg = out.new_page(width=w, height=h)
        pg.insert_image(pg.rect, stream=png)
    out.save(str(f), deflate=True, garbage=3)
    out.close()


def split_pdf(
    pdf: Path,
    out_root: Path,
    size: int | None = 50,
    tag: str | None = None,
    overwrite: bool = False,
    pages_range: tuple[int, int] | None = None,
    max_bytes: int | None = None,
    max_pages: int | None = None,
    rec_pages: int | None = None,
    render_dpi: int = 200,
    encode: str = "none",
    target: str = "",
) -> list[dict]:
    """切一个 PDF 到 out_root/<tag>/，返回每块信息。已存在且页数正确的块跳过（断点续跑）。
    size 即 rec_pages（每块建议页数，两者取小）。pages_range=(a,b) 为原 PDF 页码、闭区间。
    max_bytes/max_pages 任一给出 → 按体积装块；encode="flate" → 灰度无损重编码。
    manifest 的 start/end 始终是原 PDF 页码。"""
    from pypdf import PdfReader, PdfWriter

    if encode not in ("none", "flate"):
        raise ValueError("encode 必须是 none 或 flate")
    reader = PdfReader(str(pdf))
    total = len(reader.pages)
    a0, b0 = pages_range if pages_range else (1, total)
    if not (1 <= a0 <= b0 <= total):
        raise ValueError(f"页范围 {a0}-{b0} 超出 1-{total}")
    caps = [x for x in (size, rec_pages) if x]
    rec = min(caps) if caps else None
    tag = tag or volume_tag(pdf)
    d = out_root / tag
    d.mkdir(parents=True, exist_ok=True)
    sized = max_bytes is not None or max_pages is not None
    npages = b0 - a0 + 1
    doc = None
    tmp = tempfile.TemporaryDirectory()
    pngs: dict[int, tuple[Path, float, float]] = {}
    if encode == "flate":
        import fitz

        doc = fitz.open(str(pdf))
    if not sized and encode == "none":
        rel = plan(npages, rec or 50)
    else:
        pb: list[int] = []
        for p in range(a0, b0 + 1):
            if encode == "flate":
                assert doc is not None
                png, w, h = _render_png(doc, p, render_dpi)
                fp = Path(tmp.name) / f"p{p}.png"
                fp.write_bytes(png)
                pngs[p] = (fp, w, h)
                pb.append(len(png) + PAGE_OVERHEAD_BYTES)
            else:
                bio = io.BytesIO()
                w1 = PdfWriter()
                w1.add_page(reader.pages[p - 1])
                w1.write(bio)
                pb.append(bio.tell())
        budget = None if max_bytes is None else max_bytes - BLOCK_BASE_BYTES
        rel = plan_by_size(pb, budget, max_pages, rec)
    rows: list[dict] = []
    try:
        for i, (ra, rb) in enumerate(rel, 1):
            a, b = a0 + ra - 1, a0 + rb - 1
            f = d / f"{tag}_B{i:02d}_p{a:03d}-{b:03d}.pdf"
            status = "written"
            if f.exists() and not overwrite:
                try:
                    if len(PdfReader(str(f)).pages) == b - a + 1:
                        status = "skipped"
                except Exception:
                    pass
            if status == "written":
                if encode == "flate":
                    blk = [(pngs[p][0].read_bytes(), pngs[p][1], pngs[p][2]) for p in range(a, b + 1)]
                    _write_reencoded(blk, f)
                else:
                    wr = PdfWriter()
                    for p in range(a - 1, b):
                        wr.add_page(reader.pages[p])
                    with open(f, "wb") as fh:
                        wr.write(fh)
            nbytes = f.stat().st_size
            ok = (max_bytes is None or nbytes <= max_bytes) and (max_pages is None or b - a + 1 <= max_pages)
            rows.append({"tag": tag, "block": i, "start": a, "end": b, "pages": b - a + 1, "file": f.name,
                         "status": status, "bytes": nbytes, "target": target, "ok": ok})
    finally:
        if doc is not None:
            doc.close()
        tmp.cleanup()
    man = d / "manifest.tsv"
    man.write_text(
        "tag\tblock\tstart\tend\tpages\tfile\tsource\tbytes\ttarget\tok\n"
        + "".join(
            f"{r['tag']}\t{r['block']}\t{r['start']}\t{r['end']}\t{r['pages']}\t{r['file']}\t{pdf.name}"
            f"\t{r['bytes']}\t{r['target']}\t{'true' if r['ok'] else 'false'}\n"
            for r in rows
        ),
        encoding="utf-8",
    )
    return rows
