"""`booklayout sample`: one command for a small end-to-end trial of a page range (issue #70).

native PDF pages -> ingest-native -> Google translate (yiku glossary) -> figures extract ->
auto metadata -> make (counts only the sample pages) -> three-line summary.
Replaces the hand-run six-step chain.  No model is called.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def parse_range(s: str) -> tuple[int, int]:
    a, _, b = s.partition("-")
    lo, hi = int(a), int(b or a)
    if lo < 1 or hi < lo:
        raise ValueError(f"bad page range: {s}")
    return lo, hi


def make_meta(title: str, first: int, volume: str = "", running_left: str = "") -> dict[str, Any]:
    return {"title": title, "volume": volume, "running_left": running_left or title,
            "running_right": f"p.{first}", "include_front_matter": False, "include_contents": False,
            "chapter_headings": False, "body_start_page": first, "title_page": False}


def summarize(rep: dict[str, Any], mk: dict[str, Any], seconds: float) -> list[str]:
    probs = mk.get("problems", [])
    untr = sum(1 for p in probs if "no translation" in p)
    return [
        f"translate: {rep.get('blocks', 0)} blocks, {rep.get('chars', 0)} chars, "
        f"google_requests={rep.get('google_requests', 0)} cache_hits={rep.get('cache_hits', 0)} "
        f"glossary_applied={rep.get('glossary_applied', 0)}",
        f"gate: {'OK' if mk.get('ok') else 'FAIL'}; {len(probs)} problem(s)"
        + (f" ({untr} about untranslated blocks)" if untr else "")
        + "".join(f"\n  - {p.splitlines()[0][:160]}" for p in probs),
        f"pdf: {mk.get('files', {}).get('pdf', '-')}  total {seconds:.0f}s",
    ]


def _bl(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "booklayout", *map(str, args)], capture_output=True, text=True)


def run_sample(pdf: Path, pages: str, sl: str, tl: str, out: Path, title: str = "", name: str = "",
               glossary: str | None = "分类学", source_check: bool = False) -> int:
    t0 = time.time()
    lo, hi = parse_range(pages)
    out.mkdir(parents=True, exist_ok=True)
    name = name or f"{pdf.stem}_p{lo}-{hi}"
    src, zh, rep_f, figs, meta = (out / "aligned_src.json", out / "aligned_zh.json", out / "translate.report.json",
                                  out / "figs", out / "meta.json")
    steps = [("ingest-native", ["ingest-native", pdf, "--pages", pages, "-o", src]),
             ("translate", ["translate-aligned", "--aligned", src, "--out", zh, "--sl", sl, "--tl", tl,
                            "--report", rep_f, *(["--glossary", glossary] if glossary else [])]),
             ("figures", ["figures", "extract", "--pdf", pdf, "--out", figs, "--first", lo, "--last", hi,
                          "--aligned", src, "--lenient"])]
    for label, a in steps:
        r = _bl(*a)
        # figures extract exits 1 when its audit finds issues; the manifest is still written and make re-audits
        if r.returncode != 0 and not (label == "figures" and (figs / "figures_manifest.json").exists()):
            print(f"sample: stage '{label}' failed:\n{(r.stderr or r.stdout)[-600:]}", file=sys.stderr)
            return 2
    meta.write_text(json.dumps(make_meta(title or pdf.stem, lo), ensure_ascii=False, indent=1), encoding="utf-8")
    mk_args = ["make", "--aligned", zh, "--figures", figs, "--metadata", meta, "--out-dir", out / "make",
               "--name", name, "--pages", pages]
    if source_check:
        mk_args += ["--source-pdf", pdf, "--translated"]
    r = _bl(*mk_args)
    mk = json.loads((out / "make" / f"{name}.make.json").read_text(encoding="utf-8")) \
        if (out / "make" / f"{name}.make.json").exists() else {"ok": False, "problems": [(r.stderr or r.stdout)[-300:]]}
    rep = json.loads(rep_f.read_text(encoding="utf-8")) if rep_f.exists() else {}
    print("\n".join(summarize(rep, mk, time.time() - t0)))
    return 0 if mk.get("ok") else 1


def add_parser(sub: Any) -> None:
    p = sub.add_parser("sample", help="one-command trial of a page range: ingest, Google translate, figures, make, summary")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", required=True, help="first-last, e.g. 78-85")
    p.add_argument("--sl", default="en")
    p.add_argument("--tl", default="zh-CN")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", default="")
    p.add_argument("--name", default="")
    p.add_argument("--glossary", nargs="?", const="分类学", default="分类学", metavar="DOMAIN")
    p.add_argument("--source-check", action="store_true", help="also run source-check (slow, ~15 s)")
    p.set_defaults(func=lambda a: run_sample(a.pdf, a.pages, a.sl, a.tl, a.out, a.title, a.name, a.glossary, a.source_check))
