"""apply_review_queue 闸口（issue #9）：人工复核队列只落实已认可的行；合成文本，不联网。"""
import csv
import json
from pathlib import Path

import pytest

import apply_review_queue as arq

TGT = """<!-- PDF p.1 -->

The worm was 12 mm long and had *Nereis virens* Sars, 1835 (Fig. 3) on its back.

<!-- PDF p.2 -->

The worm was 12 mm long and lived deep. The gills are small.
"""
SRC = """<!-- PDF p.1 -->

Червеят беше 12 мм *Nereis virens* Sars, 1835 (Fig. 3).

<!-- PDF p.2 -->

Червеят беше 12 мм.
"""
COLS = ["chunk", "pdf_page", "severity", "old", "new", "reason", "second_model_why", "decision", "rationale", "allow"]


def queue(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "q.csv"
    with p.open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})
    return p


def run(tmp_path: Path, rows: list[dict], **kw):
    t = tmp_path / "final.md"
    if not t.exists():
        t.write_text(TGT, encoding="utf8")
    return t, arq.apply(t, queue(tmp_path, rows), **kw)


def row(**kw):
    return {"pdf_page": "2", "old": "lived deep", "new": "lived in deep water", "decision": "accept",
            "rationale": "clearer", **kw}


def test_accept_applies_only_on_stated_page(tmp_path):
    t, res = run(tmp_path, [row(old="12 mm long", new="12 mm long", pdf_page="2")])
    assert res.bad  # 新旧相同
    t, res = run(tmp_path, [row()])
    out = t.read_text(encoding="utf8")
    assert res.ok == 1 and "lived in deep water" in out and out.count("<!-- PDF p.") == 2


def test_old_must_be_unique_on_page(tmp_path):
    # "The" 在第 2 页出现两次
    t, res = run(tmp_path, [row(old="The", new="A")])
    assert res.ok == 0 and "匹配 2 次" in res.bad[0][1]
    assert t.read_text(encoding="utf8") == TGT


def test_old_on_other_page_not_matched(tmp_path):
    t, res = run(tmp_path, [row(old="had *Nereis virens*", new="had *Nereis virens* Sars", pdf_page="2")])
    assert res.ok == 0 and "匹配 0 次" in res.bad[0][1]


@pytest.mark.parametrize("old,new", [
    ("12 mm long", "13 mm long"),                                # 数字
    ("*Nereis virens*", "*Nereis diversicolor*"),                # 学名
    ("(Fig. 3)", "(Fig. 4)"),                                    # 图引用
    ("Sars, 1835", "Sars, 1836"),                                # 引文年份
    ("Sars, 1835", "Savigny, 1835"),                             # 引文作者
])
def test_changes_to_facts_are_rejected(tmp_path, old, new):
    t, res = run(tmp_path, [row(old=old, new=new, pdf_page="1")])
    assert res.ok == 0 and res.bad
    assert t.read_text(encoding="utf8") == TGT


def test_whitelist_allows_number_change(tmp_path):
    t, res = run(tmp_path, [row(old="12 mm long", new="13 mm long", pdf_page="1", allow="numbers")])
    assert res.ok == 1 and "13 mm long" in t.read_text(encoding="utf8")


def test_page_marker_cannot_be_touched(tmp_path):
    t, res = run(tmp_path, [row(old="The gills are small.", new="<!-- PDF p.9 -->\nThe gills are small.")])
    assert res.ok == 0 and t.read_text(encoding="utf8") == TGT


def test_reject_and_pending_not_applied_and_rationale_required(tmp_path):
    t, res = run(tmp_path, [row(decision="reject"), row(decision=""), row(rationale="")])
    assert res.ok == 0 and res.rejected == 1 and res.pending == 1 and len(res.bad) == 1
    assert t.read_text(encoding="utf8") == TGT


def test_reapply_is_idempotent_and_audit_log(tmp_path):
    t, r1 = run(tmp_path, [row()])
    after = t.read_text(encoding="utf8")
    t, r2 = run(tmp_path, [row()])
    assert r2.ok == 0 and len(r2.skipped) == 1 and t.read_text(encoding="utf8") == after
    log = [json.loads(x) for x in Path(str(t) + ".review_apply.jsonl").read_text(encoding="utf8").splitlines()]
    assert [x["status"] for x in log] == ["applied", "skipped"]
    assert log[0]["rationale"] == "clearer"


def test_dry_run_does_not_write(tmp_path):
    t, res = run(tmp_path, [row()], dry=True)
    assert res.ok == 1 and t.read_text(encoding="utf8") == TGT


def test_qa_rerun_blocks_new_blocking_issue(tmp_path, monkeypatch):
    calls = []

    class FakeIssue:
        blocking = True

        def __init__(self, m):
            self.message = m

    def fake(src, tgt, sl, tl, **k):
        calls.append(tgt)
        return [FakeIssue("boom")] if "lived in deep water" in tgt else []

    monkeypatch.setattr(arq, "_check_all", fake)
    s = tmp_path / "src.md"
    s.write_text(SRC, encoding="utf8")
    t, res = run(tmp_path, [row()], src=s, sl="bg", tl="en")
    assert len(calls) == 2 and res.qa_new == ["boom"] and res.ok == 0
    assert t.read_text(encoding="utf8") == TGT        # QA 不过则不写回


def test_cli_exit_code(tmp_path):
    t = tmp_path / "final.md"
    t.write_text(TGT, encoding="utf8")
    q = queue(tmp_path, [row(old="12 mm long", new="13 mm long", pdf_page="1")])
    assert arq.main([str(t), str(q)]) == 1
    q = queue(tmp_path, [row()])
    assert arq.main([str(t), str(q)]) == 0
