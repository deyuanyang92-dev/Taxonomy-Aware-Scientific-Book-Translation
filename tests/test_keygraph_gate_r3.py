"""Round-3 gate hardening: coverage, report shape, entries, unreadable input, publish stale reports."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

GOOD = """<!-- PDF p.1 -->
Key to species

1. Body long ........ 2
1'. Body short ........ Aus bus
2. Eyes present ........ Aus cus
2'. Eyes absent ........ Aus dus
"""


def bl(*a: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "booklayout", *a], cwd=ROOT, capture_output=True, text=True)


def j(p: Path, obj: object) -> Path:
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _base(tmp: Path) -> list[str]:
    return ["gate", "--qa", str(j(tmp / "qa.json", {"ok": True})), "--check", str(j(tmp / "ck.json", {"ok": True})),
            "--key-report", str(j(tmp / "kr0.json", {"breaks": [], "defects": []}))]


def _gate(tmp: Path, km: Any = None, kr: Any = None) -> tuple[int, dict]:
    a = _base(tmp)
    if km is not None:
        a += ["--key-model", str(j(tmp / "km.json", km))]
    if kr is not None:
        a += ["--keyrender", str(j(tmp / "kr.json", kr))]
    r = bl(*a)
    return r.returncode, json.loads(r.stdout.splitlines()[-1])


KM: dict[str, Any] = {"ok": True, "graph": {"errors": 0, "source_keys": 1, "source_branches": 4}}
KR = {"rules": {}, "summary": {"KR1": 0}, "findings": [], "branches": 4}


def test_coverage_field_legacy(tmp_path: Path) -> None:
    rc, rep = _gate(tmp_path)
    assert rc == 0 and rep["unchecked"] == ["key_model", "keyrender"]


def test_files_record_new_reports(tmp_path: Path) -> None:
    rc, rep = _gate(tmp_path, KM, KR)
    assert rc == 0 and rep["unchecked"] == []
    assert rep["files"]["key_model"].endswith("km.json") and rep["files"]["keyrender"].endswith("kr.json")


def test_keyrender_zero_branches_blocks(tmp_path: Path) -> None:
    rc, rep = _gate(tmp_path, KM, {**KR, "branches": 0})
    assert rc == 1 and any("missing from the PDF" in p for p in rep["problems"])


def test_keyrender_less_than_half_blocks(tmp_path: Path) -> None:
    rc, _ = _gate(tmp_path, {**KM, "graph": {**KM["graph"], "source_branches": 10}}, {**KR, "branches": 4})
    assert rc == 1


def test_keyrender_missing_branch_count_blocks_when_keys(tmp_path: Path) -> None:
    kr = {k: v for k, v in KR.items() if k != "branches"}
    assert _gate(tmp_path, KM, kr)[0] == 1


def test_keyrender_empty_object_blocks(tmp_path: Path) -> None:
    assert _gate(tmp_path, None, {})[0] == 1


def test_key_model_ok_with_errors_blocks(tmp_path: Path) -> None:
    assert _gate(tmp_path, {"ok": True, "graph": {"errors": 1, "source_keys": 1}}, KR)[0] == 1


def test_key_model_malformed_blocks(tmp_path: Path) -> None:
    assert _gate(tmp_path, {"ok": True}, KR)[0] == 1
    assert _gate(tmp_path, {"graph": {"errors": 0}}, KR)[0] == 1


def test_gate_unreadable_required_report_structured(tmp_path: Path) -> None:
    a = _base(tmp_path)
    a[a.index("--qa") + 1] = str(tmp_path / "nope.json")
    r = bl(*a)
    assert r.returncode == 1 and "Traceback" not in r.stderr


def test_entries_declares_expectation(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text("plain text\n", encoding="utf-8")
    assert bl("key-model", "--source", str(s), "--entries", "1,5").returncode == 1


def test_missing_entry_reported(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "o.json"
    assert bl("key-model", "--source", str(s), "--entries", "1,99", "--out", str(out)).returncode == 1
    g = json.loads(out.read_text(encoding="utf-8"))["graph"]["gate"]
    assert any(f["code"] == "dangling_jump" and f["entry"] == "99" for f in g)
    assert bl("key-model", "--source", str(s), "--entries", "1").returncode == 0


def test_no_keys_names_side(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    # 无标题、无表的纯正文，靠 --expect-keys 声明有表（有标题无分支现报 empty_key，见 test_keygraph）
    s.write_text("prose only\n", encoding="utf-8")
    t = tmp_path / "t.md"
    t.write_text("prose\n", encoding="utf-8")
    out = tmp_path / "o.json"
    bl("key-model", "--source", str(s), "--translation", str(t), "--out", str(out), "--expect-keys")
    sides = {f["side"] for f in json.loads(out.read_text(encoding="utf-8"))["graph"]["gate"] if f["code"] == "no_keys"}
    assert sides == {"source", "translation"}


def test_key_model_missing_translation_structured(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "o.json"
    r = bl("key-model", "--source", str(s), "--translation", str(tmp_path / "none.md"), "--out", str(out))
    assert r.returncode == 1 and "Traceback" not in r.stderr
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["ok"] is False and rep["graph"]["errors"] == 1


def test_key_model_report_has_source_branches(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "o.json"
    bl("key-model", "--source", str(s), "--out", str(out))
    assert json.loads(out.read_text(encoding="utf-8"))["graph"]["source_branches"] == 4


def test_publish_stale_reports_removed_and_failure_blocks(tmp_path: Path, monkeypatch: Any) -> None:
    import publish_book as pb

    for f in ("key_model.json", "qa.json", "gate.json", "keyrender.json"):
        (tmp_path / f).write_text('{"ok": true}', encoding="utf-8")
    seen: dict[str, bool] = {}

    def fake_run(cmd: list[str]) -> dict[str, Any]:
        seen[cmd[-1] if len(cmd) < 3 else " ".join(cmd[2:4])] = (tmp_path / "gate.json").exists()
        rc = 1 if "keyrender" in " ".join(cmd) else 0
        return {"cmd": " ".join(cmd), "rc": rc, "seconds": 0, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(pb, "_run", fake_run)
    src = tmp_path / "s.md"
    src.write_text("x", encoding="utf-8")
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF")
    rc = pb.main(["run", "--work", str(tmp_path), "--source-md", str(src), "--translation-md", str(src),
                  "--pdf", str(pdf), "--only", "qa,gate"])
    run = json.loads((tmp_path / "publish_run.json").read_text(encoding="utf-8"))
    assert rc == 1 and run["releasable"] is False
    assert not any(seen.values())  # old gate.json was deleted before any command ran
