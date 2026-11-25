"""Per-edition trace database: find where any text came from and went wrong.

Problem (2026-11-25, Vol.21 EN/ZH key tables lost "..... 2" targets): to locate
one defect an agent had to open aligned files, Google output, page maps and
PDFs by hand.  `booklayout make` now writes `<name>.work/trace.db` (SQLite)
and these commands query it in one step:

  trace find  <db> "Eusyllinae"      any text, any language, any stage -> block, page, PDF page
  trace block <db> p046_b06          full lineage of one block + qa issues + edits
  trace set   <db> p046_b06 --text T --reason R   fix final text; logged, db refreshed

Lineage: `translate-aligned` writes top-level `lineage` (derived_from, stage) so
the chain  OCR -> corrected ES -> Google EN  is followed automatically.
Edits go to `edits.jsonl` next to the db (survives rebuilds, replayed on build).
Flags: digits/page targets present in an earlier stage but absent in the final.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

_NUM = re.compile(r"\d+")
SCHEMA = """
CREATE TABLE stage(idx INT, label TEXT, path TEXT, info TEXT);
CREATE TABLE blk(stage INT, block_id TEXT, page INT, ord INT, role TEXT, text TEXT, translation TEXT);
CREATE TABLE pdfpage(pdf_page INT, text TEXT);
CREATE TABLE blockmap(block_id TEXT, pdf_page INT);
CREATE TABLE issue(src TEXT, kind TEXT, page INT, block_id TEXT, detail TEXT);
CREATE TABLE edit(ts TEXT, block_id TEXT, field TEXT, old TEXT, new TEXT, reason TEXT);
CREATE INDEX i_blk ON blk(block_id);
"""


def _chain(aligned: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Final aligned first, then each ancestor via top-level `lineage.derived_from`."""
    out, seen = [], set()
    p: Path | None = aligned
    while p and p.exists() and str(p) not in seen:
        seen.add(str(p))
        data = json.loads(p.read_text(encoding="utf8"))
        out.append((p, data))
        d = (data.get("lineage") or {}).get("derived_from")
        p = Path(d) if d else None
    return out


def lost_numbers(src: str, dst: str) -> list[str]:
    """Digit runs in `src` that do not occur (with multiplicity) in `dst`."""
    c = Counter(_NUM.findall(src or "")) - Counter(_NUM.findall(dst or ""))
    return sorted(c.elements())


_LEAD = r"(?:\.{3,}|…+|(?:\.\s){3,})"
_TARGET_END = re.compile(_LEAD + r"\s*(?:[^.…\n]*?\(\s*(?:p|pág|页|第)?\.?\s*(\d+)\s*\)|(\d{1,3}))\s*$", re.M)
_KEY_ROLES = {"key", "couplet", "index"}


def _targets(s: str) -> list[str]:
    """Trailing key targets of every line: "..... 3" -> "3"; "..... Eusyllinae (p. 47)" -> "47"."""
    return [a or b for a, b in _TARGET_END.findall(s or "")]


def key_target_losses(aligned: Path) -> list[dict[str, Any]]:
    """Key/index lines whose trailing target exists in the source text or an upstream stage
    but is missing from the final translation (H9: ES corrections not reaching Google)."""
    chain = _chain(aligned)
    up: dict[str, list[str]] = {}
    for _p, data in chain[1:]:
        for pg in data.get("pages", []):
            for b in pg.get("blocks", []):
                # corrected source (translation of the upstream stage) wins over raw OCR text
                up.setdefault(b.get("block_id") or "", []).append(b.get("translation") or b.get("text") or "")
    out = []
    for pg in chain[0][1].get("pages", []):
        for b in pg.get("blocks", []):
            if b.get("role") not in _KEY_ROLES or not b.get("translation"):
                continue
            srcs = up.get(b.get("block_id") or "") or [b.get("text") or ""]
            want = {t for s in srcs for t in _targets(s)}
            have = set(_targets(b["translation"]))
            lost = sorted(want - have)
            if lost:
                out.append({"page": pg.get("page"), "block_id": b.get("block_id"), "lost": lost})
    return out


def _issues(wk: Path) -> list[tuple[str, str, Any, str, str]]:
    rows: list[tuple[str, str, Any, str, str]] = []
    for name in ("qa", "check", "gate", "key"):
        f = wk / f"{name}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf8"))
        for k, v in d.items():
            if k == "problems" and isinstance(v, list):
                rows += [(name, "problem", None, "", str(x)[:300]) for x in v]
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                for it in v:
                    rows.append((name, k, it.get("page"), str(it.get("block_id") or ""),
                                 json.dumps(it, ensure_ascii=False)[:300]))
            elif isinstance(v, list) and v:
                rows += [(name, k, None, "", str(x)[:300]) for x in v]
    return rows


def build(aligned: Path, db: Path, pdf: Path | None = None, wk: Path | None = None) -> dict[str, Any]:
    wk = wk or db.parent
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    chain = _chain(aligned)
    for i, (p, data) in enumerate(chain):
        lin = data.get("lineage") or {}
        label = "final" if i == 0 else f"ancestor{i}"
        con.execute("INSERT INTO stage VALUES(?,?,?,?)", (i, label, str(p), json.dumps(lin, ensure_ascii=False)))
        for pg in data.get("pages", []):
            for j, b in enumerate(pg.get("blocks", [])):
                con.execute("INSERT INTO blk VALUES(?,?,?,?,?,?,?)", (
                    i, b.get("block_id") or "", pg.get("page"), j, b.get("role"),
                    b.get("text") or "", b.get("translation") or ""))
    pm = wk / "page_map.json"
    if pm.exists():
        for k, v in json.loads(pm.read_text(encoding="utf8")).items():
            if k.startswith("block:"):
                con.execute("INSERT INTO blockmap VALUES(?,?)", (k[6:], v))
    if pdf and pdf.exists():
        txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        for n, t in enumerate(txt.split("\f"), 1):
            if t.strip():
                con.execute("INSERT INTO pdfpage VALUES(?,?)", (n, t))
    con.executemany("INSERT INTO issue VALUES(?,?,?,?,?)", _issues(wk))
    ej = wk / "edits.jsonl"
    if ej.exists():
        for line in ej.read_text(encoding="utf8").splitlines():
            e = json.loads(line)
            con.execute("INSERT INTO edit VALUES(?,?,?,?,?,?)", (e["ts"], e["block_id"], e["field"], e["old"], e["new"], e["reason"]))
    con.commit()
    n = con.execute("SELECT count(*) FROM blk WHERE stage=0").fetchone()[0]
    con.close()
    return {"db": str(db), "stages": len(chain), "blocks": n}


def _stages(con: sqlite3.Connection) -> dict[int, str]:
    return {i: lab for i, lab in con.execute("SELECT idx,label FROM stage")}


def lineage(con: sqlite3.Connection, block_id: str) -> dict[str, Any]:
    st = _stages(con)
    rows = con.execute("SELECT stage,page,role,text,translation FROM blk WHERE block_id=? ORDER BY stage", (block_id,)).fetchall()
    layers = [{"stage": st[s], "page": pg, "role": r, "text": t, "translation": tr} for s, pg, r, t, tr in rows]
    flags = []
    if layers:
        fin = layers[0]["translation"] or layers[0]["text"]
        for lay in layers:
            for field in ("text", "translation"):
                if lay is layers[0] and field == "translation":
                    continue
                lost = lost_numbers(lay[field], fin)
                if lost and lay[field]:
                    flags.append(f"digits lost vs final: {lost} (in {lay['stage']}.{field})")
                    break
    pm = con.execute("SELECT pdf_page FROM blockmap WHERE block_id=?", (block_id,)).fetchone()
    return {"block_id": block_id, "pdf_page": pm[0] if pm else None, "layers": layers, "flags": flags,
            "issues": [dict(zip(("src", "kind", "page", "detail"), r)) for r in con.execute(
                "SELECT src,kind,page,detail FROM issue WHERE block_id=?", (block_id,))],
            "edits": [dict(zip(("ts", "field", "old", "new", "reason"), r)) for r in con.execute(
                "SELECT ts,field,old,new,reason FROM edit WHERE block_id=?", (block_id,))]}


def find(con: sqlite3.Connection, q: str, limit: int = 20) -> list[dict[str, Any]]:
    like = f"%{q}%"
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT block_id FROM blk WHERE block_id!='' AND (text LIKE ? OR translation LIKE ?) "
        "ORDER BY page,ord LIMIT ?", (like, like, limit))]
    hits = [lineage(con, i) for i in ids]
    pdf_only = [r[0] for r in con.execute("SELECT pdf_page FROM pdfpage WHERE text LIKE ?", (like,))]
    return [{"query": q, "pdf_pages_with_text": pdf_only, "blocks": hits}] if hits or pdf_only else []


def _snip(s: str, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", s or "")
    return s if len(s) <= n else s[: n // 2] + " … " + s[-(n // 2 - 3):]  # keep the tail: page targets live there


def show(res: dict[str, Any]) -> None:
    print(f"{res['block_id']}  PDF p.{res['pdf_page']}")
    for lay in res["layers"]:
        print(f"  [{lay['stage']:9}] p{lay['page']} {lay['role']}")
        print(f"      text : {_snip(lay['text'])}")
        print(f"      trans: {_snip(lay['translation'])}")
    for f in res["flags"]:
        print("  FLAG", f)
    for i in res["issues"]:
        print("  ISSUE", i["src"], i["kind"], _snip(i["detail"], 140))
    for e in res["edits"]:
        print("  EDIT", e["ts"], e["field"], "|", e["reason"])


def set_text(db: Path, aligned: Path, block_id: str, field: str, text: str, reason: str) -> dict[str, Any]:
    """Edit the final aligned file in place (first time: .bak) and log to edits.jsonl."""
    data = json.loads(aligned.read_text(encoding="utf8"))
    for pg in data["pages"]:
        for b in pg["blocks"]:
            if b.get("block_id") == block_id:
                bak = aligned.with_suffix(aligned.suffix + ".bak")
                if not bak.exists():
                    bak.write_text(aligned.read_text(encoding="utf8"), encoding="utf8")
                e = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "block_id": block_id, "field": field,
                     "old": b.get(field, ""), "new": text, "reason": reason}
                b[field] = text
                aligned.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
                with (db.parent / "edits.jsonl").open("a", encoding="utf8") as fh:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
                return e
    raise SystemExit(f"block not found in {aligned}: {block_id}")


def _db(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"no trace db: {p} (run booklayout make, or trace build)")
    return sqlite3.connect(p)


def run(args: argparse.Namespace) -> int:
    if args.tcmd == "build":
        print(json.dumps(build(args.aligned, args.db, args.pdf), ensure_ascii=False))
    elif args.tcmd == "find":
        res = find(_db(args.db), args.query, args.limit)
        if not res:
            print("no hit")
            return 1
        print(f"PDF pages containing text: {res[0]['pdf_pages_with_text']}")
        for h in res[0]["blocks"]:
            show(h)
    elif args.tcmd == "block":
        show(lineage(_db(args.db), args.block_id))
    elif args.tcmd == "set":
        print(json.dumps(set_text(args.db, args.aligned, args.block_id, args.field, args.text, args.reason), ensure_ascii=False))
        print("now: booklayout make ... (db refreshed on make) or trace build")
    return 0


def add_parser(sub: Any) -> None:
    t = sub.add_parser("trace", help="per-edition trace db: find/block/set (where did this text come from?)")
    ts = t.add_subparsers(dest="tcmd", required=True)
    b = ts.add_parser("build")
    b.add_argument("--aligned", type=Path, required=True)
    b.add_argument("--db", type=Path, required=True)
    b.add_argument("--pdf", type=Path)
    f = ts.add_parser("find")
    f.add_argument("db")
    f.add_argument("query")
    f.add_argument("--limit", type=int, default=20)
    k = ts.add_parser("block")
    k.add_argument("db")
    k.add_argument("block_id")
    s = ts.add_parser("set")
    s.add_argument("db", type=Path)
    s.add_argument("block_id")
    s.add_argument("--aligned", type=Path, required=True)
    s.add_argument("--field", default="translation")
    s.add_argument("--text", required=True)
    s.add_argument("--reason", required=True)
    t.set_defaults(func=run)
