"""Unified release acceptance report (issue #19).

A zero exit code from a font/encoding checker must never imply a publishable
edition.  ``build_acceptance`` combines separate stage reports into ONE
machine-readable report whose ``status`` is ``release`` only if every stage is
present, passes, and carries the fingerprint of the current manuscript:

=====================  =====================================================
stage                  input JSON
=====================  =====================================================
translation_review     {"ok": true, "manuscript_sha256": ...}
technical              {"ok": true}  (yzz.py zh check result, fonts/encoding)
structure              qa / check / key-report outputs, each {"ok": ...}
pilot                  {"items": {contents, cross_page_paragraph, key,
                       figure_caption: bool}, "manuscript_sha256": ...}
visual                 {"reviewer", "reviewed_strata", "required_strata",
                       "open_defects", "manuscript_sha256"}
quality                receipt from ``quality-gate`` (see quality.py)
=====================  =====================================================

Statuses: ``release`` | ``rejected`` (a stage failed) | ``incomplete`` (a
stage is missing or unreviewed).  Rejected/incomplete artifacts stay usable
as drafts but never receive a release status.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .quality import _MODEL_NAME, sha256_file, verify_receipt

ACCEPT_SCHEMA = "booklayout.acceptance/1"
PILOT_ITEMS = ("contents", "cross_page_paragraph", "key", "figure_caption")
STAGES = ("translation_review", "technical", "structure", "pilot", "visual", "quality")


def _load(path: Path | None) -> dict | None:
    if path is None or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fp(report: dict, manuscript_sha: str, required: bool) -> list[str]:
    got = report.get("manuscript_sha256")
    if got is None:
        return ["no manuscript fingerprint"] if required else []
    return [] if got == manuscript_sha else ["built from an older manuscript fingerprint"]


def _stage_ok(report: dict | None, manuscript_sha: str, fingerprint_required: bool) -> tuple[str, list[str]]:
    if report is None:
        return "missing", ["report not provided"]
    reasons = _fp(report, manuscript_sha, fingerprint_required)
    if not report.get("ok"):
        reasons.append(f"stage not ok: {str(report.get('problems', ''))[:200]}")
    return ("pass" if not reasons else "fail"), reasons


def build_acceptance(aligned: Path, files: dict[str, Path | None], quality_receipt: Path | None,
                     builder_version: str = __version__, command: str = "",
                     now: str | None = None) -> dict[str, Any]:
    ms = sha256_file(aligned)
    stages: dict[str, dict[str, Any]] = {}

    for name in ("translation_review", "technical"):
        st, why = _stage_ok(_load(files.get(name)), ms, name == "translation_review")
        stages[name] = {"status": st, "reasons": why}

    reasons: list[str] = []
    status = "pass"
    parts = [("qa", files.get("qa")), ("check", files.get("check")), ("key_report", files.get("key_report"))]
    for label, path in parts:
        rep = _load(path)
        if rep is None:
            status, reasons = "missing", reasons + [f"{label}: report not provided"]
            continue
        if label == "key_report":
            ok = not rep.get("breaks") and not rep.get("defects")
            rep = {"ok": ok, "problems": {"breaks": len(rep.get("breaks", [])),
                                          "defects": len(rep.get("defects", []))},
                   "manuscript_sha256": rep.get("manuscript_sha256")}
        s, w = _stage_ok(rep, ms, False)
        if s != "pass":
            reasons += [f"{label}: {x}" for x in w]
            if status != "missing":
                status = s
    stages["structure"] = {"status": status, "reasons": reasons}

    pilot = _load(files.get("pilot"))
    if pilot is None:
        stages["pilot"] = {"status": "missing", "reasons": ["pilot report not provided"]}
    else:
        why = _fp(pilot, ms, True)
        items = pilot.get("items") or {}
        why += [f"pilot item not passed: {i}" for i in PILOT_ITEMS if items.get(i) is not True]
        stages["pilot"] = {"status": "pass" if not why else "fail", "reasons": why}

    vis = _load(files.get("visual"))
    if vis is None:
        stages["visual"] = {"status": "missing", "reasons": ["visual QA record not provided"]}
    else:
        why = _fp(vis, ms, True)
        who = str(vis.get("reviewer", "")).strip()
        if not who or _MODEL_NAME.search(who):
            why.append("visual QA needs a named human reviewer")
        unrev = sorted(set(vis.get("required_strata") or []) - set(vis.get("reviewed_strata") or []))
        if not vis.get("required_strata"):
            why.append("required_strata not declared")
        if unrev:
            why.append(f"unreviewed strata: {unrev}")
        if vis.get("open_defects", 1):
            why.append(f"open visual defects: {vis.get('open_defects', 'unknown')}")
        stages["visual"] = {"status": "pass" if not why else ("missing" if unrev else "fail"),
                            "reasons": why}

    rc = _load(quality_receipt)
    if rc is None:
        stages["quality"] = {"status": "missing", "reasons": ["quality receipt not provided"]}
    else:
        why = verify_receipt(rc, aligned, builder_version)
        stages["quality"] = {"status": "pass" if not why else
                             ("missing" if rc.get("status") == "indeterminate" else "fail"),
                             "reasons": why}

    sts = [stages[s]["status"] for s in STAGES]
    final = "rejected" if "fail" in sts else ("incomplete" if "missing" in sts else "release")
    return {
        "schema": ACCEPT_SCHEMA, "status": final, "ok": final == "release",
        "manuscript": {"path": str(aligned), "sha256": ms},
        "builder_version": builder_version, "command": command,
        "stages": stages,
        "timestamp": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def verify_acceptance(report: dict, aligned: Path, builder_version: str = __version__) -> list[str]:
    """Problems that stop a release-labelled build (empty list = allowed)."""
    probs: list[str] = []
    if report.get("schema") != ACCEPT_SCHEMA:
        return ["unknown acceptance schema"]
    if report.get("status") != "release":
        probs.append(f"acceptance status is {report.get('status')}")
    if report.get("manuscript", {}).get("sha256") != sha256_file(aligned):
        probs.append("acceptance built from an older manuscript fingerprint")
    if report.get("builder_version") != builder_version:
        probs.append("acceptance builder version differs")
    return probs


def pilot_problems(pilot: dict, aligned: Path) -> list[str]:
    """Gate before a full-book build."""
    probs = _fp(pilot, sha256_file(aligned), True)
    items = pilot.get("items") or {}
    probs += [f"pilot item not passed: {i}" for i in PILOT_ITEMS if items.get(i) is not True]
    return probs
