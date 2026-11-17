#!/usr/bin/env python3
"""快书调度：Lean + 块/章并行，冲 400 页 ≈ 30 分钟墙钟（质量闸口不砍）。

    python3 scripts/fast_book.py estimate --pages 400 --lean -j 8
    python3 scripts/fast_book.py run SRC.md -o WORK --sl de --tl en --glossary G.tsv --lean -j 8
    python3 scripts/fast_book.py chapters DIR -o WORK --sl de --tl en --glossary G.tsv --lean -j 4 --chapter-jobs 4

设计（separate-before-serializing）：
  - 块级：auto_translate --workers 并行 revise/check，每块只写 revise/cNNN.json
  - 章级：每章独立 WORK/chapters/<名>/，互不写同一文件；主进程最后拼 report
  - Lean 默认开；verify 默认 none（质控至多 1 次 LLM）；见 skill/TOKEN_ECONOMY.md（Cursor 优化）
  - 速度模式默认设 LLM_SKIP_OFFPEAK=1；可用 --respect-offpeak 关掉

墙钟模型（estimate，可测假设，非承诺）：
  draft≈0.8s/页；lean 送模≈12% × 14s/块/并发；默认不再加第二模型 verify。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from token_economy import LEAN_REWRITE_KINDS  # noqa: E402

CHUNK_PAGES = 3
SEC_DRAFT_PER_PAGE = 0.8
SEC_REVISE_PER_MODEL_CHUNK = 14.0
SEC_CHECK_PER_CHUNK = 8.0
LEAN_MODEL_PAGE_FRAC = 0.12
RISKY_PAGE_FRAC = 0.20
FULL_MODEL_PAGE_FRAC = 1.0


def estimate(pages: int, workers: int, lean: bool, *, verify: bool = False) -> dict[str, Any]:
    """返回各阶段秒数与合计。默认无第二模型 verify（Cursor 优化）。"""
    w = max(1, workers)
    draft_s = pages * SEC_DRAFT_PER_PAGE
    model_frac = LEAN_MODEL_PAGE_FRAC if lean else FULL_MODEL_PAGE_FRAC
    all_chunks = max(1, int(pages / CHUNK_PAGES + 0.999))
    llm_chunks = max(1, int(all_chunks * model_frac + 0.999)) if lean else all_chunks
    revise_s = (llm_chunks * SEC_REVISE_PER_MODEL_CHUNK) / w
    check_pages = pages * (RISKY_PAGE_FRAC if lean else 1.0)
    check_chunks = max(1, int(check_pages / CHUNK_PAGES + 0.999))
    check_s = (check_chunks * SEC_CHECK_PER_CHUNK) / w
    verify_s = (check_s * 0.6) if verify else 0.0
    total = draft_s + revise_s + check_s + verify_s
    return {
        "pages": pages,
        "workers": w,
        "lean": lean,
        "draft_s": round(draft_s, 1),
        "revise_s": round(revise_s, 1),
        "check_s": round(check_s, 1),
        "verify_s": round(verify_s, 1),
        "total_s": round(total, 1),
        "total_min": round(total / 60, 1),
        "llm_chunks_est": llm_chunks,
        "check_chunks_est": check_chunks,
        "under_30min": total <= 1800,
        "notes": (
            f"Lean={lean}（kinds={LEAN_REWRITE_KINDS if lean else 'ALL'}）；"
            f"verify={'on' if verify else 'off(默认)'}；Cursor 优化档。"
        ),
    }


def _print_estimate(e: dict[str, Any]) -> None:
    print(f"页数 {e['pages']}  并行 {e['workers']}  Lean={e['lean']}")
    print(f"  draft  ≈ {e['draft_s']}s")
    print(f"  revise ≈ {e['revise_s']}s  (约 {e['llm_chunks_est']} 块调模型)")
    print(f"  check  ≈ {e['check_s']}s  (约 {e['check_chunks_est']} 块)")
    if e["verify_s"]:
        print(f"  verify ≈ {e['verify_s']}s")
    print(f"  合计   ≈ {e['total_min']} 分钟（{e['total_s']}s）"
          f"{'  ✓ 目标≤30分钟' if e['under_30min'] else '  ✗ 超过30分钟：加 -j 或保持 --lean'}")
    print(e["notes"])


def _auto_cmd(src: Path, work: Path, a: argparse.Namespace, tgt: Path | None = None) -> list[str]:
    py = sys.executable
    script = Path(__file__).resolve().parent / "auto_translate.py"
    if tgt is None:
        cmd = [py, str(script), "run", str(src), "-o", str(work),
               "--sl", a.sl, "--tl", a.tl, "--engine", a.engine,
               "--workers", str(a.j), "--verify-engine", a.verify_engine]
    else:
        cmd = [py, str(script), "check", str(src), str(tgt), "-o", str(work),
               "--sl", a.sl, "--tl", a.tl, "--engine", a.engine,
               "--workers", str(a.j), "--verify-engine", a.verify_engine]
    if a.glossary:
        cmd += ["--glossary", a.glossary]
    if a.names:
        cmd += ["--names", a.names]
    if a.lean:
        cmd.append("--lean")
    else:
        cmd.append("--no-lean")
    if a.allow_same_verify:
        cmd.append("--allow-same-verify")
    if a.stop_after:
        cmd += ["--stop-after", a.stop_after]
    return cmd


def run_one(src: Path, work: Path, a: argparse.Namespace) -> int:
    work.mkdir(parents=True, exist_ok=True)
    if not a.respect_offpeak:
        os.environ.setdefault("LLM_SKIP_OFFPEAK", "1")
    cmd = _auto_cmd(src, work, a)
    print("[fast_book]", " ".join(cmd), flush=True)
    t0 = time.time()
    rc = subprocess.call(cmd)
    (work / "fast_book_wallclock.json").write_text(
        json.dumps({"src": str(src), "seconds": round(time.time() - t0, 1), "rc": rc},
                   ensure_ascii=False, indent=1),
        encoding="utf8")
    return rc


def _chapter_job(args: tuple[Any, ...]) -> dict[str, Any]:
    src_s, work_s, ns = args
    src, work = Path(src_s), Path(work_s)
    # 子进程重建 Namespace
    a = argparse.Namespace(**ns)
    rc = run_one(src, work, a)
    return {"src": src_s, "work": work_s, "rc": rc}


def run_chapters(src_dir: Path, work: Path, a: argparse.Namespace) -> int:
    """每章独立 work 子目录并行。章文件：*.md（跳过 draft/revised 等产物名）。"""
    files = sorted(p for p in src_dir.glob("*.md")
                   if p.stem not in {"draft", "revised", "final", "report"} and not p.name.startswith("_"))
    if not files:
        print(f"目录里没有章 md：{src_dir}", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if not a.respect_offpeak:
        os.environ.setdefault("LLM_SKIP_OFFPEAK", "1")
    ns = {k: getattr(a, k) for k in
          ("sl", "tl", "engine", "j", "verify_engine", "glossary", "names", "lean",
           "allow_same_verify", "stop_after", "respect_offpeak")}
    jobs = []
    for src in files:
        ch_work = work / "chapters" / src.stem
        jobs.append((str(src), str(ch_work), ns))
    print(f"[fast_book] 并行 {min(a.chapter_jobs, len(jobs))} 章 × 块并行 {a.j}", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=max(1, a.chapter_jobs)) as ex:
        futs = {ex.submit(_chapter_job, j): j[0] for j in jobs}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            print(f"[fast_book] 章完成 {Path(r['src']).name} rc={r['rc']}", flush=True)
    summary = {"chapters": results, "ok": sum(1 for r in results if r["rc"] == 0)}
    (work / "chapters_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                                encoding="utf8")
    return 0 if all(r["rc"] == 0 for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("estimate", help="估算墙钟（不跑翻译）")
    e.add_argument("--pages", type=int, required=True)
    e.add_argument("-j", type=int, default=8, help="块并行度")
    e.add_argument("--lean", action="store_true")

    r = sub.add_parser("run", help="单份 SRC.md 快跑（调 auto_translate）")
    r.add_argument("src")
    r.add_argument("-o", "--work", required=True)
    r.add_argument("--sl", default="de")
    r.add_argument("--tl", default="en")
    r.add_argument("--glossary")
    r.add_argument("--names")
    r.add_argument("--engine", default="auto")
    r.add_argument("--verify-engine", default="none",
                   help="默认 none（质控至多 1 次 LLM）")
    r.add_argument("--allow-same-verify", action="store_true", default=False)
    r.add_argument("--lean", action="store_true", default=True)
    r.add_argument("--no-lean", action="store_false", dest="lean")
    r.add_argument("-j", type=int, default=8)
    r.add_argument("--stop-after", choices=["draft", "revise"], default=None)
    r.add_argument("--respect-offpeak", action="store_true",
                   help="遵守 DeepSeek 闲时窗（默认跳过，否则白天无法 30 分钟）")

    c = sub.add_parser("chapters", help="目录下多章 md 并行（每章独立 work）")
    c.add_argument("src_dir")
    c.add_argument("-o", "--work", required=True)
    c.add_argument("--sl", default="de")
    c.add_argument("--tl", default="en")
    c.add_argument("--glossary")
    c.add_argument("--names")
    c.add_argument("--engine", default="auto")
    c.add_argument("--verify-engine", default="none")
    c.add_argument("--allow-same-verify", action="store_true", default=False)
    c.add_argument("--lean", action="store_true", default=True)
    c.add_argument("--no-lean", action="store_false", dest="lean")
    c.add_argument("-j", type=int, default=4, help="每章块并行")
    c.add_argument("--chapter-jobs", type=int, default=4, help="同时跑几章")
    c.add_argument("--stop-after", choices=["draft", "revise"], default=None)
    c.add_argument("--respect-offpeak", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "estimate":
        _print_estimate(estimate(a.pages, a.j, a.lean, verify=False))
        return 0
    if a.cmd == "run":
        pages = len([ln for ln in Path(a.src).read_text(encoding="utf8").splitlines()
                     if ln.strip().startswith("<!-- PDF p.")])
        if pages:
            _print_estimate(estimate(pages, a.j, a.lean, verify=a.verify_engine not in ("none", "")))
        return run_one(Path(a.src), Path(a.work), a)
    return run_chapters(Path(a.src_dir), Path(a.work), a)


if __name__ == "__main__":
    raise SystemExit(main())
