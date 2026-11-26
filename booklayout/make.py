"""`booklayout make`: one command from aligned JSON to a gated deliverable.

Replaces the hand-run chain build -> map-pages -> build -> key-report -> build ->
qa/check/stylecheck/source-check -> gate -> html.  Each stage is timed; the
independent gates run in parallel; the third build pass runs only when
key-report asks for forced breaks.  Output: <out-dir>/<name>[.DRAFT].{docx,pdf,html}
and <name>.make.json (stage timings, gate verdict).  No model is called.
"""
from __future__ import annotations

import hashlib
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


def _sha_bytes(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p + b"\0")
    return h.hexdigest()


def _file_sha(p: Path | None) -> str:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest() if p else "-"
    except OSError:
        return "missing"


def aligned_digests(aligned: Path, translation_md: Path | None = None) -> dict[str, str]:
    """Hashes that decide which gates a change can affect (design 2026-11-26, D.2/D.3).

    src = every page/block field except the translation fields and the named style, so the source
          text, roles, levels and coordinates; a block's own `src.hash` is part of it when present.
    tr  = the translation fields (`translation*`) and an external translation file, if any.
    aligned/1 files carry no src.hash: the hash is computed here from the block's own fields, which
    is stricter, not looser.
    """
    data = _jload(aligned)
    src: list[object] = []
    tr: list[object] = []
    for p in data.get("pages", []):
        src.append({k: v for k, v in p.items() if k != "blocks"})
        for b in p.get("blocks", []):
            src.append({k: v for k, v in b.items() if not k.startswith("translation") and k != "style"})
            tr.append([b.get("block_id"), {k: v for k, v in b.items() if k.startswith("translation")}])
    dump = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False).encode("utf-8")  # noqa: E731
    return {"src": _sha_bytes(dump(src)), "tr": _sha_bytes(dump(tr), _file_sha(translation_md).encode())}


def classify_change(prev: dict, cur: dict, fast: str | None, release: bool = False,
                    translated: bool = False) -> dict:
    """Decide what `make --fast` may skip.  Pure: previous and current state dicts in, decision out.

    Only source-check is ever skipped (it is the one gate that is slow and depends on the source
    text and scans rather than the typesetting).  Everything else always runs.  A skip is reported
    as a skip, never as a pass.  Rows follow design D.2:
      full         no --fast; --release; no/old state; source-check inputs or code changed; source text changed
      translation  source text unchanged, translation changed (translated edition only)
      style        source text and translation unchanged, profile changed
      none         nothing changed
    A same-language edition (not --translated) uses the translation field as its output text, which
    source-check exists to verify, so a translation change there is a full run.
    """
    def full(why: str) -> dict:
        return {"mode": "full", "skip_source_check": False, "reason": why}

    if not fast:
        return full("--fast not given")
    if release:
        return full("--release-acceptance: release always runs every gate")
    if not prev or not prev.get("sc_done"):
        return full("no previous source-check state")
    for k, label in (("sc_key", "source-check inputs (source pdf, pages, language, accepted, metadata)"),
                     ("source_fp", "source-check code")):
        if prev.get(k) != cur.get(k):
            return full(f"{label} changed")
    if prev.get("sc_src") != cur["src"]:
        return full("source text changed since the last source-check")
    if prev.get("tr") != cur["tr"]:
        if not translated:
            return full("same-language edition: translation is the output text, source-check must re-verify it")
        mode = "translation"
    elif prev.get("profile") != cur.get("profile"):
        mode = "style"
    else:
        mode = "none"
    if fast == "style" and mode == "translation":
        return full("--fast=style but the translation changed")
    return {"mode": mode, "skip_source_check": True,
            "reason": f"src unchanged, hash={cur['src'][:12]}"}


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

    fast = getattr(args, "fast", None)
    state_f = wk / "make_state.json"
    prev_state = _jload(state_f)
    sc_opts = {"source_pdf": str(args.source_pdf), "size": (Path(args.source_pdf).stat().st_size
                                                              if args.source_pdf and Path(args.source_pdf).exists() else 0),
               "pages": args.pages, "lang": args.lang, "dict_lang": args.dict_lang,
               "translated": bool(args.translated)} if args.source_pdf else {}
    from . import buildcache
    cur_state = {**aligned_digests(Path(args.aligned), getattr(args, "translation", None)),
                 "profile": _file_sha(args.profile),
                 "sc_key": _sha_bytes(json.dumps(sc_opts, sort_keys=True).encode(), _file_sha(args.accepted).encode(),
                                      _file_sha(args.metadata).encode()),
                 "source_fp": buildcache.fingerprints()["source"]}
    decision = classify_change(prev_state, cur_state, fast, bool(args.release_acceptance), bool(args.translated))
    skip_sc = bool(args.source_pdf) and decision["skip_source_check"] and (wk / "source_check.json").exists()
    if fast:
        log.append(f"fast={fast}: mode={decision['mode']}, source-check "
                   + (f"SKIPPED ({decision['reason']})" if skip_sc else f"runs ({decision['reason']})"))

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
    if args.source_pdf and not skip_sc:
        jobs["source-check"] = lambda: _bl(
            "source-check", "--source-pdf", args.source_pdf, "--pages", args.pages, "--pdf", pdf,
            "--metadata", args.metadata, "--work", wk / "sc", "--out", sc,
            "--lang", "spa" if args.translated else args.lang, "--dict-lang", "es" if args.translated else args.dict_lang,
            *(["--translated"] if args.translated else []),
            *(["--accepted", args.accepted] if args.accepted else []), "--jobs", str(args.jobs))
    gate_s: dict[str, float] = {}

    def timed(k: str, f):
        def run():
            t0 = time.time()
            try:
                return f()
            finally:
                gate_s[k] = round(time.time() - t0, 1)
        return run

    t = time.time()
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {k: ex.submit(timed(k, f)) for k, f in jobs.items()}
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
    skipped = ([{"gate": "source-check", "reason": decision["reason"], "mode": decision["mode"],
                 "hash": cur_state["src"], "note": "previous verdict reused, not re-checked"}] if skip_sc else [])
    if skipped:
        try:  # a skipped gate must be visible in the gate report itself, not only in make.json
            gj = _jload(gate)
            gj["skipped"] = skipped
            gate.write_text(json.dumps(gj, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    if args.source_pdf and not skip_sc and "source-check" in res and res["source-check"].returncode in (0, 1):
        cur_state.update({"sc_done": True, "sc_src": cur_state["src"]})
    elif skip_sc:
        cur_state.update({"sc_done": True, "sc_src": prev_state.get("sc_src")})
    state_f.write_text(json.dumps(cur_state, indent=1), encoding="utf-8")
    summary = {"ok": ok, "draft": draft, "problems": problems, "seconds": times, "gate_seconds": gate_s,
               "fast": decision if fast else None, "skipped": skipped,
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
    print(("PASS" if ok else "FAIL") + f" total={summary['total_s']}s stages={times} gates={gate_s}")
    for s_ in skipped:
        print(f"  SKIPPED (not checked): {s_['gate']}: {s_['reason']}")
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
    m.add_argument("--fast", nargs="?", const="auto", choices=["auto", "style"], default=None,
                   help="skip source-check when the source text is unchanged since its last run (see classify_change); "
                        "the skip is reported in gate.json/make.json. Release builds ignore it. =style: refuse if text changed")
    m.add_argument("--html", action="store_true", help="also read-only HTML from the DOCX")
    m.add_argument("--edit-html", action="store_true", help="also the editable HTML (see edit-html)")
    m.set_defaults(func=make)
