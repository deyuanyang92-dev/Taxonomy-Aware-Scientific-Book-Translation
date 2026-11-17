"""fast_book：墙钟估算与章目录发现。不调真实 API。"""
from pathlib import Path

import fast_book as fb


def test_estimate_lean_under_30min_for_400_pages():
    e = fb.estimate(400, workers=8, lean=True)
    assert e["under_30min"] is True
    assert e["total_min"] < 30
    full = fb.estimate(400, workers=8, lean=False)
    assert full["total_s"] > e["total_s"]


def test_estimate_more_workers_faster():
    slow = fb.estimate(400, workers=2, lean=True)
    fast = fb.estimate(400, workers=8, lean=True)
    assert fast["revise_s"] < slow["revise_s"]
    assert fast["check_s"] < slow["check_s"]


def test_chapters_discovers_md(tmp_path: Path):
    d = tmp_path / "chs"
    d.mkdir()
    (d / "ch01.md").write_text("<!-- PDF p.1 -->\nHallo\n", encoding="utf8")
    (d / "ch02.md").write_text("<!-- PDF p.2 -->\nWelt\n", encoding="utf8")
    (d / "draft.md").write_text("skip\n", encoding="utf8")
    files = sorted(p for p in d.glob("*.md")
                   if p.stem not in {"draft", "revised", "final", "report"} and not p.name.startswith("_"))
    assert [p.name for p in files] == ["ch01.md", "ch02.md"]


def test_cli_estimate(capsys):
    assert fb.main(["estimate", "--pages", "400", "--lean", "-j", "8"]) == 0
    out = capsys.readouterr().out
    assert "分钟" in out and "Lean=True" in out
