#!/usr/bin/env python3
"""本地 PaddleOCR 版面引擎（须在装有 paddleocr 的 venv 里跑，如 /root/ocr_eval/venv_gpu/bin/python）。

输出与云端同构的 JSON：{"layout":{"width_px","height_px","pruned_result":{"parsing_res_list":[{block_label,block_bbox,block_content,block_order}]}},"seconds"}。
  python layout_paddle_local.py vl|structure <page.png> -o out.json
  python layout_paddle_local.py doclayout <outdir> <s22.png> <s23.png> ...   # 只出版面框（无文字），文字由适配器用 tesseract 填
vl = PaddleOCRVL（PP-DocLayoutV3 + VL 0.9B）；structure = PPStructureV3（版面 + PP-OCRv5）。
实测（GTX 1660S 6GB，2026-11-26）：vl 单页 >280 s 未出结果；structure 缺模型且无网络下载，均失败；doclayout 约 1 s/页可用。
"""
import json
import sys
import time


def doclayout(outdir: str, pngs: list[str]) -> int:
    import os
    from PIL import Image
    from paddleocr import LayoutDetection
    os.makedirs(outdir, exist_ok=True)
    m = LayoutDetection(model_name="PP-DocLayoutV3")
    for png in pngs:
        w, h = Image.open(png).size
        t = time.time()
        res = list(m.predict(png, batch_size=1))
        sec = time.time() - t
        lst = []
        for r in res:
            j = r.json.get("res", r.json)
            for k, b in enumerate(j["boxes"]):
                lst.append({"block_label": b["label"], "block_bbox": [float(c) for c in b["coordinate"]], "block_content": "",
                            "block_order": b.get("order", k)})
        stem = os.path.basename(png).removeprefix("s").removesuffix(".png")
        json.dump({"layout": {"width_px": w, "height_px": h, "pruned_result": {"parsing_res_list": lst}}, "seconds": round(sec, 2)},
                  open(os.path.join(outdir, f"p{int(stem):04d}.json"), "w"), ensure_ascii=False)
        print(png, len(lst), round(sec, 2), "s")
    return 0


def main() -> int:
    if sys.argv[1] == "doclayout":
        return doclayout(sys.argv[2], sys.argv[3:])
    mode, png = sys.argv[1], sys.argv[2]
    out = sys.argv[sys.argv.index("-o") + 1]
    from PIL import Image
    w, h = Image.open(png).size
    t = time.time()
    if mode == "vl":
        from paddleocr import PaddleOCRVL
        pipe = PaddleOCRVL()
    else:
        from paddleocr import PPStructureV3
        pipe = PPStructureV3(use_table_recognition=False, use_formula_recognition=False, use_chart_recognition=False)
    res = pipe.predict(png)
    sec = time.time() - t
    lst = []
    for r in res:
        j = r.json if hasattr(r, "json") else r
        j = j.get("res", j)
        for k, b in enumerate(j.get("parsing_res_list", [])):
            lst.append({"block_label": b.get("block_label"), "block_bbox": b.get("block_bbox"),
                        "block_content": b.get("block_content"), "block_order": b.get("block_order") if b.get("block_order") is not None else k})
    json.dump({"layout": {"width_px": w, "height_px": h, "pruned_result": {"parsing_res_list": lst}}, "seconds": round(sec, 2)},
              open(out, "w"), ensure_ascii=False)
    print(mode, len(lst), "blocks", round(sec, 1), "s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
