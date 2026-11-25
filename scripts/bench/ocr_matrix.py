#!/usr/bin/env python3
"""Tesseract vs PaddleOCR 同台矩阵：同页、同两套金标（sonnet G1 / Datalab）、同打分，多版本多参数。
用法：python3 scripts/bench/ocr_matrix.py ru fr la [--only P0,T0] [--list] [--ledger]
产物：bench/matrix/<tag>/<id>.{txt,json}；汇总 bench/matrix/results.json 与 results.md。
Paddle 行框经 docstore.layout.order_rows 排序后逐行拼接（无 ja 专用过滤，与 Tesseract 公平）。
"""
import argparse, csv, datetime, json, os, subprocess, sys, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/bench")]
from ocr_score import score_page, cer, norm  # noqa: E402
from docstore.layout import order_rows  # noqa: E402
from multi_ocr_lib import clean_md  # noqa: E402
import fitz  # noqa: E402

M = ROOT / "bench/matrix"
PY = "/root/ocr_eval/venv_gpu/bin/python"
V6 = {"text_detection_model_name": "PP-OCRv6_medium_det", "text_recognition_model_name": "PP-OCRv6_medium_rec"}
NOORI = {"use_doc_orientation_classify": False, "use_doc_unwarping": False, "use_textline_orientation": False}
REC5 = {"ru": "eslav", "fr": "latin", "la": "latin", "de": "latin"}
TESS_L = {"ru": "rus", "fr": "fra", "la": "lat", "de": "deu"}


def paddle_cfgs(lang):
    r5 = REC5[lang] + "_PP-OCRv5_mobile_rec"
    base = {**NOORI, **V6}
    c = {
        "P0_v6m": (base, 200),
        "P1_v5sdet+lang5rec": ({**NOORI, "text_detection_model_name": "PP-OCRv5_server_det", "text_recognition_model_name": r5}, 200),
        "P2_v6mdet+lang5rec": ({**NOORI, "text_detection_model_name": "PP-OCRv6_medium_det", "text_recognition_model_name": r5}, 200),
        "P3_v6m_unclip2": ({**base, "text_det_unclip_ratio": 2.0}, 200),
        "P4_v6m_thresh.2": ({**base, "text_det_thresh": 0.2, "text_det_box_thresh": 0.5}, 200),
        "P5_v6m_limitmax2000": ({**base, "text_det_limit_type": "max", "text_det_limit_side_len": 2000}, 200),
        "P6_v6m_textlineori": ({**base, "use_textline_orientation": True}, 200),
        "P7_v6m_dpi300": (base, 300),
        "P8_v5sdet+v6mrec": ({**NOORI, "text_detection_model_name": "PP-OCRv5_server_det", "text_recognition_model_name": "PP-OCRv6_medium_rec"}, 200),
        "P9_lang_default": ({**NOORI, "lang": {"ru": "ru", "fr": "fr", "la": "la"}.get(lang, lang)}, 200),
        "P10_v5mdet+lang5rec": ({**NOORI, "text_detection_model_name": "PP-OCRv5_mobile_det", "text_recognition_model_name": r5}, 200),
    }
    if lang == "ru":
        c["P11_v5sdet+cyrillic5rec"] = ({**NOORI, "text_detection_model_name": "PP-OCRv5_server_det", "text_recognition_model_name": "cyrillic_PP-OCRv5_mobile_rec"}, 200)
    return c


def tess_cfgs(lang):
    L = TESS_L[lang]
    best = ROOT / "bench/tessdata_best"
    c = {
        "T0_base": dict(l=L, psm=3, dpi=200),
        "T1_psm4": dict(l=L, psm=4, dpi=200),
        "T2_psm6": dict(l=L, psm=6, dpi=200),
        "T3_dpi300": dict(l=L, psm=3, dpi=300),
        "T4_dpi400": dict(l=L, psm=3, dpi=400),
        "T5_+eng": dict(l=L + "+eng", psm=3, dpi=200),
        "T6_otsu": dict(l=L, psm=3, dpi=300, prep="otsu"),
        "T7_denoise": dict(l=L, psm=3, dpi=300, prep="denoise"),
        "T8_noheavynr_dict_off": dict(l=L, psm=3, dpi=300, cfg=["-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"]),
    }
    if (best / (L + ".traineddata")).exists():
        c["T9_best"] = dict(l=L, psm=3, dpi=300, tessdata=str(best))
        c["T10_best_dpi200"] = dict(l=L, psm=3, dpi=200, tessdata=str(best))
    # 语言包组合与参数（2026-11-22 第二轮）：+eng 吸收学名拉丁字母；+lat 吸收拉丁学名；best=tessdata_best
    c["T11_+eng_dpi300"] = dict(l=L + "+eng", psm=3, dpi=300)
    c["T12_+eng+lat"] = dict(l=L + "+eng" + ("" if lang == "la" else "+lat"), psm=3, dpi=200)
    c["T13_+eng_ips"] = dict(l=L + "+eng", psm=3, dpi=200, cfg=["-c", "preserve_interword_spaces=1"])
    c["T14_+eng_psm1"] = dict(l=L + "+eng", psm=1, dpi=200)
    c["T15_+eng_oem1"] = dict(l=L + "+eng", psm=3, dpi=200, cfg=["--oem", "1"])
    if all((best / (x + ".traineddata")).exists() for x in L.split("+") + ["eng"]):
        c["T16_best+eng"] = dict(l=L + "+eng", psm=3, dpi=300, tessdata=str(best))
        c["T17_best+eng_dpi200"] = dict(l=L + "+eng", psm=3, dpi=200, tessdata=str(best))
    if all((best / (x + ".traineddata")).exists() for x in L.split("+") + ["eng", "lat"]):
        c["T18_best+eng+lat"] = dict(l=L + "+eng" + ("" if lang == "la" else "+lat"), psm=3, dpi=300, tessdata=str(best))
    return c


def render(r, dpi, prep=""):
    d = M / "img"; d.mkdir(parents=True, exist_ok=True)
    p = d / f"{r['id']}_{dpi}{'_' + prep if prep else ''}.png"
    if not p.exists():
        base = d / f"{r['id']}_{dpi}.png"
        if not base.exists():
            fitz.open(r["pdf"])[int(r["page"]) - 1].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).save(str(base))
        if prep:
            import cv2
            im = cv2.imread(str(base), 0)
            if prep == "otsu":
                im = cv2.threshold(im, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            elif prep == "denoise":
                im = cv2.fastNlMeansDenoising(im, None, 10, 7, 21)
            cv2.imwrite(str(p), im)
        else:
            return base
    return p


def run_tess(tag, cfg, rows):
    from concurrent.futures import ThreadPoolExecutor
    od = M / tag; od.mkdir(parents=True, exist_ok=True)
    todo = [r for r in rows if not (od / f"{r['id']}.txt").exists()]
    for r in todo:
        render(r, cfg["dpi"], cfg.get("prep", ""))  # 先串行渲染，避免线程同时写同一张图
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda r: _tess_one(od, cfg, r), todo))


def _tess_one(od, cfg, r):
    if True:
        out = od / f"{r['id']}.txt"
        img = render(r, cfg["dpi"], cfg.get("prep", ""))
        cmd = ["tesseract", str(img), "stdout", "-l", cfg["l"], "--psm", str(cfg["psm"]), "--dpi", str(cfg["dpi"])]
        if cfg.get("tessdata"):
            cmd += ["--tessdata-dir", cfg["tessdata"]]
        cmd += cfg.get("cfg", [])
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        t = subprocess.run(cmd, capture_output=True, text=True, env=env)
        out.write_text(t.stdout, encoding="utf-8")


def run_paddle(cfgs, rows):
    jobs = []
    for tag, (init, dpi) in cfgs.items():
        od = M / tag; od.mkdir(parents=True, exist_ok=True)
        jobs.append({"tag": tag, "init": init, "items": [{"png": str(render(r, dpi)), "out": str(od / f"{r['id']}.json")} for r in rows]})
    jf = M / "jobs.json"; jf.write_text(json.dumps(jobs))
    subprocess.run([PY, "-u", str(ROOT / "scripts/bench/ppocr_matrix_worker.py"), str(jf)], cwd="/tmp", check=False,
                   stderr=subprocess.DEVNULL)
    for tag in cfgs:
        for r in rows:
            jp = M / tag / f"{r['id']}.json"
            tp = M / tag / f"{r['id']}.txt"
            if jp.exists() and not tp.exists():
                d = json.loads(jp.read_text())
                if "rows" in d:
                    rr = [x for x in d["rows"] if x[1].strip()]
                    tp.write_text("\n".join(str(x[1]) for x in order_rows(rr)), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("langs", nargs="+"); ap.add_argument("--only", default=""); ap.add_argument("--list", action="store_true")
    ap.add_argument("--ledger", action="store_true")
    a = ap.parse_args()
    allrows = list(csv.DictReader(open(ROOT / "bench/samples.csv", encoding="utf-8")))
    only = set(filter(None, a.only.split(",")))
    results = json.loads((M / "results.json").read_text()) if (M / "results.json").exists() else {}
    for lang in a.langs:
        rows = [r for r in allrows if r["lang"] == lang]
        pc, tc = paddle_cfgs(lang), tess_cfgs(lang)
        if only:
            pc = {k: v for k, v in pc.items() if k.split("_")[0] in only or k in only}
            tc = {k: v for k, v in tc.items() if k.split("_")[0] in only or k in only}
        if a.list:
            print(lang, list(pc), list(tc)); continue
        M.mkdir(parents=True, exist_ok=True)
        for tag, cfg in tc.items():
            run_tess(tag, cfg, rows)
        run_paddle(pc, rows)
        for tag in [*pc, *tc]:
            per = []
            for r in rows:
                hp = M / tag / f"{r['id']}.txt"
                if not hp.exists():
                    continue
                hyp = hp.read_text(encoding="utf-8")
                g1 = Path(r["gold_path"]).read_text(encoding="utf-8") if r["gold_path"] else ""
                dl = ROOT / "bench/gold_dl" / lang / f"{r['id']}.md"
                g2 = clean_md(dl.read_text(encoding="utf-8")) if dl.exists() else None
                s1 = score_page(g1, hyp) if g1 else {"cer_norm": float("nan"), "bag_err": float("nan")}; s2 = score_page(g2, hyp) if g2 else None
                per.append({"id": r["id"], "cer1": s1["cer_norm"], "cer2": s2 and s2["cer_norm"], "bag1": s1["bag_err"], "bag2": s2 and s2["bag_err"]})
            results.setdefault(lang, {})[tag] = per
    if a.list:
        return
    (M / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    mean = lambda v: sum(v) / len(v) if v else float("nan")  # noqa: E731
    lines = ["# Tesseract vs PaddleOCR 矩阵（cer_norm 越低越好；排名与结论只看 DL=Datalab 金标（用户规定，禁 Sonnet）；G1 列仅历史参照，均非人工真值）\n"]
    for lang, d in results.items():
        n = max((len(v) for v in d.values()), default=0)
        lines += [f"\n## {lang}（n={n} 页）\n", "| 配置 | CER vs G1 | CER vs DL | bag vs G1 | bag vs DL | 失败页 |", "|---|---|---|---|---|---|"]
        for tag, per in sorted(d.items(), key=lambda kv: mean([p["cer2"] for p in kv[1] if p["cer2"] is not None])):
            fail = n - len(per)
            lines.append(f"| {tag} | {mean([p['cer1'] for p in per]):.4f} | {mean([p['cer2'] for p in per if p['cer2'] is not None]):.4f} | "
                         f"{mean([p['bag1'] for p in per]):.4f} | {mean([p['bag2'] for p in per if p['bag2'] is not None]):.4f} | {fail} |")
    (M / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


main()
