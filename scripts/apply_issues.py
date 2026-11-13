#!/usr/bin/env python3
"""核译闸口：把子代理 JSONL 问题清单精确替换进译文，并追加对照报告。
用法: python3 apply_issues.py <书目录> <issues.jsonl> [--dry]
行格式: {"file","old","new","type":"误译|漏译|增译|术语|语序|格式","reason","en"}
闸口: old 在文件中恰好 1 次；old≠new；非 术语/误译/漏译/增译 类不得丢失英文词或数字。
幂等: 问题单可重复应用。已应用的条目（new 已在 old 的位置上）跳过并注明，不再叠加；
  判据是文本本身——old 不在文中而 new 在；或 old 的每一处出现都落在某处 new 之内（加性改动：补标题、补括注、补译注，
  new 包含 old）。old 只有一部分落在 new 内（歧义）仍按「匹配 N 次」拒绝。"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any

TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]+|\d+(?:\.\d+)?")
GATED_TYPES = ("术语", "误译", "漏译", "增译")


@dataclass
class Result:
    ok: int = 0
    bad: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


def already_applied(text: str, old: str, new: str) -> bool:
    """new 是否已经替换（或已包含）old：old 不在文中而 new 在；或 old 的每处出现都落在某处 new 里。new 为空串不判（无从判断）。"""
    if not new or new not in text:
        return False
    if old not in text:
        return True
    offsets = [k for k in range(len(new) - len(old) + 1) if new.startswith(old, k)]   # old 在 new 里的位置
    if not offsets:
        return False
    pos = text.find(old)
    while pos != -1:
        if not any(pos - k >= 0 and text.startswith(new, pos - k) for k in offsets):
            return False
        pos = text.find(old, pos + 1)
    return True


def apply(book: pathlib.Path, path: pathlib.Path, dry: bool = False) -> Result:
    zh_dir, report = book / "译文", book / "核译" / "核译对照报告.md"
    res = Result()
    for ln, line in enumerate(path.read_text(encoding="utf8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            it = json.loads(line)
        except Exception as e:
            res.bad.append((ln, f"JSON 错: {e}"))
            continue
        f = zh_dir / it["file"]
        if not f.exists():
            res.bad.append((ln, f"文件不存在 {it['file']}"))
            continue
        t = f.read_text(encoding="utf8")
        old, new = it["old"], it["new"]
        n = t.count(old)
        if old == new:
            res.bad.append((ln, "新旧相同"))
            continue
        if already_applied(t, old, new):
            res.skipped.append((ln, f"已应用，跳过 {it['file']}: {new[:40]}"))
            continue
        if n != 1:
            res.bad.append((ln, f"{it['file']} 匹配 {n} 次: {old[:40]}"))
            continue
        lost = set(TOKEN.findall(old)) - set(TOKEN.findall(new))
        if lost and it.get("type") not in GATED_TYPES:
            res.bad.append((ln, f"丢失英文/数字 {sorted(lost)[:5]}（type={it.get('type')}）"))
            continue
        if not dry:
            f.write_text(t.replace(old, new, 1), encoding="utf8")
        res.ok += 1
        res.rows.append(it)
    if not dry and res.rows:
        def esc(s: str) -> str:
            return s.replace("|", "｜").replace("\n", " ")
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("a", encoding="utf8") as w:
            w.write(f"\n## {path.stem}（{datetime.datetime.now():%m-%d %H:%M}，应用 {res.ok}，拒绝 {len(res.bad)}，已应用跳过 {len(res.skipped)}）\n\n")
            w.write("| 文件 | 类型 | 原译 | 改为 | 理由 |\n|---|---|---|---|---|\n")
            for it in res.rows:
                w.write(f"| {it['file'][:6]} | {it.get('type', '')} | {esc(it['old'])} | {esc(it['new'])} | {esc(it.get('reason', ''))} |\n")
            if res.bad:
                w.write("\n拒绝：\n" + "".join(f"- 行{ln_}: {msg}\n" for ln_, msg in res.bad))
    return res


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry" in argv
    res = apply(pathlib.Path(args[0]), pathlib.Path(args[1]), dry)
    skip = f"，已应用跳过 {len(res.skipped)}" if res.skipped else ""
    print(f"应用 {res.ok}，拒绝 {len(res.bad)}{skip}" + (" (dry)" if dry else ""))
    for ln_, msg in res.bad:
        print(f"  行{ln_}: {msg}")
    for ln_, msg in res.skipped:
        print(f"  行{ln_}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
