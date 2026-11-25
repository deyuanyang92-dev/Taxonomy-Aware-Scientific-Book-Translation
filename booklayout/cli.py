#!/usr/bin/env python3
"""booklayout command line interface.

Subcommands:
  build            aligned JSON + figure crops -> DOCX (optionally PDF)
  preview          DRAFT HTML/Typst slice preview (not delivery)
  map-pages        rendered PDF + aligned JSON -> source/printed page map
  check            structural report for an aligned book package
  qa               three deterministic reviews (default strict: PDF required)
  verify           STRICT delivery: keys-check + qa + check + key-report + taxostyle + gate
  audit            static key+text audit on aligned JSON (no PDF)
  keys-check       strict identification-key format check
  taxostyle        阶元体例审计（aligned 标记 + 可选 DOCX italic_check）
  normalize        deterministic block repairs
  key-align        re-cut identification-key pages from the translated markdown
  backfill-source  restore source text and geometry lost in a page patch
  patch-blocks     block-level translation/role edits by block_id
  extract-blocks   pack block + source page image/OCR for model repair
  repair           replace selected pages from a declarative patch
  restore          OCR line boxes -> vector PDF, original page geometry
  gate             refuse delivery unless qa + check + key-report + taxostyle are clean
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from .builder import BookMeta, BookPaths, build, load_aligned, make_page_map
from .keyalign import align_document
from .normalize import apply_block_edits, apply_page_patch, backfill_source, normalize_aligned
from .preview import run_preview


def _meta(args: argparse.Namespace) -> BookMeta:
    if getattr(args, "metadata", None):
        return BookMeta.from_json(args.metadata)
    return BookMeta(title=getattr(args, "title", "") or "Untitled")


def _write_json(path: Path | None, data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
        and not re.match(r"^(?:Fig(?:ure)?\b|L[aá]m\b|Tabla\b|Table\b|Plate\b|图|図|表)",
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


def cmd_preview(args: argparse.Namespace) -> int:
    """DRAFT page/chapter slice preview (HTML or Typst). Not a delivery path."""
    if not args.pages and not args.chapter:
        print("preview requires --pages N-M or --chapter KEY", file=sys.stderr)
        return 2
    try:
        report = run_preview(
            aligned=args.aligned,
            figures=args.figures,
            out=args.out,
            engine=args.engine,
            pages_spec=args.pages,
            chapter=args.chapter,
            title=getattr(args, "title", None) or "Preview",
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"DRAFT preview engine={report['engine']} out={report['out']} "
        f"pages={report['pages']} figures_embedded={report.get('figures_embedded', 0)} "
        f"delivery=false"
    )
    if report.get("index"):
        print(f"index={report['index']}")
    if report.get("pdf"):
        print(f"pdf={report['pdf']}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    _require_figure_audit(args.figures)
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
    data = build(args.out, page_map, paths, meta, key_breaks)
    report = _report(data, args.figures, meta)
    report.update({"out_docx": str(args.out), "page_map_entries": len(page_map)})
    pdf = None
    if args.pdf:
        pdf = _convert_pdf(args.out, args.pdf_out)
        report["out_pdf"] = str(pdf)
    _write_json(args.report, report)
    print(f"docx={args.out} source_pages={report['source_pages']} blocks={report['blocks']} "
          f"untranslated={report['untranslated_blocks']} "
          f"content_missing={report['untranslated_content_blocks']} figures={report['figures']}")
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


_KEY_START = re.compile(r"^(?:•|—|\d{1,3}\.)$")
_KEY_COUPLET = re.compile(r"^(?:•|—|\d{1,3}\.)")
_LEADER_TOKEN = re.compile(r"^[.…·]+$")
# 同行 flush 检测仍用西语 (p. N)；换行目标另见 _is_key_target_line
_TARGET_END = re.compile(r"\(p\.\s*\d+\)\s*$")
_NUMBER_END = re.compile(r"(?:…|\.\s*\.)\s*\d{1,3}\s*$")
# 点线独占一行时，下一行可为 (Fig./图) 或种名结论（今岛等）
_WRAPPED_TARGET = re.compile(
    r"(?:"
    r"\(p\.\s*\d+\)\s*$"
    r"|[（(](?:Fig|Figs?|図|图)[^)）]*[)）]\s*$"
    r"|\*?[A-Z][a-z][A-Za-z-]*\*?"
    r"(?:\s+\([A-Z][A-Za-z-]+\))?"
    r"(?:\s+\*?[a-z][a-z-]+\*?){0,2}"
    r"(?:\s+[A-Z][a-z]+)?"
    r"(?:\s*[（(][^)）]*[)）]){0,2}"
    r"\s*$"
    r")"
)
MIN_KEY_LEADER_MM = 40.0
MIN_KEY_LEADER_PT = MIN_KEY_LEADER_MM * 72 / 25.4
_DOT_RUN = re.compile(r"(?:[.·…]\s*){2,}")


def _is_key_target_line(text: str) -> bool:
    """True when a PDF continuation line looks like a couplet target."""
    t = (text or "").strip()
    if not t:
        return False
    if _WRAPPED_TARGET.search(t) or _NUMBER_END.search(t):
        return True
    if re.fullmatch(r"\d{1,3}['′ʹ]?", t):
        return True
    return False


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
                  if re.match(r"^(?:•|—|\d{1,3}\.)", line["text"])}
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
    # 点线和紧随其后的斜体目标（学名）在同一视觉行，PyMuPDF 却拆成两个 line：
    # 只合并「纯点线片段 + 同块同基线、位于其右侧的片段」，不动其他行。
    merged: list[list[tuple]] = []
    for line in ordered:
        prev = merged[-1] if merged else None
        if (prev is not None and prev[0][5] == line[0][5]
                and all(_LEADER_TOKEN.match(w[4]) or _DOT_RUN.fullmatch(w[4]) for w in prev)
                and abs(prev[0][1] - line[0][1]) < 1.5 and line[0][0] >= prev[-1][2] - 1):
            prev.extend(line)
        else:
            merged.append(list(line))
    ordered = merged

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
    # 破折号行（—）也算偶句标记，但检索表页必有至少一条编号行（N.）；
    # 只有破折号的页多半是种名索引（「— 种名 …… 页码」），不当检索表审。
    if not any(re.match(r"\d{1,3}\.$", line[0][4]) for line in keyish):
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
            if gaps and max(gaps) > 15:
                problems.append({"reason": "wide gaps",
                                 "gap_pt": round(max(gaps), 1), "line": text[:90]})
            continue
        if not starts_key(line):
            continue
        same_block = index + 1 < len(ordered) and ordered[index + 1][0][5] == line[0][5]
        following = ordered[index + 1] if same_block else None
        if has_leader(line) and _LEADER_TOKEN.match(line[-1][4]):
            if following and _is_key_target_line(text_of(following)):
                continue  # wrapped target on its own leader line is legitimate
            # 纯点/省略号行：换行填充或叙述省略，不是丢了检索表目标
            if re.fullmatch(r"[.…·\s]+", text or ""):
                continue
            # 中文叙述省略号常独占一行，下一行仍是特征描写（无拉丁目标）→ 非制表符点线
            if following:
                nxt = text_of(following)
                if re.search(r"[\u4e00-\u9fff\u3000-\u303f]", nxt) and not re.search(
                    r"[A-Za-z]{4,}", nxt
                ):
                    continue
                # 下一行只剩顿号/逗号等标点（PDF 把省略号与续行拆开）
                if re.fullmatch(r"[\s、，,；;：:．.]+", nxt or ""):
                    continue
            problems.append({"reason": "leader without target",
                             "x1": round(line[-1][2], 1), "line": text[:90]})
            continue
        # 目标被拆：仍只认西语 (p. N)；今岛种名/Fig 换行由 leader-without-target 分支覆盖
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
    """Third review: deep text-layout audit on every printable role."""
    from .textaudit import audit_text

    return audit_text(data, meta)


def cmd_qa(args: argparse.Namespace) -> int:
    """Run the three deterministic reviews used before delivery.

    默认严格：无 PDF 即失败。仅 ``--draft`` 允许跳过 PDF（不得称正式交付）。
    """
    strict = not getattr(args, "draft", False)
    _require_figure_audit(args.figures)
    data = load_aligned(args.aligned)
    meta = _meta(args)
    report = _report(data, args.figures, meta)
    report["strict"] = strict
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

    # 检索表：对齐数据静态审计（不需 PDF；串行/丢目标在排版前拦住）
    from .keyaudit import audit_key_blocks

    key_audit = audit_key_blocks(data)
    report["key_audit"] = {
        "ok": key_audit["ok"],
        "format_ok": key_audit["format_ok"],
        "key_blocks": key_audit["key_blocks"],
        "couplet_blocks": key_audit.get("couplet_blocks"),
        "by_reason": key_audit["by_reason"],
        "defect_count": len(key_audit["defects"]),
        "defects": key_audit["defects"][:200],  # 报告截断，全量见 keys-check / audit
        "strict": key_audit.get("strict", True),
    }
    if key_audit["defects"]:
        structure_problems.append(
            f"{len(key_audit['defects'])} identification-key format defects "
            f"({', '.join(f'{k}={v}' for k, v in sorted(key_audit['by_reason'].items()))})"
        )

    layout_problems = []
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
            # 严格模式：极端词距也拦（原先只记 audit 不失败）
            if strict:
                wide = [
                    x for x in (report.get("body_spacing_tail") or [])
                    if (x.get("gap_pt") or x.get("width") or 0) >= 12
                    # 误挂成正文的检索表偶行：句末是跳转号，词距被拉开
                    and not re.search(
                        r"\b([1-9]|[1-9]\d)\s*$", (x.get("line") or "").rstrip()
                    )
                ]
                if wide:
                    layout_problems.append(
                        f"{len(wide)} body word gaps ≥ 12 pt (strict)"
                    )
        except Exception as exc:  # pragma: no cover - environment specific
            layout_problems.append(f"cannot read PDF: {exc}")
    elif strict:
        layout_problems.append(
            "no PDF supplied; strict QA requires --pdf (use --draft to skip)"
        )
    # --draft 且无 PDF：不记 layout 失败，只做结构+文字（不得称正式交付）

    from .textaudit import text_problem_lines

    text = _text_qa(data, meta)
    text_problems = text_problem_lines(text)
    report["three_reviews"] = {
        "review1_structure": {"ok": not structure_problems, "problems": structure_problems},
        "review2_layout": {"ok": not layout_problems, "problems": layout_problems},
        "review3_text": {"ok": not text_problems, "problems": text_problems, **text},
    }
    problems = structure_problems + layout_problems + text_problems
    report["problems"] = problems
    report["ok"] = not problems
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "stage1": len(structure_problems),
                      "stage2": len(layout_problems),
                      "stage3": len(text_problems),
                      "coverage": (text.get("coverage") or {}).get("ok"),
                      "by_role": text.get("checked_by_role"),
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
                      "oversized": len(text.get("oversized_translations") or []),
                      "nbsp": len(text.get("bad_nbsp") or []),
                      "orphan_hyphen": len(text.get("orphan_hyphen") or []),
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
    # check 默认可只做结构；正式交付用 --strict（要 PDF + 检索表格式）
    strict = bool(getattr(args, "strict", False))
    _require_figure_audit(args.figures)
    data = load_aligned(args.aligned)
    report = _report(data, args.figures, _meta(args))
    report["strict"] = strict
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
            if layout.get("overflow_words"):
                problems.append(
                    f"{len(layout['overflow_words'])} words sit outside the text area")
            if report.get("fallback_fonts"):
                problems.append(f"fallback fonts: {report['fallback_fonts']}")
        except Exception as exc:  # pragma: no cover - environment specific
            problems.append(f"cannot read PDF: {exc}")
    elif strict:
        problems.append("no PDF supplied; --strict check requires --pdf")
    if strict:
        from .keyaudit import audit_key_blocks

        key_audit = audit_key_blocks(data, strict=True)
        report["key_audit"] = {
            "ok": key_audit["ok"],
            "format_ok": key_audit["format_ok"],
            "defect_count": len(key_audit["defects"]),
            "by_reason": key_audit["by_reason"],
        }
        if key_audit["defects"]:
            problems.append(
                f"{len(key_audit['defects'])} identification-key format defects "
                f"({key_audit['by_reason']})"
            )
    report["problems"] = problems
    report["ok"] = not problems
    _write_json(args.out, report)
    print(json.dumps({"ok": report["ok"], "problems": problems, "source_pages": report["source_pages"]},
                     ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_normalize(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    report = normalize_aligned(data)
    out = args.out or args.aligned
    _write_json(out, data)
    _write_json(args.report, report)
    print(json.dumps({"out": str(out), "changed_blocks": report["changed_blocks"],
                      "changed_pages": report["changed_pages"]}, ensure_ascii=False))
    return 0


def cmd_key_align(args: argparse.Namespace) -> int:
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
    data = load_aligned(args.aligned)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    report = backfill_source(data, source)
    out = args.out or args.aligned
    _write_json(out, data)
    _write_json(args.report, report)
    print(json.dumps({"out": str(out), "filled_blocks": report["filled_blocks"],
                      "unmatched_blocks": len(report["unmatched_blocks"])}, ensure_ascii=False))
    return 0


def cmd_patch_blocks(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    patch = json.loads(args.patch.read_text(encoding="utf-8"))
    report = apply_block_edits(data, patch)
    out = args.out or args.aligned
    _write_json(out, data)
    _write_json(args.report, report)
    print(json.dumps({"out": str(out), "applied": len(report["applied"]),
                      "removed": len(report["removed"]),
                      "missing": report["missing"]}, ensure_ascii=False))
    return 0


def cmd_extract_blocks(args: argparse.Namespace) -> int:
    """Pack (source_text, bad translation, page image/OCR) for model re-translation."""
    from .extract_blocks import extract_blocks

    data = load_aligned(args.aligned)
    ids: list[str] = []
    if args.block_ids:
        ids.extend(x.strip() for x in args.block_ids.split(",") if x.strip())
    if args.blocks_file:
        raw = json.loads(args.blocks_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "block_ids" in raw:
            ids.extend(str(x) for x in raw["block_ids"])
        elif isinstance(raw, list):
            ids.extend(str(x) for x in raw)
    # de-dupe preserve order
    seen: set[str] = set()
    block_ids = []
    for bid in ids:
        if bid not in seen:
            seen.add(bid)
            block_ids.append(bid)
    if not block_ids:
        print(json.dumps({"ok": False, "error": "no block_ids"}, ensure_ascii=False))
        return 2
    report = extract_blocks(
        data,
        block_ids,
        doc_key=args.doc_key,
        pdf=args.pdf,
        out_dir=args.out_dir,
        render_if_missing=not args.no_render,
        dpi=args.dpi,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report.get("missing") else 1


def cmd_repair(args: argparse.Namespace) -> int:
    data = load_aligned(args.aligned)
    patch = json.loads(args.patch.read_text(encoding="utf-8"))
    report = apply_page_patch(data, patch)
    out = args.out or args.aligned
    _write_json(out, data)
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
                  if re.match(r"^(?:•|—|\d{1,3}\.)", line["text"])}
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
        if re.match(r"^(?:•|—|\d{1,3}\.)", text):
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


def cmd_gate(args: argparse.Namespace) -> int:
    """Refuse delivery unless every deterministic review is clean.

    正式交付：检索表格式（key_audit / keys-check）零缺陷；PDF key-report
    零 breaks/defects；qa+check 均为 ok；阶元斜体审计（taxostyle）无
    major/critical。任一格式错误 → 退出码 1。
    """
    problems: list[str] = []
    qa_payload: dict[str, Any] = {}
    for label, path in (("qa", args.qa), ("check", args.check)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if label == "qa":
            qa_payload = payload
        if not payload.get("ok"):
            detail = payload.get("problems", [])
            problems.append(f"{label} not ok: {detail}")
    # 即便旧版 qa.json 漏设 ok，gate 也要硬拦检索表与文字深检字段
    key_audit = qa_payload.get("key_audit") or {}
    if key_audit.get("defect_count") or (
        key_audit.get("ok") is False
    ) or (
        key_audit.get("format_ok") is False
    ):
        n = key_audit.get("defect_count") or len(key_audit.get("defects") or [])
        problems.append(f"qa key_audit: {n} identification-key format defects")
    if getattr(args, "key_audit", None):
        ka = json.loads(Path(args.key_audit).read_text(encoding="utf-8"))
        if not ka.get("ok", True) or not ka.get("format_ok", True) or ka.get("defects"):
            problems.append(
                f"key-audit format defects: "
                f"{len(ka.get('defects') or [])} ({ka.get('by_reason')})"
            )
    text_review = (qa_payload.get("three_reviews") or {}).get("review3_text") or {}
    from .textaudit import text_problem_lines

    for line in text_problem_lines(text_review):
        problems.append(f"qa {line}")
    key = json.loads(args.key_report.read_text(encoding="utf-8"))
    if key.get("breaks"):
        problems.append(f"{len(key['breaks'])} key couplets still need a forced break")
    if key.get("defects"):
        problems.append(f"{len(key['defects'])} key leader defects remain")
    italic_path = getattr(args, "italic_audit", None)
    if italic_path:
        italic = json.loads(Path(italic_path).read_text(encoding="utf-8"))
        if not italic.get("ok", True) or italic.get("major_or_critical"):
            problems.append(
                f"taxostyle italic defects: {italic.get('major_or_critical', 0)} "
                f"({italic.get('by_kind')})"
            )
    # 去重：qa not ok 已含同类问题时保留明细即可
    unique: list[str] = []
    seen: set[str] = set()
    for p in problems:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    report = {
        "ok": not unique,
        "problems": unique,
        "key_format_ok": not any("key" in p.lower() for p in unique),
        "files": {
            "qa": str(args.qa),
            "check": str(args.check),
            "key_report": str(args.key_report),
            "key_audit": str(args.key_audit) if getattr(args, "key_audit", None) else None,
            "italic_audit": str(italic_path) if italic_path else None,
        },
    }
    if args.out:
        _write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_taxostyle(args: argparse.Namespace) -> int:
    """阶元体例审计：aligned 标记 + 可选成品 DOCX。"""
    from .taxostyle import audit_taxostyle, resolve_docx

    docx = resolve_docx(getattr(args, "pdf", None), getattr(args, "docx", None))
    report = audit_taxostyle(aligned=args.aligned, docx=docx)
    if args.out:
        _write_json(args.out, report)
    print(json.dumps({
        "ok": report["ok"],
        "major_or_critical": report["major_or_critical"],
        "by_kind": report["by_kind"],
        "parts": [
            {"source": p.get("source"), "major_or_critical": p.get("major_or_critical"),
             "by_kind": p.get("by_kind")}
            for p in report.get("parts") or []
        ],
    }, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_keys_check(args: argparse.Namespace) -> int:
    """Strict identification-key format check (aligned JSON only)."""
    from .keyaudit import audit_key_blocks

    data = load_aligned(args.aligned)
    report = audit_key_blocks(data, strict=not getattr(args, "lenient", False))
    from .keyblocks import audit_couplets

    couplets = audit_couplets(data)
    if couplets["couplets"]:
        report["ok"] = bool(report["ok"] and couplets["ok"])
        report["couplet_audit"] = {"couplets": couplets["couplets"],
                                   "by_reason": couplets["by_reason"],
                                   "defects": couplets["defects"][:200]}
    if args.out:
        _write_json(args.out, report)
    print(json.dumps({
        "ok": report["ok"],
        "format_ok": report["format_ok"],
        "graph_ok": report.get("graph_ok", True),
        "key_blocks": report["key_blocks"],
        "couplet_blocks": report["couplet_blocks"],
        "couplet_audit": (report.get("couplet_audit") or {}).get("by_reason"),
        "defects": len(report["defects"]),
        "by_reason": report["by_reason"],
        "key_graph": {
            "nodes": (report.get("key_graph") or {}).get("nodes"),
            "runs": (report.get("key_graph") or {}).get("runs"),
            "by_reason": (report.get("key_graph") or {}).get("by_reason"),
        },
    }, ensure_ascii=False))
    return 0 if report["ok"] else 1


def _load_names(path: Path | None) -> dict[str, str] | None:
    """日文类群名 → 中文阶元名（TSV：日名、拉丁名、中文名…，取第 1 与第 3 列）。"""
    if not path or not path.exists():
        return None
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0] and cols[2] and not line.startswith("#"):
            out[cols[0].strip()] = cols[2].strip()
    return out


def cmd_apply_keys(args: argparse.Namespace) -> int:
    """Replace identification-key pages of an aligned package with rebuilt couplet blocks.

    keys.json comes from ``docstore keys extract``; the translation sidecar from
    ``scripts/keys_translate.py collect``.  The command is deterministic and
    idempotent: it overwrites the pages named in keys.json's layout and nothing else.
    """
    from . import keyblocks

    data = load_aligned(args.aligned)
    keys = json.loads(args.keys.read_text(encoding="utf-8"))
    tr = (json.loads(args.tr.read_text(encoding="utf-8"))
          if args.tr and args.tr.exists() else {"items": {}})
    genera = keyblocks.known_genera(keys, data)
    if args.genera:
        genera |= {ln.strip() for ln in args.genera.read_text(encoding="utf-8").splitlines() if ln.strip()}
    report = keyblocks.apply_keys(data, keys, tr, args.lang, genera=genera,
                                  names=_load_names(args.names))
    audit = keyblocks.audit_couplets(data)
    report["audit"] = {"ok": audit["ok"], "by_reason": audit["by_reason"]}
    if not args.dry:
        _write_json(args.aligned, data)
    if args.out:
        _write_json(args.out, {**report, "defects": audit["defects"]})
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in report.items()},
                     ensure_ascii=False))
    return 0 if audit["ok"] or args.allow_defects else 1


def cmd_repair_keys(args: argparse.Namespace) -> int:
    """Deterministic key-role / marker / leader repairs on aligned JSON."""
    from .keyaudit import audit_key_blocks
    from .keyrepair import repair_key_blocks

    data = load_aligned(args.aligned)
    before = audit_key_blocks(data, strict=True)
    report = repair_key_blocks(data)
    for page in data.get("pages") or []:
        page["blocks"] = [
            b for b in (page.get("blocks") or []) if not b.get("_drop")
        ]
    after = audit_key_blocks(data, strict=True)
    out = args.out or args.aligned
    _write_json(out, data)
    payload = {
        "out": str(out),
        "changed": report["changed"],
        "by_action": report["by_action"],
        "defects_before": len(before["defects"]),
        "defects_after": len(after["defects"]),
        "by_reason_after": after["by_reason"],
        "format_ok": after["format_ok"],
    }
    if args.report:
        _write_json(args.report, {**payload, "changes": report["changes"],
                                  "defects": after["defects"][:200]})
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if after["ok"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """一键严格验收：keys-check + qa + check + key-report + taxostyle + gate.

    全部通过才退出 0。正式交付唯一推荐入口。
    """
    from .taxostyle import resolve_docx

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    aligned, figures, pdf, meta = args.aligned, args.figures, args.pdf, args.metadata
    keys_path = out_dir / "keys_check.json"
    qa_path = out_dir / "qa.json"
    check_path = out_dir / "check.json"
    key_report_path = out_dir / "key_report.json"
    italic_path = out_dir / "italic_audit.json"
    gate_path = out_dir / "gate.json"
    docx = resolve_docx(pdf, getattr(args, "docx", None))

    steps: list[tuple[str, int]] = []
    rc = cmd_keys_check(argparse.Namespace(
        aligned=aligned, out=keys_path, lenient=False,
    ))
    steps.append(("keys-check", rc))

    rc = cmd_qa(argparse.Namespace(
        aligned=aligned, figures=figures, pdf=pdf, metadata=meta,
        out=qa_path, title=getattr(args, "title", None), draft=False,
    ))
    steps.append(("qa", rc))

    rc = cmd_check(argparse.Namespace(
        aligned=aligned, figures=figures, pdf=pdf, metadata=meta,
        source=getattr(args, "source", None), out=check_path,
        title=getattr(args, "title", None), strict=True, draft=False,
    ))
    steps.append(("check", rc))

    rc = cmd_key_report(argparse.Namespace(pdf=pdf, out=key_report_path))
    steps.append(("key-report", rc))

    rc = cmd_taxostyle(argparse.Namespace(
        aligned=aligned, docx=docx, pdf=pdf, out=italic_path,
    ))
    steps.append(("taxostyle", rc))

    rc = cmd_gate(argparse.Namespace(
        qa=qa_path, check=check_path, key_report=key_report_path,
        key_audit=keys_path, italic_audit=italic_path, out=gate_path,
    ))
    steps.append(("gate", rc))

    ok = all(code == 0 for _, code in steps)
    summary = {
        "ok": ok,
        "strict": True,
        "steps": [{"name": n, "ok": c == 0} for n, c in steps],
        "out_dir": str(out_dir),
        "docx": str(docx) if docx else None,
    }
    _write_json(out_dir / "verify.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


def cmd_audit(args: argparse.Namespace) -> int:
    """Static audit: keys + deep text on aligned JSON (no PDF required)."""
    from .keyaudit import audit_key_blocks
    from .textaudit import text_problem_lines

    data = load_aligned(args.aligned)
    meta = _meta(args)
    key_audit = audit_key_blocks(data)
    text = _text_qa(data, meta)
    problems: list[str] = []
    if key_audit["defects"]:
        problems.append(
            f"{len(key_audit['defects'])} key defects "
            f"({', '.join(f'{k}={v}' for k, v in sorted(key_audit['by_reason'].items()))})"
        )
    problems.extend(text_problem_lines(text))
    report = {
        "ok": not problems,
        "problems": problems,
        "key_audit": key_audit,
        "text": text,
    }
    _write_json(args.out, report)
    print(json.dumps({
        "ok": report["ok"],
        "problems": len(problems),
        "key_defects": len(key_audit["defects"]),
        "coverage": (text.get("coverage") or {}).get("ok"),
        "by_role": text.get("checked_by_role"),
        "short": len(text.get("short_translations") or []),
        "oversized": len(text.get("oversized_translations") or []),
        "nbsp": len(text.get("bad_nbsp") or []),
        "key_outside": len(text.get("key_text_outside_key") or []),
    }, ensure_ascii=False))
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
    b.add_argument("--out", type=Path, required=True, help="output DOCX")
    b.add_argument("--pdf", action="store_true", help="convert DOCX to PDF with LibreOffice")
    b.add_argument("--pdf-out", type=Path, help="PDF path when --pdf is used")
    b.add_argument("--report", type=Path, help="write build_report.json")
    b.add_argument("--title", help="fallback title when --metadata is omitted")
    b.set_defaults(func=cmd_build)

    pv = sub.add_parser(
        "preview",
        help="DRAFT HTML/Typst page slice (not delivery; browser or typst PDF)",
    )
    pv.add_argument("--aligned", type=Path, required=True)
    pv.add_argument(
        "--figures",
        type=Path,
        required=True,
        help="figure directory (real crops via source_figure_audit.json)",
    )
    pv.add_argument("--pages", help="source page window N or N-M")
    pv.add_argument("--chapter", help="chapter key filter (optional with --pages)")
    pv.add_argument(
        "--engine",
        choices=["html", "typst"],
        default="html",
        help="html (default, always usable) or typst (needs typst binary)",
    )
    pv.add_argument("--out", type=Path, required=True, help="work/temp output directory")
    pv.add_argument("--title", help="preview document title")
    pv.set_defaults(func=cmd_preview)

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
    c.add_argument(
        "--strict",
        action="store_true",
        help="formal delivery: require --pdf and fail on key format defects",
    )
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
    q.add_argument(
        "--draft",
        action="store_true",
        help="allow missing PDF (not for formal delivery)",
    )
    q.set_defaults(func=cmd_qa)

    v = sub.add_parser(
        "verify",
        help="STRICT delivery verify: keys-check + qa + check + key-report + taxostyle + gate",
    )
    v.add_argument("--aligned", type=Path, required=True)
    v.add_argument("--figures", type=Path, required=True)
    v.add_argument("--pdf", type=Path, required=True)
    v.add_argument(
        "--docx",
        type=Path,
        help="交付 DOCX；缺省尝试与 PDF 同名的 .docx，供 italic_check 硬拦科名斜体",
    )
    v.add_argument("--metadata", type=Path)
    v.add_argument("--source", type=Path)
    v.add_argument("--out-dir", type=Path, required=True)
    v.add_argument("--title")
    v.set_defaults(func=cmd_verify)

    n = sub.add_parser("normalize", help="apply deterministic block repairs to aligned JSON")
    n.add_argument("--aligned", type=Path, required=True)
    n.add_argument("--out", type=Path, help="output JSON (default: rewrite --aligned)")
    n.add_argument("--report", type=Path, help="write normalization_report.json")
    n.set_defaults(func=cmd_normalize)

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
    pb.set_defaults(func=cmd_patch_blocks)

    eb = sub.add_parser(
        "extract-blocks",
        help="pack block + source page image/OCR for model repair (then patch-blocks)",
    )
    eb.add_argument("--aligned", type=Path, required=True)
    eb.add_argument("--out-dir", type=Path, required=True)
    eb.add_argument(
        "--block-ids",
        help="comma-separated block_id list",
    )
    eb.add_argument(
        "--blocks-file",
        type=Path,
        help='JSON list of ids, or {"block_ids": [...]}',
    )
    eb.add_argument(
        "--doc-key",
        help="docstore key (e.g. Imajima2001) for PDF path + page images/OCR",
    )
    eb.add_argument("--pdf", type=Path, help="override source PDF path")
    eb.add_argument(
        "--no-render",
        action="store_true",
        help="do not render PDF page when docstore image missing",
    )
    eb.add_argument("--dpi", type=int, default=150)
    eb.set_defaults(func=cmd_extract_blocks)

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

    g = sub.add_parser(
        "gate",
        help="delivery gate: qa + check + key-report + taxostyle must be clean",
    )
    g.add_argument("--qa", type=Path, required=True)
    g.add_argument("--check", type=Path, required=True)
    g.add_argument("--key-report", type=Path, required=True)
    g.add_argument(
        "--key-audit",
        type=Path,
        help="keys-check / audit JSON; any format defect blocks delivery",
    )
    g.add_argument(
        "--italic-audit",
        type=Path,
        help="taxostyle / italic_audit.json; major/critical blocks delivery (#33)",
    )
    g.add_argument("--out", type=Path)
    g.set_defaults(func=cmd_gate)

    ts = sub.add_parser(
        "taxostyle",
        help="阶元体例审计：aligned Markdown 斜体 + 可选 DOCX italic_check",
    )
    ts.add_argument("--aligned", type=Path, required=True)
    ts.add_argument("--docx", type=Path, help="成品 DOCX（可与 --pdf 同名自动发现）")
    ts.add_argument("--pdf", type=Path, help="用于推断同名 .docx")
    ts.add_argument("--out", type=Path)
    ts.set_defaults(func=cmd_taxostyle)

    kc = sub.add_parser(
        "keys-check",
        help="strict identification-key format check on aligned JSON (delivery blocker)",
    )
    kc.add_argument("--aligned", type=Path, required=True)
    kc.add_argument("--out", type=Path)
    kc.add_argument(
        "--lenient",
        action="store_true",
        help="only flag couplets that clearly need a tab (not for release)",
    )
    kc.set_defaults(func=cmd_keys_check)

    ak = sub.add_parser(
        "apply-keys",
        help="rebuild identification-key pages from docstore keys.json as couplet blocks",
    )
    ak.add_argument("--aligned", type=Path, required=True)
    ak.add_argument("--keys", type=Path, required=True, help="docstore keys extract output")
    ak.add_argument("--tr", type=Path, help="translation sidecar (keys_translate.py collect)")
    ak.add_argument("--lang", choices=["en", "zh"], required=True)
    ak.add_argument("--names", type=Path, help="families.tsv: ja group, Latin, zh name")
    ak.add_argument("--genera", type=Path,
                    help="extra genus names (one per line) for splitting OCR-fused binomials")
    ak.add_argument("--out", type=Path, help="write report + defects here")
    ak.add_argument("--dry", action="store_true", help="do not write aligned.json")
    ak.add_argument("--allow-defects", action="store_true", help="exit 0 even if the audit finds defects")
    ak.set_defaults(func=cmd_apply_keys)

    rk = sub.add_parser(
        "repair-keys",
        help="fix key roles/markers/leaders on aligned JSON (deterministic)",
    )
    rk.add_argument("--aligned", type=Path, required=True)
    rk.add_argument("--out", type=Path, help="default: rewrite --aligned")
    rk.add_argument("--report", type=Path)
    rk.set_defaults(func=cmd_repair_keys)

    rs = sub.add_parser(
        "restore",
        help="OCR line boxes -> vector PDF with original page geometry (1:1 restore)",
    )
    rs.add_argument("--pdf", type=Path, required=True, help="source scanned PDF")
    rs.add_argument("--pages", default="1", help="e.g. 1-50 or 1,3,5-7 (1-based)")
    rs.add_argument("--font", type=Path, help="TTF to use (default: built-in Times)")
    rs.add_argument("--out", type=Path, required=True, help="output PDF (never overwritten)")
    rs.add_argument("--cache-dpi", type=int, default=200, help="PP-OCR cache dpi")
    rs.add_argument("--report", type=Path, help="write restore report JSON")
    rs.set_defaults(func=cmd_restore)

    au = sub.add_parser(
        "audit",
        help="static layout audit on aligned JSON only (keys + text roles; no PDF)",
    )
    au.add_argument("--aligned", type=Path, required=True)
    au.add_argument("--metadata", type=Path)
    au.add_argument("--out", type=Path, required=True)
    au.add_argument("--title")
    au.set_defaults(func=cmd_audit)
    return ap


def cmd_restore(args: argparse.Namespace) -> int:
    import fitz

    from .restore import parse_pages, restore_pdf

    with fitz.open(str(args.pdf)) as d:
        pages = parse_pages(args.pages, d.page_count)
    rep = restore_pdf(
        args.pdf, pages, args.out,
        font=str(args.font) if args.font else None,
        cache_dpi=args.cache_dpi, report=args.report,
    )
    print(json.dumps({k: rep[k] for k in ("out", "n_pages", "font")}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
