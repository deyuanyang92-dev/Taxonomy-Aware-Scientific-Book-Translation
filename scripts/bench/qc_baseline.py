#!/usr/bin/env python3
"""静默漏检率基线：量 docstore.qc.score_page 对「置信度正常、内容有错」的页放过多少。

三个指标（分开报）：
  seeded_detect      金标页植入错误（字替换/改数字/丢行，OCR 置信设为 0.95）后，qc 判 redo/human 的比例
  clean_false_alarm  未植入的金标页被 qc 判 redo/human 的比例
  real_silent_miss   真实 OCR 输出里 cer_norm >= REAL_CER 的页，qc 仍判 pass 的比例
植入页的 ocr_conf 固定 0.95、dpi 300、无多引擎信息：模拟「引擎自信但读错」，这是静默错误的定义。
用法（仓库根）：
  python3 scripts/bench/qc_baseline.py <lang> [--run-tag ppocrv6_medium_200] [--n 5]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import ocr_score  # noqa: E402
from docstore import qc  # noqa: E402

KINDS = ("char_sub", "digit", "drop_lines")
REAL_CER = 0.03
CONF = 0.95


def empty_yiku(tmp: Path) -> qc.YikuIndex:
    return qc.YikuIndex(tmp / "no_such.db")


def seed_error(text: str, kind: str, seed: int) -> str:
    rng = random.Random(seed)
    if kind == "char_sub":
        idx = [i for i, c in enumerate(text) if c.isalpha()]
        chars = list(text)
        pool = [text[i] for i in idx]
        for i in rng.sample(idx, max(1, len(idx) // 20)):
            new = rng.choice(pool)
            chars[i] = new if new != chars[i] else (pool[0] if pool[0] != chars[i] else pool[-1])
        return "".join(chars)
    if kind == "digit":
        pos = [m.start() for m in re.finditer(r"\d", text)]
        if not pos:
            return text + "7"
        chars = list(text)
        for i in rng.sample(pos, min(2, len(pos))):
            chars[i] = str((int(chars[i]) + rng.randint(1, 8)) % 10)
        return "".join(chars)
    if kind == "drop_lines":
        lines = text.split("\n")
        keep = [ln for i, ln in enumerate(lines) if rng.random() > 0.2 or i == 0]
        return "\n".join(keep) if len(keep) < len(lines) else "\n".join(lines[:-1])
    raise ValueError(kind)


def qc_action(text: str, *, yiku: qc.YikuIndex, conf: float = CONF) -> str:
    page = {"key": "bench", "page": 1, "text": text, "dpi": 300, "verify_level": "ocr_raw",
            "quality": qc.text_quality(text, conf)}
    return qc.score_page(page, cfg=qc.load_config(), yiku=yiku, has_multi_ocr=True).action


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def baseline(gold_pages: dict[str, str], real: list[tuple[str, str]], *, yiku: qc.YikuIndex) -> dict[str, Any]:
    clean = [qc_action(t, yiku=yiku) != "pass" for t in gold_pages.values()]
    seeded = [qc_action(seed_error(t, k, i), yiku=yiku) != "pass"
              for i, t in enumerate(gold_pages.values()) for k in KINDS]
    bad = [(g, h) for g, h in real if ocr_score.score_page(g, h)["cer_norm"] >= REAL_CER]
    real_miss = [qc_action(h, yiku=yiku) == "pass" for _g, h in bad]
    return {"seeded_detect": _rate(seeded), "clean_false_alarm": _rate(clean),
            "real_silent_miss": _rate(real_miss),
            "n_clean": len(clean), "n_seeded": len(seeded), "n_real": len(real_miss)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lang")
    ap.add_argument("--run-tag", default="ppocrv6_medium_200")
    ap.add_argument("--gold-level", default="G0")
    ap.add_argument("--runs-dir", default="", help="hyp 目录；缺省 test-ocr/runs/<run-tag>")
    ap.add_argument("--split", default="dev", help="dev/val/all")
    ap.add_argument("--manifest", default=str(ROOT / "bench" / "samples.csv"))
    a = ap.parse_args(argv)
    rows = [r for r in csv.DictReader(open(a.manifest, encoding="utf-8"))
            if r["lang"] == a.lang and r["gold_level"] == a.gold_level and a.split in ("all", r["split"])]
    runs = Path(a.runs_dir) if a.runs_dir else ROOT / "test-ocr" / "runs" / a.run_tag
    gold, real = {}, []
    for r in rows:
        g = Path(r["gold_path"]).read_text(encoding="utf-8")
        gold[r["id"]] = g
        hp = runs / f"{r['id']}.txt"
        if hp.exists():
            real.append((g, hp.read_text(encoding="utf-8")))
    print(json.dumps({"lang": a.lang, "gold_level": a.gold_level, "run_tag": a.run_tag,
                      **baseline(gold, real, yiku=qc.YikuIndex())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
