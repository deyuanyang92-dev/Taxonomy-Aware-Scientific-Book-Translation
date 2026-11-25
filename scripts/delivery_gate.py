"""交付门一键：章清单 + 排版三审 + **严格检索表格式**；非 ok 退出码 1。

    # 试译档
    python3 scripts/delivery_gate.py WORK --tier draft

    # 正式交付（必须）
    python3 scripts/delivery_gate.py WORK --tier release \\
        --qa final/qa.json --check final/check.json \\
        --key-report final/key_report.json \\
        --key-audit final/keys_check.json
    # 或直接喂对齐稿现场审查：
    #   --aligned final/aligned.json

正式交付硬条件：
- 分章且 draft+revised+checked+report 齐
- 必须提供 qa / check / key-report，且全部 ok、检索表 PDF 无 breaks/defects
- 必须提供 key-audit 或 aligned；``key_audit.ok / format_ok`` 为真（零格式缺陷）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import chapter_manifest as cm

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf8"))


def _run_keys_check(aligned: Path) -> dict[str, Any]:
    from booklayout.keyaudit import audit_key_blocks
    from booklayout.builder import load_aligned

    data = load_aligned(aligned)
    return audit_key_blocks(data, strict=True)


def run_gate(
    work: Path,
    *,
    tier: str = "draft",
    qa: Path | None = None,
    check: Path | None = None,
    key_report: Path | None = None,
    key_audit: Path | None = None,
    aligned: Path | None = None,
    fail_on_check_failed: bool | None = None,
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

    # 正式交付默认硬拦未决核译；试译档默认不拦
    if fail_on_check_failed is None:
        fail_on_check_failed = tier == "release"

    man = cm.build_manifest(work)
    cm.write_manifest(work)
    problems: list[str] = []
    key_format: dict[str, Any] | None = None

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
        # 正式交付：排版与检索表格式文件不可缺
        if qa is None:
            problems.append("release 必须提供 --qa（booklayout qa）")
        if check is None:
            problems.append("release 必须提供 --check")
        if key_report is None:
            problems.append("release 必须提供 --key-report")
        if key_audit is None and aligned is None:
            problems.append(
                "release 必须提供 --key-audit（keys-check）或 --aligned（现场严格审查）"
            )

    for label, path in (("qa", qa), ("check", check)):
        if path is None:
            continue
        payload = _load_json(path)
        if not payload.get("ok"):
            problems.append(f"{label} not ok: {payload.get('problems', [])}")
        # qa 内嵌的检索表审计也硬拦
        if label == "qa":
            embedded = payload.get("key_audit") or {}
            if embedded.get("defect_count") or embedded.get("ok") is False \
                    or embedded.get("format_ok") is False:
                n = embedded.get("defect_count") or len(embedded.get("defects") or [])
                problems.append(f"qa.key_audit format defects={n}")

    if key_report is not None:
        key = _load_json(key_report)
        if key.get("breaks"):
            problems.append(f"key_report breaks={len(key['breaks'])}")
        if key.get("defects"):
            problems.append(f"key_report defects={len(key['defects'])}")

    # 严格检索表格式
    if key_audit is not None:
        key_format = _load_json(key_audit)
    elif aligned is not None and tier == "release":
        key_format = _run_keys_check(aligned)
        (work / "keys_check.json").write_text(
            json.dumps(key_format, ensure_ascii=False, indent=2) + "\n",
            encoding="utf8",
        )
    if key_format is not None:
        defects = key_format.get("defects") or []
        if not key_format.get("ok", True) or not key_format.get("format_ok", True) or defects:
            problems.append(
                f"key format defects={len(defects)} "
                f"({key_format.get('by_reason')})"
            )

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
            if data:
                fails.append(str(p))
        if fails:
            problems.append(f"check_failed 未清空：{fails}")

    # 去重
    unique: list[str] = []
    seen: set[str] = set()
    for p in problems:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    ok = not unique
    report = {
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "tier": tier,
        "problems": unique,
        "key_format_ok": key_format.get("format_ok", True) if key_format else None,
        "key_format": {
            "defects": len((key_format or {}).get("defects") or []),
            "by_reason": (key_format or {}).get("by_reason"),
        } if key_format else None,
        "manifest": man,
        "files": {
            "qa": str(qa) if qa else None,
            "check": str(check) if check else None,
            "key_report": str(key_report) if key_report else None,
            "key_audit": str(key_audit) if key_audit else None,
            "aligned": str(aligned) if aligned else None,
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
    ap.add_argument("--key-audit", type=Path, help="booklayout keys-check JSON")
    ap.add_argument("--aligned", type=Path, help="aligned.json；release 且无 --key-audit 时现场审查")
    ap.add_argument(
        "--fail-on-check-failed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="release 默认开启：check_failed 未清空则失败",
    )
    a = ap.parse_args(argv)
    report = run_gate(
        Path(a.work),
        tier=a.tier,
        qa=a.qa,
        check=a.check,
        key_report=a.key_report,
        key_audit=a.key_audit,
        aligned=a.aligned,
        fail_on_check_failed=a.fail_on_check_failed,
    )
    print(json.dumps(
        {k: report[k] for k in (
            "ok", "exit_code", "tier", "key_format_ok", "problems",
        )},
        ensure_ascii=False,
        indent=2,
    ))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
