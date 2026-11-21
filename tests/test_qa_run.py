import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import auto_translate as at  # noqa: E402
import pytest  # noqa: E402
import qa_run as qr  # noqa: E402
import token_economy as te  # noqa: E402

SRC = """<!-- PDF p.1 | x -->

Тялото късо. 4 очи. *Exogone gemmifera* Pagenstecher, 1863.

1(2) Хоботът със зъбче …… 2. *G. limbata* Claparède

<!-- PDF p.2 | x -->

Дължина. 2—3 mm.
"""

TGT = """<!-- PDF p.1 | x -->

Body short. 4 eyes. *Exogone gemmifera* Pagenstecher, 1863.

1(2) Proboscis with a small tooth …… 2. *G. limbata* Claparède

<!-- PDF p.2 | x -->

Length. 2—3 mm.
"""

EDIT = {"pdf_page": 1, "old": "4 eyes", "new": "4 large eyes", "severity": "major", "reason": "adjective dropped"}
ACCEPT = {"id": 0, "quote": "4 очи", "old_faithful": False, "new_faithful": True}
UNSURE = {"id": 0, "quote": "4 очи", "old_faithful": None, "new_faithful": None}


@pytest.fixture(autouse=True)
def _clean_budget():
    te.set_budget(None)
    te.reset_spent()
    yield
    te.set_budget(None)
    te.reset_spent()


def _fake(edits=(), verdict=None, calls=None):
    def fake(engine, system, user, tag, usage_file, **kw):
        if calls is not None:
            calls.append(tag)
        if "/check/" in tag:
            return json.dumps(list(edits) + [{"receipt": True, "pages": [1, 2]}]), {}
        if "/verify/" in tag:
            return json.dumps([verdict] if verdict else []), {}
        return "[]", {}
    return fake


def _run(tmp_path, *extra, work="work", tgt_path=None):
    d = tmp_path / "in"
    d.mkdir(exist_ok=True)
    (d / "src.md").write_text(SRC, encoding="utf-8")
    if tgt_path is None:
        tgt_path = d / "tgt.md"
        tgt_path.write_text(TGT, encoding="utf-8")
    return qr.main([str(d / "src.md"), str(tgt_path), "-o", str(tmp_path / work), "--sl", "bg", "--tl", "en", *extra])


def _applied(work):
    text = (work / "qa_applied.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def _queue(work):
    with open(work / "qa_sample.csv", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r["source"] == "queue"]


def test_dry_run_writes_estimate_and_makes_no_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", lambda *a, **k: pytest.fail("model called"))
    assert _run(tmp_path, "--dry") == 0
    est = json.loads((tmp_path / "work" / "qa_estimate.json").read_text(encoding="utf-8"))
    assert est["pages"] == 2


def test_budget_exceeded_stops_and_still_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", lambda *a, **k: te.record_usage({"input_tokens": 10**6}) and ("[]", {}))
    code = _run(tmp_path, "--budget-tokens", "1000")
    work = tmp_path / "work"
    assert code == 2 and "budget_exceeded" in (work / "qa_report.md").read_text(encoding="utf-8")
    assert te.budget_limit() is None                                  # 预算覆盖值不泄漏到调用者的进程


def test_unverified_edit_is_never_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([EDIT], UNSURE))
    assert _run(tmp_path) == 0
    work = tmp_path / "work"
    assert (work / "qa_final.md").read_bytes() == (tmp_path / "in" / "tgt.md").read_bytes()
    assert _applied(work) == []
    assert any("4 large eyes" in r["reason"] for r in _queue(work))


def test_verified_edit_is_applied_listed_and_reversible(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT))
    assert _run(tmp_path) == 0
    work = tmp_path / "work"
    final = (work / "qa_final.md").read_text(encoding="utf-8")
    assert "4 large eyes" in final and final != TGT
    rows = _applied(work)
    assert len(rows) == 1 and {"file", "old", "new", "type", "reason", "pdf_page", "chunk"} <= set(rows[0])
    back, log = at.apply_edits(SRC, final, [{"pdf_page": rows[0]["pdf_page"], "old": rows[0]["new"],
                                             "new": rows[0]["old"]}])
    assert log[0]["result"] == "applied" and back == TGT
    assert "4 large eyes" in (work / "qa_report.md").read_text(encoding="utf-8")


def test_final_differs_from_input_only_by_listed_edits_with_unitalicised_binomial(tmp_path, monkeypatch):
    """stage_check 的 taxoformat 与 whole() 都会悄悄改文：qa_final.md 不得带这类未列出的改动。"""
    tgt = TGT.replace("*Exogone gemmifera*", "Exogone gemmifera")
    d = tmp_path / "in"
    d.mkdir()
    (d / "tgt2.md").write_text(tgt, encoding="utf-8")
    monkeypatch.setattr(at, "llm", _fake([EDIT], UNSURE))
    assert _run(tmp_path, tgt_path=d / "tgt2.md") == 0
    assert (tmp_path / "work" / "qa_final.md").read_bytes() == tgt.encode("utf-8")


def test_report_lists_failed_pages_and_blind_spots(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", lambda *a, **k: ("I could not do it", {}))
    assert _run(tmp_path) == 1
    text = (tmp_path / "work" / "qa_report.md").read_text(encoding="utf-8")
    assert "失败页" in text and "p.1,2" in text
    assert "图版说明" in text and "检索表" in text


def test_rerun_on_corrected_translation_applies_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT))
    assert _run(tmp_path) == 0
    first = tmp_path / "work" / "qa_final.md"
    assert len(_applied(tmp_path / "work")) == 1
    assert _run(tmp_path, work="work2", tgt_path=first) == 0
    w2 = tmp_path / "work2"
    assert _applied(w2) == []
    assert (w2 / "qa_final.md").read_bytes() == first.read_bytes()


def test_resume_skips_finished_stages(tmp_path, monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT, calls))
    assert _run(tmp_path) == 0
    assert calls
    calls.clear()
    capsys.readouterr()
    assert _run(tmp_path) == 0
    assert calls == []
    assert "check c000" not in capsys.readouterr().out               # 阶段被跳过，不只是缓存命中
    state = json.loads((tmp_path / "work" / "qa_state.json").read_text(encoding="utf-8"))
    assert all(state["stages"].values())


def test_failed_stage_is_not_marked_done_and_rerun_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", lambda *a, **k: ("I could not do it", {}))
    assert _run(tmp_path) == 1
    state = json.loads((tmp_path / "work" / "qa_state.json").read_text(encoding="utf-8"))
    assert state["stages"]["check"] is False
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT, calls))
    assert _run(tmp_path) == 0
    assert calls and len(_applied(tmp_path / "work")) == 1


def test_post_gate_failure_rolls_back_and_queues_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT))
    bad = SimpleNamespace(code="NUM_MISMATCH", page=1, message="number mismatch", severity="critical")
    monkeypatch.setattr(qr.postgate, "new_blocking", lambda *a, **k: {1: [bad]})
    assert _run(tmp_path) == 0
    work = tmp_path / "work"
    assert (work / "qa_final.md").read_bytes() == (tmp_path / "in" / "tgt.md").read_bytes()
    assert _applied(work) == []
    assert any("POST_GATE" in r["reason"] and "4 large eyes" in r["reason"] for r in _queue(work))
    assert "回滚" in (work / "qa_report.md").read_text(encoding="utf-8")


def test_missing_check_receipt_is_unconfirmed_not_failed(tmp_path, monkeypatch):
    """flash 常忘回执：不得因此让整块失败（退出码 1），但报告必须如实写「回执未确认」。"""
    def fake(engine, system, user, tag, usage_file, **kw):
        if "/check/" in tag:
            return json.dumps([EDIT]), {}
        if "/verify/" in tag:
            return json.dumps([ACCEPT]), {}
        return "[]", {}

    monkeypatch.setattr(at, "llm", fake)
    assert _run(tmp_path) == 0
    work = tmp_path / "work"
    assert json.loads((work / "check_failed.json").read_text(encoding="utf-8")) == []
    unc = json.loads((work / "check_unconfirmed.json").read_text(encoding="utf-8"))
    assert unc and unc[0]["pages"] == [1, 2]
    assert "回执未确认" in (work / "qa_report.md").read_text(encoding="utf-8")
    assert "4 large eyes" in (work / "qa_final.md").read_text(encoding="utf-8")     # 改动照常复核落实


# ---- 最终评审（Final）加的回归：每条都是评审里复现过的失败场景 ----

TOOTH_EDIT = {"pdf_page": 1, "old": "tooth", "new": "small tooth", "severity": "major", "reason": "adjective dropped"}
TGT_TOOTH = TGT.replace("a small tooth", "a tooth")


def _tgt_file(tmp_path, text, name="tgt_x.md"):
    d = tmp_path / "in"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d / name


def test_rerun_on_corrected_translation_does_not_stack_an_additive_edit(tmp_path, monkeypatch):
    """评审 I-4：old 是 new 的子串（加性改动）时，对已改好的译文再跑一遍不得叠加成 'small small tooth'。"""
    monkeypatch.setattr(at, "llm", _fake([TOOTH_EDIT], ACCEPT))
    assert _run(tmp_path, tgt_path=_tgt_file(tmp_path, TGT_TOOTH)) == 0
    first = tmp_path / "work" / "qa_final.md"
    assert "a small tooth" in first.read_text(encoding="utf-8") and len(_applied(tmp_path / "work")) == 1
    assert _run(tmp_path, work="work2", tgt_path=first) == 0
    w2 = tmp_path / "work2"
    assert "small small" not in (w2 / "qa_final.md").read_text(encoding="utf-8")
    assert _applied(w2) == []
    assert (w2 / "qa_final.md").read_bytes() == first.read_bytes()


def test_budget_stop_in_check_does_not_report_full_coverage(tmp_path, monkeypatch):
    """评审 I-1：预算在 check 阶段停机时，覆盖率不得写成 2 / 2（check_failed.json 还没写，不能当作「无失败」）。"""
    monkeypatch.setattr(at, "llm", lambda *a, **k: te.record_usage({"input_tokens": 10**6}) and ("[]", {}))
    assert _run(tmp_path, "--budget-tokens", "1000") == 2
    text = (tmp_path / "work" / "qa_report.md").read_text(encoding="utf-8")
    assert "2 / 2" not in text
    assert "找错与复核已运行：0 / 2" in text and "段落对齐已覆盖：0 / 2" in text


def test_changed_glossary_content_invalidates_finished_stages(tmp_path, monkeypatch):
    """评审 I-2：术语表路径不变、内容变了，必须重新调用模型，不得整阶段跳过。"""
    gl = tmp_path / "gl.tsv"
    gl.write_text("Хобот\tproboscis\n", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT, calls))
    assert _run(tmp_path, "--glossary", str(gl)) == 0
    calls.clear()
    gl.write_text("Хобот\tproboscis\nзъбче\ttooth\n", encoding="utf-8")
    assert _run(tmp_path, "--glossary", str(gl)) == 0
    assert calls                                                        # 旧结果没有被静默沿用


def test_changed_sample_parameters_rebuild_the_sample(tmp_path, monkeypatch):
    """评审 I-2：--per-stratum / --seed 变了，抽样阶段要按新参数重做，不得因旧摘要相同而跳过。"""
    monkeypatch.setattr(at, "llm", _fake([EDIT], UNSURE))
    seen: list[tuple[int, int]] = []
    real = qr.stage_sample

    def spy(src_pg, a, work, per_stratum, seed):
        seen.append((per_stratum, seed))
        return real(src_pg, a, work, per_stratum, seed)

    monkeypatch.setattr(qr, "stage_sample", spy)
    assert _run(tmp_path, "--per-stratum", "1") == 0
    assert _run(tmp_path, "--per-stratum", "1") == 0           # 参数没变：续跑，不重抽
    assert _run(tmp_path, "--per-stratum", "5") == 0
    assert _run(tmp_path, "--per-stratum", "5", "--seed", "99") == 0
    assert [x[0] for x in seen] == [1, 5, 5] and seen[2][1] == 99


def test_input_change_does_not_leave_previous_results_as_final(tmp_path, monkeypatch):
    """评审 I-3：输入变了、重跑又在中途停机，工作目录里不得还躺着上一输入的 qa_final.md 与改动清单。"""
    monkeypatch.setattr(at, "llm", _fake([EDIT], ACCEPT))
    assert _run(tmp_path) == 0
    work = tmp_path / "work"
    assert "4 large eyes" in (work / "qa_final.md").read_text(encoding="utf-8")
    changed = _tgt_file(tmp_path, TGT.replace("Length.", "Lengths."))
    monkeypatch.setattr(at, "llm", lambda *a, **k: te.record_usage({"input_tokens": 10**6}) and ("[]", {}))
    assert _run(tmp_path, "--budget-tokens", "1000", tgt_path=changed) == 2
    assert not (work / "qa_final.md").exists() and not (work / "qa_applied.jsonl").exists()
    assert "4 large eyes" not in (work / "qa_report.md").read_text(encoding="utf-8")
    assert list(work.glob("stale_*/qa_final.md"))                      # 旧结果移走保留，不删
    state = json.loads((work / "qa_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "budget_exceeded"


def test_crash_does_not_leave_the_previous_status_in_state(tmp_path, monkeypatch):
    """评审 I-3：同输入重跑中途崩溃，qa_state.json 不得还写着上一轮的 status。"""
    monkeypatch.setattr(at, "llm", lambda *a, **k: te.record_usage({"input_tokens": 10**6}) and ("[]", {}))
    assert _run(tmp_path, "--budget-tokens", "1000") == 2

    def boom(*a, **k):
        raise RuntimeError("crash")

    monkeypatch.setattr(qr, "stage_check", boom)
    with pytest.raises(RuntimeError):
        _run(tmp_path)
    state = json.loads((tmp_path / "work" / "qa_state.json").read_text(encoding="utf-8"))
    assert "status" not in state
