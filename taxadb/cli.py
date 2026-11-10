"""taxadb 命令行：split / verify / check / export / status。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

from .db import TREATMENT_COLS, USAGE_COLS, db_path, open_db
from .rules import load_rules
from .split import split_volume, usages

# 关键字段：用于名录、描述前须对原页核对
KEY_FIELDS = ["taxon", "author_year", "zh_name", "pdf_page_start", "地理分布"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _by(a: argparse.Namespace) -> str:
    return a.by or os.environ.get("TAXADB_AGENT") or os.environ.get("DOCSTORE_AGENT") or "unknown"


def _store(a: argparse.Namespace):
    from docstore import open_store
    return open_store(a.root)


def cmd_split(a: argparse.Namespace) -> int:
    rules = load_rules(a.rules)
    st = _store(a)
    doc = st.doc(a.key)
    pages = list(st.pages(a.key))
    res = split_volume(pages, rules, key=a.key)
    ts = res["treatments"]
    for line in res["report"]:
        print("  ·", line)
    n_exp = rules.expected_species
    print(f"{a.key}: 书中种数 {n_exp if n_exp is not None else '未给'}（{rules.inventory_source}），"
          f"清单识出 {len(res['inventory'])}，切分 {len(ts)}")
    if a.dry:
        return 0
    con = open_db(a.db)
    by = _by(a)
    with con:
        # 保留已核字段：重切不丢 field_check
        con.execute("DELETE FROM name_usage WHERE work_id=?", (a.key,))
        con.execute("DELETE FROM treatment WHERE work_id=?", (a.key,))
        con.execute(
            "INSERT OR REPLACE INTO work(work_id,title,authors,year,citation,local_path,page_offset,rules,expected_species,"
            "inventory_source,split_by,split_time,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.key, doc.get("title", ""), doc.get("authors", ""), doc.get("year", ""), "", doc.get("path", ""),
             rules.page_offset, Path(rules.path).name, n_exp, rules.inventory_source, by, _now(),
             f"清单识出 {len(res['inventory'])}；切分 {len(ts)}"))
        for t in ts:
            tid = f"{a.key}:{t['num']:03d}"
            row = {**{c: t.get(c, "") for c in TREATMENT_COLS}, "treatment_id": tid, "work_id": a.key,
                   "level": "L4", "verify_status": "机器初识", "flags": "；".join(t["flags"]),
                   "note": t.get("note", "")}
            con.execute(f"INSERT INTO treatment({','.join(TREATMENT_COLS)}) VALUES({','.join('?' * len(TREATMENT_COLS))})",
                        [row[c] for c in TREATMENT_COLS])
            for k, u in enumerate(usages(t)):
                urow = {**{c: u.get(c, "") for c in USAGE_COLS}, "usage_id": f"{tid}:{k:02d}", "work_id": a.key,
                        "treatment_id": tid, "pages": t["pages"], "aphia_id": "",
                        "verify_status": "机器初识"}
                con.execute(f"INSERT INTO name_usage({','.join(USAGE_COLS)}) VALUES({','.join('?' * len(USAGE_COLS))})",
                            [urow[c] for c in USAGE_COLS])
        _apply_checks(con, a.key)
    print(f"写入 {db_path(a.db)}：treatment {len(ts)}，name_usage "
          f"{con.execute('SELECT count(*) FROM name_usage WHERE work_id=?', (a.key,)).fetchone()[0]}")
    return 0 if n_exp is None or n_exp == len(ts) else 2


def _apply_checks(con, key: str) -> None:
    """把 field_check 里已看原页核过的值写回 treatment（重切后仍然有效），并更新 verify_status。"""
    rows = con.execute("SELECT * FROM field_check WHERE treatment_id LIKE ?", (f"{key}:%",)).fetchall()
    done: dict[str, set] = {}
    for r in rows:
        if r["field"] in TREATMENT_COLS and r["page_value"] not in (None, "") and not r["ok"]:
            con.execute(f'UPDATE treatment SET "{r["field"]}"=? WHERE treatment_id=?', (r["page_value"], r["treatment_id"]))
        done.setdefault(r["treatment_id"], set()).add(r["field"])
    for tid, fs in done.items():
        if all(f in fs for f in KEY_FIELDS):
            con.execute("UPDATE treatment SET verify_status='关键字段已核' WHERE treatment_id=?", (tid,))
            con.execute("UPDATE name_usage SET verify_status='关键字段已核' WHERE treatment_id=? AND usage_type LIKE '有效名%'",
                        (tid,))


def cmd_verify(a: argparse.Namespace) -> int:
    """列出待看原页核对的关键字段：带疑点的记录全列；--sample N 另抽 N 条（固定种子，可复现）。"""
    con = open_db(a.db)
    rows = con.execute("SELECT * FROM treatment WHERE work_id=? ORDER BY num", (a.key,)).fetchall()
    if not rows:
        print(f"{a.key}：taxa.sqlite 中无记录，先 taxadb split", file=sys.stderr)
        return 1
    checked = {r["treatment_id"] for r in con.execute("SELECT DISTINCT treatment_id FROM field_check")}
    ref = _load_reference(a.reference) if a.reference else {}
    todo = []
    for r in rows:
        why = [f for f in (r["flags"] or "").split("；") if f]
        if ref:
            e = ref.get(r["zh_name"]) or ref.get((r["taxon"] or "").lower())
            if not e:
                why.append("参照表无此名")
            else:
                if e["latin"].lower() != (r["taxon"] or "").lower():
                    why.append(f"参照表学名 {e['latin']}")
                if e.get("author") and e["author"].replace(" ", "") != (r["author_year"] or "").replace(" ", ""):
                    why.append(f"参照表命名人 {e['author']}")
                if e.get("page") and str(e["page"]) != str(r["pdf_page_start"]):
                    why.append(f"参照表页 {e['page']}")
        if why and r["treatment_id"] not in checked:
            todo.append((r, why))
    sample = []
    if a.sample:
        rnd = random.Random(a.seed)
        sample = rnd.sample(list(rows), min(a.sample, len(rows)))
    out = open(a.out, "w", encoding="utf-8", newline="") if a.out else sys.stdout
    w = csv.writer(out, delimiter="\t")
    w.writerow(["treatment_id", "num", "pdf_page", "taxon", "author_year", "zh_name", "地理分布", "原因"])
    for r, why in todo:
        w.writerow([r["treatment_id"], r["num"], r["pdf_page_start"], r["taxon"], r["author_year"], r["zh_name"],
                    (r["地理分布"] or "")[:200], "；".join(why)])
    for r in sample:
        w.writerow([r["treatment_id"], r["num"], r["pdf_page_start"], r["taxon"], r["author_year"], r["zh_name"],
                    (r["地理分布"] or "")[:200], f"抽查（seed={a.seed}）"])
    if a.out:
        out.close()
    n_ok = con.execute("SELECT count(*) FROM treatment WHERE work_id=? AND verify_status='关键字段已核'", (a.key,)).fetchone()[0]
    print(f"{a.key}：记录 {len(rows)}，带疑点待核 {len(todo)}，抽查 {len(sample)}，关键字段已核 {n_ok}", file=sys.stderr)
    return 0


def _load_reference(path: str) -> dict:
    """参照表（如 yzz-translate 的 基准_<书>.tsv）：拉丁名(志书印刷)、命名人、中文名、阶元、PDF页。"""
    ref: dict = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("阶元") not in ("种", "亚种"):
                continue
            e = {"latin": (r.get("拉丁名(志书印刷)") or "").strip(), "author": (r.get("命名人") or "").strip(),
                 "zh": (r.get("中文名") or "").strip(), "page": (r.get("PDF页") or "").strip()}
            ref[e["zh"]] = e
            ref[e["latin"].lower()] = e
    return ref


def cmd_check(a: argparse.Namespace) -> int:
    """导入看原页核对的结果（jsonl，每行 {treatment_id, field, db_value, page_value, ok, pdf_page, note}）。"""
    con = open_db(a.db)
    n = 0
    by = _by(a)
    with con:
        for line in open(a.file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if "field" not in d or "treatment_id" not in d:
                continue
            con.execute("INSERT OR REPLACE INTO field_check VALUES(?,?,?,?,?,?,?,?,?)",
                        (d["treatment_id"], d["field"], d.get("db_value", ""), d.get("page_value", ""),
                         1 if d.get("ok") else 0, d.get("pdf_page"), d.get("by", by), d.get("time", _now()),
                         d.get("note", "")))
            n += 1
        key = a.key or ""
        if key:
            _apply_checks(con, key)
    print(f"导入核对 {n} 条")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    con = open_db(a.db)
    q = "SELECT * FROM treatment WHERE 1=1"
    args: list = []
    if a.work:
        q += " AND work_id=?"
        args.append(a.work)
    if a.family:
        q += " AND (family=? OR family LIKE ?)"
        args += [a.family, a.family + "%"]
    rows = con.execute(q + " ORDER BY work_id, num", args).fetchall()
    cols = ["work_id", "num", "family", "subfamily", "genus", "taxon", "author_year", "zh_name", "rank", "pages",
            "figures", "地理分布", "verify_status", "flags"]
    out = open(a.out, "w", encoding="utf-8", newline="") if a.out else sys.stdout
    if a.format == "json":
        json.dump([{c: r[c] for c in cols} for r in rows], out, ensure_ascii=False, indent=1)
    else:
        w = csv.writer(out, delimiter="\t" if a.format == "tsv" else ",")
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    if a.out:
        out.close()
    print(f"导出 {len(rows)} 条", file=sys.stderr)
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    con = open_db(a.db)
    for r in con.execute("SELECT w.work_id, w.expected_species, count(t.treatment_id) n, "
                         "sum(t.verify_status='关键字段已核') ok, sum(t.flags!='') fl FROM work w "
                         "LEFT JOIN treatment t ON t.work_id=w.work_id GROUP BY w.work_id"):
        print(f"{r['work_id']}\t书中 {r['expected_species']}\t切分 {r['n']}\t关键字段已核 {r['ok']}\t带疑点 {r['fl']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="taxadb", description="分类数据库：从 docstore 页面切分物种记述")
    p.add_argument("--db", help=f"taxa.sqlite 路径（默认 $TAXADB_PATH 或 {db_path()}）")
    p.add_argument("--root", help="docstore 库根（默认 $DOCSTORE_ROOT 或 docstore 默认）")
    p.add_argument("--by", help="写入者（模型名）；缺省取 TAXADB_AGENT / DOCSTORE_AGENT")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="按规则切分一卷，写入 taxa.sqlite")
    s.add_argument("key")
    s.add_argument("--rules", required=True, help="规则 toml（路径或 taxadb/rules 下的名字，如 动物志）")
    s.add_argument("--dry", action="store_true", help="只报告，不写库")
    s.set_defaults(func=cmd_split)
    v = sub.add_parser("verify", help="列关键字段待看原页核对的记录")
    v.add_argument("key")
    v.add_argument("--reference", help="参照表 tsv（如 基准_动物志33.tsv）")
    v.add_argument("--sample", type=int, default=0)
    v.add_argument("--seed", type=int, default=33)
    v.add_argument("-o", "--out")
    v.set_defaults(func=cmd_verify)
    c = sub.add_parser("check", help="导入看原页核对的结果 jsonl")
    c.add_argument("file")
    c.add_argument("--key")
    c.set_defaults(func=cmd_check)
    e = sub.add_parser("export", help="导出名录")
    e.add_argument("--family")
    e.add_argument("--work")
    e.add_argument("--format", choices=["tsv", "csv", "json"], default="tsv")
    e.add_argument("-o", "--out")
    e.set_defaults(func=cmd_export)
    st = sub.add_parser("status")
    st.set_defaults(func=cmd_status)
    a = p.parse_args(argv)
    return int(a.func(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
