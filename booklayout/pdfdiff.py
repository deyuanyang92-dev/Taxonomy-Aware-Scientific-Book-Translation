"""Layout regression: compare two PDFs word by word (text and bbox), or the current builder with git HEAD.

    python3 -m booklayout.pdfdiff old.pdf new.pdf [--tol 0.6]
    python3 -m booklayout.pdfdiff --vs-git HEAD --aligned a.json --figures figs --profile p.json [--tol 0.6]

Design 2026-11-26 C.4: same aligned.json, page count and words equal, every word box within
tolerance (pdftotext -bbox).  Exit 0 when OK, 1 on regression.  Real-book case that found the
Key Table row-height drift (T3b): Vol21 EN 48 pages, profile {"key_style": "table"}.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_WORD = re.compile(r'\s*<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*)</word>')


def words(pdf: str | Path) -> list[list[tuple]]:
    """Per page: [(text, xmin, ymin, xmax, ymax)] from `pdftotext -bbox`."""
    out = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    pages: list[list[tuple]] = []
    for line in out.splitlines():
        if line.strip().startswith("<page"):
            pages.append([])
        m = _WORD.match(line)
        if m and pages:
            pages[-1].append((m.group(5), *map(float, m.groups()[:4])))
    return pages


def compare(old: str | Path, new: str | Path, tol: float = 0.6) -> dict:
    """{ok, pages_old, pages_new, max_bbox, text_diff_pages, over_tol_pages}."""
    a, b = words(old), words(new)
    max_d, text_bad, over = 0.0, [], []
    for i, (x, y) in enumerate(zip(a, b), 1):
        if [w[0] for w in x] != [w[0] for w in y]:
            text_bad.append(i)
            continue
        d = max((abs(p[k] - q[k]) for p, q in zip(x, y) for k in range(1, 5)), default=0.0)
        max_d = max(max_d, d)
        if d > tol:
            over.append(i)
    ok = len(a) == len(b) and not text_bad and max_d <= tol
    return {"ok": ok, "pages_old": len(a), "pages_new": len(b), "max_bbox": round(max_d, 2),
            "text_diff_pages": text_bad, "over_tol_pages": over}


def _build(cwd: Path, args: argparse.Namespace, out: Path) -> Path:
    cmd = [sys.executable, "-m", "booklayout", "build", "--aligned", args.aligned, "--figures", args.figures,
           "--profile", args.profile, "--out", str(out / "x.docx"), "--pdf", "--no-cache"]
    if args.metadata:
        cmd += ["--metadata", args.metadata]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    pdfs = sorted(out.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"build failed in {cwd}:\n{r.stdout[-800:]}{r.stderr[-800:]}")
    return pdfs[0]


def vs_git(args: argparse.Namespace) -> dict:
    """Build the same input with the committed code (git archive of `rev`) and the working tree."""
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="bl_regress_") as tmp:
        head = Path(tmp) / "head"
        head.mkdir()
        tar = subprocess.run(["git", "archive", args.vs_git, "booklayout"], cwd=root, capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(head)], input=tar.stdout, check=True)
        (Path(tmp) / "o_old").mkdir()
        (Path(tmp) / "o_new").mkdir()
        old = _build(head, args, Path(tmp) / "o_old")
        new = _build(root, args, Path(tmp) / "o_new")
        return compare(old, new, args.tol)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="booklayout.pdfdiff", description=__doc__.split("\n")[0])
    ap.add_argument("pdfs", nargs="*", help="old.pdf new.pdf")
    ap.add_argument("--tol", type=float, default=0.6, help="max word-box difference in pt")
    ap.add_argument("--vs-git", metavar="REV", help="build with REV's booklayout and the working tree, then compare")
    ap.add_argument("--aligned")
    ap.add_argument("--figures")
    ap.add_argument("--profile")
    ap.add_argument("--metadata")
    args = ap.parse_args(argv)
    if args.vs_git:
        if not (args.aligned and args.figures and args.profile):
            ap.error("--vs-git needs --aligned --figures --profile")
        res = vs_git(args)
    elif len(args.pdfs) == 2:
        res = compare(args.pdfs[0], args.pdfs[1], args.tol)
    else:
        ap.error("give old.pdf new.pdf or --vs-git REV")
    print(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
