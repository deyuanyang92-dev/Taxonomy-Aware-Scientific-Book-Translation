#!/usr/bin/env python3
"""OvisOCR2 本地推理（transformers，fp16；官方只给 vLLM，本机 GTX1660S 无 bf16，见 docs/ocr_eval）。
用法：/root/ocr_eval/venv_vlm/bin/python scripts/bench/ovis_hf.py ru fr la [--limit N] [--maxpix 1600]
输出 bench/api_runs/OvisOCR2-local/<lang>/<id>.md（与云 API 同目录结构，供同一打分脚本使用）。
提示词逐字取自官方 README（ATH-MaaS/OvisOCR2）。
"""
import csv
import sys
import time
import re
from pathlib import Path
import fitz
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

ROOT = Path(__file__).resolve().parents[2]
MP = "/root/ocr_eval/ovis/OvisOCR2"
PROMPT = "\nundefined"
a = sys.argv[1:]
limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 10**9
maxpix = int(a[a.index("--maxpix") + 1]) if "--maxpix" in a else 1600
langs = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in ("--limit", "--maxpix"))]
proc = AutoProcessor.from_pretrained(MP)
model = AutoModelForImageTextToText.from_pretrained(MP, torch_dtype=torch.float16).cuda().eval()


def derep(t):
    if len(t) < 8000: return t
    for p in range(1, 201):
        m = re.search(r"(.{%d})\1{4,}\Z" % p, t, re.S)
        if m and len(m.group(0)) >= 100: return t[: m.start()] + m.group(1)
    return t


for lang in langs:
    od = ROOT / "bench/api_runs/OvisOCR2-local" / lang; od.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.DictReader(open(ROOT / "bench/samples.csv", encoding="utf-8")) if r["lang"] == lang and not (od / f"{r['id']}.md").exists()][:limit]
    for r in rows:
        t0 = time.time()
        try:
            pg = fitz.open(r["pdf"])[int(r["page"]) - 1]
            pix = pg.get_pixmap(dpi=200); img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            s = min(1.0, (maxpix * maxpix / (img.width * img.height)) ** 0.5)
            if s < 1: img = img.resize((int(img.width * s), int(img.height * s)))
            msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
            text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inp = proc(text=[text], images=[img], return_tensors="pt").to("cuda")
            with torch.no_grad():
                out = model.generate(**inp, max_new_tokens=4096, do_sample=False, stop_strings=["<think>"], tokenizer=proc.tokenizer)
            md = proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
            md = md.split("<think>")[0].strip()
            md = derep(re.sub(r'<img src="images/bbox_[^>]*/>', "", md))
            (od / f"{r['id']}.md").write_text(md, encoding="utf-8")
            print("ok", r["id"], len(md), round(time.time() - t0), "s", torch.cuda.max_memory_allocated() // 2**20, "MiB", flush=True)
        except Exception as e:
            print("ERR", r["id"], repr(e)[:300], flush=True); torch.cuda.empty_cache()
