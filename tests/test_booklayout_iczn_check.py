from pathlib import Path

import fitz

from booklayout.iczn import pdf_italic_family_group


def test_detects_italic_family_name(tmp_path: Path):
    pdf = tmp_path / "t.pdf"
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((72, 72), "Nereididae", fontname="tiit")      # Times italic
    pg.insert_text((72, 100), "Nereididae", fontname="tiro")     # Times roman
    d.save(str(pdf))
    hits = pdf_italic_family_group(str(pdf))
    assert [h["name"] for h in hits] == ["Nereididae"]
