"""文本化：文本层直取，扫描页多引擎 OCR 共识 + 规则纠错。"""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Iterator

from .consensus import Reading, vote
from .engines import ENGINE_MAP
from .engines.rapidocr import rapidocr_run
from .lexicon import Fixer
from .store import Store, agent, make_version

ENGINE_NAMES = {"rapidocr", "tesseract", *ENGINE_MAP}
MIN_CHARS = 30
# 这些 producer 生成的「文本层」本身是机器 OCR，不当原生文本层
OCR_LAYER_PRODUCERS = ("paper capture", "abbyy", "finereader", "clearscan", "ocr", "pagegenie", ".tif")

_FIXER = None

# 多进程 OCR 的启动方式。spawn 最稳（父进程里没有 onnxruntime/sqlite 状态要带过去）；测试里改成 fork 以继承桩函数。
MP_START = "spawn"


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

def _is_real_ocr(v: dict) -> bool:
    """版本是否真由 OCR 引擎识出（latinfix 等后处理版继承底本 method/engine，文本层底本不算）。"""
    eng = str(v.get("engine") or "")
    return v.get("method") == "ocr" and "PyMuPDF" not in eng and "内嵌" not in eng


def layer_is_ocr(meta: dict, pdf=None) -> bool:
    """PDF 自带的文本层是不是扫描件上的 OCR 层。先看 producer/creator；再看版面：抽 3 页，
    有文字且整页被一张图覆盖（≥80% 面积）即为扫描件 OCR 层。
    起因（2026-11-15）：Hartmann-Schröder 1992《Drei neue…》producer 为 PageGenie、1992 Ascension 无 producer，
    文本层字母隔开、双栏乱序，却被当成原生文本层，没有重识。"""
    prod = ((meta or {}).get("producer") or "").lower() + " " + ((meta or {}).get("creator") or "").lower()
    if any(w in prod for w in OCR_LAYER_PRODUCERS):
        return True
    if pdf is None:
        return False
    n = len(pdf)
    for i in sorted({0, n // 2, n - 1}):
        pg = pdf[i]
        area = abs(pg.rect) or 1
        if not pg.get_text().strip():
            continue
        for info in pg.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            if (x1 - x0) * (y1 - y0) >= 0.8 * area:
                return True
    return False


def _iter_engines(path: str, n: int, dpi: int, engines: list[str]) -> Iterator[tuple[str, str, float | None, float]]:
    """逐引擎识别一页，惰性产出 (引擎, 文本, 置信度, 本页已用秒数)。"""
    t_page = time.perf_counter()  # 单调时钟：WSL 下 time.time() 会跳变
    for eng in engines:
        txt, conf = _run_engine(eng, path, n, dpi)
        yield eng, txt, conf, round(time.perf_counter() - t_page, 2)


def _pool_init(threads: int) -> None:
    """OCR 工作进程初始化：限制每进程的 onnxruntime / OpenMP 线程数，使 进程数 x 线程数 约等于核数。"""
    for var in ("OMP_THREAD_LIMIT", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(threads)
    from .engines.rapidocr import set_ort_threads

    set_ort_threads(threads)
    try:  # OpenCV 默认开「核数」个线程，多进程时互相抢核
        import cv2

        cv2.setNumThreads(threads)
    except ImportError:  # pragma: no cover
        pass


def _pool_task(path: str, n: int, dpi: int, engines: list[str]) -> list[tuple[str, str, float | None, float]]:
    return list(_iter_engines(path, n, dpi, engines))


def default_ocr_threads(workers: int) -> int:
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover
        cores = os.cpu_count() or 1
    return max(1, cores // max(1, workers))


# 登记语言 → Tesseract 模型。单语种模型优于混合：Hartmann-Schröder 德文 6 页金标准上词袋错误率
# deu 2.0%、deu+eng 3.5%（变音错 10/229 vs 74/229）、PP-OCRv5 latin 6.2%、PDF 内嵌 ABBYY 层 53%（2026-11-15）。
# 2026-11-22 bench（对 Datalab 参照，n=50/语种，配对 bootstrap）：ru rus→rus+eng CER 0.301→0.131（49/50 页更好）；
# la lat→lat+eng 0.191→0.178（Δ 0.0131 [0.0107,0.0156]，50/50 页）；fr 加 eng 无差别（Δ 0.0003，CI 跨 0），故不加。
TESS_LANG = {"de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "nl": "nld", "la": "lat+eng",
             "ru": "rus+eng", "en": "eng", "zh": "chi_sim+eng", "ja": "jpn"}
_USER_TESS_LANG = os.environ.get("DOCSTORE_TESS_LANG")  # 用户显式设置时始终以它为准


def tess_lang_for(lang: str | None) -> str:
    if _USER_TESS_LANG:
        return _USER_TESS_LANG
    return TESS_LANG.get((lang or "").strip(), "chi_sim+eng")


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
    pages: list[int] | None = None,
    fix: bool = True,
    ocr_threads: int | None = None,
    layer_only: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """文本化。workers>1 时 OCR（渲染+引擎）在进程池里并行，所有写库仍在本进程；每页即时落盘并提交，可续跑。
    pages：只处理这些页（1 起）；fix：对共识文本再跑 lexicon 纠错。"""
    import fitz

    d = store.doc(key)
    path = d["path"]
    if not path or not os.path.exists(path):
        log(f"[{key}] 原件缺失，跳过")
        return {"key": key, "skipped": True}
    by = agent(by)
    os.environ["DOCSTORE_TESS_LANG"] = tess_lang_for(d.get("lang"))  # 子进程池继承
    have = set(store.page_numbers(key))
    with fitz.open(path) as pdf:
        npages = len(pdf)
        ocr_layer = layer_is_ocr(pdf.metadata, pdf)
        todo = [n for n in range(1, npages + 1) if n not in have]
        need_ocr = []
        if ocr_layer:  # 断点续跑：只有内嵌 OCR 层、还没跑过 OCR 的页
            for n in sorted(have):
                pg = store.read_page(key, n) or {}
                vs = [pg] + pg.get("alternates", [])
                if not any(_is_real_ocr(v) for v in vs):
                    need_ocr.append(n)
        if pages is not None:
            want = {p for p in pages if 1 <= p <= npages}
            todo = [n for n in todo if n in want]
            need_ocr = [n for n in need_ocr if n in want]
        if limit is not None:  # 两类页合计不超过 limit
            todo = todo[:limit]
            need_ocr = need_ocr[:max(0, limit - len(todo))]
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
    if layer_only:
        # 只取 PDF 自带文本层（含扫描件的 OCR 层，记 ocr_raw）不做 OCR：大批文献先建检索与语料统计用
        # （2026-11-15 薛整理-杨接力 2906 份）；无文本层的页不落库，之后不带此参数再跑即补 OCR
        _reindex(store, key)
        log(f"[{key}] 只取文本层：原生 {n_text} 页，OCR 层/无文本层待重识 {len(need_ocr)} 页")
        return {"key": key, "text_layer": n_text, "ocr": 0, "pending_ocr": len(need_ocr), "layer_only": True}
    if n_text:
        _reindex(store, key)
        log(f"[{key}] 文本层 {n_text} 页")
    t0 = time.perf_counter()
    done = 0
    engines = engines or ["rapidocr", "tesseract"]
    global _FIXER
    if _FIXER is None:
        _FIXER = Fixer(os.path.join(os.path.dirname(__file__), "rules", "ocr_fix.toml"))

    def save(n: int, results):
        nonlocal done
        readings: list[Reading] = []
        for eng, txt, conf, secs in results:
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
                extra={"run_by": by, "seconds": secs},
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
        single = len({r.source for r in readings}) < 2  # 只有一个引擎读数：无从比对，不算抽检
        fixed, changes = _FIXER.apply(text) if fix else (text, [])
        lv = "ocr_sampled" if unresolved == 0 and not single else "ocr_raw"
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
        pg = store.read_page(key, n) or {}
        cur = str(pg.get("producer") or "")
        # 主版本来自 PDF 文本层（含被 latinfix 改写过的）：新 OCR 必须取代它（2026-11-15 Drei Neue 第 3 页：错层页 20.7% → 1.3%）
        layer_primary = bool(pg) and not _is_real_ocr(pg) and str(pg.get("verify_level") or "") != "ocr_verified"
        store.put_version(key, n, v, promote=True if (cur in ENGINE_NAMES or cur.startswith("consensus(") or layer_primary) else None)
        done += 1
        if done % 10 == 0 or done == len(need_ocr):
            el = time.perf_counter() - t0
            rate = el / done
            log(f"[{key}] OCR {done}/{len(need_ocr)}  {rate:.1f}s/页(墙钟)  预计剩余 {rate * (len(need_ocr) - done) / 60:.1f} 分钟")

    if need_ocr:
        bad = [e for e in engines if e != "rapidocr" and e not in ENGINE_MAP]
        if bad:
            raise ValueError(f"未知 OCR 引擎: {','.join(bad)}")
        log(f"[{key}] 需 OCR {len(need_ocr)} 页，engines={','.join(engines)}")
        if workers <= 1 or len(need_ocr) == 1:
            for n in need_ocr:
                save(n, _iter_engines(path, n, dpi, engines))  # 惰性：每个引擎一出结果就写盘
        else:
            threads = ocr_threads or default_ocr_threads(workers)
            pool = ProcessPoolExecutor(
                max_workers=min(workers, len(need_ocr)),
                mp_context=multiprocessing.get_context(MP_START),
                initializer=_pool_init,
                initargs=(threads,),
            )
            try:
                futs = {pool.submit(_pool_task, path, n, dpi, engines): n for n in need_ocr}
                for fut in as_completed(futs):
                    save(futs[fut], fut.result())
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            pool.shutdown()
    total = len(store.page_numbers(key))
    store.update_doc(key, status="text_done" if total >= npages else f"text_partial {total}/{npages}")
    return {
        "key": key,
        "text_layer": n_text,
        "ocr": len(need_ocr),
        "seconds": round(time.perf_counter() - t0, 1),
        "pages_done": total,
        "pages": npages,
        "engines": engines,
        "vlm": vlm or "",
        "workers": workers,
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
        prod = str(pg.get("producer") or "")
        # 主版本是旧共识或引擎原文：新共识替换它；主版本是模型/人工 OCR 或校正稿：新共识只进 alternates，
        # 不覆盖（2026-11-13 杨德渐2006 cursor 页因无 dpi 被共识按 version_rank 误覆盖 190 页）
        replace = prod.startswith("consensus(") or prod in ENGINE_NAMES
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
        readings = [r for r in readings if not r.source.startswith("consensus(")]
        if not readings:
            continue
        txt, conf, disagreements, unresolved = vote(readings)
        single = len({r.source for r in readings}) < 2
        if _FIXER is None:
            fixer = Fixer(os.path.join(os.path.dirname(__file__), "rules", "ocr_fix.toml"))
        else:
            fixer = _FIXER
        fixed, changes = fixer.apply(txt)
        lv = "ocr_sampled" if unresolved == 0 and not single else "ocr_raw"
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
        store.put_version(key, n, ver, promote=replace)
        touched += 1
    return {"key": key, "recomputed": touched}


def _reindex(store: Store, key: str) -> None:
    for p in store.pages(key):
        store._index_page(p)
    store.con.commit()
