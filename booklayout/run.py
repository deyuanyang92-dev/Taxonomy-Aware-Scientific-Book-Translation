"""`booklayout run`: native PDF -> typeset translated PDF in one command (no model except Google).

Stages: ingest-native || figures -> translate (Google + yiku glossary; --no-translate copies the source
text for a layout/timing run) -> metadata -> make (build, gates, source-check on the native text layer,
html).  Every stage is timed and written to <out>/run.status.json as it finishes, so progress can be read
from the file.  Stages are skipped when their output exists and the input stamp is unchanged.

Exit codes: 0 pass; 10 only untranslated blocks remain (draft); 20 gate problems need a human
(review/problem list in the summary); 30 a stage or tool failed; 40 bad configuration.
Budget: a stage over --stage-budget seconds is reported as WARN in the status file.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .sample import make_meta, summarize

EXIT_PASS, EXIT_DRAFT, EXIT_HUMAN, EXIT_TOOL, EXIT_CONFIG = 0, 10, 20, 30, 40


def _bl(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "booklayout", *map(str, args)], capture_output=True, text=True)


def _stamp(*parts: object) -> str:
    return hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()[:16]


def _pdf_stamp(pdf: Path) -> str:
    st = pdf.stat()
    return f"{pdf.resolve()}|{st.st_size}|{st.st_mtime_ns}"


class Status:
    def __init__(self, path: Path, budget: float) -> None:
        self.path, self.budget = path, budget
        self.data: dict[str, Any] = {"stages": {}, "warnings": [], "state": "running"}
        self.t0 = time.time()
        self.save()

    def save(self) -> None:
        self.data["elapsed_s"] = round(time.time() - self.t0, 1)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def stage(self, name: str, seconds: float, ok: bool, note: str = "") -> None:
        self.data["stages"][name] = {"s": round(seconds, 1), "ok": ok, "note": note}
        if seconds > self.budget:
            self.data["warnings"].append(f"{name} took {seconds:.0f}s > budget {self.budget:.0f}s")
        self.save()


def parse_pages(spec: str | None, n_pages: int) -> tuple[int, int]:
    if not spec or spec == "all":
        return 1, n_pages
    a, _, b = spec.partition("-")
    lo, hi = int(a), int(b or a)
    if lo < 1 or hi < lo or hi > n_pages:
        raise ValueError(f"page range {spec} outside 1-{n_pages}")
    return lo, hi


def copy_source_as_translation(src: Path, dst: Path) -> int:
    data = json.loads(src.read_text(encoding="utf-8"))
    n = 0
    for p in data.get("pages", []):
        for b in p.get("blocks", []):
            if b.get("text") and not b.get("translation"):
                b["translation"] = b["text"]
                n += 1
    dst.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return n


def run_book(pdf: Path, out: Path, pages: str | None, sl: str, tl: str, title: str, glossary: str | None,
             translate: bool, source_check: bool, html: bool, budget: float, profile: Path | None) -> int:
    if not pdf.is_file():
        print(f"run: no such PDF: {pdf}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        import fitz
        n_pages = fitz.open(str(pdf)).page_count
        lo, hi = parse_pages(pages, n_pages)
    except (ValueError, ImportError) as exc:
        print(f"run: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    out.mkdir(parents=True, exist_ok=True)
    st = Status(out / "run.status.json", budget)
    pr = f"{lo}-{hi}"
    name = f"{pdf.stem}_p{lo}-{hi}"
    src, zh, rep_f, figs, meta = (out / "aligned_src.json", out / "aligned_zh.json", out / "translate.report.json",
                                  out / "figs", out / "meta.json")
    stamp_f = out / "run.stamps.json"
    stamps = json.loads(stamp_f.read_text(encoding="utf-8")) if stamp_f.exists() else {}
    base = _stamp(_pdf_stamp(pdf), pr)

    def fail(label: str, r: subprocess.CompletedProcess | str) -> int:
        msg = r if isinstance(r, str) else (r.stderr or r.stdout)[-600:]
        st.stage(label, 0, False, msg)
        st.data["state"] = "tool-failure"
        st.save()
        print(f"run: stage '{label}' failed:\n{msg}", file=sys.stderr)
        return EXIT_TOOL

    def ingest() -> tuple[str, subprocess.CompletedProcess | None, float]:
        t = time.time()
        if stamps.get("ingest") == base and src.exists():
            return "ingest-native", None, time.time() - t
        r = _bl("ingest-native", pdf, "--pages", pr, "-o", src)
        return "ingest-native", r, time.time() - t

    def figures() -> tuple[str, subprocess.CompletedProcess | None, float]:
        t = time.time()
        if stamps.get("figures") == base and (figs / "figures_manifest.json").exists():
            return "figures", None, time.time() - t
        r = _bl("figures", "extract", "--pdf", pdf, "--out", figs, "--first", lo, "--last", hi, "--lenient")
        return "figures", r, time.time() - t

    with ThreadPoolExecutor(2) as ex:
        results = [f.result() for f in [ex.submit(ingest), ex.submit(figures)]]
    for label, r, secs in results:
        if r is not None and r.returncode != 0:
            return fail(label, r)
        st.stage(label, secs, True, "cached" if r is None else "")
        stamps["ingest" if label == "ingest-native" else "figures"] = base
    # figures need the aligned JSON only for page selection in sample; here the page range is explicit.
    t = time.time()
    tstamp = _stamp(base, sl, tl, glossary, translate, src.stat().st_mtime_ns)
    rep: dict[str, Any] = {}
    if stamps.get("translate") == tstamp and zh.exists():
        st.stage("translate", time.time() - t, True, "cached")
    elif translate:
        r = _bl("translate-aligned", "--aligned", src, "--out", zh, "--sl", sl, "--tl", tl, "--report", rep_f,
                *(["--glossary", glossary] if glossary else []))
        if r.returncode != 0:
            return fail("translate", r)
        st.stage("translate", time.time() - t, True)
        stamps["translate"] = tstamp
    else:
        n = copy_source_as_translation(src, zh)
        st.stage("translate", time.time() - t, True, f"SKIPPED (--no-translate): {n} blocks copied as-is; layout/timing run only")
        stamps["translate"] = tstamp
    if rep_f.exists():
        rep = json.loads(rep_f.read_text(encoding="utf-8"))
    stamp_f.write_text(json.dumps(stamps, indent=1), encoding="utf-8")
    meta.write_text(json.dumps(make_meta(title or pdf.stem, lo), ensure_ascii=False, indent=1), encoding="utf-8")
    mk = ["make", "--aligned", zh, "--figures", figs, "--metadata", meta, "--out-dir", out / "make", "--name", name,
          "--pages", pr, "--translated", "--lang", {"en": "eng"}.get(sl, sl)]
    if profile:
        mk += ["--profile", profile]
    if source_check:
        mk += ["--source-pdf", pdf]
    if html:
        mk += ["--html"]
    t = time.time()
    r = _bl(*mk)
    mkj = out / "make" / f"{name}.make.json"
    if not mkj.exists():
        return fail("make", r)
    res = json.loads(mkj.read_text(encoding="utf-8"))
    st.stage("make", time.time() - t, bool(res.get("ok")), "")
    for k, v in (res.get("seconds") or {}).items():
        st.data["stages"][f"make.{k}"] = {"s": v, "ok": True, "note": ""}
        if v > budget:
            st.data["warnings"].append(f"make.{k} took {v:.0f}s > budget {budget:.0f}s")
    probs = res.get("problems", [])
    untranslated_only = bool(probs) and all("no translation" in p for p in probs)
    code = EXIT_PASS if res.get("ok") else (EXIT_DRAFT if untranslated_only else EXIT_HUMAN)
    st.data.update({"state": {0: "pass", 10: "draft", 20: "needs-human"}[code], "exit": code,
                    "pdf": res.get("files", {}).get("pdf"), "problems": probs})
    st.save()
    print("\n".join(summarize(rep, res, time.time() - st.t0)))
    print(f"status: {st.path}  exit={code}")
    for w in st.data["warnings"]:
        print(f"  WARN {w}")
    return code


def add_parser(sub: Any) -> None:
    p = sub.add_parser("run", help="native PDF -> typeset translated PDF, one command, timed status file, exit codes")
    p.add_argument("pdf", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pages", help="first-last (default: whole book)")
    p.add_argument("--sl", default="en")
    p.add_argument("--tl", default="zh-CN")
    p.add_argument("--title", default="")
    p.add_argument("--glossary", nargs="?", const="分类学", default="分类学", metavar="DOMAIN")
    p.add_argument("--no-translate", action="store_true", help="copy source text as translation (layout/timing run)")
    p.add_argument("--no-source-check", action="store_true")
    p.add_argument("--no-html", action="store_true")
    p.add_argument("--profile", type=Path)
    p.add_argument("--stage-budget", type=float, default=60.0, help="WARN when a stage exceeds this many seconds")
    p.set_defaults(func=lambda a: run_book(a.pdf, a.out, a.pages, a.sl, a.tl, a.title, a.glossary,
                                           not a.no_translate, not a.no_source_check, not a.no_html,
                                           a.stage_budget, a.profile))
