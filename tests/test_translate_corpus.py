import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import translate_corpus as tc  # noqa: E402

FAKE = textwrap.dedent('''
    import sys, pathlib
    args = sys.argv[1:]
    src = pathlib.Path(args[1]); work = pathlib.Path(args[args.index("-o") + 1])
    text = src.read_text(encoding="utf-8")
    work.mkdir(parents=True, exist_ok=True)
    (work / "calls.txt").open("a").write("x\\n")
    (work / "draft.md").write_text(text)
    if "BOOM" in text:
        sys.exit(3)
    (work / "revise").mkdir(exist_ok=True)
    c0 = work / "revise" / "c000.json"
    if not c0.exists():
        c0.write_text("{}")
        if "INTERRUPT" in text:
            sys.exit(130)          # 模拟 revise 中途被打断：c000 已落盘
    (work / "revised.md").write_text(text)
    (work / "checked.md").write_text(text)
    (work / "report.md").write_text("ok")
    (work / "human_review_queue.csv").write_text("chunk\\n")
''')


def _ns(tmp_path, **kw):
    fake = tmp_path / "fake_auto.py"
    fake.write_text(FAKE, encoding="utf-8")
    argv = ["run", *kw.pop("sources"), "--work", str(tmp_path / "root"), "--sl", "de", "--tl", "en",
            "--auto-script", str(fake)]
    return argv


def _book(tmp_path, name, body="Text."):
    p = tmp_path / f"{name}.md"
    p.write_text(f"<!-- PDF p.1 -->\n{body}\n\n<!-- PDF p.2 -->\nMehr.\n", encoding="utf-8")
    return str(p)


def test_validation_rejects_missing_markers_and_duplicate_keys(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("no markers", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        tc.resolve_sources([str(bad)], None)
    assert e.value.code == 2
    d = tmp_path / "d"
    d.mkdir()
    a = _book(tmp_path, "same")
    (d / "same.md").write_text(Path(a).read_text(), encoding="utf-8")
    with pytest.raises(SystemExit, match="重复"):
        tc.resolve_sources([a, str(d / "same.md")], None)
    # docstore key 经 --md-dir
    assert tc.resolve_sources(["same"], tmp_path)[0][0] == "same"


def test_two_books_one_fails_queue_continues_and_manifest(tmp_path):
    good, boom = _book(tmp_path, "good"), _book(tmp_path, "boom", "BOOM")
    rc = tc.main(_ns(tmp_path, sources=[boom, good]))
    assert rc == 1
    root = tmp_path / "root"
    st = json.loads((root / "corpus_status.json").read_text())["books"]
    assert st["good"]["exit_status"] == 0 and st["good"]["stage"] == "done"
    assert st["boom"]["exit_status"] == 3 and st["boom"]["stage"].startswith("failed@")
    assert st["good"]["pages_done"] == 2 and st["good"]["attempts"] == 1
    assert Path(st["boom"]["log"]).exists()
    man = json.loads((root / "delivery_manifest.json").read_text())
    names = [b["book"] for b in man["books"]]
    assert sorted(names) == ["boom", "good"]
    g = next(b for b in man["books"] if b["book"] == "good")
    assert g["complete"] and Path(g["checked"]).exists() and g["source_digest"] and g["prompt_version"]
    assert not next(b for b in man["books"] if b["book"] == "boom")["complete"]


def test_interrupt_resume_reuses_chunks_and_no_duplication(tmp_path):
    b = _book(tmp_path, "intr", "INTERRUPT")
    assert tc.main(_ns(tmp_path, sources=[b])) == 1
    c0 = tmp_path / "root" / "intr" / "revise" / "c000.json"
    m0 = c0.stat().st_mtime_ns
    assert tc.main(_ns(tmp_path, sources=[b])) == 0
    assert c0.stat().st_mtime_ns == m0           # 已完成块没被删/重写
    out = (tmp_path / "root" / "intr" / "checked.md").read_text()
    assert out.count("<!-- PDF p.1 -->") == 1
    st = json.loads((tmp_path / "root" / "corpus_status.json").read_text())["books"]["intr"]
    assert st["attempts"] == 2


def test_skip_when_done_and_source_change_invalidates(tmp_path):
    b = _book(tmp_path, "sk")
    assert tc.main(_ns(tmp_path, sources=[b])) == 0
    calls = tmp_path / "root" / "sk" / "calls.txt"
    assert calls.read_text().count("x") == 1
    assert tc.main(_ns(tmp_path, sources=[b])) == 0
    assert calls.read_text().count("x") == 1                      # 跳过
    st = json.loads((tmp_path / "root" / "corpus_status.json").read_text())["books"]["sk"]
    assert st["skipped"] is True
    Path(b).write_text("<!-- PDF p.1 -->\nChanged.\n", encoding="utf-8")
    assert tc.main(_ns(tmp_path, sources=[b])) == 0
    assert calls.read_text().count("x") == 2                      # 原文变了：重跑
    assert list((tmp_path / "root" / "sk").glob("checked.md.bak-*"))   # 旧稿留底
    assert tc.main([*_ns(tmp_path, sources=[b]), "--force"]) == 0
    assert calls.read_text().count("x") == 3


def test_parallel_jobs_isolated_dirs(tmp_path):
    bs = [_book(tmp_path, f"b{i}") for i in range(3)]
    assert tc.main([*_ns(tmp_path, sources=bs), "--jobs", "3"]) == 0
    for i in range(3):
        assert (tmp_path / "root" / f"b{i}" / "checked.md").exists()


def test_release_tier_requires_chapters_and_verify(tmp_path):
    b = _book(tmp_path, "r")
    with pytest.raises(SystemExit, match="release"):
        tc.main([*_ns(tmp_path, sources=[b]), "--tier", "release"])
    with pytest.raises(SystemExit, match="force-engine"):
        tc.main([*_ns(tmp_path, sources=[b]), "--engine", "claude-opus"])
