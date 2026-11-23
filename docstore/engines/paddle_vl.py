"""PaddleOCR AI Studio 云 API（PaddleOCR-VL，免费额度），设计见 docs/ocr_eval/paddle_cloud_design.md 第 3 节（v2）。

密钥读环境变量 PADDLEOCR_TOKEN 或 ~/.paddleocr_aistudio_token，不入库。缺密钥抛 RuntimeError，由 textify 按路由表降级到本地引擎。
模型名可用 DOCSTORE_PADDLE_VL_MODEL 覆盖（缺省 PaddleOCR-VL-1.6）。返回文本经 clean_md 去 markdown/HTML 标记
（与 bench 评分同口径）；云 API 不给置信度，返回 None。

只有通过全部闸口（HTTP/业务码、进度、JSONL 结构、页身份、逐页文本）的页才返回；其余页写进 failed，由调用方降级。
网络：requests.Session，trust_env=False（直连，实测经代理上传大文件会断）；PADDLEOCR_USE_PROXY=1 时走系统代理。
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import fitz
import requests

URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
OPT = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}
TIMEOUT_S = 1800  # 块总等待上限；env DOCSTORE_PADDLE_JOB_TIMEOUT 覆盖
UPLOAD_TIMEOUT_S = 300
POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 3.0
BACKOFF_S = (10, 30, 90)  # 暂时性错误退避
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_BYTES = 45 * 1024 * 1024
SIZE_TOL_PX = 2  # 页身份校验：返回宽高 vs 提交页 rect x2 的容差
BLANK_DPI = 30
BLANK_INK_FRAC = 0.005
_sleep: Callable[[float], None] = time.sleep
_now: Callable[[], float] = time.monotonic
_FITZ_LOCK = threading.Lock()  # fitz(MuPDF) 非线程安全：所有 fitz 操作串行


class PaddleConfigError(ValueError):
    """配置错（密钥/模型/权限）：立即上抛，不降级。"""


class PaddleQuotaError(RuntimeError):
    """配额用尽：停止所有云提交，剩余页只用 fallback 引擎。"""


class PaddleStopped(RuntimeError):
    """共享停止事件已置位（配额/配置错）：本块不再提交。"""


class PaddleJobError(RuntimeError):
    """云任务失败。kind: transient（可退避重试/重提）| shrink（缩块）| file（文件问题，不重试）
    | job（已有 jobId 的轮询/下载耗尽或超时：块失败，不重新上传）。"""

    def __init__(self, msg: str, kind: str = "transient"):
        super().__init__(msg)
        self.kind = kind


def clean_md(t: str) -> str:
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"</?[a-z][^>]*>", "", t)
    return re.sub(r"[*_]{1,3}", "", t)


def _token() -> str:
    tok = os.environ.get("PADDLEOCR_TOKEN")
    if tok:
        return tok.strip()
    p = Path.home() / ".paddleocr_aistudio_token"
    if p.exists():
        return p.read_text().strip()
    raise RuntimeError("缺 PaddleOCR 云密钥（PADDLEOCR_TOKEN 或 ~/.paddleocr_aistudio_token）")


def _new_session() -> Any:
    s = requests.Session()
    s.trust_env = os.environ.get("PADDLEOCR_USE_PROXY") == "1"
    return s


def _env_int(name: str, default: int, lo: int, hi: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        v = int(raw)
    except ValueError:
        raise PaddleConfigError(f"{name}={raw!r} 不是整数") from None
    if v < lo or (hi is not None and v > hi):
        raise PaddleConfigError(f"{name}={v} 越界 [{lo},{hi if hi is not None else '∞'}]")
    return v


def max_pages() -> int:
    return _env_int("DOCSTORE_PADDLE_MAX_PAGES", DEFAULT_MAX_PAGES, 1, 100)


# ---------------------------------------------------------------- 分块

def _build_pdf(pdf_path: str, pages: list[int]) -> bytes:
    """按给定顺序把若干页（1 起）拼成一个 PDF。"""
    with _FITZ_LOCK, fitz.open(pdf_path) as src, fitz.open() as out:
        for p in pages:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        return out.tobytes()


def plan_chunks(
    pdf_path: str, pages: list[int], *, max_pages_: int | None = None, max_bytes: int | None = None
) -> tuple[list[tuple[list[int], bytes]], dict[int, str]]:
    """有序页码 -> [(块页码, 块 PDF 字节)], {超限页: 原因}。每块 <= max_pages；字节超限则对半拆，单页仍超则记失败。"""
    mp = max_pages_ if max_pages_ is not None else max_pages()
    mb = max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES
    chunks: list[tuple[list[int], bytes]] = []
    oversize: dict[int, str] = {}

    def fit(ps: list[int]) -> None:
        data = _build_pdf(pdf_path, ps)
        if len(data) <= mb:
            chunks.append((ps, data))
        elif len(ps) == 1:
            oversize[ps[0]] = f"oversize: 单页 {len(data)} 字节 > {mb}"
        else:
            mid = len(ps) // 2
            fit(ps[:mid])
            fit(ps[mid:])

    for i in range(0, len(pages), mp):
        fit(list(pages[i:i + mp]))
    return chunks, oversize


# ---------------------------------------------------------------- 错误分类

def _classify(status: int, code: Any) -> str:
    """-> config | quota | shrink | file | transient（设计 3.3）。"""
    if status == 401 or (status == 403 and code != 12001) or code in (10007, 10008, 10009, 11001):
        return "config"
    if code == 12001 or (status == 429 and code != 12002):
        return "quota"
    if code in (10003, 10006) or status == 413:
        return "shrink"
    if code in (10001, 10002, 10004, 10005):
        return "file"
    return "transient"


def _body(r: Any) -> dict:
    try:
        b = r.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def _check(r: Any, what: str) -> dict:
    """HTTP 200 且 code==0 才返回 body，否则按分类抛异常。"""
    status = r.status_code
    b = _body(r)
    code = b.get("code")
    if status == 200 and code == 0:
        return b
    msg = f"{what}: HTTP {status} code={code} msg={b.get('msg')!r} traceId={b.get('traceId')}"
    kind = _classify(status, code)
    if kind == "config":
        raise PaddleConfigError(msg)
    if kind == "quota":
        raise PaddleQuotaError(msg)
    if kind in ("shrink", "file"):
        raise PaddleJobError(msg, kind)
    raise PaddleJobError(msg + (" " + (r.text or "")[:200] if not b else ""), "transient")


def _net(fn: Callable[[], Any], what: str) -> Any:
    try:
        return fn()
    except requests.RequestException as e:
        raise PaddleJobError(f"{what}: 网络错误 {e!r}") from e


def _retry_same(fn: Callable[[], Any], log: Callable[[str], None], what: str, deadline: float | None = None) -> Any:
    """轮询/下载的暂时错误：只重试同一 jobId，不重复提交。耗尽或越过截止时间抛 kind=job（块失败，不重传）。"""
    for i in range(len(BACKOFF_S) + 1):
        try:
            return fn()
        except PaddleJobError as e:
            if e.kind != "transient":
                raise
            if i == len(BACKOFF_S):
                raise PaddleJobError(f"{what} 重试耗尽: {e}", "job") from e
            if deadline is not None and _now() + BACKOFF_S[i] > deadline:
                raise PaddleJobError(f"{what} 超过截止时间，放弃重试: {e}", "job") from e
            log(f"[paddle] {what} 暂时错误，{BACKOFF_S[i]}s 后重试同一任务: {e}")
            _sleep(BACKOFF_S[i])
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------- 一个块

def _int_like(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if math.isfinite(v) and v >= 0 and v == int(v) else None
    if isinstance(v, str) and re.fullmatch(r"[0-9]+", v.strip()):
        return int(v.strip())
    return None


def _pos_finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _label(ps: list[int]) -> str:
    """日志块标签：连续页 a-b，否则页码列表。"""
    if len(ps) == 1:
        return str(ps[0])
    if ps == list(range(ps[0], ps[0] + len(ps))):
        return f"{ps[0]}-{ps[-1]}"
    return ",".join(map(str, ps))


def _page_sizes(pdf_path: str, pages: list[int]) -> list[tuple[float, float]]:
    with _FITZ_LOCK, fitz.open(pdf_path) as pdf:
        return [(pdf[p - 1].rect.width, pdf[p - 1].rect.height) for p in pages]  # rect 已含旋转


def _is_blank(pdf_path: str, page_no: int) -> bool:
    """无文本层且 30 dpi 灰度渲染非白像素 < 0.5%。"""
    with _FITZ_LOCK, fitz.open(pdf_path) as pdf:
        pg = pdf[page_no - 1]
        if pg.get_text().strip():
            return False
        pix = pg.get_pixmap(dpi=BLANK_DPI, colorspace=fitz.csGRAY)
        s = pix.samples
        return sum(1 for b in s if b < 250) / max(1, len(s)) < BLANK_INK_FRAC


def _parse_result(
    text: str, pdf_path: str, pages: list[int], sizes: list[tuple[float, float]]
) -> list[str]:
    """闸口 b-e：JSONL -> 每个提交页一条 markdown 原文。任一不过抛 PaddleJobError。"""
    recs: list[dict] = []
    seen: set[Any] = set()
    for ln in text.split("\n"):  # JSONL 只按 LF 分行（U+2028 等可合法出现在字符串内）；去行尾 CR
        ln = ln[:-1] if ln.endswith("\r") else ln
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except ValueError as e:
            raise PaddleJobError(f"JSONL 行无法解析: {e}") from e
        if not isinstance(rec, dict):
            raise PaddleJobError("JSONL 行不是对象")
        if rec.get("errorCode") != 0:
            raise PaddleJobError(f"JSONL errorCode={rec.get('errorCode')} msg={rec.get('errorMsg')!r}")
        lid = rec.get("logId")
        if isinstance(lid, bool) or not isinstance(lid, (str, int)):
            raise PaddleJobError(f"JSONL logId 类型不符: {type(lid).__name__}")
        if lid in seen:
            raise PaddleJobError(f"JSONL logId 重复: {lid}")
        seen.add(lid)
        recs.append(rec)
    mds: list[Any] = []
    dims: list[tuple[Any, Any]] = []
    for rec in recs:
        res = rec.get("result")
        if not isinstance(res, dict):
            raise PaddleJobError("JSONL result 不是对象")
        lpr = res.get("layoutParsingResults")
        di = res.get("dataInfo")
        if not isinstance(di, dict):
            raise PaddleJobError("JSONL dataInfo 不是对象")
        dpages = di.get("pages")
        if not isinstance(lpr, list) or not isinstance(dpages, list):
            raise PaddleJobError("JSONL 缺 layoutParsingResults/dataInfo.pages")
        if not (len(lpr) == di.get("numPages") == len(dpages)):
            raise PaddleJobError(f"JSONL 行内页数不一致: {len(lpr)}/{di.get('numPages')}/{len(dpages)}")
        for it, dp in zip(lpr, dpages):
            md = it.get("markdown") if isinstance(it, dict) else None
            if not isinstance(md, dict):
                raise PaddleJobError("JSONL markdown 不是对象")
            if not isinstance(dp, dict):
                raise PaddleJobError("JSONL dataInfo.pages 元素不是对象")
            mds.append(md.get("text"))
            dims.append((dp.get("width"), dp.get("height")))
    if len(mds) != len(pages):
        raise PaddleJobError(f"返回 {len(mds)} 页 != 提交 {len(pages)} 页")
    for i, ((w, h), (rw, rh)) in enumerate(zip(dims, sizes)):
        if not _pos_finite(w) or not _pos_finite(h) \
                or abs(w - rw * 2) > SIZE_TOL_PX or abs(h - rh * 2) > SIZE_TOL_PX:
            raise PaddleJobError(f"页身份不符: 第 {i + 1} 个结果 {w}x{h} != 提交页 {pages[i]} 的 {rw * 2:.0f}x{rh * 2:.0f}")
    if not all(isinstance(m, str) for m in mds):
        raise PaddleJobError("某页 markdown.text 不是字符串")
    return [str(m) for m in mds]


def _judge_pages(
    pdf_path: str, pages: list[int], mds: list[str]
) -> tuple[dict[int, tuple[str, dict]], dict[int, str]]:
    """闸口 4：逐页文本判定。"""
    ok: dict[int, tuple[str, dict]] = {}
    failed: dict[int, str] = {}
    for p, raw in zip(pages, mds):
        txt = clean_md(raw)
        if txt.strip():
            ok[p] = (txt, {"empty_reason": None})
        elif "![" in raw or "<img" in raw:
            ok[p] = (txt, {"empty_reason": "image_only"})
        elif _is_blank(pdf_path, p):
            ok[p] = (txt, {"empty_reason": "blank"})
        else:
            failed[p] = "empty_suspect: 云端返回空文本但页面非空白（疑似漏识）"
    return ok, failed


def _attempt(
    session: Any, data: bytes, pdf_path: str, pages: list[int], sizes: list[tuple[float, float]],
    log: Callable[[str], None], stop: threading.Event | None = None,
) -> tuple[dict[int, tuple[str, dict]], dict[int, str], dict]:
    """提交一次 + 轮询 + 校验。成功返回 (ok, failed, {job_id, trace_id})；块级失败抛异常。
    已有 jobId 后的轮询/下载耗尽或超时 -> kind=job（不重传）；state=failed / 校验不过 -> transient（可重提）。"""
    if stop is not None and stop.is_set():  # 每次 POST 前检查共享停止事件
        raise PaddleStopped("已停止提交（其他块触发配额/配置错误）")
    headers = {"Authorization": f"bearer {_token()}"}
    model = os.environ.get("DOCSTORE_PADDLE_VL_MODEL", "PaddleOCR-VL-1.6")
    r = _net(lambda: session.post(
        URL, headers=headers, data={"model": model, "optionalPayload": json.dumps(OPT)},
        files={"file": ("chunk.pdf", data, "application/pdf")}, timeout=UPLOAD_TIMEOUT_S), "提交")
    sub = _check(r, "提交").get("data")
    if not isinstance(sub, dict):
        raise PaddleJobError(f"提交响应 data 不是对象: {str(sub)[:100]}")
    job_raw = sub.get("jobId")
    if isinstance(job_raw, bool) or not isinstance(job_raw, (str, int)):
        raise PaddleJobError(f"提交响应 jobId 类型异常: {str(job_raw)[:100]}")
    if job_raw in ("", 0):
        raise PaddleJobError("提交成功但无 jobId")
    job = str(job_raw)
    timeout = _env_int("DOCSTORE_PADDLE_JOB_TIMEOUT", TIMEOUT_S, 1)
    deadline = _now() + timeout  # 统一截止时间：轮询、退避、下载共用

    def left() -> float:
        return deadline - _now()

    def expired() -> PaddleJobError:
        return PaddleJobError(f"任务超时 job={job} > {timeout}s", "job")

    def poll() -> dict:
        if left() <= 0:
            raise expired()
        rr = _net(lambda: session.get(f"{URL}/{job}", headers=headers, timeout=max(1.0, min(POLL_TIMEOUT_S, left()))), "轮询")
        b = _check(rr, "轮询")
        d = b.get("data")
        if not isinstance(d, dict) or str(d.get("jobId")) != job or d.get("state") not in (
                "pending", "running", "done", "failed"):
            raise PaddleJobError(f"轮询响应异常 traceId={b.get('traceId')}: {str(d)[:200]}")
        d["_traceId"] = b.get("traceId")
        return d

    while True:
        d = _retry_same(poll, log, f"轮询 job={job}", deadline)
        if left() <= 0:  # 处理任何状态（含 failed/done）前先查统一截止时间；超时即块失败，不重提
            raise expired()
        if d["state"] == "failed":
            raise PaddleJobError(f"任务失败 job={job}: {d.get('errorMsg')}")
        if d["state"] == "done":
            break
        if left() < POLL_INTERVAL_S:
            raise expired()
        _sleep(POLL_INTERVAL_S)
    if "extractProgress" not in d:
        log(f"[paddle] 警告: job={job} done 但无 extractProgress，以 JSONL 为准")
    else:
        ep = d["extractProgress"]
        if not isinstance(ep, dict):
            raise PaddleJobError(f"extractProgress 不是对象 job={job}: {str(ep)[:100]}")
        tp, xp = _int_like(ep.get("totalPages")), _int_like(ep.get("extractedPages"))
        if tp is None or xp is None:
            raise PaddleJobError(f"extractProgress 值无法归一化为非负整数: {str(ep)[:100]}")
        if tp != len(pages) or xp != len(pages):
            raise PaddleJobError(f"extractProgress 不符: total={tp} extracted={xp} 提交 {len(pages)}")
    url = ((d.get("resultUrl") or {}).get("jsonUrl")) if isinstance(d.get("resultUrl"), dict) else None
    if not url:
        raise PaddleJobError(f"done 但无 jsonUrl job={job}")

    def download() -> str:
        if left() <= 0:
            raise expired()
        rr = _net(lambda: session.get(url, timeout=max(1.0, min(120.0, left()))), "下载结果")
        if rr.status_code != 200:
            kind = _classify(rr.status_code, _body(rr).get("code"))
            msg = f"下载结果 HTTP {rr.status_code}"
            if kind == "config":
                raise PaddleConfigError(msg)
            if kind == "quota":
                raise PaddleQuotaError(msg)
            raise PaddleJobError(msg)
        return rr.text

    text = _retry_same(download, log, f"下载 job={job}", deadline)
    if left() <= 0:
        raise expired()
    try:
        mds = _parse_result(text, pdf_path, pages, sizes)
        ok, failed = _judge_pages(pdf_path, pages, mds)
    except PaddleJobError as e:
        if e.kind == "transient":
            raise PaddleJobError(f"job={job} {e}") from e  # 校验不过：允许重新提交
        raise
    return ok, failed, {"job_id": job, "trace_id": d.get("_traceId")}


def run_chunk(
    pdf_path: str, pages: list[int], *, session: Any = None, log: Callable[[str], None] = print,
    chunk_no: int = 1, data: bytes | None = None, stop: threading.Event | None = None,
    out: tuple[dict[int, tuple[str, dict]], dict[int, str]] | None = None,
) -> tuple[dict[int, tuple[str, dict]], dict[int, str]]:
    """识别一个块。返回 (ok {页: (文本, 元数据)}, failed {页: 原因})；配置错/配额抛 PaddleConfigError/PaddleQuotaError，
    stop 置位抛 PaddleStopped。传入 out=(ok, failed) 时，异常上抛前已通过的子块结果仍留在其中。
    暂时性错误退避重试，仍败且多页则对半拆（一轮）；缩块码（10003/10006/413）一直对半拆。"""
    session = session or _new_session()
    ok, failed = out if out is not None else ({}, {})
    pages = list(pages)

    def solve(ps: list[int], blob: bytes | None, split_done: bool) -> None:
        blob = blob if blob is not None else _build_pdf(pdf_path, ps)
        sizes = _page_sizes(pdf_path, ps)
        last: PaddleJobError | None = None
        for i in range(len(BACKOFF_S) + 1):
            t0 = _now()
            try:
                o, f, info = _attempt(session, blob, pdf_path, ps, sizes, log, stop)
            except PaddleJobError as e:
                last = e
                log(f"[paddle] 块{chunk_no} 页{_label(ps)} 失败({e.kind}): {e}")
                if e.kind != "transient" or i == len(BACKOFF_S):
                    break
                _sleep(BACKOFF_S[i])
                continue
            for p, (txt, meta) in o.items():
                meta.update(info, chunk=chunk_no, seconds=round((_now() - t0) / max(1, len(ps)), 2))
            ok.update(o)
            failed.update(f)
            log(f"[paddle] 块{chunk_no} 页{_label(ps)} 通过 {len(o)}/{len(ps)} "
                f"{_now() - t0:.1f}s job={info['job_id']}")
            return
        assert last is not None
        if len(ps) > 1 and (last.kind == "shrink" or (last.kind == "transient" and not split_done)):
            mid = len(ps) // 2
            nxt = split_done or last.kind == "transient"
            solve(ps[:mid], None, nxt)
            solve(ps[mid:], None, nxt)
            return
        for p in ps:
            failed[p] = f"{last.kind}: {last}"

    solve(pages, data, False)
    return ok, failed


# ---------------------------------------------------------------- 多块并发

def run_pages(pdf_path: str, pages: list[int], *, log: Callable[[str], None] = print) -> dict:
    """父进程里批量识别：分块、线程并发（DOCSTORE_PADDLE_CONCURRENCY，默认 4 块）。
    返回 {"ok": {页: (文本, 元数据)}, "failed": {页: 原因}, "quota_hit": bool}。配置错直接上抛。
    共享停止事件：配额/配置错一出现，所有线程在每次 POST 前停止，未开始的块取消；已通过的子块结果保留。"""
    ok: dict[int, tuple[str, dict]] = {}
    failed: dict[int, str] = {}
    pages = sorted(set(pages))
    try:
        _token()
    except RuntimeError as e:
        return {"ok": ok, "failed": {p: f"no_token: {e}" for p in pages}, "quota_hit": False}
    conc = _env_int("DOCSTORE_PADDLE_CONCURRENCY", 4, 1)
    chunks, oversize = plan_chunks(pdf_path, pages)
    failed.update(oversize)
    stop = threading.Event()
    quota = threading.Event()
    lock = threading.Lock()
    config_errs: list[PaddleConfigError] = []
    futs: list[Any] = []
    log(f"[paddle] {len(pages)} 页 -> {len(chunks)} 块，并发 {conc}")

    def work(i: int, ps: list[int], data: bytes) -> None:
        cok: dict[int, tuple[str, dict]] = {}
        cfail: dict[int, str] = {}
        why = "cancelled: 其他块触发配额/配置错误，未提交"
        try:
            if stop.is_set():
                raise PaddleStopped(why)
            run_chunk(pdf_path, ps, session=_new_session(), log=log, chunk_no=i, data=data, stop=stop, out=(cok, cfail))
        except PaddleQuotaError as e:
            quota.set()
            stop.set()
            why = f"quota: {e}"
            log(f"[paddle] 配额用尽，停止云提交，剩余页走 fallback: {e}")
        except PaddleConfigError as e:
            with lock:
                config_errs.append(e)
            stop.set()
            why = f"config: {e}"
            for fu in futs:
                fu.cancel()
        except PaddleStopped:
            pass
        with lock:
            ok.update(cok)
            failed.update(cfail)
            failed.update({p: why for p in ps if p not in cok and p not in cfail})

    with ThreadPoolExecutor(max_workers=min(conc, max(1, len(chunks)))) as ex:
        futs.extend(ex.submit(work, i, ps, d) for i, (ps, d) in enumerate(chunks, 1))
        for fu in futs:
            if not fu.cancelled():
                fu.result()
    if config_errs:
        raise config_errs[0]
    return {"ok": ok, "failed": failed, "quota_hit": quota.is_set()}


# ---------------------------------------------------------------- 单页（降级链用）

def paddle_vl_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    """一页 -> 云端识别 -> 纯文本；复用 run_chunk（1 页块），过同样闸口。dpi 不用。失败抛 PaddleJobError。"""
    ok, failed = run_chunk(pdf_path, [page_no], log=lambda s: None)
    if page_no in ok:
        return ok[page_no][0], None
    raise PaddleJobError(failed.get(page_no, "未知失败"))
