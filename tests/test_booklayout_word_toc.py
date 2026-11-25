import json
import re
import zipfile
from pathlib import Path

from booklayout.cli import main as cli_main


def _data():
    def blk(i, role, text, level=None):
        b = {"block_id": f"b{i}", "role": role, "text": text, "translation": text, "y0": i}
        if level:
            b["level"] = level
        return b
    pages = [
        {"page": 1, "chapter": "A", "kind": "body", "blocks": [blk(1, "heading", "INTRODUCCIÓN", 1), blk(2, "body", "Texto uno.")]},
        {"page": 2, "chapter": "A", "kind": "body", "blocks": [blk(3, "heading", "Sistemática", 2), blk(4, "body", "Texto dos.")]},
    ]
    return {"pages": pages}


def test_word_toc_field_and_outline(tmp_path: Path):
    (tmp_path / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")
    al = tmp_path / "a.json"
    al.write_text(json.dumps(_data()), encoding="utf-8")
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"title": "T", "include_front_matter": False, "include_contents": False,
                                "title_page": False}), encoding="utf-8")
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"word_toc": True, "word_toc_after_page": 0, "toc_depth": 2}), encoding="utf-8")
    out = tmp_path / "o.docx"
    rc = cli_main(["build", "--aligned", str(al), "--figures", str(tmp_path), "--metadata", str(meta),
                   "--profile", str(prof), "--out", str(out)])
    assert rc in (0, None)
    z = zipfile.ZipFile(tmp_path / "o.DRAFT.docx")
    doc = z.read("word/document.xml").decode()
    assert re.search(r'TOC \\o "1-2"', doc)
    assert "Índice de apartados" in doc and "INTRODUCCIÓN" in doc
    assert 'w:val="Heading1"' in doc and 'w:val="Heading2"' in doc
    # no stray leading page break before the TOC title
    assert doc.index("Índice de apartados") < doc.index("Texto uno")
