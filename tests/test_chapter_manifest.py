"""章级交付清单。"""
from pathlib import Path

import chapter_manifest as cm


def test_scan_and_write_manifest(tmp_path: Path):
    root = tmp_path / "work"
    ch1 = root / "chapters" / "ch01"
    ch2 = root / "chapters" / "ch02"
    ch1.mkdir(parents=True)
    ch2.mkdir(parents=True)
    (ch1 / "draft.md").write_text("d", encoding="utf8")
    (ch1 / "revised.md").write_text("r", encoding="utf8")
    (ch1 / "checked.md").write_text("c", encoding="utf8")
    (ch1 / "report.md").write_text("ok", encoding="utf8")
    (ch2 / "draft.md").write_text("d", encoding="utf8")

    man = cm.build_manifest(root)
    assert man["chapters"]["ch01"]["draft"] is True
    assert man["chapters"]["ch01"]["checked"] is True
    assert man["chapters"]["ch01"]["ready_draft"] is True
    assert man["chapters"]["ch01"]["ready_release"] is True
    assert man["chapters"]["ch02"]["ready_release"] is False
    assert man["ok_release"] is False

    out = cm.write_manifest(root)
    assert out.exists()
    assert "ch01" in out.read_text(encoding="utf8")


def test_single_work_without_chapters(tmp_path: Path):
    work = tmp_path / "one"
    work.mkdir()
    (work / "draft.md").write_text("d", encoding="utf8")
    (work / "revised.md").write_text("r", encoding="utf8")
    man = cm.build_manifest(work)
    assert man["mode"] == "single"
    assert man["chapters"]["_"]["draft"] is True
    assert man["ok_release"] is False  # 单文件不算分章交付
