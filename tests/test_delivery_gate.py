"""交付门：非 ok 退出码 1。"""
import json
from pathlib import Path

import delivery_gate as dg


def test_gate_fails_release_incomplete_chapters(tmp_path: Path):
    root = tmp_path / "work"
    ch = root / "chapters" / "ch01"
    ch.mkdir(parents=True)
    (ch / "draft.md").write_text("d", encoding="utf8")
    report = dg.run_gate(root, tier="release")
    assert report["ok"] is False
    assert report["exit_code"] == 1
    assert any("ready_release" in p or "checked" in p for p in report["problems"])


def test_gate_passes_draft_with_draft_md(tmp_path: Path):
    root = tmp_path / "work"
    ch = root / "chapters" / "ch01"
    ch.mkdir(parents=True)
    (ch / "draft.md").write_text("d", encoding="utf8")
    report = dg.run_gate(root, tier="draft")
    assert report["ok"] is True
    assert report["exit_code"] == 0


def test_gate_includes_booklayout_files(tmp_path: Path):
    root = tmp_path / "work"
    ch = root / "chapters" / "a"
    ch.mkdir(parents=True)
    for name in ("draft.md", "revised.md", "checked.md", "report.md"):
        (ch / name).write_text("x", encoding="utf8")
    qa = tmp_path / "qa.json"
    check = tmp_path / "check.json"
    key = tmp_path / "key.json"
    qa.write_text(json.dumps({"ok": False, "problems": ["wide"]}), encoding="utf8")
    check.write_text(json.dumps({"ok": True}), encoding="utf8")
    key.write_text(json.dumps({"breaks": [], "defects": []}), encoding="utf8")
    report = dg.run_gate(root, tier="release", qa=qa, check=check, key_report=key)
    assert report["ok"] is False
    assert any("qa" in p for p in report["problems"])
