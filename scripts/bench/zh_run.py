#!/usr/bin/env python3
"""中文动物志 30 页：跑一个引擎，对 Datalab 金标打分。输出 test-ocr/runs/zh_<tag>/<id>.txt + score.json。
用法（仓库根）：
  /root/ocr_eval/venv_gpu/bin/python scripts/bench/zh_run.py <tag> --engine pp --model PP-OCRv6_medium --dpi 200
  python3 scripts/bench/zh_run.py <tag> --engine tess --lang chi_sim --psm 3 --dpi 300
  python3 scripts/bench/zh_run.py --score-only <tag>
金标 = zh_fauna/datalab/<id>.md 去 markdown 标记（clean_md）。注意：Datalab 是参照而非人工真值，分数为「与 Datalab 的差异」。
"""
import argparse, csv, json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TO = ROOT / "test-ocr"; ZF = TO / "zh_fauna"
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/bench")]
import ocr_score  # noqa: E402


def clean_md(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)          # 图片
    s = re.sub(r"<[^>]+>", "", s)                          # html 标签 (sup/br/math)
    s = re.sub(r"^\s*\|?[\s:|-]+\|?\s*$", "", s, flags=re.M)  # 表格分隔行
    s = s.replace("|", " ")
    s = re.sub(r"^#+\s*", "", s, flags=re.M)
    s = re.sub(r"[*_`]{1,3}", "", s)
    return s


_CJK = re.compile(r"[\u3400-\u9fff]")
_EN_STOP = re.compile(r"\b(the|of|and|showing|with|an|is|are|view|views|detail|each|labeled|illustration|diagram|structures?)\b", re.I)
_HEAD = re.compile(r"^\s*(\d{1,3}\s*)?中国动物志.*$|^\s*(各论|总论)\s.*\d{1,3}\s*$|^\s*\d{1,3}\s*$")


def strip_gold_artifacts(s: str) -> tuple[str, int]:
    """去 Datalab 自生成的英文图片描述（整段无汉字且含 ≥2 个英文功能词，或 'A: Dorsal view' 形式）；返回(文本, 删除段数)。"""
    keep, n = [], 0
    for para in re.split(r"\n\s*\n", s):
        if not _CJK.search(para) and (len(_EN_STOP.findall(para)) >= 2 or re.match(r"^[A-Z]{1,2}: ", para.strip())):
            n += 1; continue
        keep.append(para)
    return "\n\n".join(keep), n


def strip_header(s: str) -> str:
    return "\n".join(ln for ln in s.splitlines() if not _HEAD.match(ln))


def score(tag: str) -> dict:
    out = TO / "runs" / f"zh_{tag}"; res = {}
    for m in csv.DictReader(open(ZF / "zh_manifest.csv", encoding="utf-8")):
        g, h = ZF / "datalab" / f"{m['id']}.md", out / f"{m['id']}.txt"
        if g.exists() and h.exists():
            gt, nd = strip_gold_artifacts(clean_md(g.read_text(encoding="utf-8")))
            gt = strip_header(gt)
            if len(gt.strip()) < 20:  # 金标无正文（纯图页/仅英文描述）：不计分，避免 CER=1 假象
                continue
            r = ocr_score.score_page(gt, strip_header(h.read_text(encoding="utf-8")))
            r["book"] = m["book"]; r["gold_paras_dropped"] = nd; res[m["id"]] = r
    agg = {}
    for bk in ["all", "z09", "z33", "z54"]:
        v = [r for r in res.values() if bk == "all" or r["book"] == bk]
        if v:
            agg[bk] = {k: round(sum(r[k] for r in v) / len(v), 4) for k in ("cer_norm", "cer_nopunct", "bag_err")}
            agg[bk]["n"] = len(v)
    (out / "score.json").write_text(json.dumps({"agg": agg, "pages": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    return agg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tag"); ap.add_argument("--engine", default="pp"); ap.add_argument("--model", default="PP-OCRv6_medium")
    ap.add_argument("--dpi", type=int, default=200); ap.add_argument("--lang", default="chi_sim"); ap.add_argument("--psm", default="3")
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args()
    out = TO / "runs" / f"zh_{a.tag}"; out.mkdir(parents=True, exist_ok=True)
    if not a.score_only:
        times = {}
        if a.engine == "pp":
            os.environ.update(DOCSTORE_PPOCR_MODEL=a.model, DOCSTORE_PPOCR_ADAPTIVE="0", DOCSTORE_PPOCR_CACHE=str(out / "cache"), DOCSTORE_PPOCR_PARAMS="")
            from docstore.engines.ppocr import ppocr_rows, rows_to_text
        for m in csv.DictReader(open(ZF / "zh_manifest.csv", encoding="utf-8")):
            pdf = ZF / "pages" / f"{m['id']}.pdf"; t0 = time.time()
            if a.engine == "pp":
                rows, w = ppocr_rows(str(pdf), 1, a.dpi); txt = rows_to_text(rows, w)[0]
            else:
                png = ZF / "pages" / f"{m['id']}.png"
                txt = subprocess.run(["tesseract", str(png), "-", "-l", a.lang, "--psm", a.psm], capture_output=True, text=True).stdout
            times[m["id"]] = round(time.time() - t0, 2); (out / f"{m['id']}.txt").write_text(txt, encoding="utf-8")
        (out / "time.json").write_text(json.dumps(times))
    print(a.tag, json.dumps(score(a.tag), ensure_ascii=False))
