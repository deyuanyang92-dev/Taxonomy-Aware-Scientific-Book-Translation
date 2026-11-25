"""章级交付清单：每章 draft/revised/checked/polish/qa/report 是否齐。

    python3 scripts/chapter_manifest.py WORK
    python3 scripts/chapter_manifest.py WORK --write
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STAGES = ("draft", "revised", "checked", "polish", "qa", "report")
# 交付最低：初稿+改写+核对+报告（polish/qa 另计，排版 qa 常在 layout/）
RELEASE_NEED = ("draft", "revised", "checked", "report")
DRAFT_NEED = ("draft",)


def _stage_flags(d: Path) -> dict[str, bool]:
    return {
        "draft": (d / "draft.md").exists(),
        "revised": (d / "revised.md").exists(),
        "checked": (d / "checked.md").exists() or (d / "final.md").exists(),
        "polish": (d / "polished.md").exists() or (d / "polish.md").exists(),
        "qa": (d / "qa.json").exists(),
        "report": (d / "report.md").exists(),
    }


def _ready(flags: dict[str, bool], need: tuple[str, ...]) -> bool:
    return all(flags.get(k) for k in need)


def scan_dir(d: Path) -> dict[str, Any]:
    flags = _stage_flags(d)
    return {
        **flags,
        "path": str(d),
        "ready_draft": _ready(flags, DRAFT_NEED),
        "ready_release": _ready(flags, RELEASE_NEED),
    }


def build_manifest(work: Path) -> dict[str, Any]:
    """有 chapters/ 则按章；否则整 work 记为 single（不算分章交付）。"""
    work = Path(work)
    ch_root = work / "chapters"
    chapters: dict[str, Any] = {}
    if ch_root.is_dir() and any(ch_root.iterdir()):
        mode = "chapters"
        for ch in sorted(p for p in ch_root.iterdir() if p.is_dir()):
            chapters[ch.name] = scan_dir(ch)
    else:
        mode = "single"
        chapters["_"] = scan_dir(work)
    ok_draft = all(c["ready_draft"] for c in chapters.values()) if chapters else False
    ok_release = (
        mode == "chapters"
        and bool(chapters)
        and all(c["ready_release"] for c in chapters.values())
    )
    return {
        "work": str(work),
        "mode": mode,
        "chapters": chapters,
        "ok_draft": ok_draft,
        "ok_release": ok_release,
        "n_chapters": len(chapters) if mode == "chapters" else 0,
        "stages": list(STAGES),
        "release_need": list(RELEASE_NEED),
    }


def write_manifest(work: Path, path: Path | None = None) -> Path:
    man = build_manifest(work)
    out = path or (Path(work) / "chapter_manifest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work")
    ap.add_argument("--write", action="store_true", help="写入 work/chapter_manifest.json")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    man = build_manifest(Path(a.work))
    if a.write or a.out:
        out = write_manifest(Path(a.work), a.out)
        print(out)
    else:
        print(json.dumps(man, ensure_ascii=False, indent=2))
    return 0 if man["ok_draft"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
