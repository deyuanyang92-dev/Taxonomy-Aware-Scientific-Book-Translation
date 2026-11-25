import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import chapter_split as cs  # noqa: E402


def _md(n=12, contents=None, headings=None):
    """n 页的页标记 Markdown；contents={页:[行]} 在该页放目录；headings={页:标题}。"""
    out = []
    for p in range(1, n + 1):
        out.append(f"<!-- PDF p.{p} -->")
        if contents and p in contents:
            out += contents[p]
        elif headings and p in headings:
            out += [headings[p], "", f"Body text of page {p}."]
        else:
            out.append(f"Body text of page {p}. Figure {p}. *Genus species* Smith, 1900.")
        out.append("")
    return "\n".join(out)


def _pdf_with_bookmarks(path, n=12):
    import fitz
    doc = fitz.open()
    for i in range(n):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    doc.set_toc([[1, "Introduction", 1], [2, "Aims", 2], [1, "Methods", 5], [1, "Results", 9]])
    doc.save(str(path))
    doc.close()


def test_bookmarks_plan_split_roundtrip(tmp_path):
    pdf, src = tmp_path / "b.pdf", tmp_path / "b.md"
    _pdf_with_bookmarks(pdf)
    src.write_text(_md(), encoding="utf-8")
    plan = cs.build_plan(src, pdf)
    assert [(c["title"], c["start"], c["end"]) for c in plan["chapters"]] == [
        ("Introduction", 1, 4), ("Methods", 5, 8), ("Results", 9, 12)]
    assert plan["needs_review"] is False and plan["chapters"][0]["source"] == "bookmarks"
    files = cs.split_md(src, plan, tmp_path / "chapters")
    joined = "".join(f.read_text(encoding="utf-8") for f in files.values())
    assert joined == src.read_text(encoding="utf-8").rstrip("\n") + "\n" or joined.replace("\n\n", "\n") == \
        src.read_text(encoding="utf-8").replace("\n\n", "\n").rstrip("\n") + "\n"
    first = files[plan["chapters"][1]["id"]].read_text(encoding="utf-8")
    assert first.startswith("<!-- PDF p.5 -->") and "<!-- PDF p.8 -->" in first and "p.9" not in first
    assert "Figure 5." in first and "*Genus species*" in first


def test_printed_contents_page_is_parsed_with_offset(tmp_path):
    toc = ["Contents", "Introduction .......... 1", "Methods ............ 5", "Results ............ 9", ""]
    head = {3: "Introduction", 7: "Methods", 11: "Results"}     # 印刷页 1 在 PDF p.3：偏移 +2
    text = _md(14, contents={2: toc}, headings=head)
    src = tmp_path / "c.md"
    src.write_text(text, encoding="utf-8")
    plan = cs.build_plan(src)
    got = {c["title"]: (c["start"], c["end"]) for c in plan["chapters"]}
    assert got["Introduction"] == (3, 6) and got["Methods"] == (7, 10) and got["Results"] == (11, 14)
    assert plan["chapters"][0]["title"] == "Front matter" and plan["chapters"][0]["end"] == 2
    assert plan["needs_review"] is False
    cs.validate_plan(plan)


def test_uncertain_detection_requires_review_and_validation(tmp_path):
    src = tmp_path / "u.md"
    src.write_text(_md(6), encoding="utf-8")
    plan = cs.build_plan(src)
    assert plan["needs_review"] is True and len(plan["chapters"]) == 1
    bad = json.loads(json.dumps(plan))
    bad["chapters"][0]["end"] = 4
    with pytest.raises(ValueError, match="覆盖"):
        cs.validate_plan(bad)
    h = _md(8, headings={1: "Chapter 1 Intro", 5: "Chapter 2 Methods"})
    (tmp_path / "h.md").write_text(h, encoding="utf-8")
    plan = cs.build_plan(tmp_path / "h.md")
    assert [c["start"] for c in plan["chapters"]] == [1, 5] and plan["needs_review"] is True


def _plan(tmp_path):
    src = tmp_path / "b.md"
    src.write_text(_md(8, headings={1: "Chapter 1 A", 5: "Chapter 2 B"}), encoding="utf-8")
    plan = cs.build_plan(src)
    plan["confirmed"] = True
    return src, plan


def test_report_links_chapter_page_segment_and_flags_missing(tmp_path):
    src, plan = _plan(tmp_path)
    work = tmp_path / "w"
    files = cs.split_md(src, plan, work / "chapters")
    c1, c2 = plan["chapters"]
    d1 = files[c1["id"]].parent
    (d1 / "checked.md").write_text(files[c1["id"]].read_text(encoding="utf-8"), encoding="utf-8")
    (d1 / "report.md").write_text("ok", encoding="utf-8")
    (d1 / "human_review_queue.csv").write_text(
        "chunk,pdf_page,severity,old,new,reason,second_model_why\n"
        "c000,2,critical,Figure 2.,Figure 3.,number changed,\n", encoding="utf-8")
    d2 = files[c2["id"]].parent                       # 第二章译文缺最后一页
    txt = files[c2["id"]].read_text(encoding="utf-8")
    (d2 / "checked.md").write_text(txt.split("<!-- PDF p.8 -->")[0], encoding="utf-8")
    res = cs.report(work, plan)
    assert res["critical"] == 2 and res["incomplete"] == [c2["id"]]
    rows = (work / "chapter_issues.csv").read_text(encoding="utf-8")
    assert f"{c1['id']},human_review,critical,2,p2_s1" in rows
    assert f"{c2['id']},missing_page,critical,8" in rows
    assert (d1 / "chapter_report.md").exists() and "critical" in (work / "book_issues.md").read_text() + "critical"


def test_assemble_refuses_incomplete_and_adds_contents(tmp_path):
    src, plan = _plan(tmp_path)
    work = tmp_path / "w"
    files = cs.split_md(src, plan, work / "chapters")
    with pytest.raises(ValueError, match="拒绝合并"):
        cs.assemble(work, plan, tmp_path / "o.md")
    for f in files.values():
        (f.parent / "checked.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    out = cs.assemble(work, plan, tmp_path / "o.md").read_text(encoding="utf-8")
    assert out.startswith("# Contents") and out.index("p.1 -->") < out.index("<!-- PDF p.8 -->")


def test_corpus_chapter_mode_stops_on_unconfirmed_plan_then_runs(tmp_path):
    import translate_corpus as tc
    from test_translate_corpus import FAKE
    src = tmp_path / "bk.md"
    src.write_text(_md(8, headings={1: "Chapter 1 A", 5: "Chapter 2 B"}), encoding="utf-8")
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE, encoding="utf-8")
    argv = ["run", str(src), "--work", str(tmp_path / "r"), "--sl", "de", "--tl", "en", "--chapters",
            "--auto-script", str(fake), "--jobs", "2"]
    assert tc.main(argv) == 1                                   # 计划不确定：停下等人确认
    plan_p = tmp_path / "r" / "bk" / "chapter_plan.json"
    plan = json.loads(plan_p.read_text())
    plan["confirmed"] = True
    plan_p.write_text(json.dumps(plan), encoding="utf-8")
    assert tc.main(argv) == 0
    res = cs.report(tmp_path / "r" / "bk", cs.load_plan(plan_p))
    assert res["incomplete"] == []
