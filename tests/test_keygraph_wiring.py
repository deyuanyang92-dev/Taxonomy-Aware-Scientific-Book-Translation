"""key-model graph wiring and gate inputs (--key-model, --keyrender)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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


def test_zero_keys_with_heading_fails(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text("<!-- PDF p.1 -->\nKey to species\n\nsome prose only here.\n", encoding="utf-8")
    out = tmp_path / "o.json"
    r = bl("key-model", "--source", str(s), "--out", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["ok"] is False
    # 有标题无分支：keygraph 保留空表报 empty_key（error）；无标题时才报 no_keys
    assert any(f["code"] == "no_keys" for f in rep["graph"]["gate"]) or any(
        f["code"] == "empty_key" for f in rep["graph"]["source"]
    )


def test_expect_keys_flag_without_heading(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text("plain text\n", encoding="utf-8")
    assert bl("key-model", "--source", str(s)).returncode == 0
    assert bl("key-model", "--source", str(s), "--expect-keys").returncode == 1


def test_small_key_passes(tmp_path: Path) -> None:
    s = tmp_path / "s.md"
    s.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "o.json"
    r = bl("key-model", "--source", str(s), "--out", str(out))
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stdout + rep["graph"].__repr__()
    assert rep["graph"]["source_keys"] == 1 and rep["graph"]["errors"] == 0


def _base(tmp_path: Path) -> list[str]:
    return ["gate", "--qa", str(j(tmp_path / "qa.json", {"ok": True})),
            "--check", str(j(tmp_path / "ck.json", {"ok": True})),
            "--key-report", str(j(tmp_path / "kr0.json", {"breaks": [], "defects": []}))]


def test_gate_legacy_call_ok(tmp_path: Path) -> None:
    assert bl(*_base(tmp_path)).returncode == 0


def test_gate_key_model_not_ok(tmp_path: Path) -> None:
    ok = j(tmp_path / "km_ok.json", {"ok": True, "graph": {"errors": 0}})  # r3: graph.errors is a required field
    bad = j(tmp_path / "km_bad.json", {"ok": False, "graph": {"errors": 2}})
    assert bl(*_base(tmp_path), "--key-model", str(ok)).returncode == 0
    assert bl(*_base(tmp_path), "--key-model", str(bad)).returncode == 1


def test_gate_keyrender(tmp_path: Path) -> None:
    clean = j(tmp_path / "r_ok.json", {"rules": {}, "summary": {"KR1": 0}, "findings": []})
    fail = j(tmp_path / "r_bad.json", {"rules": {}, "summary": {"KR3": 1},
                                       "findings": [{"rule": "KR3", "page": 1, "detail": "x", "lead": "1"}]})
    assert bl(*_base(tmp_path), "--keyrender", str(clean)).returncode == 0
    assert bl(*_base(tmp_path), "--keyrender", str(fail)).returncode == 1
    assert bl(*_base(tmp_path), "--keyrender", str(tmp_path / "missing.json")).returncode == 1
