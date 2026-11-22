#!/usr/bin/env python3
"""用 docstore.spellfix 纠 aligned.json 的 VL 拼写错误。
用法：python3 scripts/vl_spellfix.py <aligned.json ...> [--tess-root DIR] [--worms CACHE] [--llm] [--apply] [--out DIR]
默认只出报告 <out>/spellfix_issues.jsonl；--apply 另写 <out>/<目录名>.aligned.spellfixed.json（不覆盖原文件）。
--llm：疑点交 DeepSeek flash（须在折扣时段；llm_engines 自动等待）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from docstore import spellfix as sf  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aligned", nargs="+", type=Path)
    ap.add_argument("--tess-root", type=Path, default=None)
    ap.add_argument("--worms", default=str(Path.home() / ".specimen_inventory" / "worms_cache.sqlite"))
    ap.add_argument("--tess-name", default=None, help="--tess-root 下固定用这个子目录（默认按 aligned 的上级目录名）")
    ap.add_argument("--lang", default="es,en")
    ap.add_argument("--skip-roles", default="ref")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--engine", default="deepseek-flash")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--inplace", action="store_true",
                    help="直接改写输入的 aligned.json（原件先备份为 aligned.pre_spellfix.json，已有则不覆盖）；隐含 --apply")
    ap.add_argument("--out", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    if a.inplace:
        a.apply = True
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in a.aligned]
    dicts: dict[str, str] = {}
    for lg in filter(None, a.lang.split(",")):
        dicts.update(sf.aspell_forms(lg.strip()))
    genera, epith = sf.worms_names(a.worms)
    lex = sf.Lexicon(dicts, genera, epith)
    for d in docs:
        for pg in d["pages"]:
            for b in pg["blocks"]:
                lex.add_text(b.get("text", ""))
    decide = None
    a.out.mkdir(parents=True, exist_ok=True)
    if a.llm:
        import llm_engines
        decide = lambda pend: sf.llm_decide(pend, lambda *x, **k: llm_engines.call(*x, usage_file=a.out / "usage.jsonl", **k), a.engine, cache=a.out / "llm_cache.json")  # noqa: E731
    tdirs = [(a.tess_root / (a.tess_name or p.parent.name)) if a.tess_root else None for p in a.aligned]
    issues = sf.fix_aligned(docs, [str(p) for p in a.aligned], lex, tdirs, set(filter(None, a.skip_roles.split(","))),
                            decide, apply=a.apply)
    (a.out / "spellfix_issues.jsonl").write_text(
        "\n".join(json.dumps(i, ensure_ascii=False) for i in issues) + ("\n" if issues else ""), encoding="utf-8")
    if a.inplace:
        for p, d in zip(a.aligned, docs):
            bak = p.with_name(p.stem + ".pre_spellfix.json")
            if not bak.exists():
                bak.write_bytes(p.read_bytes())
            p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    elif a.apply:
        for p, d in zip(a.aligned, docs):
            (a.out / (p.parent.name + ".aligned.spellfixed.json")).write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(1 for i in issues if i.get("applied"))
    by: dict[str, int] = {}
    for i in issues:
        if i.get("applied"):
            by[i["why"]] = by.get(i["why"], 0) + 1
    print("applied %d %s; suggestions %d -> %s" % (n, by, len(issues) - n, a.out / "spellfix_issues.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
