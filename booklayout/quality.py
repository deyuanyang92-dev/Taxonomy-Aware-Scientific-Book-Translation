"""Numeric quality gate and release receipt (issue #26).

``evaluate`` turns measured metrics plus ``quality_baseline.toml`` into
``pass | fail | indeterminate``; ``make_receipt`` wraps the result with
hashes; ``verify_receipt`` is what delivery commands call.  Status is
conservative: anything unmeasured, unreviewed or self-certified is
``indeterminate`` and never ``pass``.  Exit codes: pass 0, fail 1,
indeterminate 2.

metrics JSON (see docs/quality_gate.md)::

    {"artifact_type": "ocr"|"translation", "difficulty": "clean_300dpi",
     "coverage": {"total_units": 100, "measured_units": 100, "unreadable_regions": []},
     "ocr": {"error_chars": 90, "sample_chars": 100000, "page_cer_max": 0.02,
             "critical_errors": 0, "review_plan": true},
     "translation": {"sample_segments": 500, "defect_segments": 2,
                     "critical": 0, "anchor_failures": 0, "segment_coverage": 0.99},
     "sample": {"strata_required": [...], "strata_reviewed": [...], "ids": [...]},
     "reviewers": [{"name": "Zhang San", "kind": "human", "ts": "...", "sample_ids": [...]}]}
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

PASS, FAIL, INDETERMINATE = "pass", "fail", "indeterminate"
EXIT = {PASS: 0, FAIL: 1, INDETERMINATE: 2}
RECEIPT_SCHEMA = "booklayout.quality_receipt/1"
Z95 = 1.959964
_MODEL_NAME = re.compile(
    r"claude|gpt|codex|deepseek|gemini|grok|llm|model|bot|assistant|haiku|sonnet|opus|glm|cursor",
    re.I)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Two-sided Wilson score interval for a proportion (lower, upper)."""
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def load_baseline(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _human_reviewers(reviewers: list[dict], min_n: int) -> tuple[list[dict], list[str]]:
    reasons: list[str] = []
    good = []
    for r in reviewers:
        name = str(r.get("name", "")).strip()
        if (not name or _MODEL_NAME.search(name) or r.get("kind") != "human"
                or not r.get("sample_ids") or not r.get("ts")):
            reasons.append(f"reviewer rejected (needs human name, ts and sample_ids): {name or '?'}")
            continue
        good.append(r)
    if len({r["name"] for r in good}) < min_n:
        reasons.append(f"need {min_n} named human reviewer(s), have {len({r['name'] for r in good})}")
    return good, reasons


def _coverage_reasons(cov: dict, min_cov: float) -> tuple[float, list[str]]:
    total = cov.get("total_units") or 0
    measured = cov.get("measured_units") or 0
    frac = measured / total if total else 0.0
    reasons = []
    if not total:
        reasons.append("coverage unknown (total_units missing)")
    elif frac < min_cov:
        reasons.append(f"coverage {frac:.4f} < {min_cov}")
    if cov.get("unreadable_regions"):
        reasons.append(f"{len(cov['unreadable_regions'])} unreadable region(s) not measured")
    return frac, reasons


def evaluate(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Return {status, values, thresholds, fail_reasons, indeterminate_reasons}."""
    kind = metrics.get("artifact_type")
    fails: list[str] = []
    unknown: list[str] = []
    values: dict[str, Any] = {}
    if kind == "ocr":
        diff = metrics.get("difficulty", "clean_300dpi")
        th = baseline.get("ocr", {}).get(diff)
        if th is None:
            return _result(INDETERMINATE, values, {}, fails, [f"no baseline for ocr/{diff}"])
        if th.get("measured") is False or "cer_max" not in th:
            return _result(INDETERMINATE, values, th, fails,
                           [f"ocr/{diff}: threshold not measured yet (needs a pilot)"])
        o = metrics.get("ocr") or {}
        n = int(o.get("sample_chars") or 0)
        err = int(o.get("error_chars") or 0)
        cer = err / n if n else None
        lo, hi = wilson(err, n)
        values.update(cer=cer, cer_ucb95=hi if n else None, sample_chars=n,
                      page_cer_max=o.get("page_cer_max"), critical_errors=o.get("critical_errors"))
        if n < th["min_sample_chars"]:
            unknown.append(f"sample_chars {n} < {th['min_sample_chars']}")
        if o.get("critical_errors") is None:
            unknown.append("critical_errors not measured")
        elif o["critical_errors"] > th["critical_errors_max"]:
            fails.append(f"critical errors {o['critical_errors']} > {th['critical_errors_max']}")
        if o.get("page_cer_max") is not None and o["page_cer_max"] > th["page_cer_max"]:
            fails.append(f"worst page CER {o['page_cer_max']} > {th['page_cer_max']}")
        if cer is not None:
            if hi > th["cer_ucb_ceiling"]:
                fails.append(f"CER upper bound {hi:.4f} > ceiling {th['cer_ucb_ceiling']}")
            elif cer > th["cer_acceptable_max"]:
                fails.append(f"CER {cer:.4f} > {th['cer_acceptable_max']}")
            elif cer > th["cer_max"] and not o.get("review_plan"):
                fails.append(f"CER {cer:.4f} > {th['cer_max']} without a documented review plan")
        frac, cr = _coverage_reasons(metrics.get("coverage") or {}, th["min_coverage"])
    elif kind == "translation":
        th = baseline.get("translation", {}).get(metrics.get("difficulty", "default"))
        if th is None:
            return _result(INDETERMINATE, values, {}, fails, ["no baseline for translation"])
        t = metrics.get("translation") or {}
        n = int(t.get("sample_segments") or 0)
        bad = int(t.get("defect_segments") or 0)
        lcb, _ = wilson(n - bad, n)
        values.update(clean_lcb95=lcb if n else None, sample_segments=n,
                      critical=t.get("critical"), anchor_failures=t.get("anchor_failures"),
                      segment_coverage=t.get("segment_coverage"))
        if n < th["min_sample_segments"]:
            unknown.append(f"sample_segments {n} < {th['min_sample_segments']}")
        if t.get("critical") is None or t.get("anchor_failures") is None:
            unknown.append("critical / anchor_failures not measured")
        else:
            if t["critical"] > th["critical_max"]:
                fails.append(f"critical defects {t['critical']} > {th['critical_max']}")
            if t["anchor_failures"] > th["anchor_failures_max"]:
                fails.append(f"anchor failures {t['anchor_failures']} > {th['anchor_failures_max']}")
        if n >= th["min_sample_segments"] and lcb < th["clean_lcb_min"]:
            fails.append(f"clean-segment lower bound {lcb:.4f} < {th['clean_lcb_min']}")
        sc = t.get("segment_coverage")
        if sc is None:
            unknown.append("segment_coverage missing")
        elif sc < th["coverage_min"]:
            fails.append(f"segment coverage {sc} < {th['coverage_min']}")
        frac, cr = _coverage_reasons(metrics.get("coverage") or {}, 1.0)
    else:
        return _result(INDETERMINATE, values, {}, fails, [f"unknown artifact_type {kind!r}"])
    values["coverage_fraction"] = frac
    unknown.extend(cr)
    s = metrics.get("sample") or {}
    missing = sorted(set(s.get("strata_required") or []) - set(s.get("strata_reviewed") or []))
    if missing:
        unknown.append(f"unreviewed strata: {missing}")
    if not s.get("ids"):
        unknown.append("no sample ids recorded")
    good, rr = _human_reviewers(metrics.get("reviewers") or [], int(th.get("min_reviewers", 1)))
    unknown.extend(rr)
    values["reviewers"] = [r["name"] for r in good]
    status = FAIL if fails else (INDETERMINATE if unknown else PASS)
    return _result(status, values, th, fails, unknown)


def _result(status: str, values: dict, th: dict, fails: list[str], unknown: list[str]) -> dict[str, Any]:
    return {"status": status, "values": values, "thresholds": th,
            "fail_reasons": fails, "indeterminate_reasons": unknown}


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def make_receipt(result: dict, metrics: dict, manuscript: Path, baseline_path: Path,
                 builder_version: str = __version__, now: str | None = None) -> dict[str, Any]:
    body = {
        "schema": RECEIPT_SCHEMA,
        "status": result["status"],
        "artifact_type": metrics.get("artifact_type"),
        "manuscript": {"path": str(manuscript), "sha256": sha256_file(manuscript)},
        "builder_version": builder_version,
        "baseline": {"path": str(baseline_path), "sha256": sha256_file(baseline_path)},
        "metrics": result["values"],
        "thresholds": result["thresholds"],
        "fail_reasons": result["fail_reasons"],
        "indeterminate_reasons": result["indeterminate_reasons"],
        "coverage": metrics.get("coverage"),
        "sample": metrics.get("sample"),
        "reviewers": metrics.get("reviewers"),
        "timestamp": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    body["integrity"] = hashlib.sha256(_canonical(body)).hexdigest()
    return body


def verify_receipt(receipt: dict, manuscript: Path,
                   builder_version: str = __version__) -> list[str]:
    """Return problems; an empty list means the receipt authorises release.

    The integrity hash detects accidental edits and stale files; it is not a
    signature.  Human-review fields are only as trustworthy as the reviewers.
    """
    problems: list[str] = []
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return ["unknown receipt schema"]
    body = {k: v for k, v in receipt.items() if k != "integrity"}
    if hashlib.sha256(_canonical(body)).hexdigest() != receipt.get("integrity"):
        problems.append("receipt integrity hash mismatch (edited by hand?)")
    if receipt.get("status") != PASS:
        problems.append(f"receipt status is {receipt.get('status')}, not pass")
    if receipt.get("manuscript", {}).get("sha256") != sha256_file(manuscript):
        problems.append("manuscript hash differs from receipt (stale receipt)")
    if receipt.get("builder_version") != builder_version:
        problems.append(f"builder version {builder_version} != receipt {receipt.get('builder_version')}")
    _, rr = _human_reviewers(receipt.get("reviewers") or [], 1)
    if rr:
        problems.extend(rr)
    return problems
