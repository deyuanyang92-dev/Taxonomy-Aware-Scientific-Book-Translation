"""交付门一键：章清单 + 可选 booklayout qa/check/key-report；非 ok 退出码 1。

    python3 scripts/delivery_gate.py WORK --tier draft
    python3 scripts/delivery_gate.py WORK --tier release \\
        --qa final/qa.json --check final/check.json --key-report final/key_report.json

试译档：各章至少有 draft.md。
交付档：分章且 draft+revised+checked+report 齐；若给了 layout 文件则须全部 ok。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import chapter_manifest as cm


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf8"))


def run_gate(
    work: Path,
    *,
    tier: str = "draft",
    qa: Path | None = None,
    check: Path | None = None,
    key_report: Path | None = None,
    fail_on_check_failed: bool = False,
) -> dict[str, Any]:
    work = Path(work)
    tier = (tier or "draft").strip().lower()
    if tier in ("交付", "publish"):
        tier = "release"
    if tier not in ("draft", "release"):
        return {
            "ok": False,
            "exit_code": 1,
            "problems": [f"未知 tier {tier!r}"],
            "tier": tier,
        }

    man = cm.build_manifest(work)
    cm.write_manifest(work)
    problems: list[str] = []

    if tier == "draft":
        if not man["ok_draft"]:
            missing = [
                name
                for name, ch in man["chapters"].items()
                if not ch.get("ready_draft")
            ]
            problems.append(f"draft 未齐：缺 draft.md → {missing}")
    else:
        if man["mode"] != "chapters":
            problems.append("release 须分章（work/chapters/<章>/）")
        if not man["ok_release"]:
            bad = [
                name
                for name, ch in man["chapters"].items()
                if not ch.get("ready_release")
            ]
            problems.append(
                f"release 未齐（需 draft+revised+checked+report）：{bad}"
            )

    for label, path in (("qa", qa), ("check", check)):
        if path is None:
            continue
        payload = _load_json(path)
        if not payload.get("ok"):
            problems.append(f"{label} not ok: {payload.get('problems', [])}")

    if key_report is not None:
        key = _load_json(key_report)
        if key.get("breaks"):
            problems.append(f"key_report breaks={len(key['breaks'])}")
        if key.get("defects"):
            problems.append(f"key_report defects={len(key['defects'])}")

    if fail_on_check_failed:
        fails: list[str] = []
        roots = list((work / "chapters").glob("*/check_failed.json")) if (work / "chapters").is_dir() else []
        if (work / "check_failed.json").exists():
            roots.append(work / "check_failed.json")
        for p in roots:
            try:
                data = json.loads(p.read_text(encoding="utf8"))
            except json.JSONDecodeError:
                fails.append(str(p))
                continue
            if data:  # 非空列表/字典即未决
                fails.append(str(p))
        if fails:
            problems.append(f"check_failed 未清空：{fails}")

    ok = not problems
    report = {
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "tier": tier,
        "problems": problems,
        "manifest": man,
        "files": {
            "qa": str(qa) if qa else None,
            "check": str(check) if check else None,
            "key_report": str(key_report) if key_report else None,
        },
    }
    out = work / "delivery_gate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work")
    ap.add_argument("--tier", choices=["draft", "release"], default="draft")
    ap.add_argument("--qa", type=Path)
    ap.add_argument("--check", type=Path)
    ap.add_argument("--key-report", type=Path)
    ap.add_argument("--fail-on-check-failed", action="store_true")
    a = ap.parse_args(argv)
    report = run_gate(
        Path(a.work),
        tier=a.tier,
        qa=a.qa,
        check=a.check,
        key_report=a.key_report,
        fail_on_check_failed=a.fail_on_check_failed,
    )
    print(json.dumps({k: report[k] for k in ("ok", "exit_code", "tier", "problems")},
                      ensure_ascii=False, indent=2))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
