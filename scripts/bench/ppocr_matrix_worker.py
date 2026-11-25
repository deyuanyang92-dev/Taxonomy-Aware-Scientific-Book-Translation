#!/usr/bin/env python3
"""PaddleOCR 矩阵 worker（在 venv_gpu 里跑）。argv[1]=jobs.json：[{tag, init:{...}, items:[{png,out}]}]
每页写 out（JSON：rows=[[poly,text,score]...], w, sec）。同 tag 只加载一次模型。"""
import json, sys, time, os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
from paddleocr import PaddleOCR
jobs = json.load(open(sys.argv[1]))
for j in jobs:
    todo = [it for it in j["items"] if not os.path.exists(it["out"])]
    if not todo:
        continue
    try:
        ocr = PaddleOCR(**j["init"])
    except Exception as e:  # 模型下载/构造失败：记录，不中断其他配置
        for it in todo:
            json.dump({"error": repr(e)[:300]}, open(it["out"], "w"))
        print("FAIL", j["tag"], repr(e)[:200], flush=True)
        continue
    for it in todo:
        t = time.time()
        try:
            r = ocr.predict(it["png"])[0]
            rows = [[[[float(x), float(y)] for x, y in p], str(tx), float(s)]
                    for p, tx, s in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"])]
            json.dump({"rows": rows, "sec": time.time() - t}, open(it["out"], "w"), ensure_ascii=False)
        except Exception as e:
            json.dump({"error": repr(e)[:300]}, open(it["out"], "w"))
    print("DONE", j["tag"], flush=True)
