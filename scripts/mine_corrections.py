#!/usr/bin/env python3
"""从「Google 初稿 vs 终稿」挖稳定的替换，作为术语表「异写」列的候选（0 token）。

用户 2026-11-15：「分类文献主要是术语，句式很统一……我们没法本地训练，只能靠你帮我优化」。
做法：两份译文按段 ID 对齐（transqa.segments），逐段词级 diff，收集 1–4 词的替换对 old→new；
某个 old 出现的段里，被换成同一个 new 的比例 = 一致率。次数 ≥ --min-count 且一致率 ≥ --min-consistency 的输出为候选。
候选只是候选：人或主会话审过（approve 列填 y）后，用 --apply 写进术语表的 variants 列（以原文为锚的 transqa.terms 规范化会用它），
下一本同语种书的零成本档即可自动修正，不再交模型。

    python3 mine_corrections.py mine DRAFT.md FINAL.md -o candidates.tsv
    python3 mine_corrections.py apply candidates.tsv --glossary G.tsv
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transqa.segments import segments_from_pages  # noqa: E402

TOKEN = re.compile(r"[\w'’-]+|[^\w\s]")


def _tok(s: str) -> list[str]:
    return TOKEN.findall(s)


def pairs(draft: str, final: str, max_len: int = 4) -> list[tuple[str, str]]:
    """一段的替换对（词级 replace 操作，两边都 ≤ max_len 词、且不只是标点）。"""
    a, b = _tok(draft), _tok(final)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "replace" or i2 - i1 > max_len or j2 - j1 > max_len:
            continue
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if not re.search(r"[A-Za-z]", old + new) or re.fullmatch(r"[\d\W]+", old):
            continue
        out.append((old, new))
    return out


def mine(draft_md: str, final_md: str, min_count: int = 3, min_consistency: float = 0.8) -> list[dict]:
    d = {s.id: s.text for s in segments_from_pages(draft_md)}
    f = {s.id: s.text for s in segments_from_pages(final_md)}
    rep: dict[str, Counter] = defaultdict(Counter)
    for sid, dt in d.items():
        ft = f.get(sid)
        if ft is None:
            continue
        ps = pairs(dt, ft)
        for old, new in ps:
            rep[old.lower()][new] += 1
    rows = []
    for old, c in rep.items():
        new, n = c.most_common(1)[0]
        # 一致率：old 出现过的段里，被换成 new 的段数比例（old 没被改的段也算分母）
        segs_with_old = sum(1 for t in d.values() if re.search(r"(?<!\w)" + re.escape(old) + r"(?!\w)", t.lower()))
        cons = n / max(segs_with_old, n)
        if n >= min_count and cons >= min_consistency:
            rows.append({"old": old, "new": new, "count": n, "segments_with_old": segs_with_old,
                         "consistency": round(cons, 2), "approve": ""})
    rows.sort(key=lambda r: (-r["count"], r["old"]))
    return rows


def apply(cands: Path, glossary: Path) -> int:
    """approve=y 的候选写进术语表：若某条目的 en 与 new 相同（不分大小写），把 old=new 加进它的 variants；
    否则另起一行（de 列留空，只作全书异写），由人补 de 列。返回写入条数。"""
    rows = list(csv.DictReader(cands.open(encoding="utf-8"), delimiter="\t"))
    ok = [r for r in rows if r.get("approve", "").strip().lower() in ("y", "yes", "1")]
    lines = glossary.read_text(encoding="utf-8").splitlines()
    head, body = lines[0], [ln.split("\t") for ln in lines[1:]]
    n = 0
    for r in ok:
        hit = [c for c in body if len(c) >= 2 and c[1].lower() == r["new"].lower()]
        if hit:
            c = hit[0]
            while len(c) < 4:
                c.append("")
            vs = [v for v in c[2].split(";") if v]
            item = f"{r['old']}={r['new']}"
            if item not in vs and r["old"] not in vs:
                c[2] = ";".join(vs + [item])
                n += 1
        else:
            body.append(["", r["new"], f"{r['old']}={r['new']}", f"mine_corrections 候选（{r['count']} 次，一致率 {r['consistency']}）"])
            n += 1
    glossary.write_text("\n".join([head] + ["\t".join(c) for c in body]) + "\n", encoding="utf-8")
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mine")
    m.add_argument("draft")
    m.add_argument("final")
    m.add_argument("-o", "--out", required=True)
    m.add_argument("--min-count", type=int, default=3)
    m.add_argument("--min-consistency", type=float, default=0.8)
    p = sub.add_parser("apply")
    p.add_argument("candidates")
    p.add_argument("--glossary", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "mine":
        rows = mine(Path(a.draft).read_text(encoding="utf-8"), Path(a.final).read_text(encoding="utf-8"),
                    a.min_count, a.min_consistency)
        with open(a.out, "w", encoding="utf-8", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=["old", "new", "count", "segments_with_old", "consistency", "approve"],
                               delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        print(f"候选 {len(rows)} 条 → {a.out}（审核后在 approve 列填 y，再运行 apply）")
    else:
        print(f"写入 {apply(Path(a.candidates), Path(a.glossary))} 条")


if __name__ == "__main__":
    main()
