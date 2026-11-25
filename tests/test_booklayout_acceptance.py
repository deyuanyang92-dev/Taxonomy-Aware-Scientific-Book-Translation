"""Issue #19: release acceptance blocks incomplete structural/visual QA."""
from __future__ import annotations

import json
from pathlib import Path

from booklayout import quality as q
from booklayout.acceptance import build_acceptance, pilot_problems, verify_acceptance
from booklayout.cli import main

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "quality_baseline.toml"
HUMANS = [{"name": "Zhang San", "kind": "human", "ts": "t", "sample_ids": ["a"]},
          {"name": "Li Si", "kind": "human", "ts": "t", "sample_ids": ["b"]}]


def setup(tmp_path: Path, **over) -> tuple[Path, dict[str, Path], Path]:
    ms = tmp_path / "aligned.json"
    ms.write_text('{"pages": []}', encoding="utf-8")
    sha = q.sha256_file(ms)

    def w(name: str, obj: dict) -> Path:
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    d = {
        "translation_review": {"ok": True, "manuscript_sha256": sha},
        "technical": {"ok": True},
        "qa": {"ok": True, "manuscript_sha256": sha},
        "check": {"ok": True, "manuscript_sha256": sha},
        "key_report": {"breaks": [], "defects": []},
        "pilot": {"manuscript_sha256": sha, "items": {
            "contents": True, "cross_page_paragraph": True, "key": True, "figure_caption": True}},
        "visual": {"reviewer": "Zhang San", "required_strata": ["contents", "key"],
                   "reviewed_strata": ["contents", "key"], "open_defects": 0,
                   "manuscript_sha256": sha},
    }
    for k, v in over.items():
        d[k] = v
    files = {k: w(k, v) for k, v in d.items()}
    metrics = {"artifact_type": "translation", "coverage": {"total_units": 9, "measured_units": 9},
               "translation": {"sample_segments": 2000, "defect_segments": 2, "critical": 0,
                               "anchor_failures": 0, "segment_coverage": 0.99},
               "sample": {"strata_required": ["c"], "strata_reviewed": ["c"], "ids": ["s"]},
               "reviewers": HUMANS}
    rc = q.make_receipt(q.evaluate(metrics, q.load_baseline(BASE)), metrics, ms, BASE)
    rp = w("receipt", rc)
    return ms, files, rp


def test_all_stages_pass_gives_release(tmp_path) -> None:
    ms, files, rp = setup(tmp_path)
    rep = build_acceptance(ms, files, rp, command="booklayout build ...")
    assert rep["status"] == "release" and rep["ok"]
    assert verify_acceptance(rep, ms) == []


def test_technical_pass_but_contents_key_header_fail_is_rejected(tmp_path) -> None:
    bad = {"ok": False, "problems": ["contents formatting", "running header", "key flattened"]}
    ms, files, rp = setup(tmp_path, qa=bad)
    rep = build_acceptance(ms, files, rp)
    assert rep["stages"]["technical"]["status"] == "pass"   # zh check alone passes
    assert rep["status"] == "rejected" and not rep["ok"]


def test_missing_visual_or_receipt_is_incomplete(tmp_path) -> None:
    ms, files, rp = setup(tmp_path)
    files["visual"] = None
    assert build_acceptance(ms, files, rp)["status"] == "incomplete"
    ms, files, rp = setup(tmp_path)
    assert build_acceptance(ms, files, None)["status"] == "incomplete"


def test_unreviewed_visual_sample_and_model_reviewer(tmp_path) -> None:
    ms, files, rp = setup(tmp_path)
    sha = q.sha256_file(ms)
    v = {"reviewer": "Zhang San", "required_strata": ["contents", "key"],
         "reviewed_strata": ["contents"], "open_defects": 0, "manuscript_sha256": sha}
    files["visual"].write_text(json.dumps(v), encoding="utf-8")
    assert build_acceptance(ms, files, rp)["status"] == "incomplete"
    v.update(reviewed_strata=["contents", "key"], reviewer="claude-opus")
    files["visual"].write_text(json.dumps(v), encoding="utf-8")
    assert build_acceptance(ms, files, rp)["status"] == "rejected"


def test_older_manuscript_fingerprint_rejected(tmp_path) -> None:
    ms, files, rp = setup(tmp_path)
    ms.write_text('{"pages": [1]}', encoding="utf-8")   # manuscript changed after QA
    rep = build_acceptance(ms, files, rp)
    assert rep["status"] == "rejected"
    assert any("older" in r or "stale" in r for st in rep["stages"].values() for r in st["reasons"])


def test_pilot_must_pass_all_items(tmp_path) -> None:
    ms, files, _ = setup(tmp_path)
    pilot = json.loads(files["pilot"].read_text())
    assert pilot_problems(pilot, ms) == []
    pilot["items"]["key"] = False
    assert pilot_problems(pilot, ms)


def test_cli_acceptance_exit_codes(tmp_path) -> None:
    ms, files, rp = setup(tmp_path)
    out = tmp_path / "acc.json"
    args = ["acceptance", "--aligned", str(ms), "--receipt", str(rp), "--out", str(out)]
    for k, p in files.items():
        args += [f"--{k.replace('_', '-')}", str(p)]
    assert main(args) == 0
    assert json.loads(out.read_text())["status"] == "release"
    files["qa"].write_text('{"ok": false}')
    assert main(args) == 1


def test_build_release_gate_renames_draft_and_pilot_blocks(tmp_path, monkeypatch) -> None:
    from booklayout import cli

    ms, files, rp = setup(tmp_path)
    built: list[Path] = []
    monkeypatch.setattr(cli, "_require_figure_audit", lambda d: None)
    monkeypatch.setattr(cli, "build", lambda out, *a, **k: built.append(out) or {"pages": []})
    monkeypatch.setattr(cli, "_report", lambda *a, **k: {
        "source_pages": 0, "blocks": 0, "untranslated_blocks": 0,
        "untranslated_content_blocks": 0, "figures": 0})
    base = ["build", "--aligned", str(ms), "--figures", str(tmp_path), "--out", str(tmp_path / "b.docx"), "--no-cache"]
    # no acceptance at all -> draft-labelled, exit 0
    assert cli.main(base) == 0
    assert built[-1].name == "b.DRAFT.docx"
    # already-draft name is not doubled
    assert cli.main(["build", "--aligned", str(ms), "--figures", str(tmp_path), "--out", str(tmp_path / "c.DRAFT.docx"), "--no-cache"]) == 0
    assert built[-1].name == "c.DRAFT.docx"
    # invalid acceptance -> draft-labelled, nonzero
    bad = tmp_path / "acc_bad.json"
    bad.write_text(json.dumps({"schema": "x"}))
    assert cli.main(base + ["--release-acceptance", str(bad)]) == 4
    assert built[-1].name == "b.DRAFT.docx"
    # valid acceptance -> release file name, exit 0
    acc = tmp_path / "acc.json"
    cli.main(["acceptance", "--aligned", str(ms), "--receipt", str(rp), "--out", str(acc)]
             + [a for k, p in files.items() for a in (f"--{k.replace('_', '-')}", str(p))])
    assert cli.main(base + ["--release-acceptance", str(acc)]) == 0
    assert built[-1].name == "b.docx"
    # failing pilot blocks the full build before anything is built
    n = len(built)
    pilot = json.loads(files["pilot"].read_text())
    pilot["items"]["contents"] = False
    files["pilot"].write_text(json.dumps(pilot))
    assert cli.main(base + ["--pilot", str(files["pilot"])]) == 5
    assert len(built) == n
