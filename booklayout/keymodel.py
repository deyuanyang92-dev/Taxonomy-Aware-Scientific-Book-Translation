"""Structured dichotomous-key model for source and translation (issue #11, #38).

A key is a list of *couplet branches*: ``lead`` (``"3"``, alternate ``"3'"``),
``text``, ``target`` (jump number, page reference or taxon name) and the page
the branch starts on.  The same model is filled from

* page-marked text (``<!-- PDF p.N -->``, one branch per line), source or
  translation (``parse_key_text``), and
* ``docstore keys`` output (``from_docstore``),

so source and translation are compared branch by branch (``align_keys``), not
by word counts.  ``render_key`` writes branches as aligned paragraphs (hanging
lead column, dot leader, right-aligned target) and keeps a couplet pair on
one page.  ``validate_key`` is the source-side graph check: every N has N',
every branch has a target, every jump number exists, no lead repeats.

Limits: ``parse_key_text`` needs one branch per line (as PDF text extraction
and the markdown masters give).  Flat one-line pages must be split first.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PAGE_MARK = re.compile(r"<!--\s*PDF p\.(\d+)\s*-->")
LEADER = re.compile(r"(?:[.…·]\s*){3,}")
BULLET = "•·▪●–—-"
LEAD_RE = re.compile(
    rf"^\s*(?:(?P<bullet>[{re.escape(BULLET)}])|(?P<num>\d{{1,3}})(?P<prime>['’′]?)[.．])\s+")
HEADING_RE = re.compile(r"^\s*(?:#+\s*)?(?:Key\b|Keys\b|Clave\b|Claves\b|Bestimmungsschl|Cl[eé]\b|検索|检索|檢索)", re.I)
JUMP_RE = re.compile(r"^\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?$")
RUNNING_HEAD = re.compile(r"^\s*(?:\d{1,4}\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,.\-]{3,}|[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,.\-]{3,}\s+\d{1,4})\s*$")
PAGE_ONLY = re.compile(r"^\s*(?:\d{1,4}|[ivxlc]+)\s*$", re.I)
TRAIL_TARGET = re.compile(r"\s(?P<t>\d{1,3}['’′]?|\(p+\.\s*\d+(?:[-–]\d+)?\)|p+\.\s*\d+)\s*$")
LATIN = re.compile(r"\b[A-Z][a-z]+(?:\s+[a-z]{3,})?\b")


@dataclass
class Branch:
    lead: str
    text: str
    target: str
    page: int
    marker: str = ""
    kind: str = ""  # jump | page | taxon | "" (no target)

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Key:
    heading: str
    branches: list[Branch] = field(default_factory=list)
    first_page: int = 0
    last_page: int = 0
    closed_by: str = ""

    def asdict(self) -> dict[str, Any]:
        return {"heading": self.heading, "first_page": self.first_page, "last_page": self.last_page,
                "closed_by": self.closed_by, "branches": [b.asdict() for b in self.branches]}


def classify_target(target: str) -> str:
    t = target.strip()
    if not t:
        return ""
    if JUMP_RE.match(t):
        return "jump"
    if re.fullmatch(r"\(?pp?\.\s*\d+(?:\s*[-–]\s*\d+)?\)?", t):
        return "page"
    return "taxon"


def _split_target(text: str) -> tuple[str, str]:
    m = None
    for m in LEADER.finditer(text):
        pass  # keep the last leader run: text before it may itself contain ellipses
    if m is not None and text[m.end():].strip():
        return text[:m.start()].strip(), text[m.end():].strip()
    t = TRAIL_TARGET.search(text)
    if t:
        return text[:t.start()].strip(), t.group("t").strip()
    return text.strip(), ""


class _Open:
    """Branch under construction (wrapped lines are appended until a target)."""

    def __init__(self, lead: str, marker: str, text: str, page: int) -> None:
        self.lead, self.marker, self.text, self.page = lead, marker, text, page

    def add(self, more: str) -> None:
        a, b = self.text, more
        self.text = a[:-1] + b if a.endswith("-") and b[:1].islower() else f"{a} {b}".strip()

    def done(self) -> Branch:
        left, target = _split_target(self.text)
        return Branch(self.lead, left, target, self.page, self.marker, classify_target(target))


def parse_key_text(markdown: str, first_heading: bool = False,
                   heading_re: re.Pattern[str] = HEADING_RE,
                   skip_line: re.Pattern[str] | None = None) -> list[Key]:
    """Parse page-marked text into keys.

    A key opens at a heading line, or at the first branch line when no heading
    is open.  It closes at the next heading or at a non-branch line that
    follows a complete branch (page numbers and ``skip_line`` matches are
    skipped).  Bullets continue the previous number as its alternate.
    """
    keys: list[Key] = []
    key: Key | None = None
    cur: _Open | None = None
    page = 0
    last_num = ""
    pending_heading = ""
    fresh_page = False

    def flush() -> None:
        nonlocal cur
        if cur is not None and key is not None:
            key.branches.append(cur.done())
            key.last_page = max(key.last_page, cur.page)
        cur = None

    def close(why: str) -> None:
        nonlocal key
        flush()
        if key is not None:
            key.closed_by = why
        key = None

    for raw in markdown.splitlines():
        pm = PAGE_MARK.search(raw)
        if pm:
            page = int(pm.group(1))
            fresh_page = True
            continue
        line = raw.strip()
        first_on_page, fresh_page = fresh_page and bool(line), fresh_page and not line
        if first_on_page and RUNNING_HEAD.match(line):
            continue
        if not line or PAGE_ONLY.match(line) or (skip_line and skip_line.search(line)):
            continue
        if heading_re.match(line) and not LEAD_RE.match(line):
            close("heading")
            pending_heading = line.lstrip("# ").strip()
            continue
        lm = LEAD_RE.match(line)
        if lm:
            if key is None:
                key = Key(pending_heading, first_page=page, last_page=page)
                keys.append(key)
                pending_heading = ""
                last_num = ""
            flush()
            if lm.group("bullet"):
                lead = last_num + "'" if last_num else "?"
                marker = lm.group("bullet")
            else:
                lead = lm.group("num") + ("'" if lm.group("prime") else "")
                marker = lm.group("num") + lm.group("prime") + "."
                if not lm.group("prime"):
                    last_num = lm.group("num")
            cur = _Open(lead, marker, line[lm.end():].strip(), page)
            continue
        if key is None:
            continue
        if cur is not None and not _split_target(cur.text)[1]:
            cur.add(line)  # wrapped text of an incomplete branch
        else:
            close("text")
    close("eof")
    return keys


def from_docstore(data: Mapping[str, Any]) -> list[Key]:
    """Build keys from ``docstore keys extract`` output (``keys.json``)."""
    keys: dict[Any, Key] = {}
    for c in data["couplets"]:
        k = keys.setdefault(c["key"], Key("", first_page=c["page"], last_page=c["page"]))
        tgt = " ".join(c.get("terminals") or [])
        k.branches.append(Branch(str(c["lead"]), c["text"], tgt, int(c["page"]), "", classify_target(tgt)))
        k.last_page = max(k.last_page, int(c["page"]))
    for lay_page, items in (data.get("layout") or {}).items():
        for it in items:
            if it.get("t") == "heading" and it.get("key") in keys and not keys[it["key"]].heading:
                keys[it["key"]].heading = it["text"]
    return list(keys.values())


def _num(lead: str) -> str:
    return lead.rstrip("'")


def validate_key(key: Key) -> list[str]:
    """Source-side graph check; each message names the lead and page."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for b in key.branches:
        seen[b.lead] = seen.get(b.lead, 0) + 1
        if not b.target:
            out.append(f"no target: {b.lead} p{b.page}")
    out += [f"duplicate lead: {lead}" for lead, n in seen.items() if n > 1]
    for b in key.branches:
        if "'" not in b.lead and b.lead + "'" not in seen:
            out.append(f"missing alternate for {b.lead} p{b.page}")
        if b.kind == "jump" and _num(b.target.split("-")[0].strip()) not in {_num(x) for x in seen}:
            out.append(f"dangling jump {b.target} from {b.lead} p{b.page}")
    return out


def _latin(text: str) -> list[str]:
    return sorted(set(LATIN.findall(text)))


def align_keys(src: Sequence[Key], tgt: Sequence[Key]) -> list[dict[str, Any]]:
    """Branch-by-branch comparison of source and translated keys.

    Findings: ``key_count``, ``missing_branch``, ``extra_branch``,
    ``duplicate_branch``, ``order_changed``, ``target_changed`` (jump/page
    numbers must be identical; taxon targets compare their Latin names),
    ``page_changed`` (informational: the page may legitimately differ).
    """
    out: list[dict[str, Any]] = []
    if len(src) != len(tgt):
        out.append({"code": "key_count", "src": len(src), "tgt": len(tgt)})
    for ki, (s, t) in enumerate(zip(src, tgt), start=1):
        tcount: dict[str, int] = {}
        for b in t.branches:
            tcount[b.lead] = tcount.get(b.lead, 0) + 1
        tmap = {b.lead: b for b in t.branches}
        for lead, n in tcount.items():
            if n > 1:
                out.append({"code": "duplicate_branch", "key": ki, "lead": lead, "count": n})
        for b in s.branches:
            o = tmap.get(b.lead)
            if o is None:
                out.append({"code": "missing_branch", "key": ki, "lead": b.lead, "page": b.page})
                continue
            if b.kind in ("jump", "page") or o.kind in ("jump", "page"):
                if _norm_t(b.target) != _norm_t(o.target):
                    out.append({"code": "target_changed", "key": ki, "lead": b.lead,
                                "src": b.target, "tgt": o.target})
            elif b.target and (_latin(b.target) != _latin(o.target)
                               or re.findall(r"\d+", b.target) != re.findall(r"\d+", o.target)):
                out.append({"code": "target_changed", "key": ki, "lead": b.lead,
                            "src": b.target, "tgt": o.target})
        sl = {b.lead for b in s.branches}
        out += [{"code": "extra_branch", "key": ki, "lead": b.lead} for b in t.branches if b.lead not in sl]
        so = [b.lead for b in s.branches if b.lead in tmap]
        to = [b.lead for b in t.branches if b.lead in sl]
        if so != to and sorted(so) == sorted(to):
            out.append({"code": "order_changed", "key": ki, "src": so, "tgt": to})
    return out


def _norm_t(t: str) -> str:
    return re.sub(r"[\s’′]", lambda m: "'" if m.group() in "’′" else "", t)


def render_key(doc: Any, key: Key, size: float = 9.5, genera: Iterable[str] | None = None,
               heading_size: float = 10.5) -> list[Any]:
    """Write a key as aligned paragraphs; return them.

    One paragraph per branch via ``builder.tabbed`` (no first-line indent,
    taxon-name column, right-aligned target behind a dot leader).  A branch
    is kept with its alternate (``keep_with_next`` on the first of a pair) and
    never split (``keep_together``), so a couplet does not straddle a page.
    """
    from docx.shared import Pt

    from .builder import _add_par, style_pt, tabbed

    paras: list[Any] = []
    if key.heading:
        p = _add_par(doc, "Key Heading")  # size/bold/keep_with_next live in the style
        r = p.add_run(key.heading)
        r.bold = True  # also direct: callers/tests read the run, not the style
        p.paragraph_format.keep_with_next = True
        if abs(heading_size - style_pt("Key Heading")) > 0.005:
            r.font.size = Pt(heading_size)
        paras.append(p)
    gen = set(genera) if genera else None
    for i, b in enumerate(key.branches):
        marker = b.marker or (b.lead + ".")
        left = f"{marker} {b.text}".strip()
        p = tabbed(doc, left, b.target or "", size, 0.0, gen, force_break=False)
        p.paragraph_format.keep_together = True
        nxt = key.branches[i + 1] if i + 1 < len(key.branches) else None
        if nxt is not None and "'" not in b.lead and nxt.lead == b.lead + "'":
            p.paragraph_format.keep_with_next = True
        paras.append(p)
    return paras


def key_blocks(keys: Sequence[Key], prefix: str = "K") -> list[dict[str, Any]]:
    """Translation units: one per branch, target kept verbatim and separate.

    The model translates ``text`` only; ``target`` and ``lead`` are copied
    back by the caller, so a jump number or taxon name cannot drift.
    """
    out = []
    for ki, k in enumerate(keys, start=1):
        if k.heading:
            out.append({"id": f"{prefix}{ki}-h", "key": ki, "kind": "heading", "text": k.heading})
        for b in k.branches:
            out.append({"id": f"{prefix}{ki}-{b.lead}", "key": ki, "kind": "branch", "lead": b.lead, "marker": b.marker,
                        "text": b.text, "target": b.target, "target_kind": b.kind, "page": b.page})
    return out


def merge_translation(blocks: Sequence[Mapping[str, Any]], translated: Mapping[str, str]) -> list[Key]:
    """Rebuild keys from source blocks plus ``{block id: translated text}``.

    Lead, marker, target and order come from the source blocks; a missing
    translation leaves the branch text empty, which ``check_merge`` reports.
    """
    by_key: dict[Any, Key] = {}
    for b in blocks:
        k = by_key.setdefault(b["key"], Key(""))
        if b["kind"] == "heading":
            k.heading = translated.get(b["id"], "")
            continue
        k.branches.append(Branch(b["lead"], translated.get(b["id"], ""), b["target"], b["page"],
                                 b["marker"], b["target_kind"]))
    return list(by_key.values())


def check_merge(keys: Sequence[Key]) -> list[str]:
    return [f"empty translation: {b.lead} p{b.page}" for k in keys for b in k.branches if not b.text.strip()]


def add_parser(sub: Any) -> None:
    k = sub.add_parser("key-model", help="parse keys from page-marked text; validate and align source vs translation")
    k.add_argument("--source", type=Path, required=True, help="source markdown with <!-- PDF p.N --> markers")
    k.add_argument("--translation", type=Path, help="translated markdown with the same markers")
    k.add_argument("--out", type=Path, help="write JSON report (keys, validation, alignment, blocks)")
    k.add_argument("--expect-keys", action="store_true",
                   help="source is declared to contain keys; zero recognised keys fails (auto if a key heading is present)")
    k.add_argument("--entries", help="comma-separated expected entry numbers, e.g. 1,5")
    k.set_defaults(func=cmd_key_model)


def _sided(findings: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """Tag gate findings with the side (source/translation) so a double no_keys is readable."""
    return [{**f, "side": side, "detail": f"{side}: {f.get('detail', '')}"} for f in findings]


def _graph_report(args: Any, report: dict[str, Any]) -> int:
    """Add report["graph"] from booklayout.keygraph; return the number of error-severity findings."""
    from . import keygraph

    src_md = args.source.read_text(encoding="utf-8")
    entries = [e.strip() for e in (getattr(args, "entries", None) or "").split(",") if e.strip()] or None
    expect = bool(getattr(args, "expect_keys", False)) or bool(entries) or any(
        keygraph.HEADING_RE.match(ln) for ln in src_md.splitlines())
    sk = keygraph.parse_text(src_md)
    graph: dict[str, Any] = {"expect_keys": expect, "source_keys": len(sk),
                             "source_branches": sum(len(k.branches) for k in sk), "source": [], "translation": [],
                             "alignment": [], "gate": _sided(keygraph.gate(sk, expect), "source")}
    for i, k in enumerate(sk, 1):
        graph["source"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
    couplets = {b.couplet for k in sk for b in k.branches}
    for e in entries or []:  # a declared entry that no recognised key contains
        if sk and e not in couplets:
            graph["gate"].append({**keygraph._f("dangling_jump", "error", e,
                                                f"declared entry {e} is not in any recognised key"), "entry": e})
    if args.translation:
        tk = keygraph.parse_text(args.translation.read_text(encoding="utf-8"))
        graph["translation_keys"] = len(tk)
        for i, k in enumerate(tk, 1):
            graph["translation"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
        graph["alignment"] = keygraph.align(sk, tk)
        if expect and not tk:
            graph["gate"] += _sided(keygraph.gate(tk, True), "translation")
    items = graph["source"] + graph["translation"] + graph["alignment"] + graph["gate"]
    graph["errors"] = sum(1 for f in items if f.get("severity") == "error")
    graph["warnings"] = sum(1 for f in items if f.get("severity") == "warn")
    report["graph"] = graph
    return int(graph["errors"])


def _fail_report(args: Any, what: str, err: Exception) -> int:
    """Structured failure (unreadable input) instead of a traceback; keeps the gate-readable shape."""
    report = {"ok": False, "error": f"{what} unreadable: {err}",
              "graph": {"errors": 1, "warnings": 0, "source_keys": 0, "source_branches": 0,
                        "gate": [{"code": "unreadable_input", "severity": "error", "lead": "",
                                  "detail": f"{what}: {err}"}]}}
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"key-model: {report['error']}")
    return 1


def cmd_key_model(args: Any) -> int:
    for what, path in (("source", args.source), ("translation", args.translation)):
        if path is not None and not path.is_file():
            return _fail_report(args, what, FileNotFoundError(str(path)))
    try:
        src = parse_key_text(args.source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as e:
        return _fail_report(args, "source", e)
    report: dict[str, Any] = {"source_keys": [k.asdict() for k in src],
                              "source_problems": {str(i): validate_key(k) for i, k in enumerate(src, 1)},
                              "blocks": key_blocks(src)}
    findings: list[dict[str, Any]] = []
    if args.translation:
        try:
            tgt = parse_key_text(args.translation.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as e:
            return _fail_report(args, "translation", e)
        findings = align_keys(src, tgt)
        report["translation_keys"] = [k.asdict() for k in tgt]
        report["alignment"] = findings
    graph_bad = _graph_report(args, report)
    bad = sum(len(v) for v in report["source_problems"].values()) + len(findings) + graph_bad
    report["ok"] = bad == 0
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    g = report["graph"]
    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} problems={bad} "
          f"graph_keys={g['source_keys']} graph_errors={g['errors']} graph_warn={g['warnings']}")
    return 0 if bad == 0 else 1
