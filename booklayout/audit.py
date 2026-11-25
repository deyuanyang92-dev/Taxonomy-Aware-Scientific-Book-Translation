"""Read-only whole-book defect audit: one run, one table of counts.

Replaces "one defect class per full rebuild" (postmortem 2026-11-17, P0).
Text checks run on the aligned JSON alone; layout checks (key leaders,
caption gap, caption word breaks) additionally need the rendered PDF and
reuse the existing cli checks.  Nothing is written except optional stdout.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LEADER = r"(?:…+|\.{3,}|(?:\.\s){3,}\.?)"
_LEADER_RUN = re.compile(LEADER)
_TARGET = r"(?:\(p\.\s*\d+\)|\d{1,3})"
# a target followed by a new couplet marker on the same line = two entries
_INLINE = re.compile(LEADER + r"\s*" + _TARGET + r"\s+(?:•|—|\d{1,2}\.)\s*\S")
_ENDS_TARGET = re.compile(r"(\S*?)\s*([.…·]+(?:\s[.…·])*)\s*" + _TARGET + r"\s*$")
_TARGET_END = re.compile(_TARGET + r"\s*$")
_STARTS_LEADER = re.compile(r"^\s*" + LEADER)
_ENDS_LEADER = re.compile(LEADER + r"\s*$")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_KANA = re.compile(r"[぀-ヿ]")
_ES_STOP = re.compile(r"\b(?:el|la|los|las|del|con|una|por|para|sin|que|se|es|y)\b", re.I)
_PROSE_ROLES = {"body", "entry", "heading", "caption", "note", "key"}
LIMIT = 5  # examples kept per item
ITEMS = [
    ("key_inline", "检索表内联（一行含多条目）"),
    ("key_split", "检索表拆行（引导点无页码/页码无引导点）"),
    ("key_short_leader", "短引导点（文本级）"),
    ("caption_text_breaks", "图注断词（软连字符/行尾连字符）"),
    ("duplicate_paragraphs", "重复段（同页）"),
    ("truncated_endings", "截断句"),
    ("source_residue", "源语言残留"),
    ("uncovered_blocks", "覆盖率缺口（有原文无译文）"),
    ("pdf_key_layout", "PDF 检索表版面"),
    ("pdf_tight_caption_gaps", "PDF 图注与图间距过小"),
    ("pdf_caption_word_breaks", "PDF 图注断词"),
]


def _blocks(data: dict):
    for page in data.get("pages", []):
        for block in page.get("blocks", []):
            yield page.get("page"), block


def _tr(block: dict) -> str:
    return (block.get("translation") or "").strip()


def detect_source_lang(data: dict) -> str:
    """ja / es / unknown, from the source texts themselves."""
    text = " ".join((b.get("text") or "") for _, b in _blocks(data))[:200000]
    if not text.strip():
        return "unknown"
    if len(_KANA.findall(text)) / max(len(text), 1) > 0.02:
        return "ja"
    words = re.findall(r"[^\W\d_]+", text)
    if words and len(_ES_STOP.findall(text)) / len(words) > 0.12:
        return "es"
    return "unknown"


def _ex(page, block: dict, **extra) -> dict:
    return {"page": page, "block_id": block.get("block_id"), **extra}


def _key_checks(data: dict) -> tuple[list, list, list]:
    inline: list = []
    split: list = []
    short: list = []
    for page, block in _blocks(data):
        if block.get("role") != "key" or not _tr(block):
            continue
        for line in _tr(block).splitlines():
            line = line.strip()
            if not line:
                continue
            if _INLINE.search(line) or len(_LEADER_RUN.findall(line)) >= 2:
                inline.append(_ex(page, block, text=line[:120]))
            if _ENDS_LEADER.search(line) or (
                    _STARTS_LEADER.search(line) and not _TARGET_END.search(line)):
                split.append(_ex(page, block, text=line[:120]))
            m = _ENDS_TARGET.search(line)
            if m and not _LEADER_RUN.search(m.group(2)):
                short.append(_ex(page, block, leader=m.group(2), text=line[:120]))
    return inline, split, short


def _caption_breaks(data: dict) -> list:
    out = []
    for page, block in _blocks(data):
        if block.get("role") != "caption":
            continue
        t = block.get("translation") or ""
        if "­" in t or re.search(r"[A-Za-z]-\s*\n\s*[a-z]", t):
            out.append(_ex(page, block, text=t[:120]))
    return out


def _residue(data: dict, sl: str, tl: str, es_phrases: list) -> list:
    out: list = []
    if sl == "ja":
        for page, block in _blocks(data):
            if block.get("role") in _PROSE_ROLES and _KANA.search(_tr(block)):
                out.append(_ex(page, block, text=_tr(block)[:120]))
    if tl == "en" and sl in ("ja", "es"):
        seen_ids = {x["block_id"] for x in out}
        for page, block in _blocks(data):
            if (block.get("role") != "ref" and _HAN.search(_tr(block))
                    and block.get("block_id") not in seen_ids):
                out.append(_ex(page, block, text=_tr(block)[:120]))
    if sl == "es" and tl != "zh":
        out.extend(es_phrases)
        seen = {x["block_id"] for x in es_phrases}
        for page, block in _blocks(data):
            t = _tr(block)
            words = re.findall(r"[^\W\d_]+", t)
            if (block.get("role") in {"body", "entry", "caption", "note"} and len(words) >= 8
                    and block.get("block_id") not in seen
                    and len(_ES_STOP.findall(t)) / len(words) > 0.25):
                out.append(_ex(page, block, text=t[:120]))
    return out


def _coverage(data: dict) -> tuple[int, int, list]:
    total = done = 0
    missing: list = []
    for page, block in _blocks(data):
        if block.get("_figure_only") or not (block.get("text") or "").strip():
            continue
        if not re.search(r"[^\W\d_]", block["text"]):
            continue
        total += 1
        if _tr(block):
            done += 1
        else:
            missing.append(_ex(page, block, role=block.get("role"), text=block["text"][:100]))
    return total, done, missing


def audit_aligned(data: dict, pdf: Path | None = None, source_lang: str | None = None) -> dict:
    """Return {items: {name: {count, examples}}, coverage: {...}, ...}."""
    from .cli import _pdf_layout_problems, _text_qa  # lazy: cli registers this module

    sl = source_lang or detect_source_lang(data)
    tl = str((data.get("metadata") or {}).get("lang") or "").lower()
    tqa = _text_qa(data)
    inline, split, short = _key_checks(data)
    total, done, missing = _coverage(data)
    found: dict[str, list] = {
        "key_inline": inline,
        "key_split": split,
        "key_short_leader": short,
        "caption_text_breaks": _caption_breaks(data),
        "duplicate_paragraphs": tqa["duplicate_paragraphs"],
        "truncated_endings": tqa["truncated_endings"],
        "source_residue": _residue(data, sl, tl, tqa["spanish_residue"]),
        "uncovered_blocks": missing,
    }
    if pdf is not None:
        lay = _pdf_layout_problems(pdf)
        found["pdf_key_layout"] = lay["key_layout"]
        found["pdf_tight_caption_gaps"] = lay["tight_caption_gaps"]
        found["pdf_caption_word_breaks"] = lay["caption_word_breaks"]
    items = {k: {"count": len(v), "examples": v[:LIMIT]} for k, v in found.items()}
    return {
        "source_lang": sl,
        "target_lang": tl or "unknown",
        "pdf_checked": pdf is not None,
        "coverage": {"source_blocks": total, "translated_blocks": done,
                     "percent": round(100 * done / total, 2) if total else None},
        "items": items,
        "defects_total": sum(v["count"] for v in items.values()),
    }


def format_table(report: dict) -> str:
    labels = dict(ITEMS)
    rows = [("item", "count", "note")]
    cov = report["coverage"]
    rows.append(("coverage", f"{cov['translated_blocks']}/{cov['source_blocks']}",
                 f"{cov['percent']}%"))
    for key, _ in ITEMS:
        if key in report["items"]:
            rows.append((key, str(report["items"][key]["count"]), labels[key]))
        else:
            rows.append((key, "n/a", labels[key] + "（需 --pdf）"))
    rows.append(("TOTAL", str(report["defects_total"]),
                 f"source={report['source_lang']} target={report['target_lang']}"))
    w = max(len(r[0]) for r in rows)
    return "\n".join(f"{r[0]:<{w}}  {r[1]:>9}  {r[2]}" for r in rows)


def cmd_audit(args: argparse.Namespace) -> int:
    data = json.loads(args.aligned.read_text(encoding="utf-8"))
    report = audit_aligned(data, args.pdf, args.source_lang)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_table(report))
    return 1 if args.strict and report["defects_total"] else 0


def add_parser(sub) -> None:
    a = sub.add_parser("audit", help="read-only whole-book defect counts (text + optional PDF layout)")
    a.add_argument("aligned", type=Path)
    a.add_argument("--pdf", type=Path, help="rendered PDF; enables layout counts")
    a.add_argument("--json", action="store_true", help="full JSON with examples")
    a.add_argument("--source-lang", choices=["ja", "es", "unknown"], help="override detection")
    a.add_argument("--strict", action="store_true", help="exit 1 when any defect is counted")
    a.set_defaults(func=cmd_audit)
