#!/usr/bin/env python3
"""多卷检索表重建报告（issue #38 验收：自洽数与残留清单，前后对比）。

用法：
  python3 scripts/keys_report.py --volume 2001=~/.cache/docstore_ppocr/966b8423a9d4/PP-OCRv5_server_200_v2:406 \\
      [--volume NAME=CACHE:LAST[:keys_fix.json]] ... [--baseline NAME=自洽数,缺陷数] --out report.md [--json report.json]
  python3 scripts/keys_report.py --imajima        # 本机已知的 Imajima 三卷缓存（无缓存则跳过并说明）

每卷输出：表数、偶句数、自洽表数、缺陷数、含缺陷的页与条目（只列页和条目号，不含书中文字）。给了
keys_fix.json 时同时报告改正前后。基线（prototype）可用 --baseline 给出。零 token，不 OCR，不写入书稿文字。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docstore import keyblocks, keys  # noqa: E402

IMAJIMA = {  # 名 → (缓存哈希, 页数, issue #38 原型 (自洽表数, 缺陷数))
    "2001": ("966b8423a9d4", 406, (9, 7)),
    "2007": ("858f37873e50", 363, (1, 21)),
    "2009": ("c1ac037a042b", 361, (2, 28)),
}


def summarize(data: dict) -> dict:
    ks = data["keys"]
    return {"keys": len(ks), "couplets": len(data["couplets"]),
            "self_consistent": sum(not k["problems"] for k in ks),
            "problems": sum(len(k["problems"]) for k in ks)}


def run_volume(name: str, cache: Path, last: int, fix: Path | None) -> dict:
    if not cache.is_dir():
        return {"name": name, "skipped": f"no cache {cache}"}
    pages, missing = keys.read_cache_pages(cache, 1, last)
    data = keys.extract(pages)
    res: dict = {"name": name, "missing_pages": len(missing), "before": summarize(data)}
    if fix:
        keys.apply_fixes(data, json.loads(fix.read_text(encoding="utf-8")))
        res["fixes_applied"] = len(data["fixes"])
    res["after"] = summarize(data)
    res["residual"] = [{"key": k["key"], "pages": [k["first_page"], k["last_page"]], "problems": k["problems"]}
                       for k in data["keys"] if k["problems"]]
    res["plan_pages"] = keyblocks.repair_plan(data)["pages_to_check"]
    res["blocks"] = len(keyblocks.couplet_blocks(data))
    return res


def to_md(results: list[dict], baseline: dict[str, tuple[int, int]]) -> str:
    lines = ["# 检索表重建报告", "", "| 卷 | 表 | 偶句 | 自洽(原型→现在) | 缺陷(原型→现在) | 改正后自洽/缺陷 |",
             "|---|---|---|---|---|---|"]
    for r in results:
        if "skipped" in r:
            lines.append(f"| {r['name']} | 跳过：{r['skipped']} | | | | |")
            continue
        b, a = r["before"], r["after"]
        base = baseline.get(r["name"])
        bs = f"{base[0]}→{b['self_consistent']}" if base else str(b["self_consistent"])
        bp = f"{base[1]}→{b['problems']}" if base else str(b["problems"])
        fx = f"{a['self_consistent']}/{a['problems']}" if "fixes_applied" in r else "未给 keys_fix.json"
        lines.append(f"| {r['name']} | {b['keys']} | {b['couplets']} | {bs} | {bp} | {fx} |")
    for r in results:
        if r.get("residual"):
            lines += ["", f"## {r['name']} 残留（待对照页面图像）：待核页 {r['plan_pages']}"]
            lines += [f"- 表{x['key']} p{x['pages'][0]}-{x['pages'][1]}：{'; '.join(x['problems'])}" for x in r["residual"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--volume", action="append", default=[], help="NAME=CACHE_DIR:LAST[:keys_fix.json]")
    ap.add_argument("--imajima", action="store_true")
    ap.add_argument("--baseline", action="append", default=[], help="NAME=自洽数,缺陷数")
    ap.add_argument("--cache-root", type=Path, default=Path.home() / ".cache" / "docstore_ppocr")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    base: dict[str, tuple[int, int]] = {}
    for b in a.baseline:
        n, v = b.split("=")
        x, y = v.split(",")
        base[n] = (int(x), int(y))
    vols: list[tuple[str, Path, int, Path | None]] = []
    for v in a.volume:
        n, rest = v.split("=", 1)
        parts = rest.rsplit(":", 2) if rest.count(":") >= 2 else rest.rsplit(":", 1)
        fix = Path(parts[2]).expanduser() if len(parts) == 3 else None
        vols.append((n, Path(parts[0]).expanduser(), int(parts[1]), fix))
    if a.imajima:
        for n, (h, last, proto) in IMAJIMA.items():
            base.setdefault(n, proto)
            vols.append((n, a.cache_root / h / "PP-OCRv5_server_200_v2", last, None))
    if not vols:
        ap.error("need --volume or --imajima")
    results = [run_volume(*v) for v in vols]
    md = to_md(results, base)
    if a.out:
        a.out.write_text(md, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
