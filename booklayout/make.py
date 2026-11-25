"""`booklayout make`: one command from aligned JSON to a gated deliverable.

Replaces the hand-run chain build -> map-pages -> build -> key-report -> build ->
qa/check/stylecheck/source-check -> gate -> html.  Each stage is timed; the
independent gates run in parallel; the third build pass runs only when
key-report asks for forced breaks.  Output: <out-dir>/<name>[.DRAFT].{docx,pdf,html}
and <name>.make.json (stage timings, gate verdict).  No model is called.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _bl(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "booklayout", *map(str, args)],
                          capture_output=True, text=True)


def _jload(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def make(args) -> int:
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name
    draft = not args.release_acceptance
    stem = name + (".DRAFT" if draft else "")
    docx, pdf = out_dir / f"{stem}.docx", out_dir / f"{stem}.pdf"
    wk = out_dir / f"{name}.work"
    wk.mkdir(exist_ok=True)
    times: dict[str, float] = {}
    log: list[str] = []
    if args.accepted is None and (Path(args.aligned).parent / "accepted.json").exists():
        # decisions already made live next to aligned.json; forgetting --accepted re-opened
        # every reviewed item (Vol25: 67 open instead of 0) and sent a model back over them
        args.accepted = Path(args.aligned).parent / "accepted.json"
        log.append(f"accepted: {args.accepted}")

    def stage(label: str, fn):
        t = time.time()
        r = fn()
        times[label] = round(time.time() - t, 1)
        if isinstance(r, subprocess.CompletedProcess) and r.returncode not in (0, 1):
            log.append(f"{label}: exit {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
        return r

    base = ["--aligned", args.aligned, "--figures", args.figures, "--metadata", args.metadata,
            "--out", docx, "--pdf"]
    if args.profile:
        base += ["--profile", args.profile]
    if args.release_acceptance:
        base += ["--release-acceptance", args.release_acceptance]
    rep = wk / "build_report.json"
    pmap, key = wk / "page_map.json", wk / "key.json"
    prof = ["--profile", args.profile] if args.profile else []

    r1 = stage("build1", lambda: _bl("build", *base, "--report", rep))
    if not pdf.exists() or (isinstance(r1, subprocess.CompletedProcess) and r1.returncode != 0):
        msg = "; ".join(log) or (r1.stderr or r1.stdout or "").strip()[-300:] if isinstance(
            r1, subprocess.CompletedProcess) else "; ".join(log)
        print("build failed: " + msg, file=sys.stderr)
        return 2
    stage("map-pages", lambda: _bl("map-pages", "--pdf", pdf, "--aligned", args.aligned,
                                   "--metadata", args.metadata, *prof, "--out", pmap))
    stage("build2", lambda: _bl("build", *base, "--map", pmap, "--report", rep))
    stage("key-report", lambda: _bl("key-report", "--pdf", pdf, "--out", key))
    if _jload(key).get("breaks"):
        stage("build3", lambda: _bl("build", *base, "--map", pmap, "--key-breaks", key, "--report", rep))
        stage("key-report2", lambda: _bl("key-report", "--pdf", pdf, "--out", key))

    qa, ck, sc = wk / "qa.json", wk / "check.json", wk / "source_check.json"
    jobs = {
        "qa": lambda: _bl("qa", "--aligned", args.aligned, "--figures", args.figures, "--pdf", pdf,
                          "--metadata", args.metadata, *prof, "--out", qa),
        "check": lambda: _bl("check", "--aligned", args.aligned, "--figures", args.figures,
                             "--pdf", pdf, "--metadata", args.metadata, "--out", ck),
        "stylecheck": lambda: _bl_mod("booklayout.stylecheck", docx),
    }
    if args.source_pdf:
        jobs["source-check"] = lambda: _bl(
            "source-check", "--source-pdf", args.source_pdf, "--pages", args.pages, "--pdf", pdf,
            "--metadata", args.metadata, "--work", wk / "sc", "--out", sc,
            "--lang", "spa" if args.translated else args.lang, "--dict-lang", "es" if args.translated else args.dict_lang,
            *(["--translated"] if args.translated else []),
            *(["--accepted", args.accepted] if args.accepted else []), "--jobs", str(args.jobs))
    t = time.time()
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        res = {k: f.result() for k, f in futs.items()}
    times["gates(parallel)"] = round(time.time() - t, 1)

    gate = wk / "gate.json"
    g = stage("gate", lambda: _bl("gate", "--qa", qa, "--check", ck, "--key-report", key,
                                  *(["--source-check", sc] if args.source_pdf else []), "--out", gate))
    problems = _jload(gate).get("problems", [])
    if res["stylecheck"].returncode != 0:
        problems.append("stylecheck: " + (res["stylecheck"].stdout + res["stylecheck"].stderr)[-300:])
    if args.html:
        stage("html", lambda: _bl("html", "--docx", docx, *prof, "--out", out_dir / f"{stem}.html"))
    if args.edit_html:
        stage("edit-html", lambda: _bl("edit-html", "--aligned", args.aligned, "--figures", args.figures,
                                       *prof, "--out", out_dir / f"{stem}.edit.html"))
    ok = g.returncode == 0 and not problems
    review_html = None
    if args.source_pdf and not ok:
        from . import review as review_module
        review_html = out_dir / f"{name}.review.html"
        t = time.time()
        rv = review_module.run(sc, review_html, args.accepted, qa)
        times["review"] = round(time.time() - t, 1)
        problems.append(f"review page ({rv['open']} source items, {rv['qa_problems']} qa): {review_html}")
    summary = {"ok": ok, "draft": draft, "problems": problems, "seconds": times,
               "total_s": round(sum(v for k, v in times.items()), 1), "files": {
                   "docx": str(docx), "pdf": str(pdf), "gate": str(gate),
                   "review": str(review_html) if review_html else None}, "log": log}
    try:  # trace db: where did each text come from (booklayout trace find/block/set)
        from . import trace as trace_module
        summary["trace_db"] = trace_module.build(Path(args.aligned), wk / "trace.db", pdf, wk)["db"]
    except Exception as exc:  # never fail a build for the index
        summary["trace_db_error"] = str(exc)
    (out_dir / f"{name}.make.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    print(("PASS" if ok else "FAIL") + f" total={summary['total_s']}s stages={times}")
    for p in problems[:10]:
        print("  -", p)
    return 0 if ok else 1


def _bl_mod(mod: str, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", mod, *map(str, args)], capture_output=True, text=True)


def add_parser(sub) -> None:
    m = sub.add_parser("make", help="one command: build (multi-pass) + all gates + html, timed")
    m.add_argument("--aligned", type=Path, required=True)
    m.add_argument("--figures", type=Path, required=True)
    m.add_argument("--metadata", type=Path, required=True)
    m.add_argument("--profile", type=Path)
    m.add_argument("--out-dir", type=Path, required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--release-acceptance", type=Path)
    m.add_argument("--source-pdf", type=Path)
    m.add_argument("--translated", action="store_true", help="edition is a translation of --source-pdf (numbers/names check only)")
    m.add_argument("--pages", default="1-50")
    m.add_argument("--accepted", type=Path)
    m.add_argument("--lang", default="spa")
    m.add_argument("--dict-lang", default="es")
    m.add_argument("--jobs", type=int, default=4)
    m.add_argument("--html", action="store_true", help="also read-only HTML from the DOCX")
    m.add_argument("--edit-html", action="store_true", help="also the editable HTML (see edit-html)")
    m.set_defaults(func=make)
