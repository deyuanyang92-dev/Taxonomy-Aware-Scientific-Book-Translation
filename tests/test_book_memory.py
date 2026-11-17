"""跨书 memory：合并术语表、absorb 候选。"""
from pathlib import Path

import book_memory as bm


def test_merge_and_absorb(tmp_path):
    user = tmp_path / "g.tsv"
    user.write_text("source\ttarget\tvariants\tnote\nBorste\tseta\t\t\n", encoding="utf8")
    root = tmp_path / "mem"
    out = tmp_path / "merged.tsv"
    bm.merge_glossary(str(user), "de", "en", "分类学", out, root=root)
    text = out.read_text(encoding="utf8")
    assert "Borste" in text
    assert (root / "de-en" / "分类学" / "variants.tsv").exists()

    cand = tmp_path / "c.tsv"
    cand.write_text(
        "old\tnew\tcount\tsegments_with_old\tconsistency\tapprove\n"
        "bristles\tsetae\t5\t5\t1.0\ty\n",
        encoding="utf8",
    )
    n = bm.absorb_candidates(cand, "de", "en", "分类学", root=root)
    assert n == 1
    mem = (root / "de-en" / "分类学" / "variants.tsv").read_text(encoding="utf8")
    assert "bristles=setae" in mem


def test_guard_engine_blocks_opus():
    import pytest
    from token_economy import guard_engine

    with pytest.raises(SystemExit, match="贵模型"):
        guard_engine("claude-opus", force=False)
    assert guard_engine("claude-opus", force=True) == "claude-opus"
    assert guard_engine("deepseek-flash") == "deepseek-flash"
