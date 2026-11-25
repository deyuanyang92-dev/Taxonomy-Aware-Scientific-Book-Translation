#!/usr/bin/env python3
"""ru/fr/la 样本页：跑 OCR 引擎，对两套金标（sonnet 单遍 G1、Datalab accurate）打分，追加 LEDGER。
用法：python3 scripts/bench/multi_ocr.py ru fr la [--engine tesseract] [--dpi 200] [--no-ledger]
hyp 存 bench/runs/<engine>/<id>.txt；Datalab 金标先用 dl_gold.py 生成（bench/gold_dl/<lang>/<id>.md）。
Datalab markdown 先去 #/**/_/图片标记再评分；两金标本身的差异也报（金标间 CER，度量金标噪声）。
"""
import argparse, csv, datetime, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/bench")]
from ocr_score import score_page, cer, norm  # noqa: E402
from docstore.engines import ENGINE_MAP  # noqa: E402

TESS = {"ru": "rus", "fr": "fra", "la": "lat+eng", "de": "deu"}


def clean_md(t: str) -> str:
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"</?[a-z][^>]*>", "", t)
    return re.sub(r"[*_]{1,3}", "", t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("langs", nargs="+"); ap.add_argument("--engine", default="tesseract")
    ap.add_argument("--dpi", type=int, default=200); ap.add_argument("--no-ledger", action="store_true")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(ROOT / "bench/samples.csv", encoding="utf-8")))
    for lang in a.langs:
        os.environ["DOCSTORE_TESS_LANG"] = TESS[lang]
        od = ROOT / "bench/runs" / a.engine; od.mkdir(parents=True, exist_ok=True)
        res = []
        for r in (x for x in rows if x["lang"] == lang):
            hp = od / f"{r['id']}.txt"
            if not hp.exists():
                txt, _ = ENGINE_MAP[a.engine](r["pdf"], int(r["page"]), a.dpi)
                hp.write_text(txt, encoding="utf-8")
            hyp, g1 = hp.read_text(encoding="utf-8"), Path(r["gold_path"]).read_text(encoding="utf-8")
            dl = ROOT / "bench/gold_dl" / lang / f"{r['id']}.md"
            g2 = clean_md(dl.read_text(encoding="utf-8")) if dl.exists() else None
            s1 = score_page(g1, hyp)
            s2 = score_page(g2, hyp) if g2 else None
            gg = cer(norm(g2), norm(g1)) if g2 else None
            res.append((r["id"], r["split"], s1["cer_norm"], s2 and s2["cer_norm"], s1["bag_err"], s2 and s2["bag_err"], gg))
            print(r["id"], r["split"], *[f"{v:.4f}" if v is not None else "NA" for v in res[-1][2:]], flush=True)
        def mean(i):
            v = [x[i] for x in res if x[i] is not None]
            return sum(v) / len(v) if v else None
        f = lambda v: "NA" if v is None else f"{v:.4f}"  # noqa: E731
        n2 = sum(1 for x in res if x[3] is not None)
        line = (f"{datetime.date.today()}\tTesseract 5.3.4 {TESS[lang]} psm3 {a.dpi}dpi\t{lang} n={len(res)} (sonnet G1) / n={n2} (Datalab accurate 参照)\t"
                f"cer_norm/bag_err\tvsSonnet {f(mean(2))}/{f(mean(4))}; vsDatalab {f(mean(3))}/{f(mean(5))}; 金标互差 CER {f(mean(6))}\tfree\t"
                f"scripts/bench/multi_ocr.py; bench/runs/{a.engine}")
        print(line)
        if not a.no_ledger:
            with open(ROOT / "docs/ocr_eval/LEDGER.tsv", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")


main()
