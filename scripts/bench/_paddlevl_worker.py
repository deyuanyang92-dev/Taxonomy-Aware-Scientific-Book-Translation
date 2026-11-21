"""PaddleOCR-VL 批处理：python _paddlevl_worker.py <img_dir> <out_raw>；每图写 <key>.txt（markdown 文本）。"""
import sys
import time
from pathlib import Path

from paddleocr import PaddleOCRVL

img_dir, raw = Path(sys.argv[1]), Path(sys.argv[2])
raw.mkdir(parents=True, exist_ok=True)
pipe = PaddleOCRVL()
for p in sorted(img_dir.glob("*.png")):
    t = time.time()
    res = pipe.predict(str(p))
    md = "\n\n".join(r.markdown["markdown_texts"] for r in res)
    (raw / f"{p.stem}.txt").write_text(md, encoding="utf-8")
    print(p.stem, f"{time.time()-t:.1f}s", flush=True)
