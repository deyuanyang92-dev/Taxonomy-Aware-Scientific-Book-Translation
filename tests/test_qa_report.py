import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import qa_report as qrep  # noqa: E402


def _w(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _workdir(tmp_path: Path) -> Path:
    _w(tmp_path / "qa_estimate.json", {"pages": 40, "calls": 94, "billable_tokens": 90000, "usd": 0.03,
                                       "budget_tokens": 180000, "multiple": 2.0})
    _w(tmp_path / "qa_state.json", {"stages": {"estimate": True}, "missing_in_tgt": [7], "missing_in_src": [],
                                    "budget_tokens": 180000, "spent_tokens": 71000})
    _w(tmp_path / "qa_issues_input.json", [{"severity": "critical", "code": "X"}, {"severity": "minor", "code": "Y"}])
    log = [{"result": "applied", "pdf_page": 3, "old": "4 eyes", "new": "4 large eyes", "reason": "r1", "chunk": "c000"},
           {"result": "rejected: 第二模型未认可（no）"},
           {"result": "queued: 裁定模型没把握，须人工"},
           {"result": "queued: GUARDRAIL: x"},
           {"result": "rejected: 预过滤: old 不在该页"}]
    (tmp_path / "check_log.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in log) + "\n",
                                              encoding="utf-8")
    _w(tmp_path / "check_failed.json", [{"chunk": "c001", "pages": [4, 5], "pass": 2, "reason": "parse_failed"}])
    _w(tmp_path / "qa_align.json", [{"page": 2, "para": 0, "type": "omitted", "quote": "q", "reason": "r"}])
    _w(tmp_path / "qa_align_dropped.json", [{"page": 2, "drop_reason": "quote_not_in_source"}])
    _w(tmp_path / "qa_align_failed.json", [{"page": 9, "reason": "parse_failed"}])
    (tmp_path / "qa_applied.jsonl").write_text(
        json.dumps({"file": "p0003", "old": "4 eyes", "new": "4 large eyes", "type": "误译", "reason": "r1",
                    "pdf_page": 3, "chunk": "c000"}, ensure_ascii=False) + "\n", encoding="utf-8")
    _w(tmp_path / "qa_postgate.json", [{"result": "rolled_back", "pdf_page": 6, "old": "a", "new": "b"}])
    (tmp_path / "qa_sample.csv").write_text(
        "source,page,para,stratum,reason,text_src,text_tgt,verdict,note\n"
        "queue,3,,,r,s,t,,\nqueue,4,,,r,s,t,,\nsample,1,0,numeric,,s,t,,\n", encoding="utf-8-sig")
    return tmp_path


def test_build_report_sections_and_no_zero_error_claim(tmp_path):
    text = qrep.build_report(_workdir(tmp_path), "failed_pages")
    for must in ("覆盖率", "失败页", "c001", "第2遍", "缺页", "图版说明", "检索表", "4 large eyes", "交换 old/new",
                 "转人工", "小样", "估算", "实际", "回滚", "UNSURE", "GUARDRAIL", "failed_pages"):
        assert must in text, must
    assert "零错误" not in text
    assert (tmp_path / "qa_report.md").read_text(encoding="utf-8") == text


def test_build_report_tolerates_missing_files(tmp_path):
    text = qrep.build_report(tmp_path, "budget_exceeded")
    assert "budget_exceeded" in text and "图版说明" in text and "零错误" not in text


def test_report_lists_pages_without_model_receipt_as_unconfirmed(tmp_path):
    work = _workdir(tmp_path)
    _w(work / "check_unconfirmed.json", [{"chunk": "c002", "pages": [31, 43, 56], "reason": "找错模型未给回执"}])
    text = qrep.build_report(work, "ok")
    assert "回执未确认" in text and "c002" in text and "p.31" in text
    assert "覆盖未确证" in text


def test_report_without_unconfirmed_file_still_builds(tmp_path):
    text = qrep.build_report(_workdir(tmp_path), "ok")
    assert "回执未确认：0 页" in text and "回执未确认的块" not in text
