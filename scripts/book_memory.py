"""跨书积累库：同语言对 + 领域共享异写，翻过一本下一本更省（0 token）。

    ~/.cache/yzz-translate/memory/{sl}-{tl}/{domain}/variants.tsv

列：source \\t target \\t variants(old=new;…) \\t note
auto_translate / fast_book 默认加载；书末 mine_corrections 写入 candidates，审核后 absorb。

    python3 scripts/book_memory.py path --sl de --tl en --domain 分类学
    python3 scripts/book_memory.py absorb CANDIDATES.tsv --sl de --tl en --domain 分类学
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT_DEFAULT = Path.home() / ".cache/yzz-translate/memory"


def _slug(s: str) -> str:
    s = (s or "general").strip() or "general"
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", s)[:80]


def memory_dir(sl: str, tl: str, domain: str = "分类学",
               root: Path | None = None) -> Path:
    return (root or ROOT_DEFAULT) / f"{sl}-{tl}" / _slug(domain)


def variants_path(sl: str, tl: str, domain: str = "分类学",
                  root: Path | None = None) -> Path:
    return memory_dir(sl, tl, domain, root) / "variants.tsv"


def ensure(sl: str, tl: str, domain: str = "分类学",
           root: Path | None = None) -> Path:
    p = variants_path(sl, tl, domain, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("source\ttarget\tvariants\tnote\n", encoding="utf8")
    return p


def load_rows(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding="utf8").splitlines()[1:]:
        if not ln.strip():
            continue
        cells = ln.split("\t")
        while len(cells) < 4:
            cells.append("")
        rows.append(cells[:4])
    return rows


def merge_glossary(user_glossary: str | None, sl: str, tl: str,
                   domain: str, out: Path, root: Path | None = None) -> Path:
    """用户术语表 + 共享 memory → 写出合并 TSV（供 terms.load / load_table）。"""
    mem = ensure(sl, tl, domain, root)
    lines = ["source\ttarget\tvariants\tnote"]
    seen: set[str] = set()
    for src in filter(None, [user_glossary, str(mem)]):
        p = Path(src)
        if not p.exists():
            continue
        for i, ln in enumerate(p.read_text(encoding="utf8").splitlines()):
            cells = [c.strip() for c in ln.split("\t")]
            if len(cells) < 2 or not cells[0]:
                continue
            if i == 0 and cells[0].lower() in ("source", "src", "en", "de", "源术语"):
                continue
            key = cells[0].lower()
            if key in seen:
                continue
            seen.add(key)
            while len(cells) < 4:
                cells.append("")
            lines.append("\t".join(cells[:4]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf8")
    return out


def absorb_candidates(cands: Path, sl: str, tl: str, domain: str = "分类学",
                      root: Path | None = None, approve_all: bool = False) -> int:
    """把 mine_corrections 候选并入共享库。默认只收 approve=y；approve_all 用于测试。"""
    mem = ensure(sl, tl, domain, root)
    body = load_rows(mem)
    by_tgt = {r[1].lower(): r for r in body if r[1]}
    n = 0
    with cands.open(encoding="utf8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if not approve_all and r.get("approve", "").strip().lower() not in ("y", "yes", "1"):
                continue
            old, new = r.get("old", "").strip(), r.get("new", "").strip()
            if not old or not new:
                continue
            item = f"{old}={new}"
            hit = by_tgt.get(new.lower())
            if hit:
                vs = [v for v in hit[2].split(";") if v]
                if item not in vs and old not in vs:
                    hit[2] = ";".join(vs + [item])
                    n += 1
            else:
                row = ["", new, item, f"memory absorb ({r.get('count', '')})"]
                body.append(row)
                by_tgt[new.lower()] = row
                n += 1
    mem.write_text(
        "source\ttarget\tvariants\tnote\n"
        + "\n".join("\t".join(r) for r in body)
        + "\n",
        encoding="utf8",
    )
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("path", help="打印共享库 variants.tsv 路径（不存在则创建）")
    p.add_argument("--sl", required=True)
    p.add_argument("--tl", required=True)
    p.add_argument("--domain", default="分类学")
    a = sub.add_parser("absorb", help="审核后的 candidates 并入共享库")
    a.add_argument("candidates")
    a.add_argument("--sl", required=True)
    a.add_argument("--tl", required=True)
    a.add_argument("--domain", default="分类学")
    a.add_argument("--all", action="store_true", help="不要求 approve=y（慎用）")
    ns = ap.parse_args(argv)
    if ns.cmd == "path":
        print(ensure(ns.sl, ns.tl, ns.domain))
        return 0
    n = absorb_candidates(Path(ns.candidates), ns.sl, ns.tl, ns.domain, approve_all=ns.all)
    print(f"写入共享库 {n} 条 → {variants_path(ns.sl, ns.tl, ns.domain)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
