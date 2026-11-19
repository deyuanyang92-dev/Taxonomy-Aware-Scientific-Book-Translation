"""Issue #26: numeric quality gate and blocking receipt."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from booklayout import quality as q

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "quality_baseline.toml"
HUMANS = [{"name": "Zhang San", "kind": "human", "ts": "2026-11-19T10:00:00Z", "sample_ids": ["p1"]},
          {"name": "Li Si", "kind": "human", "ts": "2026-11-19T11:00:00Z", "sample_ids": ["p2"]}]


def ocr(rate: float, n: int = 100000, **kw) -> dict:
    m = {"artifact_type": "ocr", "difficulty": "clean_300dpi",
         "coverage": {"total_units": 50, "measured_units": 50, "unreadable_regions": []},
         "ocr": {"error_chars": round(rate * n), "sample_chars": n, "page_cer_max": 0.03,
                 "critical_errors": 0, "review_plan": False},
         "sample": {"strata_required": ["a"], "strata_reviewed": ["a"], "ids": ["p1"]},
         "reviewers": HUMANS}
    m["ocr"].update(kw)
    return m


def tr(clean: float = 0.998, n: int = 2000, **kw) -> dict:
    m = {"artifact_type": "translation",
         "coverage": {"total_units": 100, "measured_units": 100},
         "translation": {"sample_segments": n, "defect_segments": round((1 - clean) * n),
                         "critical": 0, "anchor_failures": 0, "segment_coverage": 0.99},
         "sample": {"strata_required": ["ch1"], "strata_reviewed": ["ch1"], "ids": ["s1"]},
         "reviewers": HUMANS}
    m["translation"].update(kw)
    return m


def run(m: dict) -> str:
    return q.evaluate(m, q.load_baseline(BASE))["status"]


@pytest.mark.parametrize("rate,extra,expected", [
    (0.0, {}, "pass"),
    (0.01, {}, "pass"),
    (0.02, {}, "fail"),                       # above preferred, no review plan
    (0.02, {"review_plan": True}, "pass"),
    (0.05, {"review_plan": True}, "fail"),
])
def test_injected_ocr_rates(rate, extra, expected) -> None:
    assert run(ocr(rate, **extra)) == expected


def test_one_critical_number_error_fails_low_cer_book() -> None:
    assert run(ocr(0.01, critical_errors=1)) == "fail"


def test_worst_page_over_limit_fails() -> None:
    assert run(ocr(0.005, page_cer_max=0.08)) == "fail"


def test_translation_one_critical_fails_even_at_99_5_clean() -> None:
    assert run(tr(0.995, critical=1)) == "fail"
    assert run(tr(0.998)) == "pass"


def test_small_sample_or_unreviewed_strata_indeterminate() -> None:
    assert run(tr(1.0, n=50)) == "indeterminate"
    m = tr()
    m["sample"]["strata_reviewed"] = []
    assert run(m) == "indeterminate"


def test_difficult_scan_without_pilot_is_indeterminate() -> None:
    m = ocr(0.0)
    m["difficulty"] = "difficult_scan"
    assert run(m) == "indeterminate"


def test_unreadable_region_blocks_pass() -> None:
    m = ocr(0.0)
    m["coverage"]["unreadable_regions"] = [{"page": 7, "why": "Type3 font"}]
    r = q.evaluate(m, q.load_baseline(BASE))
    assert r["status"] == "indeterminate"
    assert any("unreadable" in x for x in r["indeterminate_reasons"])


def test_model_or_missing_reviewer_rejected() -> None:
    m = tr()
    m["reviewers"] = [{"name": "claude-opus", "kind": "human", "ts": "t", "sample_ids": ["s"]},
                      {"name": "Wang Wu", "kind": "human", "ts": "t", "sample_ids": []}]
    assert run(m) == "indeterminate"
    m["reviewers"] = HUMANS[:1]  # translation needs a second reviewer
    assert run(m) == "indeterminate"


def test_deterministic() -> None:
    assert [run(ocr(0.01)) for _ in range(3)] == ["pass"] * 3


def make(tmp_path: Path, m: dict) -> tuple[Path, dict]:
    ms = tmp_path / "aligned.json"
    ms.write_text('{"pages": []}', encoding="utf-8")
    res = q.evaluate(m, q.load_baseline(BASE))
    return ms, q.make_receipt(res, m, ms, BASE)


def test_receipt_roundtrip_and_stale_manuscript(tmp_path) -> None:
    ms, rc = make(tmp_path, tr())
    assert q.verify_receipt(rc, ms) == []
    ms.write_text('{"pages": [1]}', encoding="utf-8")  # build from hash B
    assert any("stale" in p for p in q.verify_receipt(rc, ms))


def test_receipt_edit_and_nonpass_rejected(tmp_path) -> None:
    ms, rc = make(tmp_path, tr(0.9))
    assert rc["status"] == "fail"
    assert q.verify_receipt(rc, ms)
    rc["status"] = "pass"  # self-certification by editing
    assert any("integrity" in p for p in q.verify_receipt(rc, ms))


def test_cli_exit_codes_and_release_build(tmp_path) -> None:
    from booklayout.cli import main
    mf = tmp_path / "m.json"
    ms = tmp_path / "aligned.json"
    ms.write_text('{"pages": []}', encoding="utf-8")
    mf.write_text(json.dumps(ocr(0.0)), encoding="utf-8")
    rc = tmp_path / "r.json"
    args = ["quality-gate", "--metrics", str(mf), "--manuscript", str(ms),
            "--baseline", str(BASE), "--out", str(rc)]
    assert main(args) == 0
    assert main(["verify-receipt", "--receipt", str(rc), "--manuscript", str(ms)]) == 0
    mf.write_text(json.dumps(ocr(0.05)), encoding="utf-8")
    assert main(args) == 1
    mf.write_text(json.dumps(ocr(0.0, critical_errors=None)), encoding="utf-8")
    assert main(args) == 2
