"""Run adversarial corpus against booklayout.keygraph; write report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from booklayout import keygraph as kg  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"


def run_case(case: dict) -> dict:
    src = kg.parse_text(case["source"])
    entries = case.get("declared_entries")
    codes: set[str] = set()
    got_branches = []
    for k in src:
        if entries:
            k.entries = list(entries)
        for f in kg.check(k, entries=entries):
            codes.add(f["code"])
        for b in k.branches:
            tgt = b.jump if b.kind == "jump" else (b.page if b.kind == "page" else b.target)
            got_branches.append([b.lead, b.kind, str(tgt or "")])
    for f in kg.gate(src, expect_keys=bool(entries) or case["expect"].get("keys", 0) > 0):
        codes.add(f["code"])
    if case.get("translation") is not None:  # empty string too: an empty translation must be compared
        tgt = kg.parse_text(case["translation"])
        for k in tgt:
            for f in kg.check(k):
                codes.add(f["code"])
        for f in kg.align(src, tgt):
            codes.add(f["code"])
    exp = case["expect"]
    want = set(exp.get("findings", []))
    errs = []
    if exp.get("keys") is not None and exp["keys"] != len(src):
        errs.append(f"keys want {exp['keys']} got {len(src)}")
    if want != codes:
        errs.append(f"findings missing {sorted(want - codes)} extra {sorted(codes - want)}")
    wb = [[str(x) for x in b] for b in exp.get("branches", [])]
    if wb and wb != got_branches:
        errs.append(f"branches want {wb} got {got_branches}")
    return {"id": case["id"], "ok": not errs, "errs": errs}


def main() -> int:
    res = []
    for p in sorted(CORPUS.glob("*.json")):
        case = json.loads(p.read_text(encoding="utf-8"))
        try:
            res.append(run_case(case))
        except Exception as e:  # noqa: BLE001
            res.append({"id": case.get("id", p.stem), "ok": False, "errs": [f"crash {type(e).__name__}: {e}"]})
    bad = [r for r in res if not r["ok"]]
    out = Path(__file__).parent / "corpus_report.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pass {len(res) - len(bad)}/{len(res)}")
    for r in bad:
        print(r["id"], "|", " ; ".join(r["errs"])[:400])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
