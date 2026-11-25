"""source-fix: source-check 报告 → aligned 补丁（不用大模型）。

source-check --aligned 的每个待看项带 ref（block_id + 字符区间）。本命令对可自动判定的项出补丁，其余写进 todo：

- 第二票：对原书该词的词框，放大到 --vote-dpi 再用 tesseract --psm 8 单词模式读一次。
  两次读法一致（逐字，含重音）才算证据足够；整页上下文读错（如 casi→las）会被这一票否决。
- output_error / conflict：原书置信度 >= --min-conf 且第二票 == 原书词 → 改成原书词。
  第二票 == 成品词 → 判 Tesseract 读错，列入 keep（建议加进 --accepted）。其余进 todo。
- review：第二票 == 成品词 → keep；否则 todo。
- name_suspect / missing / moved：一律 todo（斜体学名和版式问题要看图）。
- 防误改：成品词比原书词长且以原书词开头（nº→n）、含数字、成品词在块内位置对不上，一律不改。

补丁格式即 booklayout patch-blocks 的 version 1：每块一条，带 old_translation 前置条件，
块在这期间被别人改过则整条作废（stale），不会静默覆盖。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

AUTO = ("output_error", "conflict")


def vote(source_pdf: Path, page: int, box: list[int], base_dpi: int, vote_dpi: int) -> str:
    """Re-read one word box at higher resolution in single-word mode; '' on failure."""
    x0, y0, x1, y1 = box
    k = vote_dpi / base_dpi
    pad = 6
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "w"
        r = subprocess.run(["pdftoppm", "-cropbox", "-r", str(vote_dpi), "-f", str(page), "-l", str(page),
                            "-x", str(int(max(0, x0 - pad) * k)), "-y", str(int(max(0, y0 - pad) * k)),
                            "-W", str(int((x1 - x0 + 2 * pad) * k)), "-H", str(int((y1 - y0 + 2 * pad) * k)),
                            "-singlefile", "-png", str(source_pdf), str(dest)], capture_output=True)
        if r.returncode:
            return ""
        t = subprocess.run(["tesseract", f"{dest}.png", "-", "--psm", "8", "-l", "spa"], capture_output=True, text=True)
        return re.sub(r"^\W+|\W+$", "", t.stdout.strip())


NON_SPANISH_MARKS = "üëïöèàùçâêîôûäÿ"


def _marks(s: str) -> int:
    return sum(unicodedata.combining(c) for c in unicodedata.normalize("NFD", s))


def accent_unsafe(src: str, out: str) -> bool:
    """Accent-only difference where Tesseract may simply have dropped or mangled a mark (names, ü/è...)."""
    if unicodedata.normalize("NFD", src.lower()).encode("ascii", "ignore") != \
            unicodedata.normalize("NFD", out.lower()).encode("ascii", "ignore"):
        return False
    return _marks(src) < _marks(out) or any(c in NON_SPANISH_MARKS for c in (src + out).lower())


def plan(report: dict[str, Any], aligned: dict[str, Any], source_pdf: Path, base_dpi: int, vote_dpi: int,
         min_conf: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    texts = {b["block_id"]: b.get("translation") or "" for p in aligned["pages"] for b in p["blocks"]}
    fixes: list[dict[str, Any]] = []
    todo: list[dict[str, Any]] = []
    keep: list[str] = []
    for it in report["items"]:
        typ = it["type"]
        if typ == "tess_noise":
            continue
        ref = it.get("ref")
        if typ not in AUTO + ("review",) or not ref:
            todo.append({**it, "why": "needs a look" if ref or typ in ("missing", "moved") else "no block ref"})
            continue
        src, out = it["source"], it["output"]
        text = texts.get(ref["block_id"], "")
        if text[ref["start"]:ref["end"]] != out:
            todo.append({**it, "why": "span does not match aligned text"})
            continue
        v = vote(source_pdf, it["src_page"], it["box"], base_dpi, vote_dpi)
        it = {**it, "vote": v}
        if v and v == out:
            keep.append(it["id"])
            continue
        unsafe = (any(c.isdigit() for c in src + out) or (len(out) > len(src) and out.startswith(src))
                  or not src.isalpha() or len(src) < 2 or accent_unsafe(src, out))
        if typ in AUTO and v == src and it["conf"] >= min_conf and not unsafe:
            fixes.append(it)
        else:
            todo.append({**it, "why": "vote disagrees" if v != src else "unsafe or low confidence"})
    return fixes, todo, keep


def to_patch(fixes: list[dict[str, Any]], aligned: dict[str, Any]) -> dict[str, Any]:
    texts = {b["block_id"]: b.get("translation") or "" for p in aligned["pages"] for b in p["blocks"]}
    by_block: dict[str, list[dict[str, Any]]] = {}
    for f in fixes:
        by_block.setdefault(f["ref"]["block_id"], []).append(f)
    edits = []
    for bid, fs in by_block.items():
        old = texts[bid]
        new = old
        for f in sorted(fs, key=lambda f: -f["ref"]["start"]):
            new = new[:f["ref"]["start"]] + f["source"] + new[f["ref"]["end"]:]
        edits.append({"block_id": bid, "old_translation": old, "translation": new})
    return {"version": 1, "edits": edits}


def cmd_source_fix(args: argparse.Namespace) -> int:
    report = json.loads(args.report.read_text(encoding="utf-8"))
    aligned = json.loads(args.aligned.read_text(encoding="utf-8"))
    if not report.get("aligned"):
        print("error: report was not made with source-check --aligned (no block refs)")
        return 2
    fixes, todo, keep = plan(report, aligned, args.source_pdf, args.base_dpi, args.vote_dpi, args.min_conf)
    patch = to_patch(fixes, aligned)
    args.out.write_text(json.dumps(patch, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.todo:
        args.todo.write_text(json.dumps({"keep": keep, "todo": todo}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"fixes": len(fixes), "blocks": len(patch["edits"]), "keep": len(keep), "todo": len(todo)},
                     ensure_ascii=False))
    return 0


def add_parser(sub: Any) -> None:
    sf = sub.add_parser("source-fix", help="turn a source-check --aligned report into a patch-blocks patch "
                                           "(second Tesseract vote on the word crop; no LLM)")
    sf.add_argument("--report", type=Path, required=True)
    sf.add_argument("--aligned", type=Path, required=True)
    sf.add_argument("--source-pdf", type=Path, required=True)
    sf.add_argument("--out", type=Path, required=True, help="patch JSON for patch-blocks")
    sf.add_argument("--todo", type=Path, help="JSON: items left for a human look, plus ids safe to accept")
    sf.add_argument("--base-dpi", type=int, default=300, help="dpi the report boxes were measured at")
    sf.add_argument("--vote-dpi", type=int, default=450)
    sf.add_argument("--min-conf", type=float, default=80.0)
    sf.set_defaults(func=cmd_source_fix)
