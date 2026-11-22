#!/usr/bin/env python3
"""bench/samples.csv 中指定语言的样本页逐页提交 Datalab /api/v1/convert（accurate），结果存 bench/gold_dl/<lang>/<id>.md。
密钥只读环境变量 DATALAB_API_KEY，或文件 ~/.datalab_key（chmod 600）；不写进仓库。
用法：python3 scripts/bench/dl_gold.py ru fr la [--workers 4]；已存在的页跳过，可续跑。
Datalab 输出是参照金标（非人工真值）；本项目金标只用 Datalab，禁用 Sonnet（用户 2026-11-21）。
"""
import csv, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fitz
import requests

ROOT = Path(__file__).resolve().parents[2]
KEY = os.environ.get("DATALAB_API_KEY") or (Path.home() / ".datalab_key").read_text().strip()
H = {"X-API-Key": KEY}
args = sys.argv[1:]
workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 4
langs = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--workers")]


def one(r, od):
    out = od / f"{r['id']}.md"
    d = fitz.open(r["pdf"]); o = fitz.open(); o.insert_pdf(d, from_page=int(r["page"]) - 1, to_page=int(r["page"]) - 1)
    for attempt in range(3):
        try:
            j = requests.post("https://www.datalab.to/api/v1/convert", headers=H, files={"file": (r["id"] + ".pdf", o.tobytes(), "application/pdf")},
                              data={"mode": "accurate", "output_format": "markdown", "disable_image_captions": "true",
                                    "disable_image_extraction": "true"}, timeout=120)
            j.raise_for_status(); chk = j.json()["request_check_url"]; t0 = time.time()
            while True:
                time.sleep(2); k = requests.get(chk, headers=H, timeout=60).json()
                if k.get("status") == "complete" or time.time() - t0 > 600:
                    break
            if k.get("success"):
                out.write_text(k.get("markdown") or "", encoding="utf-8")
                print("ok", r["id"], len(k.get("markdown") or ""), round(time.time() - t0), "s", flush=True)
                return
            print("FAIL", r["id"], k.get("error"), flush=True)
        except Exception as e:  # 网络/限流：重试
            print("RETRY", r["id"], repr(e)[:120], flush=True); time.sleep(5 * (attempt + 1))


todo = []
for lang in langs:
    od = ROOT / "bench" / "gold_dl" / lang
    od.mkdir(parents=True, exist_ok=True)
    todo += [(r, od) for r in csv.DictReader(open(ROOT / "bench/samples.csv", encoding="utf-8"))
             if r["lang"] == lang and not (od / f"{r['id']}.md").exists()]
print("todo", len(todo), flush=True)
with ThreadPoolExecutor(workers) as ex:
    list(ex.map(lambda t: one(*t), todo))
