"""Issue #13: page-marked Markdown -> aligned JSON."""
from booklayout import alignmd, cli

SRC = """<!-- PDF p.1 -->
# Annelida

Intro paragraph of the book.

<!-- PDF p.2 -->
Key to genera
1. Eyes present ........ 2
• Eyes absent ........ Alpha (p. 4)

Figure 1. A worm.
"""
TGT = """<!-- PDF p.1 -->
# Annelida

Párrafo de introducción.

<!-- PDF p.2 -->
Clave de géneros
1. Ojos presentes ........ 2
• Ojos ausentes ........ Alpha (p. 4)

Figura 1. Un gusano.
"""


def test_roles_pairing_and_chapter():
    data, rep = alignmd.align_markdown(SRC, TGT)
    assert rep["ok"] and rep["blocks"] == 6
    p1, p2 = data["pages"]
    assert [b["role"] for b in p1["blocks"]] == ["heading", "body"] and p1["blocks"][0]["level"] == 1
    assert [b["role"] for b in p2["blocks"]] == ["heading", "key", "key", "caption"]
    assert p2["chapter"] == "Annelida"
    assert p2["blocks"][1]["translation"].startswith("1. Ojos presentes")


def test_misaligned_and_missing_pages_are_explicit():
    data, rep = alignmd.align_markdown(SRC, TGT.replace("Figura 1. Un gusano.", "").replace("<!-- PDF p.2 -->", "<!-- PDF p.3 -->"))
    assert not rep["ok"] and rep["missing_translation_pages"] == [2] and rep["extra_translation_pages"] == [3]
    _, rep2 = alignmd.align_markdown(SRC, TGT.replace("\n\nFigura 1. Un gusano.", ""))
    assert rep2["misaligned_pages"] == [{"page": 2, "source_units": 4, "translation_units": 3}]


def test_cli(tmp_path):
    s, t, o = tmp_path / "s.md", tmp_path / "t.md", tmp_path / "a.json"
    s.write_text(SRC, encoding="utf-8")
    t.write_text(TGT, encoding="utf-8")
    assert cli.main(["align-md", "--source", str(s), "--translation", str(t), "--out", str(o)]) == 0
    assert o.exists()
