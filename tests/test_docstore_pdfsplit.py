from pypdf import PdfReader, PdfWriter

from docstore import pdfsplit
from docstore.cli import main


def _mk(p, n):
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=100, height=100)
    with open(p, "wb") as f:
        w.write(f)


def test_plan_and_tag():
    assert pdfsplit.plan(120, 50) == [(1, 50), (51, 100), (101, 120)]
    assert pdfsplit.plan(50, 50) == [(1, 50)]
    assert pdfsplit.volume_tag(__import__("pathlib").Path("FAUNA IBERICA（Vol.36).pdf")) == "Vol36"


def test_split_cli_resume(tmp_path, capsys):
    src = tmp_path / "FAUNA IBERICA（Vol.25）.pdf"
    _mk(src, 120)
    out = tmp_path / "out"
    assert main(["split", str(src), "--out", str(out)]) == 0
    d = out / "Vol25"
    names = sorted(p.name for p in d.glob("*.pdf"))
    assert names == ["Vol25_B01_p001-050.pdf", "Vol25_B02_p051-100.pdf", "Vol25_B03_p101-120.pdf"]
    assert sum(len(PdfReader(str(d / n)).pages) for n in names) == 120
    assert len((d / "manifest.tsv").read_text().splitlines()) == 4
    rows = pdfsplit.split_pdf(src, out)
    assert all(r["status"] == "skipped" for r in rows)
