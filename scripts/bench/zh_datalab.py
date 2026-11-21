#!/usr/bin/env python3
"""把 zh_fauna/pages/*.pdf 逐页提交 Datalab /api/v1/convert，结果存 zh_fauna/datalab/<id>.md + .json。
密钥读环境变量 DATALAB_API_KEY（或 test-ocr/.env.datalab）。用法：python3 zh_datalab.py [--mode accurate]
"""
import argparse, json, os, time
from pathlib import Path
import requests

TO = Path(__file__).resolve().parents[2] / "test-ocr"
envf = TO / ".env.datalab"
if "DATALAB_API_KEY" not in os.environ and envf.exists():
    for ln in envf.read_text().splitlines():
        if ln.startswith("DATALAB_API_KEY="):
            os.environ["DATALAB_API_KEY"] = ln.split("=", 1)[1].strip()
H = {"X-API-Key": os.environ["DATALAB_API_KEY"]}
ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="accurate"); ap.add_argument("--ids", default="")
a = ap.parse_args()
od = TO / "zh_fauna" / "datalab"; od.mkdir(parents=True, exist_ok=True)
for pdf in sorted((TO / "zh_fauna" / "pages").glob("*.pdf")):
    if a.ids and pdf.stem not in a.ids.split(","):
        continue
    if (od / f"{pdf.stem}.md").exists():
        continue
    r = requests.post("https://www.datalab.to/api/v1/convert", headers=H,
                      files={"file": (pdf.name, open(pdf, "rb"), "application/pdf")},
                      data={"mode": a.mode, "output_format": "markdown", "disable_image_captions": "true", "disable_image_extraction": "true"}, timeout=120)
    r.raise_for_status(); chk = r.json()["request_check_url"]; t0 = time.time()
    while True:
        time.sleep(2); j = requests.get(chk, headers=H, timeout=60).json()
        if j.get("status") == "complete":
            break
        if time.time() - t0 > 600:
            raise SystemExit(f"timeout {pdf.stem}")
    if j.get("success") is False:
        print("FAIL", pdf.stem, j.get("error")); continue
    (od / f"{pdf.stem}.md").write_text(j.get("markdown") or "", encoding="utf-8")
    (od / f"{pdf.stem}.json").write_text(json.dumps({k: v for k, v in j.items() if k not in ("markdown", "json", "images")}, ensure_ascii=False), encoding="utf-8")
    print("ok", pdf.stem, len(j.get("markdown") or ""), round(time.time() - t0, 1), "s", flush=True)
