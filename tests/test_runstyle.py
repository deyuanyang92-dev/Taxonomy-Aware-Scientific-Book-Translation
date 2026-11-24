import fitz

from booklayout.runstyle import run_style_mismatches


def _pdf(path, sizes):
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for i, s in enumerate(sizes):
        page.insert_text((72, y), f"Entry number {i} here", fontsize=s)
        y += 16
    doc.save(path)


def test_uniform_run_passes(tmp_path):
    p = str(tmp_path / "a.pdf")
    _pdf(p, [10] * 8)
    assert run_style_mismatches(p) == []


def test_odd_size_inside_run_flagged(tmp_path):
    p = str(tmp_path / "b.pdf")
    _pdf(p, [10, 10, 10, 7, 10, 10, 10])
    r = run_style_mismatches(p)
    assert len(r) == 1 and r[0]["odd"][0]["size"] == 7.0


def test_short_run_ignored(tmp_path):
    p = str(tmp_path / "c.pdf")
    _pdf(p, [10, 7, 10])
    assert run_style_mismatches(p) == []
