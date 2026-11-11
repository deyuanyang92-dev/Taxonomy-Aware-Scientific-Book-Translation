"""Tesseract OCR wrapper."""

from __future__ import annotations

import subprocess
from tempfile import NamedTemporaryFile

import fitz


def tesseract_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    """Run tesseract(chi_sim+eng) on one PDF page."""
    with fitz.open(pdf_path) as doc:
        img = doc[page_no - 1].get_pixmap(dpi=dpi).tobytes("png")
    with NamedTemporaryFile(suffix=".png") as fp:
        fp.write(img)
        fp.flush()
        txt = subprocess.check_output(
            ["tesseract", fp.name, "stdout", "-l", "chi_sim+eng", "--dpi", str(dpi)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        tsv = subprocess.check_output(
            ["tesseract", fp.name, "stdout", "-l", "chi_sim+eng", "--dpi", str(dpi), "tsv"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
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

