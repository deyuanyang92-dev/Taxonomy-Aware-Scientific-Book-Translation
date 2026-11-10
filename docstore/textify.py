"""文本化：有文本层（每页可抽字符 ≥30）直取；否则 RapidOCR 300 dpi。断点续跑：已有页面记录的页跳过。

OCR 引擎可替换：把 OCR_FUNC 换成签名为 (pdf_path, page_no, dpi) -> (text, mean_conf) 的函数即可（测试用桩函数）。
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

from .store import Store, agent, make_version

MIN_CHARS = 30
# 这些 producer 生成的「文本层」本身是机器 OCR，不当原生文本层
OCR_LAYER_PRODUCERS = ("paper capture", "abbyy", "finereader", "clearscan", "ocr")

_ENGINE = None


def rapid_ocr(pdf_path: str, n: int, dpi: int) -> tuple[str, float | None]:
    global _ENGINE
    import warnings

    import fitz

    warnings.filterwarnings("ignore")
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    with fitz.open(pdf_path) as d:
        png = d[n - 1].get_pixmap(dpi=dpi).tobytes("png")
    res, _ = _ENGINE(png)
    res = res or []
    text = "\n".join(r[1] for r in res)
    conf = (sum(float(r[2]) for r in res) / len(res)) if res else None
    return text, conf


OCR_FUNC: Callable[[str, int, int], tuple[str, float | None]] = rapid_ocr
OCR_ENGINE_NAME = "RapidOCR (rapidocr_onnxruntime)"


def _job(args):
    pdf_path, n, dpi = args
    t0 = time.time()
    text, conf = OCR_FUNC(pdf_path, n, dpi)
    return n, text, conf, time.time() - t0


def layer_is_ocr(meta: dict) -> bool:
    prod = ((meta or {}).get("producer") or "").lower() + " " + ((meta or {}).get("creator") or "").lower()
    return any(w in prod for w in OCR_LAYER_PRODUCERS)


def textify(store: Store, key: str, *, by: str | None = None, workers: int = 4, dpi: int = 300,
            limit: int | None = None, log: Callable[[str], None] = print) -> dict:
    import fitz

    d = store.doc(key)
    path = d["path"]
    if not path or not os.path.exists(path):
        log(f"[{key}] 原件缺失，跳过")
        return {"key": key, "skipped": True}
    by = agent(by)
    have = set(store.page_numbers(key))
    with fitz.open(path) as pdf:
        npages = len(pdf)
        ocr_layer = layer_is_ocr(pdf.metadata)
        todo = [n for n in range(1, npages + 1) if n not in have]
        need_ocr = []
        if ocr_layer:  # 断点续跑：只有内嵌 OCR 层、还没跑过 OCR 的页
            for n in sorted(have):
                pg = store.read_page(key, n) or {}
                vs = [pg] + pg.get("alternates", [])
                if not any(v.get("method") == "ocr" for v in vs):
                    need_ocr.append(n)
        if limit is not None:
            todo = todo[:limit]
            need_ocr = need_ocr[:limit]
        n_text = 0
        for n in todo:
            txt = pdf[n - 1].get_text()
            chars = len("".join(txt.split()))
            if chars >= MIN_CHARS:
                if ocr_layer:
                    # PDF 自带的 OCR 文本层：记为 ocr_raw，再用 300 dpi 重识
                    store.put_version(key, n, make_version(txt, "text_layer_ocr", producer="pdf-text-layer",
                                                           engine=f"PDF 内嵌 OCR 层 ({pdf.metadata.get('producer')})",
                                                           level="ocr_raw", source=path), index=False)
                    need_ocr.append(n)
                else:
                    store.put_version(key, n, make_version(txt, "text_layer", producer=f"script:docstore({by})",
                                                           engine="PyMuPDF get_text", source=path), index=False)
                    n_text += 1
            else:
                need_ocr.append(n)
        store.con.commit()
    if n_text:
        _reindex(store, key)
        log(f"[{key}] 文本层 {n_text} 页")
    t0 = time.time()
    done = 0

    def save(n, text, conf, secs):
        nonlocal done
        v = make_version(text, "ocr", producer="rapidocr" if OCR_FUNC is rapid_ocr else f"ocr({by})",
                         engine=f"{OCR_ENGINE_NAME} {dpi}dpi", dpi=dpi, conf=conf, source=path,
                         extra={"run_by": by, "seconds": round(secs, 2)})
        store.put_version(key, n, v)
        done += 1
        if done % 10 == 0 or done == len(need_ocr):
            el = time.time() - t0
            rate = el / done
            log(f"[{key}] OCR {done}/{len(need_ocr)}  {rate:.1f}s/页(墙钟)  预计剩余 {rate * (len(need_ocr) - done) / 60:.1f} 分钟")

    if need_ocr:
        log(f"[{key}] 需 OCR {len(need_ocr)} 页，workers={workers}")
        jobs = [(path, n, dpi) for n in need_ocr]
        if workers <= 1:
            for j in jobs:
                save(*_job(j))
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_job, j) for j in jobs]
                for f in as_completed(futs):
                    save(*f.result())
    total = len(store.page_numbers(key))
    store.update_doc(key, status="text_done" if total >= npages else f"text_partial {total}/{npages}")
    return {"key": key, "text_layer": n_text, "ocr": len(need_ocr), "seconds": round(time.time() - t0, 1),
            "pages_done": total, "pages": npages}


def _reindex(store: Store, key: str) -> None:
    for p in store.pages(key):
        store._index_page(p)
    store.con.commit()
