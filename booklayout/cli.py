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
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from .builder import BookMeta, BookPaths, build, load_aligned, make_page_map
from .keyalign import align_document
from .normalize import apply_block_edits, apply_page_patch, backfill_source, normalize_aligned


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
        and not re.match(r"^(?:Fig\b|L[aá]m\b|Tabla\b|Plate\b|图|図|表)",
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

    # 三审覆盖 body + caption/entry/note（交付复盘 P1：原先只扫 body≈25%）
    TEXT_ROLES = frozenset({"body", "caption", "entry", "note"})
    blocks = [
        (p["page"], b)
        for p in data["pages"]
        if (meta is None or p["page"] >= meta.body_start_page)
        and not (skip_after is not None and p["page"] >= skip_after)
        and not is_index_page(p)
        for b in p["blocks"]
        if b.get("role") in TEXT_ROLES and (b.get("translation") or "").strip()
    ]
    body_blocks = [(p, b) for p, b in blocks if b.get("role") == "body"]
    by_role: dict[str, int] = {}
    for _, b in blocks:
        by_role[b.get("role") or "?"] = by_role.get(b.get("role") or "?", 0) + 1
    # Only repeated body paragraphs on the same page are layout errors.
    # Captions/entries often legitimately share short wording across a page.
    normalized = [
        (page, re.sub(r"\s+", " ", b["translation"]).strip())
        for page, b in body_blocks
    ]
    counts = Counter((page, t) for page, t in normalized if len(t) >= 80)
    duplicates = [
        {"page": page, "count": count, "text": text[:160]}
        for (page, text), count in counts.items() if count > 1
    ]
    short = []
    for page, block in blocks:
        source = re.sub(r"\s+", " ", block.get("text") or "").strip()
        translation = re.sub(r"\s+", " ", block.get("translation") or "").strip()
        role = block.get("role") or "body"
        # Captions/notes are shorter; lower the source floor so they are checked.
        floor = 40 if role in {"caption", "note"} else 120
        if len(source) >= floor and len(translation) < 0.25 * len(source):
            short.append({"page": page, "block_id": block.get("block_id"),
                          "role": role,
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
        for page, block in body_blocks
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
    for page, block in body_blocks:
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
            # caption/note 本应含形态词；可疑的是 citation/entry 吞进了描述段
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
        "checked_body_blocks": len(body_blocks),
        "checked_text_blocks": len(blocks),
        "checked_by_role": by_role,
        "text_roles": sorted(TEXT_ROLES),
    }


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


def cmd_gate(args: argparse.Namespace) -> int:
    """Refuse delivery unless every deterministic review is clean."""
    problems: list[str] = []
    for label, path in (("qa", args.qa), ("check", args.check)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            detail = payload.get("problems", [])
            problems.append(f"{label} not ok: {detail}")
    key = json.loads(args.key_report.read_text(encoding="utf-8"))
    if key.get("breaks"):
        problems.append(f"{len(key['breaks'])} key couplets still need a forced break")
    if key.get("defects"):
        problems.append(f"{len(key['defects'])} key leader defects remain")
    report = {"ok": not problems, "problems": problems,
              "files": {"qa": str(args.qa), "check": str(args.check),
                        "key_report": str(args.key_report)}}
    if args.out:
        _write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False))
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
    q.set_defaults(func=cmd_qa)

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
    g.add_argument("--out", type=Path)
    g.set_defaults(func=cmd_gate)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
