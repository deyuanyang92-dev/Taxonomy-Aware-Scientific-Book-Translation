"""booklayout.mdheadings: 中文稿 Markdown 标题层级审计（只读）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from booklayout import mdheadings as M  # noqa: E402


def test_classify():
    assert M.classify("丝鳃虫科 *Cirratulidae*") == "family"
    assert M.classify("*Orbiniidae*") == "family"
    assert M.classify("第 3 章 海稚虫") == "chapter"
    sec = M.re.compile(r"^7\.\d+(?![\d.])")
    assert M.classify("7.12 游走类", sec) == "section"
    assert M.classify("7.12.1 形态", sec) == "sub"
    assert M.classify("7.12 游走类") == "sub"
    assert M.classify("形态") == "sub"


def test_scan_proposes_targets_and_leaves_correct_headings():
    md = "# 7.4 章首\n# 海蛹科 *Orbiniidae*\n### 形态\n## 丝鳃虫科\n# 一般小节\n"
    rows, stats, dup = M.scan_text(md, "s7_4", M.re.compile(r"^7\.\d+(?![\d.])"))
    got = {r["line"]: r["new"] for r in rows}
    assert got == {2: "## 海蛹科 Orbiniidae", 5: "### 一般小节"}   # ## 小节（line 4 科 / numbered）不动
    assert stats[(1, "family")] == 1 and dup == [(1, 2)]


def test_italic_family_at_level2_only_strips_italics():
    rows, _, _ = M.scan_text("## 海蛹科 *Orbiniidae*\n", "k")
    assert rows[0]["new"] == "## 海蛹科 Orbiniidae" and "italic" in rows[0]["reason"]


def test_cli_writes_jsonl_and_never_touches_markdown(tmp_path):
    d = tmp_path / "md"
    d.mkdir()
    src = "# 第 1 章 X\n# 形态\n## 1.1 引言\n"
    (d / "ch1.md").write_text(src, encoding="utf-8")
    out = tmp_path / "rows.jsonl"
    assert M.main([str(d), "--out", str(out), "--stats", str(tmp_path / "s.md")]) == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["file"] == "ch1.md" and row["new"] == "### 形态"
    assert (d / "ch1.md").read_text(encoding="utf-8") == src
