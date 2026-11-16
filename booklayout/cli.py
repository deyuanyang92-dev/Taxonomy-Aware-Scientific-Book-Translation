#!/usr/bin/env python3
"""booklayout command line interface.

Subcommands:
  build       aligned JSON + figure crops -> DOCX (optionally PDF)
  map-pages   rendered PDF + aligned JSON -> source/printed page map
  check       structural report for an aligned book package
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .builder import BookMeta, BookPaths, build, load_aligned, make_page_map


def _meta(args: argparse.Namespace) -> BookMeta:
    if getattr(args, "metadata", None):
        return BookMeta.from_json(args.metadata)
    return BookMeta(title=getattr(args, "title", "") or "Untitled")


def _write_json(path: Path | None, data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(data: dict, figures_dir: Path) -> dict:
    blocks = [b for p in data["pages"] for b in p["blocks"]]
    missing = [b for b in blocks if not (b.get("translation") or "").strip()]
    chapters: list[str] = []
    for page in data["pages"]:
        if page["chapter"] not in chapters:
            chapters.append(page["chapter"])
    figures = 0
    missing_crops: list[str] = []
    audit_path = figures_dir / "source_figure_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        rows = audit.get("figures", [])
        figures = len(rows)
        for row in rows:
            if not (figures_dir / row["crop"]).exists():
                missing_crops.append(row["crop"])
    return {
        "source_pages": len(data["pages"]),
        "blocks": len(blocks),
        "untranslated_blocks": len(missing),
        "chapters": chapters,
        "figures": figures,
        "missing_crops": missing_crops,
    }


def _convert_pdf(docx: Path, pdf_out: Path | None) -> Path:
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise SystemExit("libreoffice/soffice not found; cannot create PDF")
    target_dir = (pdf_out.parent if pdf_out else docx.parent).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [exe, "--headless", "--convert-to", "pdf", "--outdir", str(target_dir), str(docx.resolve())],
        capture_output=True,
        text=True,
    )
    produced = target_dir / (docx.stem + ".pdf")
    if proc.returncode != 0 or not produced.exists():
        raise SystemExit(f"PDF conversion failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if pdf_out and produced.resolve() != pdf_out.resolve():
        produced.replace(pdf_out)
    return pdf_out or produced


def cmd_build(args: argparse.Namespace) -> int:
    paths = BookPaths(
        aligned=args.aligned,
        figures_dir=args.figures,
        translation=args.translation,
    )
    meta = _meta(args)
    page_map: dict[str, int] = {}
    if args.map:
        page_map = json.loads(args.map.read_text(encoding="utf-8"))
    data = build(args.out, page_map, paths, meta)
    report = _report(data, args.figures)
    report.update({"out_docx": str(args.out), "page_map_entries": len(page_map)})
    pdf = None
    if args.pdf:
        pdf = _convert_pdf(args.out, args.pdf_out)
        report["out_pdf"] = str(pdf)
    _write_json(args.report, report)
    print(f"docx={args.out} source_pages={report['source_pages']} blocks={report['blocks']} "
          f"untranslated={report['untranslated_blocks']} figures={report['figures']}")
    if pdf:
        print(f"pdf={pdf}")
    return 0


def cmd_map_pages(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    meta = _meta(args)
    page_map = make_page_map(args.pdf, data, meta)
    _write_json(args.out, page_map)
    print(f"page_map={args.out} entries={len(page_map)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    problems: list[str] = []
    data = load_aligned(args.aligned)
    report = _report(data, args.figures)
    if report["untranslated_blocks"]:
        problems.append(f"{report['untranslated_blocks']} blocks have no translation")
    if report["missing_crops"]:
        problems.append(f"{len(report['missing_crops'])} figure crops are missing")
    if report["source_pages"] == 0:
        problems.append("aligned JSON has no pages")
    if args.pdf:
        try:
            import fitz

            doc = fitz.open(args.pdf)
            report["pdf_pages"] = len(doc)
            report["fallback_fonts"] = sorted(
                {font[3] for page in doc for font in page.get_fonts() if font[3] and "dejavu" in font[3].lower()}
            )
        except Exception as exc:  # pragma: no cover - environment specific
            problems.append(f"cannot read PDF: {exc}")
    report["problems"] = problems
    report["ok"] = not problems
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "problems": problems, "source_pages": report["source_pages"]},
                     ensure_ascii=False))
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="booklayout", description="Build a typeset book from aligned translation blocks.")
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build DOCX, optionally PDF")
    b.add_argument("--aligned", type=Path, required=True, help="aligned JSON with pages/blocks")
    b.add_argument("--figures", type=Path, required=True, help="figure directory containing source_figure_audit.json")
    b.add_argument("--translation", type=Path, help="reviewed Markdown with <!-- PDF p.N --> markers")
    b.add_argument("--metadata", type=Path, help="book metadata JSON (title, headers, chapter titles, front matter)")
    b.add_argument("--map", type=Path, help="page_map.json from a first pass")
    b.add_argument("--out", type=Path, required=True, help="output DOCX")
    b.add_argument("--pdf", action="store_true", help="convert DOCX to PDF with LibreOffice")
    b.add_argument("--pdf-out", type=Path, help="PDF path when --pdf is used")
    b.add_argument("--report", type=Path, help="write build_report.json")
    b.add_argument("--title", help="fallback title when --metadata is omitted")
    b.set_defaults(func=cmd_build)

    m = sub.add_parser("map-pages", help="map source printed pages to output PDF pages")
    m.add_argument("--pdf", type=Path, required=True)
    m.add_argument("--aligned", type=Path, required=True)
    m.add_argument("--metadata", type=Path)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--title")
    m.set_defaults(func=cmd_map_pages)

    c = sub.add_parser("check", help="check an aligned package and optional PDF")
    c.add_argument("--aligned", type=Path, required=True)
    c.add_argument("--figures", type=Path, required=True)
    c.add_argument("--pdf", type=Path)
    c.add_argument("--metadata", type=Path)
    c.add_argument("--out", type=Path)
    c.add_argument("--title")
    c.set_defaults(func=cmd_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
