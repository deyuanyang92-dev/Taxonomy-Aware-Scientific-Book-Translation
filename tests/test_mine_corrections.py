import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mine_corrections as mc  # noqa: E402


def _md(paras):
    return "<!-- PDF p.1 -->\n\n" + "\n\n".join(paras) + "\n"


def test_mine_consistent_replacement():
    draft = _md([f"The bristles are long in segment {i}." for i in range(4)] + ["Front end with four eyes."])
    final = _md([f"The setae are long in segment {i}." for i in range(4)] + ["Anterior end with four eyes."])
    rows = mc.mine(draft, final, min_count=3)
    assert [(r["old"], r["new"], r["count"]) for r in rows] == [("bristles", "setae", 4)]


def test_mine_inconsistent_dropped():
    draft = _md(["The bristles are long."] * 2 + ["The bristles are short."] * 3)
    final = _md(["The setae are long."] * 2 + ["The bristles are short."] * 3)
    assert mc.mine(draft, final, min_count=2) == []


def test_apply_adds_variant(tmp_path):
    g = tmp_path / "g.tsv"
    g.write_text("de\ten\tvariants\tevidence\nBorsten\tsetae\tbristles=setae\tx\n", encoding="utf-8")
    c = tmp_path / "c.tsv"
    c.write_text("old\tnew\tcount\tsegments_with_old\tconsistency\tapprove\n"
                 "hairs\tsetae\t5\t5\t1.0\ty\nfront end\tanterior end\t4\t4\t1.0\t\n", encoding="utf-8")
    assert mc.apply(c, g) == 1
    assert "bristles=setae;hairs=setae" in g.read_text(encoding="utf-8")
