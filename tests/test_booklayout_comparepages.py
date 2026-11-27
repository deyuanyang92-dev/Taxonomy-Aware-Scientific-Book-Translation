"""compare-pages: side-by-side PNG and garble counts."""
import pytest

from booklayout import comparepages

fitz = pytest.importorskip("fitz")


def _pdf(path, texts):
    doc = fitz.open()
    for t in texts:
        doc.new_page(width=200, height=300).insert_text((20, 50), t)
    doc.save(str(path))


def test_parse_pairs():
    assert comparepages.parse_pairs("13:1, 14:2") == [(13, 1), (14, 2)]
    with pytest.raises(ValueError):
        comparepages.parse_pairs("13")


def test_garble_counts():
    text = "a\x01b" + chr(0xFFFD) + chr(0xE001) + "*" + chr(0x25A1) + " ok\n"
    assert comparepages.garble_counts(text) == {"ctrl": 1, "fffd": 1, "pua": 1, "box": 1, "star": 1}


def test_compare_writes_png_twice_as_wide(tmp_path):
    _pdf(tmp_path / "s.pdf", ["one", "two"])
    _pdf(tmp_path / "o.pdf", ["x*"])
    files = comparepages.compare(tmp_path / "s.pdf", tmp_path / "o.pdf", [(2, 1)], tmp_path / "d", dpi=36)
    assert len(files) == 1 and files[0].name == "src002_out001.png"
    pix = fitz.Pixmap(str(files[0]))
    assert pix.width > 2 * 200 * 36 / 72
    assert comparepages.page_stats(tmp_path / "o.pdf")[0]["star"] == 1
    with pytest.raises(ValueError):
        comparepages.compare(tmp_path / "s.pdf", tmp_path / "o.pdf", [(1, 5)], tmp_path / "d")
