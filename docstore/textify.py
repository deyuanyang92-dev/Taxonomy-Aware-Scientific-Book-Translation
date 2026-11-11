"""文本化：文本层直取，扫描页多引擎 OCR 共识 + 规则纠错。"""

from __future__ import annotations

import os
import time
from typing import Callable

from .consensus import Reading, vote
from .engines import ENGINE_MAP
from .engines.rapidocr import rapidocr_run
from .lexicon import Fixer
from .store import Store, agent, make_version

MIN_CHARS = 30
# 这些 producer 生成的「文本层」本身是机器 OCR，不当原生文本层
OCR_LAYER_PRODUCERS = ("paper capture", "abbyy", "finereader", "clearscan", "ocr")

_FIXER = None


def rapid_ocr(pdf_path: str, n: int, dpi: int) -> tuple[str, float | None]:
    return rapidocr_run(pdf_path, n, dpi)


OCR_FUNC: Callable[[str, int, int], tuple[str, float | None]] = rapid_ocr
OCR_ENGINE_NAME = "RapidOCR (rapidocr_onnxruntime)"


def _run_engine(name: str, pdf_path: str, n: int, dpi: int) -> tuple[str, float | None]:
    if name == "rapidocr":
        return OCR_FUNC(pdf_path, n, dpi)
    fn = ENGINE_MAP.get(name)
    if fn is None:
        raise ValueError(f"未知 OCR 引擎: {name}")
    return fn(pdf_path, n, dpi)


def layer_is_ocr(meta: dict) -> bool:
    prod = ((meta or {}).get("producer") or "").lower() + " " + ((meta or {}).get("creator") or "").lower()
    return any(w in prod for w in OCR_LAYER_PRODUCERS)


def textify(
    store: Store,
    key: str,
    *,
    by: str | None = None,
    workers: int = 4,
    dpi: int = 300,
    limit: int | None = None,
    engines: list[str] | None = None,
    vlm: str | None = None,
    log: Callable[[str], None] = print,
) -> dict:
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
    engines = engines or ["rapidocr", "tesseract"]
    global _FIXER
    if _FIXER is None:
        _FIXER = Fixer(os.path.join(os.path.dirname(__file__), "rules", "ocr_fix.toml"))

    def save(n: int):
        nonlocal done
        t_page = time.time()
        readings: list[Reading] = []
        for eng in engines:
            txt, conf = _run_engine(eng, path, n, dpi)
            c = float(conf) if conf is not None else 0.5
            readings.append(Reading(source=eng, text=txt, conf=c))
            ev = make_version(
                txt,
                "ocr",
                producer=eng,
                engine=f"{eng} {dpi}dpi",
                dpi=dpi,
                conf=conf,
                source=path,
                extra={"run_by": by, "seconds": round(time.time() - t_page, 2)},
            )
            store.put_version(key, n, ev, index=False)
        pg = store.read_page(key, n) or {}
        for av in pg.get("alternates", []):
            if av.get("method") == "ocr":
                txt = av.get("text") or ""
                q = av.get("quality") or {}
                readings.append(
                    Reading(
                        source=av.get("producer") or "alternate",
                        text=txt,
                        conf=float(q.get("ocr_conf") or 0.5),
                    )
                )
        text, conf, disagreements, unresolved = vote(readings)
        fixed, changes = _FIXER.apply(text)
        lv = "ocr_sampled" if unresolved == 0 else "ocr_raw"
        if vlm and unresolved > 0:
            # VLM 接口保留，未能确定时继续保留 [?]
            lv = "ocr_raw"
        tag = "+".join(engines) + ("+vlm" if vlm else "")
        v = make_version(
            fixed,
            "ocr",
            producer=f"consensus({tag})",
            engine=f"consensus {dpi}dpi",
            dpi=dpi,
            conf=conf,
            source=f"{path}#consensus",
            level=lv,
            extra={
                "run_by": by,
                "disagreements": disagreements,
                "unresolved_chars": unresolved,
                "lexicon_changes": changes,
            },
        )
        store.put_version(key, n, v)
        done += 1
        if done % 10 == 0 or done == len(need_ocr):
            el = time.time() - t0
            rate = el / done
            log(f"[{key}] OCR {done}/{len(need_ocr)}  {rate:.1f}s/页(墙钟)  预计剩余 {rate * (len(need_ocr) - done) / 60:.1f} 分钟")

    if need_ocr:
        log(f"[{key}] 需 OCR {len(need_ocr)} 页，engines={','.join(engines)}")
        for n in need_ocr:
            save(n)
    total = len(store.page_numbers(key))
    store.update_doc(key, status="text_done" if total >= npages else f"text_partial {total}/{npages}")
    return {
        "key": key,
        "text_layer": n_text,
        "ocr": len(need_ocr),
        "seconds": round(time.time() - t0, 1),
        "pages_done": total,
        "pages": npages,
        "engines": engines,
        "vlm": vlm or "",
    }


def consensus(store: Store, key: str, *, pages: list[int] | None = None, by: str | None = None, dpi: int = 300) -> dict:
    """Recompute consensus from existing OCR alternates/pages without rerunning OCR."""
    by = agent(by)
    nums = pages or store.page_numbers(key)
    touched = 0
    for n in nums:
        pg = store.read_page(key, n)
        if not pg:
            continue
        vars_ = [pg] + pg.get("alternates", [])
        readings = []
        for v in vars_:
            if v.get("method") == "ocr":
                readings.append(
                    Reading(
                        source=v.get("producer") or "ocr",
                        text=v.get("text") or "",
                        conf=float((v.get("quality") or {}).get("ocr_conf") or 0.5),
                    )
                )
        if len(readings) < 2:
            continue
        txt, conf, disagreements, unresolved = vote(readings)
        if _FIXER is None:
            fixer = Fixer(os.path.join(os.path.dirname(__file__), "rules", "ocr_fix.toml"))
        else:
            fixer = _FIXER
        fixed, changes = fixer.apply(txt)
        lv = "ocr_sampled" if unresolved == 0 else "ocr_raw"
        ver = make_version(
            fixed,
            "ocr",
            producer="consensus(rebuild)",
            engine=f"consensus {dpi}dpi",
            dpi=dpi,
            conf=conf,
            level=lv,
            source=(store.doc(key).get("path") or "") + "#consensus",
            extra={"run_by": by, "disagreements": disagreements, "lexicon_changes": changes},
        )
        store.put_version(key, n, ver)
        touched += 1
    return {"key": key, "recomputed": touched}


def _reindex(store: Store, key: str) -> None:
    for p in store.pages(key):
        store._index_page(p)
    store.con.commit()
