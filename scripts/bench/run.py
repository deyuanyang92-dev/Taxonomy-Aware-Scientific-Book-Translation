#!/usr/bin/env python3
"""统一评测台入口：run(stage, lang, engine) -> {cer, bag_err, n, cost, sec_per_page, split, note}。

用法（仓库根）：
  python3 scripts/bench/run.py ocr ja ppocr [--split dev] [--no-ledger]
清单 bench/samples.csv 列：id,lang,stage,pdf,page,gold_path,gold_source,gold_level,split
  split：dev（调参）/ val（验证）/ sealed（跨书封存确认集，须 --allow-sealed 才跑，跑过转入回归集）。
评分口径唯一：scripts/bench/ocr_score.py。每次运行追加 docs/ocr_eval/LEDGER.tsv 一行。
n=0 时返回 cer=None，note 标「样本不足」，不返回 NaN。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import ocr_score  # noqa: E402

MANIFEST = ROOT / "bench" / "samples.csv"
LEDGER = ROOT / "docs" / "ocr_eval" / "LEDGER.tsv"
Runner = Callable[[dict[str, str]], tuple[str, float]]  # row -> (text, cost_cny)


def _docstore_runner(engine: str, dpi: int = 200) -> Runner:
    from docstore.engines import ENGINE_MAP

    fn = ENGINE_MAP[engine]

    def go(row: dict[str, str]) -> tuple[str, float]:
        text, _conf = fn(row["pdf"], int(row["page"]), dpi)
        return text, 0.0

    return go


def run(stage: str, lang: str, engine: str, *, manifest: Path = MANIFEST, ledger: Path | None = LEDGER,
        split: str = "dev", runner: Runner | None = None, allow_sealed: bool = False,
        dpi: int = 200, gold_level: str | None = None) -> dict[str, Any]:
    if stage != "ocr":
        raise NotImplementedError(f"stage {stage!r} 尚未接入（目前仅 ocr）")
    if split == "sealed" and not allow_sealed:
        raise ValueError("sealed 封存集须显式 allow_sealed=True；跑过的页转入回归集")
    with open(manifest, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["stage"] == stage and r["lang"] == lang and r["split"] == split
                and (gold_level is None or r["gold_level"] == gold_level)]
    out: dict[str, Any] = {"stage": stage, "lang": lang, "engine": engine, "split": split,
                           "n": len(rows), "cost": 0, "cer": None, "bag_err": None,
                           "sec_per_page": None, "note": ""}
    if not rows:
        out["note"] = "样本不足（n=0）"
        return out
    runner = runner or _docstore_runner(engine, dpi)
    cers, bags, cost, t0 = [], [], 0.0, time.time()
    for r in rows:
        gold = Path(r["gold_path"]).read_text(encoding="utf-8")
        text, c = runner(r)
        s = ocr_score.score_page(gold, text)
        cers.append(s["cer_norm"])
        bags.append(s["bag_err"])
        cost += c
    out.update(cer=sum(cers) / len(cers), bag_err=sum(bags) / len(bags), cost=cost,
               sec_per_page=(time.time() - t0) / len(rows))
    levels = sorted({r["gold_level"] for r in rows})
    out["note"] = "n<10 样本不足以宣称最优" if len(rows) < 10 else ""
    if ledger is not None:
        line = "\t".join([
            datetime.date.today().isoformat(), f"{engine} {dpi}dpi",
            f"{lang} {split} n={len(rows)} gold={'/'.join(levels)}", "cer_norm/bag_err",
            f"{out['cer']:.4f}/{out['bag_err']:.4f} {out['sec_per_page']:.2f}s/页",
            "free" if cost == 0 else f"¥{cost:.2f}", f"scripts/bench/run.py {stage} {lang} {engine}"])
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage")
    ap.add_argument("lang")
    ap.add_argument("engine")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--allow-sealed", action="store_true")
    ap.add_argument("--gold-level", default=None, help="G0/G2…；同页多金标时必须指定")
    ap.add_argument("--no-ledger", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.stage, a.lang, a.engine, split=a.split, dpi=a.dpi, allow_sealed=a.allow_sealed, gold_level=a.gold_level,
            ledger=None if a.no_ledger else LEDGER)
    print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
