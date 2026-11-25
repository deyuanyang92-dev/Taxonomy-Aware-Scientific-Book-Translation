#!/usr/bin/env python3
"""PaddleOCR AI Studio 云 API（免费额度）：bench/samples.csv 的页逐页提交，结果存 bench/api_runs/<model>/<id>.md。
密钥读 ~/.paddleocr_aistudio_token 或环境变量 PADDLEOCR_TOKEN；不写进仓库。
用法：python3 scripts/bench/paddle_api.py <model> ru fr la [--limit N] [--workers 3]
model 例：PaddleOCR-VL-1.6、PP-StructureV3、PP-OCRv5（以平台实际支持为准，失败会打印 errorMsg）。
"""
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fitz
import requests

ROOT = Path(__file__).resolve().parents[2]
TOKEN = os.environ.get("PADDLEOCR_TOKEN") or (Path.home() / ".paddleocr_aistudio_token").read_text().strip()
URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
H = {"Authorization": f"bearer {TOKEN}"}
OPT = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}
a = sys.argv[1:]
model = a[0]
workers = int(a[a.index("--workers") + 1]) if "--workers" in a else 3
limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 10**9
langs = [x for i, x in enumerate(a[1:], 1) if not x.startswith("--") and a[i - 1] not in ("--workers", "--limit")]


def one(r, od):
    out = od / f"{r['id']}.md"
    d = fitz.open(r["pdf"]); o = fitz.open(); o.insert_pdf(d, from_page=int(r["page"]) - 1, to_page=int(r["page"]) - 1)
    t0 = time.time()
    try:
        j = requests.post(URL, headers=H, data={"model": model, "optionalPayload": json.dumps(OPT)},
                          files={"file": (r["id"] + ".pdf", o.tobytes(), "application/pdf")}, timeout=120)
        if j.status_code != 200:
            print("FAIL", r["id"], j.status_code, j.text[:200], flush=True); return
        jid = j.json()["data"]["jobId"]
        while time.time() - t0 < 600:
            time.sleep(3)
            k = requests.get(f"{URL}/{jid}", headers=H, timeout=60).json()["data"]
            if k["state"] == "done":
                txt = requests.get(k["resultUrl"]["jsonUrl"], timeout=120).text
                recs = [json.loads(ln)["result"] for ln in txt.strip().split("\n") if ln.strip()]
                if recs and "ocrResults" in recs[0]:  # PP-OCRv5 纯 OCR：无 markdown，按行拼接 rec_texts
                    md = "\n".join(t for rr in recs for res in rr["ocrResults"] for t in res["prunedResult"]["rec_texts"])
                else:
                    md = "\n".join(res["markdown"]["text"] for rr in recs for res in rr["layoutParsingResults"])
                out.write_text(md, encoding="utf-8")
                print("ok", r["id"], len(md), round(time.time() - t0), "s", flush=True); return
            if k["state"] == "failed":
                print("FAIL", r["id"], k.get("errorMsg"), flush=True); return
        print("TIMEOUT", r["id"], flush=True)
    except Exception as e:
        print("ERR", r["id"], repr(e)[:150], flush=True)


todo = []
for lang in langs:
    od = ROOT / "bench" / "api_runs" / model / lang
    od.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.DictReader(open(ROOT / "bench/samples.csv", encoding="utf-8")) if r["lang"] == lang and not (od / f"{r['id']}.md").exists()]
    todo += [(r, od) for r in rows[:limit]]
print("todo", len(todo), flush=True)
with ThreadPoolExecutor(workers) as ex:
    list(ex.map(lambda t: one(*t), todo))
