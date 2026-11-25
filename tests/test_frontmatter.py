"""Front-matter typography (booklayout.frontmatter) and make's failed-build handling."""
import json
import subprocess
import sys
from pathlib import Path

from docx import Document

from booklayout.frontmatter import AFFIL, FIG_TAIL, ROLE_ONLY, ROLE_TAIL, front_block


def _render(page, blocks, centred, genera=None):
    doc = Document()
    ctx = {"centred": centred, "half_title": False, "first": True}
    for b in blocks:
        front_block(doc, page, b, b["translation"], genera, ctx)
    return doc


def test_line_patterns():
    assert AFFIL.match("Departamento de Zoología, Universidad de Alcalá")
    assert not AFFIL.match("José Manuel Viéitez")
    assert ROLE_TAIL.match("Miguel A. Alonso-Zarazaga, Asesor de Nomenclatura")
    assert ROLE_ONLY.match("Ilustradores Científicos de este volumen")
    assert FIG_TAIL.match("Jordi Corbera Figuras 109-144, 153-155").group(2).startswith("Figuras")


def test_each_line_own_paragraph_name_bold_affiliation_plain():
    doc = _render(2, [{"role": "body", "translation":
                       "José Manuel Viéitez\nDepartamento de Zoología, Universidad de Alcalá"}], True)
    paras = [p for p in doc.paragraphs if p.text]
    assert [p.text for p in paras] == ["José Manuel Viéitez", "Departamento de Zoología, Universidad de Alcalá"]
    assert all(r.bold for r in paras[0].runs)
    assert not any(r.bold for r in paras[1].runs)


def test_make_fails_on_bad_figures_dir_not_stale_pass(tmp_path: Path):
    aligned = tmp_path / "a.json"
    aligned.write_text(json.dumps({"pages": []}), encoding="utf-8")
    meta = tmp_path / "m.json"
    meta.write_text("{}", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "t.DRAFT.pdf").write_bytes(b"%PDF stale")  # leftover from an earlier run
    (out / "t.DRAFT.docx").write_bytes(b"stale")
    r = subprocess.run([sys.executable, "-m", "booklayout", "make", "--aligned", str(aligned),
                        "--figures", str(tmp_path / "nofigs"), "--metadata", str(meta),
                        "--out-dir", str(out), "--name", "t"], capture_output=True, text=True)
    assert r.returncode != 0
    assert "build failed" in r.stderr


def test_run_together_flags_merged_line_in_pdf(tmp_path: Path):
    import fitz

    from booklayout.frontmatter import run_together_lines

    def pdf(lines, name):
        d = fitz.open()
        pg = d.new_page()
        for i, s in enumerate(lines):
            pg.insert_text((50, 80 + 20 * i), s)
        d.save(tmp_path / name)
        return tmp_path / name

    merged = pdf(["José Manuel Viéitez Departamento de Zoología, Universidad de Alcalá"], "m.pdf")
    split = pdf(["José Manuel Viéitez", "Departamento de Zoología, Universidad de Alcalá"], "s.pdf")
    assert run_together_lines(merged, [1])
    assert not run_together_lines(split, [1])
    assert not run_together_lines(merged, [5])  # not a front page


def test_repair_without_report_option(tmp_path: Path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"pages": [{"page": 1, "blocks": [
        {"block_id": "p001_b00", "role": "body", "translation": "x", "text": "x"}]}]}), encoding="utf-8")
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"pages": {"1": [{"block_id": "p001_b00", "role": "body", "translation": "y"}]}}),
                 encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "booklayout", "repair", "--aligned", str(a), "--patch", str(p),
                        "--out", str(tmp_path / "o.json")], capture_output=True, text=True)
    assert "AttributeError" not in r.stderr, r.stderr
