"""Fixed-format taxon treatments: aligned.json blocks -> one record per taxon, then validate.

Imajima-style order: Latin name(+author, year) / Japanese name / Chinese name (optional) /
source reference / description / distribution / figure legend / caption (図N).
Deterministic, zero model. `booklayout treatments <aligned.json> [--json]`.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LATIN = re.compile(r"^[A-Z][a-z]+(?: \([A-Z][a-z]+\))?(?: [a-z]+){0,2}\s*[\(\[]?[A-Z][^\n]{0,80}?\d{4}[\)\]]?[\s,.]*$")
LATIN_BARE = re.compile(r"^[A-Z][a-z]+(?: [a-z]+){0,2}$")
KANA = re.compile(r"^[ァ-ヿー・\s（）()新称和名属科亜]+$")
DIST = re.compile(r"^[◆◇]?\s*分布\s*[—―一\-－:：]")
FIGNO = re.compile(r"^(?:図|Fig\.?|图)\s*(\d+)")
LEGEND = re.compile(r"^[a-z]\s*[:：]")
CHN = re.compile(r"[一-鿿]{2,}")
FIELDS = ("latin", "ja", "zh", "ref", "description", "distribution", "legend", "caption")
REQUIRED = ("latin", "ja", "ref", "description", "distribution", "caption")


def _kind(b: dict) -> str:
    t = (b.get("text") or "").strip()
    r = b.get("role")
    if r == "caption" or FIGNO.match(t):
        return "caption"
    if r == "ref":
        return "ref"
    if LATIN.match(t) or (r == "heading" and LATIN_BARE.match(t) and " " in t):
        return "latin"
    if KANA.match(t) and t:
        return "ja"
    if DIST.match(t):
        return "distribution"
    if LEGEND.match(t):
        return "legend"
    if r == "heading":
        return "heading"
    return "description" if t else "empty"


def parse(data: dict) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    pend: dict = {}
    for p in data.get("pages", []):
        for b in p.get("blocks", []):
            k = _kind(b)
            t = (b.get("text") or "").strip()
            if k in ("empty", "heading"):
                continue
            if k == "latin":
                toks = t.split()
                rank = "species" if len(toks) > 1 and toks[1][0].islower() or (
                    len(toks) > 2 and toks[1].startswith("(") and toks[2][0].islower()) else "genus"
                cur = {"page": p.get("page"), "block_id": b.get("block_id"), "latin": t, "rank": rank}
                for k2, v2 in pend.items():
                    cur[k2] = v2
                pend = {}
                out.append(cur)
                continue
            if k == "legend" and cur is None:
                continue
            if k in ("caption", "legend") and (cur is None or cur.get("distribution") or cur["rank"] == "genus"):
                if k == "caption":
                    m = FIGNO.match(t)
                    pend.setdefault("caption", []).append({"no": int(m.group(1)) if m else None, "text": t})
                else:
                    pend.setdefault("legend", []).append(t)
                continue
            if cur is None:
                continue
            if k == "caption":
                m = FIGNO.match(t)
                cur.setdefault("caption", []).append({"no": int(m.group(1)) if m else None, "text": t})
            elif k == "legend":
                cur.setdefault("legend", []).append(t)
            elif k == "ja":
                cur.setdefault("ja", t)
            else:
                cur.setdefault(k, [] if k != "distribution" else [])
                if isinstance(cur[k], list):
                    cur[k].append(t)
    return out


def validate(recs: list[dict]) -> list[dict]:
    issues: list[dict] = []
    for r in recs:
        if r.get("rank") != "species":
            continue
        for f in REQUIRED:
            if not r.get(f):
                issues.append({"code": f"missing_{f}", "page": r["page"], "latin": r["latin"]})
        if r.get("legend") and not r.get("caption"):
            issues.append({"code": "legend_without_caption", "page": r["page"], "latin": r["latin"]})
        if len(r.get("caption", [])) > 1:
            issues.append({"code": "multiple_captions", "page": r["page"], "latin": r["latin"]})
    nos = [c["no"] for r in recs for c in r.get("caption", []) if c["no"] is not None]
    seen: set[int] = set()
    for n in nos:
        if n in seen:
            issues.append({"code": "duplicate_figure_no", "no": n})
        seen.add(n)
    if nos:
        for n in range(min(nos), max(nos) + 1):
            if n not in seen:
                issues.append({"code": "figure_no_gap", "no": n})
    return issues


def cmd(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.aligned).read_text(encoding="utf-8"))
    recs = parse(data)
    iss = validate(recs)
    if args.out:
        Path(args.out).write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.json:
        print(json.dumps({"treatments": len(recs), "issues": iss}, ensure_ascii=False, indent=1))
    else:
        from collections import Counter
        c = Counter(i["code"] for i in iss)
        print(f"treatments={len(recs)}")
        for k, v in sorted(c.items()):
            print(f"{k:28s}{v}")
    return 1 if (args.strict and iss) else 0


def add_parser(sub) -> None:
    p = sub.add_parser("treatments", help="parse fixed-format taxon records and validate")
    p.add_argument("aligned")
    p.add_argument("--out", help="write treatments.json")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd)
