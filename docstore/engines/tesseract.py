"""Tesseract OCR wrapper."""

from __future__ import annotations

import os
import subprocess
from tempfile import TemporaryDirectory

from .pageimg import page_png


def tesseract_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    """Run tesseract(chi_sim+eng) on one PDF page：一次识别同时输出 txt 与 tsv（原先识别两遍）。"""
    img = page_png(pdf_path, page_no, dpi)
    with TemporaryDirectory(prefix="docstore_tess_") as tmp:
        src, out = os.path.join(tmp, "page.png"), os.path.join(tmp, "out")
        with open(src, "wb") as fp:
            fp.write(img)
        # 语言可用 DOCSTORE_TESS_LANG 覆盖（纯英文书用 eng，更快更准）；
        # 每个进程限 1 线程，多 worker 并行时不互相抢核（2026-11-13：默认多线程 + 并行把 16 核机器负载推到 36，190 s/页）
        env = {**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")}
        lang = os.environ.get("DOCSTORE_TESS_LANG", "chi_sim+eng")
        subprocess.run(
            ["tesseract", src, out, "-l", lang, "--dpi", str(dpi), "txt", "tsv"],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(out + ".txt", encoding="utf-8") as f:
            txt = f.read()
        with open(out + ".tsv", encoding="utf-8") as f:
            tsv = f.read()
    confs = []
    for line in tsv.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) > 10:
            try:
                c = float(cols[10])
            except ValueError:
                continue
            if c >= 0:
                confs.append(c / 100.0)
    conf = (sum(confs) / len(confs)) if confs else None
    return txt.strip(), conf
