#!/usr/bin/env python3
"""booklayout command line interface.

Subcommands:
  build            aligned JSON + figure crops -> DOCX (optionally PDF)
  map-pages        rendered PDF + aligned JSON -> source/printed page map
  check            structural report for an aligned book package
  qa               three deterministic reviews: structure, layout, text
  normalize        deterministic block repairs
  key-align        re-cut identification-key pages from the translated markdown
  backfill-source  restore source text and geometry lost in a page patch
  patch-blocks     block-level translation/role edits by block_id
  repair           replace selected pages from a declarative patch
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from . import audit as audit_module
from . import treatments as treatments_module
from . import builder as builder_module
from .builder import BookMeta, BookPaths, build, load_aligned, make_page_map
from .furniture import aligned_furniture_blocks
from .keyalign import align_document
from .keymarkers import lost_marker_pages
from .structure import uncertain_boundaries
from .quality import sha256_file
from .normalize import apply_block_edits, apply_page_patch, backfill_source, normalize_aligned


def _meta(args: argparse.Namespace) -> BookMeta:
    if getattr(args, "metadata", None):
        return BookMeta.from_json(args.metadata)
    return BookMeta(title=getattr(args, "title", "") or "Untitled")


def _current_umask() -> int:
    """Process umask without modifying it (Linux /proc; 0o022 fallback)."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("Umask:"):
                return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    return 0o022


def _write_json(path: Path | None, data: dict) -> None:
    """Atomic write: unique temp file in the target dir, then rename.

    A symlinked target is resolved first so the link itself is kept.
    """
    if path is None:
        return
    import os

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL temp file created 0o600 so content is never world-readable while
    # being written; the final mode is set before the rename (target's mode, or
    # 0o666 & ~umask for a new file; umask read without changing it).
    for n in range(100):
        tmp_name = str(path.parent / f".{path.name}.{os.getpid()}.{n}.tmp")
        try:
            fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise OSError(f"cannot create a temp file next to {path}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2))
        try:
            mode = path.stat().st_mode & 0o7777  # keep the target's mode
        except FileNotFoundError:
            mode = 0o666 & ~_current_umask()
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


_DOT_LEADER = re.compile(r"(?:\.\s*){4,}")
# A field label set in capitals ("ESPECIE TIPO:", "MATERIAL EXAMINADO:")
# is source-language prose, not a language-neutral citation string.
_SPANISH_LABEL = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ ]{3,}:")


def _is_rendered_page(page: dict, meta: "BookMeta") -> bool:
    """Whether the builder prints this source page in the finished book."""
    if page["page"] < meta.body_start_page:
        return False
    if meta.skip_after_page is not None and page["page"] >= meta.skip_after_page:
        return False
    return not (meta.index_chapter and page.get("chapter") == meta.index_chapter)


def _is_content_block(page: dict, block: dict, meta: "BookMeta | None" = None) -> bool:
    """Whether an empty block represents text a translator should have supplied.

    Contents lines, author lists in front matter, citation/reference strings,
    index fragments and appendix synonym entries are language-neutral or are
    generated from the page map, so an empty translation there is expected.

    A caption on a page that is actually rendered is different: the builder
    drops an untranslated caption and prints the figure bare, so an empty
    caption there is missing content and must fail the structural review.
    """
    role = block.get("role")
    if meta is not None and _is_rendered_page(page, meta):
        if role == "caption":
            return True
        if role == "citation" and _SPANISH_LABEL.match((block.get("text") or "").strip()):
            return True
    if role in {"caption", "citation", "ref", "index"}:
        return False
    if page.get("kind") == "appendix" and role == "entry":
        return False
    text = (block.get("text") or "").strip()
    if not re.search(r"[^\W\d_]", text):
        return False
    if page.get("kind") == "front":
        words = re.findall(r"[^\W\d_]{2,}", text)
        if (
            _DOT_LEADER.search(text)
            or len(words) < 5
            or re.match(r"^\d{1,4}\s+\S", text)
        ):
            return False
    return True


def _report(data: dict, figures_dir: Path, meta: BookMeta | None = None) -> dict:
    blocks = [b for p in data["pages"] for b in p["blocks"]]
    missing = [b for b in blocks if not (b.get("translation") or "").strip()]
    skip_after = meta.skip_after_page if meta is not None else None
    content_missing = [
        b
        for p in data["pages"]
        if not (skip_after is not None and p["page"] >= skip_after)
        for b in p["blocks"]
        if not (b.get("translation") or "").strip() and _is_content_block(p, b, meta)
    ]
    chapters: list[str] = []
    for page in data["pages"]:
        if page["chapter"] not in chapters:
            chapters.append(page["chapter"])
    bad_captions = [
        b.get("block_id") or b.get("text", "")[:50]
        for b in blocks
        if b.get("role") == "caption"
        and not re.match(rf"^(?:{builder_module.PROFILE.caption_prefixes})(?![A-Za-z])",
                         (b.get("translation") or b.get("text") or "").strip(), re.I)
    ]
    body_blocks = [
        b
        for p in data["pages"]
        if (meta is None or p["page"] >= meta.body_start_page)
        and not (skip_after is not None and p["page"] >= skip_after)
        for b in p["blocks"]
    ]
    long_headings = [
        b.get("block_id") or b.get("text", "")[:50]
        for b in body_blocks
        if b.get("role") == "heading"
        and len(re.findall(r"[A-Za-z]{2,}", b.get("translation") or "")) > 20
    ]
    inline_acknowledgments = [
        b.get("block_id") or b.get("text", "")[:50]
        for b in body_blocks
        if b.get("role") in {"heading", "body"}
        and re.match(r"^Acknowledg(?:e)?ments\b\s+\S", b.get("translation") or "", re.I)
    ]
    all_caps_body = [
        b.get("block_id") or b.get("text", "")[:50]
        for b in body_blocks
        if b.get("role") == "body"
        and not (b.get("text") or "").lstrip().startswith("*")  # credit footnote: author surnames are caps in the source
        and len(re.findall(r"[A-Za-z]", b.get("translation") or "")) >= 40
        and sum(c.isupper() for c in b.get("translation") or "") / max(
            1, sum(c.isalpha() for c in b.get("translation") or "")) > 0.9
    ]
    # An empty synonym-list entry is dropped by the builder, so it is lost
    # text even though the citation itself is language-neutral.  The entries
    # are filled from source by normalize; this check keeps a regression
    # from slipping through as "nothing to translate".
    empty_appendix_entries = [
        b.get("block_id") or b.get("text", "")[:50]
        for b in body_blocks
        if b.get("role") == "entry"
        and not (b.get("translation") or "").strip()
        and (b.get("text") or "").strip()
    ]
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
        "untranslated_content_blocks": len(content_missing),
        "untranslated_nonprose_blocks": len(missing) - len(content_missing),
        "chapters": chapters,
        "figures": figures,
        "missing_crops": missing_crops,
        "bad_captions": bad_captions,
        "long_headings": long_headings,
        "inline_acknowledgments": inline_acknowledgments,
        "all_caps_body": all_caps_body,
        "empty_appendix_entries": empty_appendix_entries,
        "lost_markers": lost_marker_pages(data),
        "uncertain_boundaries": uncertain_boundaries(data),
        "furniture_blocks": aligned_furniture_blocks(data),
    }


def _convert_pdf(docx: Path, pdf_out: Path | None) -> Path:
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise SystemExit("libreoffice/soffice not found; cannot create PDF")
    target_dir = (pdf_out.parent if pdf_out else docx.parent).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lo-profile-") as profile:
        # Concurrent builds shared one LibreOffice profile and one of them
        # silently failed.  A per-process profile makes parallel builds safe.
        proc = subprocess.run(
            [exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
             "--convert-to", "pdf", "--outdir", str(target_dir), str(docx.resolve())],
            capture_output=True,
            text=True,
        )
    produced = target_dir / (docx.stem + ".pdf")
    if proc.returncode != 0 or not produced.exists():
        raise SystemExit(f"PDF conversion failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if pdf_out and produced.resolve() != pdf_out.resolve():
        produced.replace(pdf_out)
    return pdf_out or produced


def _require_figure_audit(figures_dir: Path) -> None:
    """Fail fast when --figures points somewhere without the audit file.

    A wrong path used to build a book with no illustrations and still pass
    check, because a missing audit was silently read as zero figures.
    """
    if not (figures_dir / "source_figure_audit.json").is_file():
        raise SystemExit(
            f"figure directory has no source_figure_audit.json: {figures_dir}"
        )


def cmd_build(args: argparse.Namespace) -> int:
    _require_figure_audit(args.figures)
    if args.pilot:
        from .acceptance import pilot_problems
        bad = pilot_problems(json.loads(args.pilot.read_text(encoding="utf-8")), args.aligned)
        if bad:
            print("pilot gate failed: " + "; ".join(bad), file=sys.stderr)
            return 5
    draft_reasons: list[str] = []
    if args.release_acceptance:
        from .acceptance import verify_acceptance
        draft_reasons = verify_acceptance(
            json.loads(args.release_acceptance.read_text(encoding="utf-8")), args.aligned)
        if draft_reasons:
            args.out = args.out.with_name(args.out.stem + ".DRAFT" + args.out.suffix)
            if args.pdf_out:
                args.pdf_out = args.pdf_out.with_name(args.pdf_out.stem + ".DRAFT" + args.pdf_out.suffix)
    paths = BookPaths(
        aligned=args.aligned,
        figures_dir=args.figures,
        translation=args.translation,
    )
    meta = _meta(args)
    page_map: dict[str, int] = {}
    if args.map:
        page_map = json.loads(args.map.read_text(encoding="utf-8"))
    key_breaks: set[str] | None = None
    if args.key_breaks:
        payload = json.loads(args.key_breaks.read_text(encoding="utf-8"))
        breaks = payload.get("breaks")
        if isinstance(breaks, list):
            key_breaks = {str(item) for item in breaks}
    from .builder import apply_profile
    from .profile import StyleProfile, validate_aligned

    profile = StyleProfile.from_file(args.profile) if args.profile else StyleProfile()
    apply_profile(profile)
    schema_errors = validate_aligned(load_aligned(args.aligned))
    if schema_errors and args.strict_schema:
        print("aligned schema errors: " + "; ".join(schema_errors[:10]), file=sys.stderr)
        return 6
    from . import buildcache

    use_cache = not getattr(args, "no_cache", False)
    key = buildcache.input_key(
        [args.aligned, args.translation, args.metadata, args.map, args.key_breaks, args.profile],
        [args.figures],
        {"out": str(args.out), "title": getattr(args, "title", None)},
    ) if use_cache else ""
    cached = buildcache.docx_hit(args.out, key) if use_cache else None
    if cached is not None:
        report = dict(cached)
        print(f"docx cache hit, skipped build: {args.out}")
    else:
        data = build(args.out, page_map, paths, meta, key_breaks)
        report = _report(data, args.figures, meta)
        if use_cache:
            buildcache.record_docx(args.out, key, report)
    report.update({"profile": profile.name, "profile_sha256": profile.sha256(),
                   "schema_errors": schema_errors})
    report.update({"out_docx": str(args.out), "page_map_entries": len(page_map),
                   "release_status": ("release" if args.release_acceptance and not draft_reasons
                                      else "draft"),
                   "draft_reasons": draft_reasons})
    pdf = None
    if args.pdf:
        target_pdf = args.pdf_out or args.out.with_suffix(".pdf")
        if use_cache and buildcache.pdf_hit(args.out, target_pdf):
            pdf = target_pdf
            print(f"pdf cache hit, skipped LibreOffice: {pdf}")
        else:
            pdf = _convert_pdf(args.out, args.pdf_out)
            if use_cache:
                buildcache.record_pdf(args.out, pdf)
        report["out_pdf"] = str(pdf)
    _write_json(args.report, report)
    print(f"docx={args.out} source_pages={report['source_pages']} blocks={report['blocks']} "
          f"untranslated={report['untranslated_blocks']} "
          f"content_missing={report['untranslated_content_blocks']} figures={report['figures']}")
    if pdf:
        print(f"pdf={pdf}")
    if draft_reasons:
        print("DRAFT, release refused: " + "; ".join(draft_reasons), file=sys.stderr)
        return 4
    return 0


def cmd_restyle(args: argparse.Namespace) -> int:
    """Re-apply the heading styles of a profile to a finished DOCX (no re-typesetting)."""
    import time

    from docx import Document

    from .builder import apply_profile, define_heading_styles
    from .profile import StyleProfile

    t0 = time.time()
    prof = StyleProfile.from_file(args.profile)
    apply_profile(prof)
    doc = Document(str(args.docx))
    define_heading_styles(doc, prof)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.out))
    t_docx = time.time() - t0
    msg = f"restyled={args.out} docx_s={t_docx:.2f}"
    if args.pdf:
        _convert_pdf(args.out, args.pdf_out)
        msg += f" total_s={time.time() - t0:.2f}"
    if args.html:
        from .htmlout import docx_to_html
        docx_to_html(args.out, args.html, prof)
        msg += f" html={args.html}"
    print(msg)
    return 0


def cmd_html(args: argparse.Namespace) -> int:
    from .builder import apply_profile
    from .htmlout import docx_to_html
    from .profile import StyleProfile

    prof = StyleProfile.from_file(args.profile)
    apply_profile(prof)
    print(docx_to_html(args.docx, args.out, prof, args.title or ""))
    return 0


def cmd_map_pages(args: argparse.Namespace) -> int:
    if getattr(args, "profile", None):
        from .builder import apply_profile
        from .profile import StyleProfile
        apply_profile(StyleProfile.from_file(args.profile))
    data = load_aligned(args.aligned)
    meta = _meta(args)
    page_map = make_page_map(args.pdf, data, meta)
    _write_json(args.out, page_map)
    print(f"page_map={args.out} entries={len(page_map)}")
    return 0


def _spacing_problems(words: list[tuple], width: float) -> tuple[list[dict], list[dict]]:
    """Measure justified-line looseness and text outside the measure.

    The Spanish original is justified and its own tail has lines with 6-7 pt
    gaps, so a threshold near the normal space width would flag hundreds of
    source-faithful lines.  Only the visible tail (median gap > 6 pt or a
    single gap > 8 pt) is reported; it is kept as an audit list rather than a
    delivery failure.
    """
    lines: dict[tuple[int, int], list[tuple]] = {}
    for word in words:
        lines.setdefault((word[5], word[6]), []).append(word)
    tail: list[dict] = []
    for line in lines.values():
        line.sort(key=lambda word: word[0])
        if len(line) < 8:
            continue
        gaps = [line[i + 1][0] - line[i][2] for i in range(len(line) - 1)]
        ordered = sorted(gaps)
        median = ordered[len(ordered) // 2]
        biggest = max(gaps)
        if (median > 6 or biggest > 8) and line[-1][2] > width - 60:
            tail.append({"gap_pt": round(biggest, 1), "median_pt": round(median, 1),
                         "line": " ".join(word[4] for word in line)[:90]})
    overflow = [
        {"x0": round(word[0], 1), "x1": round(word[2], 1), "word": word[4]}
        for word in words if word[2] > width - 40 or word[0] < 40
    ]
    return tail, overflow


_KEY_START = re.compile(r"^(?:•|\d{1,2}\.)$")
_KEY_COUPLET = re.compile(r"^(?:•|\d{1,2}\.)")
_LEADER_TOKEN = re.compile(r"^[.…·]+$")
_TARGET_END = re.compile(r"\(p\.\s*\d+\)\s*$")
_NUMBER_END = re.compile(r"(?:…|\.\s*\.)\s*\d{1,3}\s*$")
MIN_KEY_LEADER_MM = 40.0
MIN_KEY_LEADER_PT = MIN_KEY_LEADER_MM * 72 / 25.4
_DOT_RUN = re.compile(r"(?:[.·…]\s*){2,}")


def _key_span_lines(page, clip) -> list[dict]:
    """Line text plus the dot-leader spans, which Word keeps as own spans.

    Word geometry alone is unreliable for leaders: PyMuPDF can merge
    "pinnule..T." into one word, so a dots-only span is the better evidence.
    """
    payload = page.get_text("dict", clip=clip)
    lines: list[dict] = []
    for block_no, block in enumerate(payload["blocks"]):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", [])
                     if span.get("text", "").strip()]
            if not spans:
                continue
            leaders = [
                span for span in spans
                if re.fullmatch(r"[\s.·…]+", span["text"])
                and len(re.findall(r"[.·…]", span["text"])) >= 2
            ]
            lines.append({
                "text": "".join(span["text"] for span in spans),
                "block": block_no,
                "leaders": leaders,
            })
    return lines


def _key_short_leaders(page, clip) -> list[dict]:
    """Couplets whose rendered leader is shorter than MIN_KEY_LEADER_MM."""
    lines = _key_span_lines(page, clip)
    key_blocks = {line["block"] for line in lines
                  if re.match(r"^(?:•|\d{1,2}\.)", line["text"])}
    problems: list[dict] = []
    for line in lines:
        if line["block"] not in key_blocks or not line["leaders"]:
            continue
        if not _TARGET_END.search(line["text"]):
            continue
        width = (max(span["bbox"][2] for span in line["leaders"])
                 - min(span["bbox"][0] for span in line["leaders"]))
        if width < MIN_KEY_LEADER_PT:
            problems.append({"reason": "short leader",
                             "leader_mm": round(width * 25.4 / 72, 1),
                             "minimum_mm": MIN_KEY_LEADER_MM,
                             "line": line["text"][:90]})
    return problems


def _auto_hyphenation(fragment: str, following: str) -> bool:
    """True when a line-end hyphen could come from automatic hyphenation.

    "narrow-hooded" is a real compound and may break at its own hyphen;
    "Redrawn" has no hyphen in the source and only breaks there because the
    typesetter hyphenated it.  A hyphenation dictionary distinguishes the
    two.  Without pyphen, fall back to the short prefixes that auto
    hyphenation commonly produces.
    """
    if not re.match(r"[A-Za-z]+", following):
        return False
    # A hyphenation dictionary cannot tell "narrow-hooded" (a real compound)
    # from a word that the typesetter broke at the same letters.  Automatic
    # hyphenation is disabled for captions in the builder, so the check only
    # needs the short prefixes that show up when a viewer ignores that flag.
    return fragment.lower() in {
        "re", "un", "pre", "dis", "mis", "non", "co", "de", "in",
    }


def _key_layout_problems(words: list[tuple], width: float) -> list[dict]:
    """Check every couplet on a key page, not only lines with leaders.

    A page is a key page when at least two lines start with a couplet marker
    (bullet or number) and carry a target or leader.  That test is local to
    the page, so keys are found even when the running head omits "Key to".
    Bibliography lines on a key page start with a species name, not a marker,
    and are ignored.

    Defects: a target that is not at the right edge (inline or orphaned page
    reference), a target split off without a leader line, a leader run
    shorter than MIN_KEY_LEADER_MM (reads as an ellipsis), and a leader with
    no target on the following line.
    """
    lines: dict[tuple[int, int], list[tuple]] = {}
    for word in words:
        lines.setdefault((word[5], word[6]), []).append(word)
    ordered = [line for line in lines.values() if line]
    for line in ordered:
        line.sort(key=lambda word: word[0])
    ordered.sort(key=lambda line: (line[0][5], line[0][6]))

    def text_of(line: list[tuple]) -> str:
        return " ".join(word[4] for word in line)

    def starts_key(line: list[tuple]) -> bool:
        return bool(_KEY_START.match(line[0][4]) or starts_leader(line))

    def starts_leader(line: list[tuple]) -> bool:
        # PyMuPDF may merge the first dot run and the target into one token
        # ("..........Torrea"); test the token prefix, not the whole token.
        return bool(_LEADER_TOKEN.match(line[0][4]) or _DOT_RUN.match(line[0][4]))

    def has_leader(line: list[tuple]) -> bool:
        return any(_LEADER_TOKEN.match(word[4]) for word in line)

    keyish = [
        line for line in ordered
        if starts_key(line) and (
            _TARGET_END.search(text_of(line)) or _NUMBER_END.search(text_of(line))
            or has_leader(line)
        )
    ]
    if len(keyish) < 2:
        return []
    rights = [line[-1][2] for line in ordered
              if len(line) >= 3 and line[-1][2] > width * 0.5]
    right = max(rights, default=width - 51)

    problems: list[dict] = []
    # A couplet whose left text wraps continues in the same block without a
    # marker; its target still must be led and flush right.  Treat every line
    # of a block that contains a couplet marker as key text, so those wrapped
    # targets are checked too.
    key_blocks = {line[0][5] for line in ordered if _KEY_START.match(line[0][4])}
    for index, line in enumerate(ordered):
        if line[0][5] not in key_blocks:
            continue
        text = text_of(line)
        leaders = [i for i, word in enumerate(line) if _LEADER_TOKEN.match(word[4])]
        target = _TARGET_END.search(text)
        number = _NUMBER_END.search(text)
        if target or number:
            if line[-1][2] < right - 12:
                problems.append({"reason": "target not flush right",
                                 "x1": round(line[-1][2], 1), "right": round(right, 1),
                                 "line": text[:90]})
            if target and leaders:
                last = leaders[-1]
                first = last
                while first > 0 and _LEADER_TOKEN.match(line[first - 1][4]):
                    first -= 1
                span = line[last][2] - line[first][0]
                if span < MIN_KEY_LEADER_PT:
                    problems.append({
                        "reason": "short leader",
                        "leader_mm": round(span * 25.4 / 72, 1),
                        "minimum_mm": MIN_KEY_LEADER_MM,
                        "line": text[:90]})
            gaps = [line[i + 1][0] - line[i][2] for i in range(len(line) - 1)]
            # Issue #35: the name column and the target column are separated
            # on purpose.  When the line has a leader to the name column, the
            # single widest gap after that leader is the column gap.
            if leaders and leaders[-1] + 2 < len(gaps):
                after = gaps[leaders[-1] + 1:]
                gaps = gaps[: leaders[-1] + 1] + sorted(after)[:-1]
            if gaps and max(gaps) > 15:
                problems.append({"reason": "wide gaps",
                                 "gap_pt": round(max(gaps), 1), "line": text[:90]})
            continue
        if not starts_key(line):
            continue
        same_block = index + 1 < len(ordered) and ordered[index + 1][0][5] == line[0][5]
        following = ordered[index + 1] if same_block else None
        if has_leader(line) and _LEADER_TOKEN.match(line[-1][4]):
            if following and _TARGET_END.search(text_of(following)):
                continue  # wrapped target on its own leader line is legitimate
            problems.append({"reason": "leader without target",
                             "x1": round(line[-1][2], 1), "line": text[:90]})
            continue
        if following and min(following[0][3], line[0][3]) - max(following[0][1], line[0][1]) > 0.5 * (line[0][3] - line[0][1]):
            continue  # name column and target column of one visual row (issue #35 layout)
        if following and _TARGET_END.search(text_of(following)) \
                and not starts_leader(following) \
                and not _DOT_RUN.search(text_of(following)):
            problems.append({
                "reason": "target split from couplet (no leader line)",
                "line": text[-80:] + " / " + text_of(following)[:60]})
    return problems


def _pdf_layout_problems(pdf: Path) -> dict:
    """Catch blank pages, captions set against figures, and stretched lines."""
    import fitz

    doc = fitz.open(pdf)
    blank: list[int] = []
    tight: list[dict] = []
    stretched: list[dict] = []
    overflow: list[dict] = []
    key_layout: list[dict] = []
    captions_hyphenated: list[dict] = []
    for index, page in enumerate(doc, start=1):
        width, height = page.rect.width, page.rect.height
        body_clip = fitz.Rect(0, 50, width, height - 45)
        page_dict = page.get_text("dict", clip=body_clip)
        text_blocks = [b for b in page_dict["blocks"] if b.get("type") == 0]
        image_rects = [fitz.Rect(b["bbox"]) for b in page_dict["blocks"]
                       if b.get("type") == 1]
        body_blocks = [
            b for b in text_blocks
            if "".join(span.get("text", "") for line in b.get("lines", [])
                       for span in line.get("spans", [])).strip()
        ]
        words = page.get_text("words", clip=body_clip)
        page_tail, page_overflow = _spacing_problems(words, width)
        for item in page_tail:
            stretched.append({"page": index, **item})
        for item in page_overflow:
            overflow.append({"page": index, **item})
        for item in _key_layout_problems(words, width):
            key_layout.append({"page": index, **item})
        for item in _key_short_leaders(page, body_clip):
            key_layout.append({"page": index, **item})
        caption_blocks = []
        for block in body_blocks:
            text = " ".join(span.get("text", "") for line in block.get("lines", [])
                            for span in line.get("spans", [])).strip()
            if re.match(r"^(?:Fig|Table|Plate|L[aá]m)\b", text, re.I):
                caption_blocks.append((block, text))
                lines = [
                    "".join(span.get("text", "") for span in line.get("spans", []))
                    for line in block.get("lines", [])
                ]
                for current, following in zip(lines, lines[1:]):
                    if not current.rstrip().endswith(("-", "­", "‐")):
                        continue
                    if not following[:1].islower():
                        continue
                    # A real compound such as "narrow-hooded" may break at its
                    # own hyphen; that is not a typesetting defect.  Automatic
                    # hyphenation splits a whole word and leaves a short prefix
                    # such as "Re-".  Old PDFs used U+00AD, which the ASCII
                    # check missed.
                    fragment = current.rstrip().rstrip("-­‐").rsplit(None, 1)[-1]
                    if _auto_hyphenation(fragment, following):
                        captions_hyphenated.append({
                            "page": index,
                            "line": (current[-60:] + " / " + following[:40]).strip(),
                        })
                        break
        if not body_blocks:
            # A page with neither body text nor an image is a production blank.
            if not image_rects:
                blank.append(index)
            continue
        if not caption_blocks:
            continue
        for block, text in caption_blocks:
            top, left, right = block["bbox"][1], block["bbox"][0], block["bbox"][2]
            above = [r for r in image_rects
                     if r.y1 <= top + 6 and r.x0 < right and r.x1 > left]
            if not above:
                continue
            gap = top - max(r.y1 for r in above)
            if gap < 10:
                tight.append({"page": index, "gap_pt": round(gap, 1),
                              "caption": text[:80]})
    return {"blank_pages": blank, "tight_caption_gaps": tight,
            "body_spacing_tail": stretched, "overflow_words": overflow,
            "key_layout": key_layout,
            "caption_word_breaks": captions_hyphenated}


_REF_LINE = re.compile(r"^(.*?)\.{3,}\s*(\d{1,3}(?:\s*,\s*\d{1,3})*)\s*$")


def _reference_problems(pdf: Path, meta: BookMeta) -> dict:
    """Check that contents and index page numbers land on the cited entry."""
    import fitz

    doc = fitz.open(pdf)

    def norm(text: str) -> str:
        # LibreOffice may print ﬁ/ﬂ ligatures for plain "fi"/"fl" in the data.
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\xad", "").replace("‑", "-")
        text = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", text)
        return re.sub(r"\s+", " ", text).strip().lower()

    texts = [norm(page.get_text("text")) for page in doc]
    wrong: list[dict] = []
    checked = 0

    def lands_on(page_no: int, words: list[str]) -> bool:
        if not (1 <= page_no <= len(texts)) or not words:
            return True
        target = texts[page_no - 1].replace("-", "")
        return all(re.search(r"\b" + re.escape(word.replace("-", "")) + r"\b", target)
                   for word in words)

    def scan(pages: list[int], title: str, kind: str, stop: set[str]) -> int:
        nonlocal checked
        count = 0
        for index in pages:
            for line in doc[index].get_text("text").splitlines():
                match = _REF_LINE.match(line.strip())
                if not match:
                    continue
                left = match.group(1).strip()
                words = [w for w in re.findall(r"[^\W\d_]{4,}", left.lower().replace("-", ""))
                         if w not in stop]
                if not words:
                    continue
                for number in re.findall(r"\d{1,3}", match.group(2)):
                    checked += 1
                    count += 1
                    if not lands_on(int(number), words):
                        wrong.append({"section": title, "kind": kind, "page": index + 1,
                                      "entry": left[:70], "ref": int(number)})
        return count

    contents_stop = {"contents", "family", "genus", "species", "index", "names",
                     "list", "appendix", "annex", "alphabetical", "taxonomic"}
    for i, text in enumerate(texts):
        lines = [line.strip().upper() for line in doc[i].get_text("text").splitlines()[:5]]
        if any(meta.contents_title.upper() in line for line in lines):
            scan([i], "contents", "contents", contents_stop)
            break
    index_start = next((i for i in range(len(texts) - 1, -1, -1)
                        if meta.index_title.lower() in texts[i]), None)
    if index_start is not None:
        scan(list(range(index_start, len(texts))), "index", "index",
             {"type", "species", "inquirenda", "see", "figure", "plate"})
    return {"wrong_page_refs": wrong, "page_refs_checked": checked}


def _text_qa(data: dict, meta: BookMeta | None = None) -> dict:
    """Third review: repeated or implausibly short translated paragraphs."""
    from collections import Counter

    skip_after = meta.skip_after_page if meta is not None else None

    def is_index_page(page: dict) -> bool:
        chapter = page.get("chapter") or ""
        if meta is not None and meta.index_chapter:
            return chapter == meta.index_chapter
        return page.get("kind") == "index" or "index" in chapter.lower()

    blocks = [
        (p["page"], b)
        for p in data["pages"]
        if (meta is None or p["page"] >= meta.body_start_page)
        and not (skip_after is not None and p["page"] >= skip_after)
        and not is_index_page(p)
        for b in p["blocks"]
        if b.get("role") == "body" and (b.get("translation") or "").strip()
    ]
    # Only repeated paragraphs on the same page are layout errors.  Boilerplate
    # such as "Description compiled from ..." recurs legitimately across pages,
    # so a book-wide duplicate count produces false positives.
    normalized = [(page, re.sub(r"\s+", " ", b["translation"]).strip()) for page, b in blocks]
    counts = Counter((page, t) for page, t in normalized if len(t) >= 80)
    duplicates = [
        {"page": page, "count": count, "text": text[:160]}
        for (page, text), count in counts.items() if count > 1
    ]
    short = []
    for page, block in blocks:
        source = re.sub(r"\s+", " ", block.get("text") or "").strip()
        translation = re.sub(r"\s+", " ", block.get("translation") or "").strip()
        if len(source) >= 120 and len(translation) < 0.25 * len(source):
            short.append({"page": page, "block_id": block.get("block_id"),
                          "source_chars": len(source), "translation_chars": len(translation)})
    page_blocks: dict[int, list[dict]] = {}
    for page in data["pages"]:
        page_blocks.setdefault(page["page"], []).extend(page["blocks"])

    def next_body(page: int, block: dict) -> dict | None:
        """Next translated body block on the same page, if any."""
        siblings = page_blocks.get(page, [])
        try:
            position = next(i for i, b in enumerate(siblings) if b is block)
        except StopIteration:
            return None
        for later in siblings[position + 1:]:
            if (later.get("translation") or "").strip() and later.get("role") == "body":
                return later
        return None

    def split_mid_sentence(page: int, block: dict) -> bool:
        """True when the next block on the page resumes the same sentence.

        A block that is last on its page ends at the page boundary, where a
        missing full stop is normal typography.  A colon usually introduces a
        list or a citation, whose items may start with a capital letter.
        """
        later = next_body(page, block)
        if later is None:
            return False
        ending = block["translation"].strip()
        following = (later.get("translation") or "").strip()
        if ending.endswith((",", ";")):
            return bool(re.match(r"^[a-z(]", following))
        if re.search(r"\b(?:and|or|of|the|to|with|in|by|for)$", ending, re.I):
            return bool(re.match(r"^[a-z(]", following))
        return False

    truncated = [
        {"page": page, "block_id": block.get("block_id"),
         "ending": block["translation"].strip()[-40:]}
        for page, block in blocks
        if split_mid_sentence(page, block)
    ]
    # A citation or name entry must not absorb a morphological description.
    # This is the failure mode behind the broken Dinophilus / Aberranta pages:
    # the page translation was shifted by one block and a short citation block
    # received the next paragraph.  Length alone does not catch it reliably, so
    # look for descriptive vocabulary in roles that should only hold a name or
    # a bibliographic reference.
    descriptive = re.compile(
        r"\b(?:Body|Prostomium|Peristomium|Pygidium|Setigers?|Parapodi\w*|"
        r"Chaetae|Setae|Mandibles?|Maxillae|Antennae|Species|Distribution|Biology)\b"
    )
    key_in_body = []
    for page, block in blocks:
        source = re.sub(r"\s+", " ", block.get("text") or "")
        translation = re.sub(r"\s+", " ", block.get("translation") or "").strip()
        if re.search(r"…{4,}|\.{8,}", translation) or (
                re.search(r"\bKey to (?:species|genera)\b", translation, re.I)
                and not re.search(r"\bClave\b", source, re.I)):
            key_in_body.append({"page": page, "block_id": block.get("block_id"),
                                "text": translation[:160]})
    role_suspects = []
    for page in data["pages"]:
        if meta is not None and page["page"] < meta.body_start_page:
            continue
        if skip_after is not None and page["page"] >= skip_after:
            continue
        for block in page["blocks"]:
            role = block.get("role")
            if role not in {"citation", "entry"}:
                continue
            text = re.sub(r"\s+", " ", block.get("translation") or "").strip()
            words = len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", text))
            if words >= 50 and descriptive.search(text):
                role_suspects.append({
                    "page": page["page"], "block_id": block.get("block_id"),
                    "role": role, "words": words, "text": text[:160],
                })
    # Key text leaking into a non-key role is printed with the wrong style and
    # almost always means the page translation was split at the wrong block
    # boundary.  Dense key pages are one translation run, so this check is the
    # cheapest way to catch a shifted key/citation boundary.
    leaders = re.compile(r"…{4,}|(?:\.\s*){8,}")
    key_outside = []
    citation_no_year = []
    entry_no_year = []
    heading_mismatch = []
    leading_punct = []
    doubled_words = re.compile(
        r"\b(in|of|to|for|by|with|on|at|the|and|a)\s+\1\b", re.I
    )
    stray_pair = re.compile(r"\b(?:in|of|to|for|by|on|at)\s+with\b", re.I)
    # Spanish status formulas survive in the synonym list because the
    # citation around them is language-neutral.  The phrase list is specific
    # enough not to match Spanish proper names or bibliography titles.
    spanish_phrase = re.compile(
        r"\b(?:grafía(?: posterior| original| original alternativa)? incorrecta|"
        r"nombre de reemplazo(?: injustificado)?|no disponible|no publicado|"
        r"obra suprimida|colocado en la Lista|Nombres de Nivel|"
        r"Lista Oficial de Nombres|Solo se incluyen|se incluyen las denominaciones|"
        r"por designación presente|Especie Tipo|Clave de especies|"
        r"suprimida ICZN)\b",
        re.I,
    )
    function_word_pairs = []
    spanish_residue = []
    for page in data["pages"]:
        if meta is not None and page["page"] < meta.body_start_page:
            continue
        if skip_after is not None and page["page"] >= skip_after:
            continue
        if is_index_page(page):
            continue
        for block in page["blocks"]:
            role = block.get("role")
            translation = re.sub(r"\s+", " ", block.get("translation") or "").strip()
            source = re.sub(r"\s+", " ", block.get("text") or "").strip()
            if not translation:
                continue
            if role != "key" and leaders.search(translation):
                key_outside.append({
                    "page": page["page"], "block_id": block.get("block_id"),
                    "role": role, "text": translation[:160],
                })
            if role == "citation":
                years = set(re.findall(r"\b(?:1[6-9]\d\d|20\d\d)\b", source))
                if years and not any(y in translation for y in years):
                    citation_no_year.append({
                        "page": page["page"], "block_id": block.get("block_id"),
                        "text": translation[:160],
                    })
            if role == "entry":
                # A synonym-list entry is a citation: every year of the source
                # line must survive.  A missing year means the aligner paired
                # the entry with a neighbouring line.
                entry_years = re.findall(r"\b(?:1[6-9]\d\d|20\d\d)\b", source)
                missing = [year for year in entry_years if year not in translation]
                if missing:
                    entry_no_year.append({
                        "page": page["page"], "block_id": block.get("block_id"),
                        "missing": missing, "text": translation[:160],
                    })
            if role == "heading":
                m = re.match(
                    r"(?:G[eé]nero|Subg[eé]nero|Familia|Subfamilia|Especie)\s+"
                    r"([A-Z][A-Za-z-]{2,})", source)
                # "Especie Tipo:" / "Species Type:" is a field label, not a
                # taxon name; the following block carries the real heading.
                if m and m.group(1).lower() in {"tipo", "type", "especie", "species"}:
                    m = None
                if m and m.group(1).lower() not in translation.lower():
                    heading_mismatch.append({
                        "page": page["page"], "block_id": block.get("block_id"),
                        "name": m.group(1), "text": translation[:160],
                    })
            if role == "body" and translation[:1] in ",;.:)]":
                leading_punct.append({
                    "page": page["page"], "block_id": block.get("block_id"),
                    "text": translation[:160],
                })
            # A page-break join can duplicate or mis-pair a function word
            # ("ending posteriorly in" + "with a short pointed end").  The
            # result is ungrammatical and invisible to role and length checks.
            pair = doubled_words.search(translation) or stray_pair.search(translation)
            if pair is not None:
                function_word_pairs.append({
                    "page": page["page"], "block_id": block.get("block_id"),
                    "pair": pair.group(0), "text": translation[:160],
                })
            # Only roles that print as running English prose are checked;
            # reference titles may legitimately be in Spanish.
            if role in {"body", "entry", "heading", "caption", "note"}:
                residue = spanish_phrase.search(translation)
                if residue is not None:
                    spanish_residue.append({
                        "page": page["page"], "block_id": block.get("block_id"),
                        "role": role, "phrase": residue.group(0),
                        "text": translation[:160],
                    })
    return {
        "duplicate_paragraphs": duplicates,
        "short_translations": short,
        "truncated_endings": truncated,
        "role_suspects": role_suspects,
        "key_text_in_body": key_in_body,
        "key_text_outside_key": key_outside,
        "citation_year_missing": citation_no_year,
        "entry_year_missing": entry_no_year,
        "heading_name_missing": heading_mismatch,
        "body_leading_punctuation": leading_punct,
        "function_word_pairs": function_word_pairs,
        "spanish_residue": spanish_residue,
        "checked_body_blocks": len(blocks),
    }


def _delivery_problems(data: dict, pdf: str | None) -> dict:
    """Added 2026-11-23 after Fauna Iberica Vol. 21: key couplets vanished.

    Hard checks that ok:true must never skip: key pages carrying blocks the
    builder cannot print, targets cut off from their couplet, hand-broken
    lines inside justified text, and printed blocks that are absent from the PDF.
    """
    from .keyfix import repair_key_page

    repaired: list[dict] = []
    orphans: list[dict] = []
    manual_breaks: list[dict] = []
    expected: list[tuple[int, str]] = []
    for page in data.get("pages", []):
        _, counts = repair_key_page(page)
        if counts["index_to_key"] or counts["targets_merged"]:
            repaired.append({"page": page["page"], **counts})
        if counts["orphan_targets"]:
            orphans.append({"page": page["page"], "count": counts["orphan_targets"]})
        for block in page.get("blocks", []):
            tr = (block.get("translation") or "").strip()
            if block.get("role") in ("body", "caption", "note") and "\n" in tr:
                manual_breaks.append({"page": page["page"], "text": tr[:80]})
            if block.get("role") in ("body", "caption", "heading", "key") and len(tr) >= 24:
                expected.append((page["page"], tr))
    missing: list[dict] = []
    literal_tags: list[dict] = []
    if pdf:
        try:
            import fitz

            with fitz.open(pdf) as doc:
                blob = "".join(page.get_text() for page in doc)
            def squeeze(s: str) -> str:  # drop spaces, marks, half/full-width punctuation
                return re.sub(r"[\W_]+", "", s)

            for m in re.finditer(r".{0,25}</?(?:sup|sub|i|b|em)>.{0,10}", blob):
                literal_tags.append({"text": m.group(0)})
            blob = squeeze(blob)
            for number, tr in expected:
                probe = squeeze(tr)[:14]
                if probe and probe not in blob:
                    missing.append({"page": number, "text": tr[:60]})
        except Exception:  # pragma: no cover - PDF reader unavailable
            pass
    return {"key_repaired_pages": repaired, "key_orphan_targets": orphans,
            "manual_line_breaks": manual_breaks, "blocks_missing_in_pdf": missing,
            "literal_markup_in_pdf": literal_tags}


def cmd_qa(args: argparse.Namespace) -> int:
    """Run the three deterministic reviews used before delivery."""
    _require_figure_audit(args.figures)
    data = load_aligned(args.aligned)
    meta = _meta(args)
    report = _report(data, args.figures, meta)
    structure_problems = []
    if report["untranslated_content_blocks"]:
        structure_problems.append(f"{report['untranslated_content_blocks']} content blocks have no translation")
    if report["missing_crops"]:
        structure_problems.append(f"{len(report['missing_crops'])} figure crops are missing")
    if report["bad_captions"]:
        structure_problems.append(f"{len(report['bad_captions'])} captions lack a figure label")
    if report["long_headings"]:
        structure_problems.append(f"{len(report['long_headings'])} long headings are probably call-outs or notes")
    if report["inline_acknowledgments"]:
        structure_problems.append(f"{len(report['inline_acknowledgments'])} acknowledgments start inline with body text")
    if report["all_caps_body"]:
        structure_problems.append(f"{len(report['all_caps_body'])} body blocks are set in all capitals")
    if report["empty_appendix_entries"]:
        structure_problems.append(
            f"{len(report['empty_appendix_entries'])} synonym-list entries have no text"
        )

    layout_problems = []
    delivery = _delivery_problems(data, args.pdf)
    if getattr(args, "profile", None) and json.loads(Path(args.profile).read_text(encoding="utf-8")).get("unwrap_lines"):
        delivery["manual_line_breaks"] = []  # the builder joins them
    report.update(delivery)
    if delivery["key_orphan_targets"]:
        structure_problems.append(f"{len(delivery['key_orphan_targets'])} key pages have a target with no couplet")
    from .headings import stray_label_blocks
    if getattr(args, "profile", None) and json.loads(Path(args.profile).read_text(encoding="utf-8")).get("promote_captions"):
        from .headings import drop_stray_labels
        drop_stray_labels(data)  # the builder drops them under this profile
    strays = stray_label_blocks(data)
    report["stray_label_blocks"] = strays
    if strays:
        structure_problems.append(f"{len(strays)} body blocks are lone figure-panel letters (pages {sorted({s['page'] for s in strays})[:6]}); enable promote_captions or remove them")
    if delivery["literal_markup_in_pdf"]:
        structure_problems.append(f"{len(delivery['literal_markup_in_pdf'])} literal <sup>/<sub>/<i> tags are printed in the PDF")
    if delivery["blocks_missing_in_pdf"]:
        structure_problems.append(f"{len(delivery['blocks_missing_in_pdf'])} printed blocks are missing from the PDF")
    if delivery["manual_line_breaks"]:
        layout_problems.append(f"{len(delivery['manual_line_breaks'])} justified paragraphs contain hand-made line breaks")
    if args.pdf:
        try:
            import fitz

            doc = fitz.open(args.pdf)
            report["pdf_pages"] = len(doc)
            report["fallback_fonts"] = sorted(
                {font[3] for page in doc for font in page.get_fonts()
                 if font[3] and "dejavu" in font[3].lower()}
            )
            report.update(_pdf_layout_problems(args.pdf))
            report.update(_reference_problems(args.pdf, meta))
            if report["wrong_page_refs"]:
                layout_problems.append(
                    f"{len(report['wrong_page_refs'])} contents/index page references "
                    f"land on a page without the cited entry")
            if report["blank_pages"]:
                layout_problems.append(f"{len(report['blank_pages'])} blank pages: {report['blank_pages'][:10]}")
            if report["tight_caption_gaps"]:
                layout_problems.append(
                    f"{len(report['tight_caption_gaps'])} captions sit closer than 10 pt "
                    f"to the figure above them")
            # body_spacing_tail is an audit list, not a failure: the justified
            # Spanish original has the same tail of 6-7 pt word gaps.
            if report["overflow_words"]:
                layout_problems.append(
                    f"{len(report['overflow_words'])} words sit outside the text area")
            if report["key_layout"]:
                layout_problems.append(
                    f"{len(report['key_layout'])} identification-key targets are not "
                    f"flush right or are split by wide gaps")
            if report["caption_word_breaks"]:
                layout_problems.append(
                    f"{len(report['caption_word_breaks'])} captions break a word "
                    f"across lines")
            if report["fallback_fonts"]:
                layout_problems.append(f"fallback fonts: {report['fallback_fonts']}")
        except Exception as exc:  # pragma: no cover - environment specific
            layout_problems.append(f"cannot read PDF: {exc}")
    else:
        layout_problems.append("no PDF supplied; layout review skipped")

    text = _text_qa(data, meta)
    text_problems = []
    if text["duplicate_paragraphs"]:
        text_problems.append(f"{len(text['duplicate_paragraphs'])} paragraphs are repeated on the same page")
    if text["role_suspects"]:
        text_problems.append(
            f"{len(text['role_suspects'])} citation/entry blocks contain descriptive prose"
        )
    if text["key_text_in_body"]:
        text_problems.append(
            f"{len(text['key_text_in_body'])} body blocks contain key text or leader dots"
        )
    if text["key_text_outside_key"]:
        text_problems.append(
            f"{len(text['key_text_outside_key'])} non-key blocks contain key text"
        )
    if text["citation_year_missing"]:
        text_problems.append(
            f"{len(text['citation_year_missing'])} citations lose the source year"
        )
    if text["entry_year_missing"]:
        text_problems.append(
            f"{len(text['entry_year_missing'])} synonym-list entries lose a source year"
        )
    if text["heading_name_missing"]:
        text_problems.append(
            f"{len(text['heading_name_missing'])} headings lose the source taxon name"
        )
    if text["body_leading_punctuation"]:
        text_problems.append(
            f"{len(text['body_leading_punctuation'])} body blocks start with a stray punctuation mark"
        )
    if text["function_word_pairs"]:
        text_problems.append(
            f"{len(text['function_word_pairs'])} blocks join a page break with a doubled or mispaired function word"
        )
    if text["spanish_residue"]:
        text_problems.append(
            f"{len(text['spanish_residue'])} blocks keep untranslated Spanish status text"
        )
    report["three_reviews"] = {
        "review1_structure": {"ok": not structure_problems, "problems": structure_problems},
        "review2_layout": {"ok": not layout_problems, "problems": layout_problems},
        "review3_text": {"ok": not text_problems, "problems": text_problems, **text},
    }
    problems = structure_problems + layout_problems + text_problems
    report["problems"] = problems
    report["ok"] = not problems
    report["manuscript_sha256"] = sha256_file(args.aligned)
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "stage1": len(structure_problems),
                      "stage2": len(layout_problems),
                      "stage3": len(text_problems),
                      "duplicates": len(text["duplicate_paragraphs"]),
                      "role_suspects": len(text["role_suspects"]),
                      "key_outside": len(text["key_text_outside_key"]),
                      "citation_no_year": len(text["citation_year_missing"]),
                      "entry_no_year": len(text["entry_year_missing"]),
                      "heading_mismatch": len(text["heading_name_missing"]),
                      "leading_punct": len(text["body_leading_punctuation"]),
                      "function_pairs": len(text["function_word_pairs"]),
                      "spanish_residue": len(text["spanish_residue"]),
                      "short": len(text["short_translations"]),
                      "truncated": len(text["truncated_endings"])},
                     ensure_ascii=False))
    return 0 if report["ok"] else 1


def _coverage_problems(
    data: dict, source_path: Path, meta: "BookMeta | None"
) -> list[str]:
    """Flag rendered pages whose translation lost most of the source text.

    An aligner can collapse a page to one surviving block and the builder
    then prints only that block; nothing in the aligned data itself shows
    the gap. Comparing word counts against the source structure catches it.
    """
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    source_pages = {int(p["page"]): p for p in raw.get("pages", [])}
    aligned_pages = {int(p["page"]): p for p in data.get("pages", [])}
    problems: list[str] = []
    for number, src in sorted(source_pages.items()):
        if meta is not None and not _is_rendered_page(src, meta):
            continue
        src_words = sum(len((b.get("text") or "").split()) for b in src.get("blocks", []))
        page = aligned_pages.get(number)
        # A cross-page paragraph merge moves this page's opening block to the
        # previous page on purpose; those words are still in the book.
        moved = int((page or {}).get("_merged_first_block_source_words") or 0)
        src_words = max(0, src_words - moved)
        if src_words < 40:
            continue
        tr_words = 0
        if page is not None:
            tr_words = sum(
                len((b.get("translation") or "").split()) for b in page.get("blocks", [])
            )
        if tr_words < 0.25 * src_words:
            problems.append(
                f"page {number}: aligned text covers {tr_words} of {src_words} source words"
            )
    return problems


def cmd_check(args: argparse.Namespace) -> int:
    problems: list[str] = []
    _require_figure_audit(args.figures)
    data = load_aligned(args.aligned)
    report = _report(data, args.figures, _meta(args))
    if report["untranslated_content_blocks"]:
        problems.append(f"{report['untranslated_content_blocks']} content blocks have no translation")
    if report["missing_crops"]:
        problems.append(f"{len(report['missing_crops'])} figure crops are missing")
    if report["bad_captions"]:
        problems.append(f"{len(report['bad_captions'])} captions lack a figure label")
    if report["long_headings"]:
        problems.append(f"{len(report['long_headings'])} long headings are probably call-outs or notes")
    if report["inline_acknowledgments"]:
        problems.append(f"{len(report['inline_acknowledgments'])} acknowledgments paragraphs start inline with body text")
    if report["all_caps_body"]:
        problems.append(f"{len(report['all_caps_body'])} body blocks are set in all capitals")
    if report["furniture_blocks"]:
        problems.append(
            f"{len(report['furniture_blocks'])} running header/folio blocks are rendered as body: "
            + "; ".join(f"p.{f['page']} {f['text'][:30]!r}" for f in report["furniture_blocks"][:10]))
    if report["uncertain_boundaries"]:
        # Issue #16: do not guess paragraph alignment; the records are in the
        # report file (--out).  Release stays blocked until each is reviewed.
        problems.append(
            f"{len(report['uncertain_boundaries'])} uncertain paragraph boundaries block release: "
            + "; ".join(f"p.{f['page']} {f['reason']}" for f in report["uncertain_boundaries"][:10]))
    if report["lost_markers"]:
        problems.append(
            f"{len(report['lost_markers'])} key pages look like lost couplet markers: "
            + "; ".join(f"p.{f['page']} {f['reason']}" for f in report["lost_markers"][:10]))
    if report["source_pages"] == 0:
        problems.append("aligned JSON has no pages")
    if args.source:
        coverage = _coverage_problems(data, args.source, _meta(args))
        report["coverage_problems"] = coverage
        if coverage:
            problems.append(
                f"{len(coverage)} pages keep less than a quarter of their source text: "
                + "; ".join(coverage[:10])
            )
    if args.pdf:
        try:
            import fitz

            doc = fitz.open(args.pdf)
            report["pdf_pages"] = len(doc)
            report["fallback_fonts"] = sorted(
                {font[3] for page in doc for font in page.get_fonts() if font[3] and "dejavu" in font[3].lower()}
            )
            report["embedded_images"] = sum(len(page.get_images(full=True)) for page in doc)
            if report["figures"] and not report["embedded_images"]:
                problems.append(
                    f"{report['figures']} figures are audited but the PDF embeds none"
                )
            layout = _pdf_layout_problems(args.pdf)
            report.update(layout)
            if layout["blank_pages"]:
                problems.append(f"{len(layout['blank_pages'])} blank pages: {layout['blank_pages'][:10]}")
            if layout["tight_caption_gaps"]:
                problems.append(
                    f"{len(layout['tight_caption_gaps'])} captions sit closer than 10 pt "
                    f"to the figure above them")
            if layout["key_layout"]:
                problems.append(
                    f"{len(layout['key_layout'])} identification-key targets are not "
                    f"flush right or are split by wide gaps")
            if layout["caption_word_breaks"]:
                problems.append(
                    f"{len(layout['caption_word_breaks'])} captions break a word "
                    f"across lines")
        except Exception as exc:  # pragma: no cover - environment specific
            problems.append(f"cannot read PDF: {exc}")
    report["problems"] = problems
    report["ok"] = not problems
    report["manuscript_sha256"] = sha256_file(args.aligned)
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "problems": problems, "source_pages": report["source_pages"]},
                     ensure_ascii=False))
    return 0 if report["ok"] else 1


def _locked_inplace(args: argparse.Namespace, fn: Any) -> int:
    """Every command that rewrites an aligned file takes the same lock and reads the file only after it."""
    if _reject_lock_dir_paths(args):
        return 2

    inputs = [getattr(args, k, None) for k in ("aligned", "source", "translation")]
    if _overlap(args.report, inputs + [args.out]) or _overlap(args.out, inputs[1:]):
        print("error: --report/--out must not overwrite the aligned book or an input file", file=sys.stderr)
        return 2

    def run() -> int:
        try:
            return fn()
        except (ValueError, OSError) as exc:
            print(f"error: {exc} (aligned file left untouched)", file=sys.stderr)
            return 2

    return _with_locks([args.aligned, args.out or args.aligned], run)


def cmd_normalize(args: argparse.Namespace) -> int:
    return _locked_inplace(args, lambda: _normalize_locked(args))


def _normalize_locked(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    report = normalize_aligned(data)
    out = args.out or args.aligned
    _write_json(out, data)
    _write_json(args.report, report)
    print(json.dumps({"out": str(out), "changed_blocks": report["changed_blocks"],
                      "changed_pages": report["changed_pages"]}, ensure_ascii=False))
    return 0


def cmd_kana_check(args: argparse.Namespace) -> int:
    """Issue #37: kana left in a non-reference block of an English book."""
    from .paragraphs import kana_residue

    found = kana_residue(load_aligned(args.aligned))
    report = {"ok": not found, "kana_blocks": found}
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "kana_blocks": len(found)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_key_align(args: argparse.Namespace) -> int:
    return _locked_inplace(args, lambda: _key_align_locked(args))


def _key_align_locked(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    markdown = args.translation.read_text(encoding="utf-8")
    out, report = align_document(data, markdown)
    target = args.out or args.aligned
    _write_json(target, out)
    _write_json(args.report, {"items": report})
    failures = [item for item in report if "message" in item]
    print(json.dumps({"out": str(target), "updated": len(report) - len(failures),
                      "warnings": failures[:20]}, ensure_ascii=False))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    return _locked_inplace(args, lambda: _backfill_locked(args))


def _backfill_locked(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    report = backfill_source(data, source)
    out = args.out or args.aligned
    _write_json(out, data)
    _write_json(args.report, report)
    print(json.dumps({"out": str(out), "filled_blocks": report["filled_blocks"],
                      "unmatched_blocks": len(report["unmatched_blocks"])}, ensure_ascii=False))
    return 0


def _lock_dir() -> Path:
    """One shared lock root for all users, independent of TMPDIR.

    ``BOOKLAYOUT_LOCK_DIR`` overrides it (tests, unusual hosts).
    """
    import os

    return Path(os.environ.get("BOOKLAYOUT_LOCK_DIR") or "/tmp/booklayout-locks")


def _under_lock_dir(p: Path | None) -> bool:
    if p is None:
        return False
    d = _lock_dir().resolve()
    r = p.resolve()
    return r == d or d in r.parents


def _lock_file(target: Path) -> int:
    """Open (never truncate) the lock file for ``target`` in the shared lock dir.

    The lock lives outside the book directory (works on a read-only source dir,
    cannot collide with --patch/--report/--out) and is keyed by the resolved
    path of the file that gets replaced.  Lock files are mode 0o666 so another
    user can open them.  Hard links to the same file are not supported (the
    replace would diverge the copies).
    """
    import hashlib
    import os

    import stat

    d = _lock_dir()
    try:
        d.mkdir(parents=True, mode=0o1777)  # we created it: only now widen the mode
        os.chmod(d, 0o1777)
    except FileExistsError:
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode):  # symlink or file: refuse, never chmod it
            raise OSError(f"lock dir {d} is not a plain directory") from None
    try:  # lock by file identity so Book.json / book.json / symlink share one lock
        st_t = os.stat(target)
        ident = f"{st_t.st_dev}:{st_t.st_ino}"
    except OSError:
        ident = str(target.resolve())
    key = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:32]
    path = d / (key + ".lock")
    flags = os.O_RDWR | os.O_NOFOLLOW
    for _ in range(3):
        try:  # existing lock: open WITHOUT O_CREAT (fs.protected_regular refuses it for foreign owners)
            fd = os.open(path, flags)
            break
        except FileNotFoundError:
            pass
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o666)
            os.fchmod(fd, 0o666)  # created by us: umask-proof
            break
        except FileExistsError:
            continue
    else:
        raise OSError(f"cannot open lock file {path}")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"lock file {path} is not a regular file")
    return fd


def _lock_ident(t: Path) -> str:
    try:
        st_t = os.stat(t)
        return f"{st_t.st_dev}:{st_t.st_ino}"
    except OSError:
        return str(t.resolve())


def _same_file(a: Path, b: Path) -> bool:
    """File identity, not path spelling: symlinks and case-insensitive aliases are the same file."""
    try:
        return os.path.samefile(a, b)
    except OSError:  # one side does not exist yet: fall back to resolved paths
        return a.resolve() == b.resolve()


def _overlap(out: Path | None, others: list[Path | None]) -> Path | None:
    for o in others:
        if out is not None and o is not None and _same_file(out, o):
            return o
    return None


def _with_locks(targets: list[Path], fn: Any) -> int:
    import fcntl
    import os

    uniq: list[Path] = []
    for t in targets:
        if not any(_same_file(t, u) for u in uniq):
            uniq.append(t)
    for _attempt in range(50):
        order = sorted(uniq, key=lambda t: _lock_ident(t))  # sorted: no deadlock
        idents = [_lock_ident(t) for t in order]
        fds: list[int] = []
        try:
            for t in order:
                fds.append(_lock_file(t))
            for fd in fds:
                fcntl.flock(fd, fcntl.LOCK_EX)
            # a writer that held the lock replaced the file (new inode): our key is stale, retry
            if [_lock_ident(t) for t in order] == idents:
                return fn()
        finally:
            for fd in fds:
                os.close(fd)  # closing releases the flock
    raise OSError("could not obtain a stable lock: target keeps being replaced")


def _reject_lock_dir_paths(args: argparse.Namespace) -> bool:
    for name in ("aligned", "patch", "report", "out"):
        if _under_lock_dir(getattr(args, name, None)):
            print(f"error: --{name} must not be inside the lock directory {_lock_dir()}", file=sys.stderr)
            return True
    return False


def cmd_patch_blocks(args: argparse.Namespace) -> int:
    if _reject_lock_dir_paths(args):
        return 2
    return _with_locks([args.aligned, args.out or args.aligned], lambda: _patch_blocks_locked(args))


def _load_patch(path: Path) -> Any:
    """Parse a patch file; duplicate keys at any level are an error, never last-one-wins."""
    from .builder import _no_dup_pairs

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_dup_pairs)


def _patch_blocks_locked(args: argparse.Namespace) -> int:
    try:
        data = load_aligned(args.aligned)
    except (ValueError, OSError) as exc:
        print(f"error: bad aligned file (left untouched): {exc}", file=sys.stderr)
        return 2
    try:
        patch = _load_patch(args.patch)
    except (ValueError, OSError) as exc:
        print(f"error: bad patch file: {exc}", file=sys.stderr)
        return 2
    if _overlap(args.report, [args.aligned, args.patch, args.out]):
        print("error: --report must not overwrite --aligned, --patch or --out", file=sys.stderr)
        return 2
    if _overlap(args.out, [args.patch]):
        print("error: --out must not overwrite --patch", file=sys.stderr)
        return 2
    try:
        report = apply_block_edits(data, patch, allow_partial=getattr(args, "allow_partial", False))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = args.out or args.aligned
    strict = patch.get("version", 1) >= 2
    conflicts = (bool(report["stale"]) or bool(report["invalid"])
                 or (strict and bool(report["missing"])))
    allow = getattr(args, "allow_partial", False)
    reject = conflicts and not allow
    if reject:
        report["rejected"] = True
        report["not_written"] = report.pop("not_applied", None) or report.get("applied", [])
        report["not_written_removed"] = report.pop("not_applied_removed", None) or report.get("removed", [])
        report["applied"] = []
        report["removed"] = []
    else:
        _write_json(out, data)  # data first, report second
    if _overlap(args.report, [args.aligned, args.patch, args.out, out]):  # re-check: out may now exist as an alias
        print("error: --report resolves to the aligned book/patch/out; report not written", file=sys.stderr)
        return 2
    _write_json(args.report, report)
    print(json.dumps({"out": None if reject else str(out),
                      "applied": len(report["applied"]),
                      "removed": len(report["removed"]),
                      "not_written": report.get("not_written", []),
                      "missing": report["missing"], "stale": report["stale"],
                      "invalid": report["invalid"]},
                     ensure_ascii=False))
    return 1 if reject else 0


def cmd_repair(args: argparse.Namespace) -> int:
    if _reject_lock_dir_paths(args):
        return 2
    return _with_locks([args.aligned, args.out or args.aligned], lambda: _repair_locked(args))


def _repair_locked(args: argparse.Namespace) -> int:
    try:
        data = load_aligned(args.aligned)
    except (ValueError, OSError) as exc:
        print(f"error: bad aligned file (left untouched): {exc}", file=sys.stderr)
        return 2
    try:
        patch = _load_patch(args.patch)
    except (ValueError, OSError) as exc:
        print(f"error: bad patch file: {exc}", file=sys.stderr)
        return 2
    out = args.out or args.aligned
    if _overlap(out, [args.patch]) or _overlap(args.report, [args.aligned, args.patch, args.out]):
        print("error: --out/--aligned/--report must not be the --patch file or overwrite the aligned book",
              file=sys.stderr)
        return 2
    try:
        report = apply_page_patch(data, patch)
    except ValueError as exc:
        print(f"error: bad page patch: {exc}", file=sys.stderr)
        return 2
    _write_json(out, data)
    if _overlap(args.report, [args.aligned, args.patch, args.out, out]):
        print("error: --report resolves to the aligned book/patch/out; report not written", file=sys.stderr)
        return 2
    print(json.dumps({"out": str(out), "patched_pages": report["patched_pages"]},
                     ensure_ascii=False))
    return 0


def _leader_width(line: dict) -> float:
    return (max(span["bbox"][2] for span in line["leaders"])
            - min(span["bbox"][0] for span in line["leaders"]))


def _key_breaks_from_lines(lines: list[dict],
                           page_no: int = 0) -> tuple[list[str], list[dict]]:
    """Couplets whose leader is too short, as rebuild input.

    A couplet whose target does not fit keeps its leader at the end of the
    line and starts the whole target on the next line (that is what
    ``tabbed(force_break=True)`` renders).  The audit flags those short
    leaders, so the scan must read the two halves as one couplet.  An
    earlier version only looked at lines that end in ``(p. N)`` and missed
    them, so a Vol. 45 couplet failed the gate however often it was rebuilt.
    """
    from .builder import key_signature

    key_blocks = {line["block"] for line in lines
                  if re.match(r"^(?:•|\d{1,2}\.)", line["text"])}
    keyish = [
        line for line in lines
        if line["block"] in key_blocks and (
            _TARGET_END.search(line["text"]) or _DOT_RUN.search(line["text"])
        )
    ]
    # 只要有带引导点/目标的行就扫描；不再要求本页至少两条引导点行——
    # 检索表跨页时，这一页可能只剩一条条目（Vol. 45 p. 306 的 Praxillura），
    # 按「整页跳过」处理会让这条短引导点永远修不掉。构造出的签名若不属于
    # 检索表，builder 不会命中，没有副作用。
    if not keyish:
        return [], []
    breaks: list[str] = []
    defects: list[dict] = []
    pending: dict[int, str] = {}
    wrapped: dict[int, dict] = {}
    for line in lines:
        block = line["block"]
        if block not in key_blocks:
            continue
        text = line["text"]
        if re.match(r"^(?:•|\d{1,2}\.)", text):
            pending[block] = text
            wrapped.pop(block, None)
        elif block in pending:
            pending[block] = pending[block].rstrip() + " " + text
        else:
            continue
        if not _TARGET_END.search(text):
            match = _DOT_RUN.search(text)
            if match and line["leaders"]:
                prefix = (pending[block][:-len(text)].strip()
                          if pending[block].endswith(text) else "")
                wrapped[block] = {"line": line, "match": match, "prefix": prefix}
            continue
        match = _DOT_RUN.search(text)
        info = wrapped.pop(block, None)
        if (not match or not line["leaders"]) and info is None:
            pending[block] = ""
            continue
        if match and line["leaders"]:
            width = _leader_width(line)
            prefix = (pending[block][:-len(text)].strip()
                      if pending[block].endswith(text) else "")
            left = (prefix + " " + text[:match.start()]).strip()
            target = text[match.end():].strip()
            source = text
        else:
            assert info is not None
            width = _leader_width(info["line"])
            left = (info["prefix"] + " "
                    + info["line"]["text"][:info["match"].start()]).strip()
            target = text.strip()
            source = info["line"]["text"]
        pending[block] = ""
        if not left or not target:
            continue
        if width >= MIN_KEY_LEADER_PT:
            continue
        breaks.append(key_signature(left, target))
        defects.append({"page": page_no,
                        "leader_mm": round(width * 25.4 / 72, 1),
                        "line": source[:100]})
    return breaks, defects


def cmd_key_report(args: argparse.Namespace) -> int:
    """List key couplets whose leader is too short, as rebuild input.

    The builder turns each signature into a forced line break before the tab,
    so the whole target starts a leader-filled line, exactly as the Spanish
    original sets a couplet that does not fit on one line.
    """
    import fitz

    doc = fitz.open(args.pdf)
    breaks: list[str] = []
    defects: list[dict] = []
    for page_no, page in enumerate(doc, start=1):
        clip = fitz.Rect(0, 50, page.rect.width, page.rect.height - 45)
        page_breaks, page_defects = _key_breaks_from_lines(
            _key_span_lines(page, clip), page_no)
        breaks.extend(page_breaks)
        defects.extend(page_defects)
    doc.close()
    unique = sorted(set(breaks))
    payload = {"breaks": unique, "defects": defects}
    _write_json(args.out, payload)
    print(json.dumps({"breaks": len(unique), "defects": len(defects)},
                     ensure_ascii=False))
    return 0


def _load_report(path: Path, label: str, problems: list[str]) -> dict | None:
    """Read a JSON report; an unreadable or non-object file is a problem, not a traceback."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(f"{label} unreadable ({path}): {e}")
        return None
    if not isinstance(payload, dict):
        problems.append(f"{label} is not a JSON object ({path})")
        return None
    return payload


def _gate_key_model(km_path: Path, problems: list[str]) -> dict:
    kmj = _load_report(km_path, "key-model", problems)
    if kmj is None:
        return {}
    g = kmj.get("graph")
    if not isinstance(kmj.get("ok"), bool) or not isinstance(g, dict) or not isinstance(g.get("errors"), int):
        problems.append(f"key-model report malformed ({km_path.name}): needs bool ok and graph.errors")
        return kmj
    if not kmj["ok"]:
        problems.append(f"key-model not ok ({km_path.name}): graph errors {g['errors']}")
    elif g["errors"] > 0:
        problems.append(f"key-model inconsistent ({km_path.name}): ok=true but graph errors {g['errors']}")
    return kmj


def _gate_keyrender(kr_path: Path, kmj: dict, problems: list[str]) -> None:
    krj = _load_report(kr_path, "keyrender", problems)
    if krj is None:
        return
    summary = krj.get("summary")
    if not isinstance(summary, dict) or not isinstance(krj.get("findings"), list):
        problems.append(f"keyrender report malformed ({kr_path.name}): needs summary object and findings list")
        return
    fails = {r: n for r, n in summary.items() if n}
    if fails or krj["findings"]:
        problems.append(f"keyrender FAIL ({kr_path.name}): {fails or len(krj['findings'])}")
    g = kmj.get("graph")
    g = g if isinstance(g, dict) else {}
    if g.get("source_keys", 0) > 0:  # key-model saw keys: the PDF must show a comparable number of branches
        want = g.get("source_branches")
        if want is None:
            want = sum(len(k.get("branches", [])) for k in kmj.get("source_keys", []) if isinstance(k, dict))
        got = krj.get("branches")
        if not isinstance(got, int):
            problems.append(f"keyrender report lacks branch count ({kr_path.name}): cannot confirm PDF coverage")
        elif got == 0 or (want and got * 2 < want):
            problems.append(f"keyrender saw {got} key branches in the PDF, key-model has {want}: "
                            "key tables missing from the PDF")


def cmd_gate(args: argparse.Namespace) -> int:
    """Refuse delivery unless every deterministic review is clean."""
    problems: list[str] = []
    for label, path in (("qa", args.qa), ("check", args.check)):
        payload = _load_report(path, label, problems)
        if payload is not None and not payload.get("ok"):
            detail = payload.get("problems", [])
            problems.append(f"{label} not ok: {detail}")
    key = _load_report(args.key_report, "key-report", problems) or {}
    if key.get("breaks"):
        problems.append(f"{len(key['breaks'])} key couplets still need a forced break")
    if key.get("defects"):
        problems.append(f"{len(key['defects'])} key leader defects remain")
    km_path = getattr(args, "key_model", None)
    kr_path = getattr(args, "keyrender", None)
    kmj = _gate_key_model(km_path, problems) if km_path else {}
    if kr_path:
        _gate_keyrender(kr_path, kmj, problems)
    for style_path in args.style_report or []:  # scripts/taxostyle.py compare|audit 的 JSON 报告
        style = _load_report(style_path, "style report", problems)
        if style is not None and not style.get("ok"):
            problems.append(f"taxonomic typography not ok ({style_path.name}): "
                            f"{style.get('errors', '?')} errors")
    coverage = {"key_model": km_path is not None, "keyrender": kr_path is not None}
    report = {"ok": not problems, "problems": problems,
              "coverage": coverage,
              "unchecked": [k for k, v in coverage.items() if not v],
              "files": {"qa": str(args.qa), "check": str(args.check),
                        "key_report": str(args.key_report),
                        "key_model": str(km_path) if km_path else None,
                        "keyrender": str(kr_path) if kr_path else None,
                        "style_reports": [str(x) for x in args.style_report or []]}}
    if args.out:
        _write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_profile(args: argparse.Namespace) -> int:
    """Print the default style profile (a template to edit) or validate a file."""
    from .profile import StyleProfile

    if args.validate:
        prof = StyleProfile.from_file(args.validate)
        print(json.dumps({"ok": True, "name": prof.name, "sha256": prof.sha256()}, ensure_ascii=False))
    else:
        print(json.dumps(StyleProfile().to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_validate_aligned(args: argparse.Namespace) -> int:
    from .profile import validate_aligned

    errors = validate_aligned(load_aligned(args.aligned))
    print(json.dumps({"ok": not errors, "errors": errors[:50], "count": len(errors)}, ensure_ascii=False))
    return 0 if not errors else 1


def cmd_quality_gate(args: argparse.Namespace) -> int:
    """Issue #26: metrics + quality_baseline.toml -> receipt; exit 0/1/2 = pass/fail/indeterminate."""
    from . import quality as q

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    result = q.evaluate(metrics, q.load_baseline(args.baseline))
    receipt = q.make_receipt(result, metrics, args.manuscript, args.baseline)
    _write_json(args.out, receipt)
    print(json.dumps({"status": receipt["status"], "fail": result["fail_reasons"],
                      "indeterminate": result["indeterminate_reasons"]}, ensure_ascii=False))
    return q.EXIT[receipt["status"]]


def cmd_verify_receipt(args: argparse.Namespace) -> int:
    from . import quality as q

    problems = q.verify_receipt(json.loads(args.receipt.read_text(encoding="utf-8")), args.manuscript)
    print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False))
    return 0 if not problems else 1


def cmd_acceptance(args: argparse.Namespace) -> int:
    """Issue #19: one acceptance report; exit 0 only when status is `release`."""
    from .acceptance import build_acceptance

    files = {"translation_review": args.translation_review, "technical": args.technical,
             "qa": args.qa, "check": args.check, "key_report": args.key_report,
             "pilot": args.pilot, "visual": args.visual}
    report = build_acceptance(args.aligned, files, args.receipt, command=args.command or "")
    _write_json(args.out, report)
    print(json.dumps({"status": report["status"],
                      "stages": {k: v["status"] for k, v in report["stages"].items()}},
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
    b.add_argument(
        "--key-breaks",
        type=Path,
        help="key_report.json: couplets whose target must start a leader-filled line",
    )
    b.add_argument("--profile", type=Path,
                   help="style profile JSON/TOML (page size, margins, fonts, sizes); default = Vol. 48 layout")
    b.add_argument("--strict-schema", action="store_true",
                   help="refuse to build when the aligned JSON violates the block schema (exit 6)")
    b.add_argument("--pilot", type=Path,
                   help="pilot report; the full build is refused (exit 5) unless every pilot item passed")
    b.add_argument("--release-acceptance", type=Path,
                   help="acceptance.json from `booklayout acceptance`; without a valid one the output "
                        "is renamed *.DRAFT.* and the command exits 4")
    b.add_argument("--out", type=Path, required=True, help="output DOCX")
    b.add_argument("--pdf", action="store_true", help="convert DOCX to PDF with LibreOffice")
    b.add_argument("--pdf-out", type=Path, help="PDF path when --pdf is used")
    b.add_argument("--report", type=Path, help="write build_report.json")
    b.add_argument("--no-cache", action="store_true", help="ignore the input-hash cache and rebuild")
    b.add_argument("--title", help="fallback title when --metadata is omitted")
    b.set_defaults(func=cmd_build)

    rs = sub.add_parser("restyle", help="re-apply heading styles of a profile to a finished DOCX (seconds, no re-typesetting)")
    rs.add_argument("--docx", type=Path, required=True)
    rs.add_argument("--profile", type=Path, required=True)
    rs.add_argument("--out", type=Path, required=True)
    rs.add_argument("--pdf", action="store_true", help="also convert to PDF")
    rs.add_argument("--pdf-out", type=Path)
    rs.add_argument("--html", type=Path, help="also write HTML (CSS from the same profile)")
    rs.set_defaults(func=cmd_restyle)
    ht = sub.add_parser("html", help="HTML from a finished DOCX; CSS generated from the profile")
    ht.add_argument("--docx", type=Path, required=True)
    ht.add_argument("--profile", type=Path, required=True)
    ht.add_argument("--out", type=Path, required=True)
    ht.add_argument("--title")
    ht.set_defaults(func=cmd_html)
    m = sub.add_parser("map-pages", help="map source printed pages to output PDF pages")
    m.add_argument("--pdf", type=Path, required=True)
    m.add_argument("--aligned", type=Path, required=True)
    m.add_argument("--metadata", type=Path)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--title")
    m.add_argument("--profile", type=Path, help="same profile as the build (needed for heading contents)")
    m.set_defaults(func=cmd_map_pages)

    c = sub.add_parser("check", help="check an aligned package and optional PDF")
    c.add_argument("--aligned", type=Path, required=True)
    c.add_argument("--figures", type=Path, required=True)
    c.add_argument("--pdf", type=Path)
    c.add_argument("--metadata", type=Path)
    c.add_argument(
        "--source",
        type=Path,
        help="source_structure.json; compares each page's source word count with its translation",
    )
    c.add_argument("--out", type=Path)
    c.add_argument("--title")
    c.set_defaults(func=cmd_check)

    q = sub.add_parser("qa", help="three deterministic reviews: structure, layout and text")
    q.add_argument("--aligned", type=Path, required=True)
    q.add_argument("--figures", type=Path, required=True)
    q.add_argument("--pdf", type=Path)
    q.add_argument("--metadata", type=Path)
    q.add_argument("--out", type=Path)
    q.add_argument("--title")
    q.add_argument("--profile", type=Path, help="build profile (unwrap_lines makes hand-made breaks harmless)")
    q.set_defaults(func=cmd_qa)

    n = sub.add_parser("normalize", help="apply deterministic block repairs to aligned JSON")
    n.add_argument("--aligned", type=Path, required=True)
    n.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    n.add_argument("--report", type=Path, help="write normalization_report.json")
    n.set_defaults(func=cmd_normalize)

    kc = sub.add_parser("kana-check", help="fail if kana remain outside reference blocks (EN edition)")
    kc.add_argument("--aligned", type=Path, required=True)
    kc.add_argument("--out", type=Path)
    kc.set_defaults(func=cmd_kana_check)

    ka = sub.add_parser(
        "key-align",
        help="re-cut identification-key pages from the translated markdown",
    )
    ka.add_argument("--aligned", type=Path, required=True)
    ka.add_argument("--translation", type=Path, required=True)
    ka.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    ka.add_argument("--report", type=Path)
    ka.set_defaults(func=cmd_key_align)

    f = sub.add_parser(
        "backfill-source",
        help="copy source text and geometry onto aligned blocks rebuilt by a page patch",
    )
    f.add_argument("--aligned", type=Path, required=True)
    f.add_argument("--source", type=Path, required=True, help="source_structure.json")
    f.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    f.add_argument("--report", type=Path)
    f.set_defaults(func=cmd_backfill)

    pb = sub.add_parser(
        "patch-blocks",
        help="apply block-level edits (translation, role, removal) by block_id",
    )
    pb.add_argument("--aligned", type=Path, required=True)
    pb.add_argument("--patch", type=Path, required=True)
    pb.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    pb.add_argument("--report", type=Path)
    pb.add_argument("--allow-partial", action="store_true",
                    help="write the output even when some edits are stale (old_hash mismatch)")
    pb.set_defaults(func=cmd_patch_blocks)

    r = sub.add_parser("repair", help="replace selected pages from a declarative patch")
    r.add_argument("--aligned", type=Path, required=True)
    r.add_argument("--patch", type=Path, required=True)
    r.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    r.set_defaults(func=cmd_repair)

    kr = sub.add_parser(
        "key-report",
        help="list key couplets whose leader is shorter than 40 mm (rebuild input)",
    )
    kr.add_argument("--pdf", type=Path, required=True)
    kr.add_argument("--out", type=Path, required=True)
    kr.set_defaults(func=cmd_key_report)

    g = sub.add_parser("gate", help="delivery gate: qa + check + key report must all be clean")
    g.add_argument("--qa", type=Path, required=True)
    g.add_argument("--check", type=Path, required=True)
    g.add_argument("--key-report", type=Path, required=True)
    g.add_argument("--style-report", type=Path, action="append",
                   help="taxostyle JSON report (compare/audit); repeatable; not ok blocks delivery")
    g.add_argument("--key-model", type=Path, help="key_model.json; ok=false blocks delivery")
    g.add_argument("--keyrender", type=Path, help="keyrender --report JSON; any finding blocks; missing file blocks")
    g.add_argument("--out", type=Path)
    g.set_defaults(func=cmd_gate)
    from . import alignmd, keymodel, pdffigures

    alignmd.add_parser(sub)
    audit_module.add_parser(sub)
    treatments_module.add_parser(sub)
    pdffigures.add_parser(sub)
    keymodel.add_parser(sub)

    pr = sub.add_parser("profile", help="print the default style profile, or --validate a profile file")
    pr.add_argument("--validate", type=Path)
    pr.set_defaults(func=cmd_profile)

    va = sub.add_parser("validate-aligned", help="schema-check aligned JSON (generic block model)")
    va.add_argument("--aligned", type=Path, required=True)
    va.set_defaults(func=cmd_validate_aligned)

    qg = sub.add_parser("quality-gate", help="numeric quality gate -> receipt (0 pass / 1 fail / 2 indeterminate)")
    qg.add_argument("--metrics", type=Path, required=True)
    qg.add_argument("--manuscript", type=Path, required=True, help="aligned JSON the receipt is bound to")
    qg.add_argument("--baseline", type=Path, default=Path("quality_baseline.toml"))
    qg.add_argument("--out", type=Path, required=True)
    qg.set_defaults(func=cmd_quality_gate)

    vr = sub.add_parser("verify-receipt", help="check a quality receipt against the current manuscript")
    vr.add_argument("--receipt", type=Path, required=True)
    vr.add_argument("--manuscript", type=Path, required=True)
    vr.set_defaults(func=cmd_verify_receipt)

    ac = sub.add_parser("acceptance", help="unified release acceptance report (structure, visual, quality)")
    ac.add_argument("--aligned", type=Path, required=True)
    for opt in ("translation-review", "technical", "qa", "check", "key-report", "pilot", "visual", "receipt"):
        ac.add_argument(f"--{opt}", type=Path)
    ac.add_argument("--command", help="the reproducible build command, recorded verbatim")
    ac.add_argument("--out", type=Path, required=True)
    ac.set_defaults(func=cmd_acceptance)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
