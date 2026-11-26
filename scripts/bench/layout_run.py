#!/usr/bin/env python3
"""版面评测批跑（设计 A.4）：对 layout_sample.tsv 的 16 对页生成 GT、跑引擎、打分、出排名表。

用法：
  python3 scripts/bench/layout_run.py gt   --png-dir DIR [--out docs/ocr_eval/layout_gt]      # 原生页 GT + 配准到扫描页
  python3 scripts/bench/layout_run.py eval --engine tesseract|paddle-cloud --png-dir DIR [--cache DIR] [--pages 22,23]
  python3 scripts/bench/layout_run.py table --engines a,b,c -o docs/ocr_eval/layout_result.md
png 命名 s<扫描页号>.png；paddle-cloud 缓存 p<扫描页号>.json（run_pages 落盘的 layout）。
结果目录 docs/ocr_eval/layout_runs/<engine>/（engine_page + score）。
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_adapters as A  # noqa: E402
import layout_gt as G  # noqa: E402
import layout_pair as P  # noqa: E402
import layout_score as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "docs/ocr_eval/layout_sample.tsv"
GT_DIR = ROOT / "docs/ocr_eval/layout_gt"
RUNS = ROOT / "docs/ocr_eval/layout_runs"
METRICS = ["block_f1", "role_acc", "cover", "caption_recall", "body_recall", "role_macro_f1", "heading_recall", "heading_level_acc", "heading_level_strict", "order_tau", "col_interleave", "cer", "bag_f1", "italic_f1", "seconds"]


def rows(pages: list[int] | None = None) -> list[dict]:
    r = [x for x in P.read_tsv(str(SAMPLE)) if x["status"] == "ok"]
    return [x for x in r if not pages or int(x["scan_page"]) in pages]


def cmd_gt(a: argparse.Namespace) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for r in rows():
        gt = G.native_gt(r["native_pdf"], int(r["native_page"]))
        png = Path(a.png_dir) / f"s{r['scan_page']}.png"
        gt = G.project_gt(gt, str(png))
        gt.update({"stratum": r["stratum"], "scan_page": int(r["scan_page"])})
        (out / f"n{int(r['native_page']):04d}_s{int(r['scan_page']):04d}.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
        g = gt["registration"]
        print(r["native_page"], r["scan_page"], r["stratum"], g["status"], g.get("median_residual_px"), g["pairs"], len(gt["blocks"]))


def check_aspect(layout_wh: tuple[float, float], png: Path, tol: float = 0.01) -> None:
    """引擎坐标的页面宽高比必须与评测 PNG 一致，否则相对坐标整体错位（pdftoppm 默认 mediabox，fitz/云端用 cropbox，
    Greg 的 mediabox 842 pt 高 vs cropbox 792.8 pt 高，2026-11-26 实测踩过）。"""
    from PIL import Image
    w, h = Image.open(png).size
    if abs((layout_wh[1] / layout_wh[0]) / (h / w) - 1) > tol:
        raise RuntimeError(f"页面宽高比不一致：引擎 {layout_wh} vs PNG {(w, h)}；渲染 PNG 请加 pdftoppm -cropbox")


def run_engine(name: str, png: Path, scan_page: int, cache: Path | None) -> dict:
    base = name.removesuffix("+h")
    if base == "tesseract":
        res = A.tesseract_page(str(png))
    elif cache is not None and (cache / f"p{scan_page:04d}.json").exists():
        j = json.loads((cache / f"p{scan_page:04d}.json").read_text(encoding="utf-8"))
        lay = j.get("layout", j)
        check_aspect((float(lay["width_px"]), float(lay["height_px"])), png)
        res = A.paddle_blocks(lay, engine=base)
        res["seconds"] = j.get("seconds")
        if base.startswith("doclayout"):  # 只有框：文字用 tesseract 填
            res = A.fill_text(res, str(png))
    elif cache is not None and (cache / f"p{scan_page:04d}.fail").exists():
        raise RuntimeError((cache / f"p{scan_page:04d}.fail").read_text())
    else:
        raise RuntimeError(f"无缓存 {cache}/p{scan_page:04d}.json")
    if name.endswith("+h"):
        res["blocks"] = A.infer_levels(res["blocks"])
    res["engine"] = name
    return res


def cmd_eval(a: argparse.Namespace) -> None:
    pages = [int(x) for x in a.pages.split(",")] if a.pages else None
    out = RUNS / a.engine
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else None
    for r in rows(pages):
        sp, np_ = int(r["scan_page"]), int(r["native_page"])
        gtf = GT_DIR / f"n{np_:04d}_s{sp:04d}.json"
        gt = json.loads(gtf.read_text(encoding="utf-8"))
        try:
            eng = run_engine(a.engine, Path(a.png_dir) / f"s{sp}.png", sp, cache)
        except Exception as e:  # noqa: BLE001 失败记录并跳过
            (out / f"s{sp:04d}.error.txt").write_text(str(e), encoding="utf-8")
            print(sp, "FAIL", str(e)[:100])
            continue
        (out / f"s{sp:04d}.engine_page.json").write_text(json.dumps(eng, ensure_ascii=False), encoding="utf-8")
        sc = S.score_layout(gt, eng)
        sc.update({"native_page": np_, "scan_page": sp, "stratum": r["stratum"]})
        (out / f"s{sp:04d}.score.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(sp, r["stratum"], {k: sc[k] for k in ("block_f1", "role_macro_f1", "heading_level_acc", "order_tau", "cer") if k in sc})


def mean(v: list) -> float | None:
    v = [x for x in v if isinstance(x, (int, float))]
    return round(st.mean(v), 3) if v else None


def load_scores(engine: str, good_reg_only: bool = True) -> list[dict]:
    out = []
    for f in sorted((RUNS / engine).glob("*.score.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        if good_reg_only and s.get("registration") != "ok":
            continue
        out.append(s)
    return out


def cmd_table(a: argparse.Namespace) -> None:
    engines = a.engines.split(",")
    lines = ["| 引擎 | 页数(配准ok) | " + " | ".join(METRICS) + " |", "|" + "---|" * (len(METRICS) + 2)]
    for e in engines:
        sc = load_scores(e)
        lines.append(f"| {e} | {len(sc)} | " + " | ".join(str(mean([s.get(m) for s in sc])) for m in METRICS) + " |")
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gt")
    g.add_argument("--png-dir", required=True)
    g.add_argument("--out", default=str(GT_DIR))
    e = sub.add_parser("eval")
    e.add_argument("--engine", required=True)
    e.add_argument("--png-dir", required=True)
    e.add_argument("--cache")
    e.add_argument("--pages")
    t = sub.add_parser("table")
    t.add_argument("--engines", required=True)
    t.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    {"gt": cmd_gt, "eval": cmd_eval, "table": cmd_table}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
