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
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import fitz
import requests

URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
OPT = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}
# 试验用：环境变量 DOCSTORE_PADDLE_OPT（JSON）覆盖/追加 optionalPayload 键；未设置时与正式请求完全一致
OPT.update(json.loads(os.environ.get("DOCSTORE_PADDLE_OPT") or "{}"))
TIMEOUT_S = 1800  # 块总等待上限；env DOCSTORE_PADDLE_JOB_TIMEOUT 覆盖
UPLOAD_TIMEOUT_S = 300
POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 3.0
BACKOFF_S = (10, 30, 90)  # 暂时性错误退避
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_BYTES = 45 * 1024 * 1024
SIZE_TOL_PX = 2  # 页身份校验：返回宽高 vs 提交页 rect x2 的容差
BLANK_DPI = 40
BLANK_INK_FRAC = 0.005
BLANK_TINT_DELTA = 35
BLANK_MARGIN = 0.08  # 扫描边缘阴影/书脊不算墨迹
BLANK_JUNK_CHARS = 8  # 扫描件常带 'I' '/' '.' 之类 1-2 字符的垃圾文本层，不算有文本
EMPTY_OK_REASONS = ("blank", "image_only", "no_text_local")
LOCAL_OCR_MIN_CHARS = 15  # 本地 tesseract 识别出 >= 这么多字符才认定云端漏识
EMPTY_STREAK_STOP = 10  # 连续 10 页空返回 -> 启动预案（停提交 + 诊断）
PROBE_PAGES = 10  # 每个文件先试提这么多页，连续全空就不再提交其余页
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
    """文本层（去空白后 <= BLANK_JUNK_CHARS 字符）且灰度渲染去边缘后偏离纸色的像素 < 0.5%。
    2026-11-25 根因：旧版“有任何文本层即非空白”，扫描件空白页带垃圾文本层 + 边缘阴影，被误判为疑似漏识。"""
    with _FITZ_LOCK, fitz.open(pdf_path) as pdf:
        pg = pdf[page_no - 1]
        if len("".join(pg.get_text().split())) > BLANK_JUNK_CHARS:
            return False
        pix = pg.get_pixmap(dpi=BLANK_DPI, colorspace=fitz.csGRAY)
        s = pix.samples
        if not s:
            return True
        w, h = pix.width, pix.height
        x0, x1, y0, y1 = int(w * BLANK_MARGIN), int(w * (1 - BLANK_MARGIN)), int(h * BLANK_MARGIN), int(h * (1 - BLANK_MARGIN))
        if x1 > x0 and y1 > y0:
            s = b"".join(s[y * w + x0:y * w + x1] for y in range(y0, y1))
        # 泛黄/灰底纸：以页面中位灰度为底色，偏离底色 >40 才算墨迹（2026-11-24：旧版用绝对 <250，
        # 泛黄空白页被误判非空白，造成 1901 条 empty_suspect 假阳性）
        base = sorted(s[:: max(1, len(s) // 4000)])
        med = base[len(base) // 2]
        return sum(1 for b in s if abs(b - med) > BLANK_TINT_DELTA) / len(s) < BLANK_INK_FRAC


def local_ocr_chars(pdf_path: str, page_no: int) -> int | None:
    """第二道防线：本机 tesseract 识别该页，返回字母数字字符数；tesseract 不可用返回 None。
    DOCSTORE_PADDLE_LOCAL_CHECK=0 关闭。"""
    if not _env_int("DOCSTORE_PADDLE_LOCAL_CHECK", 1, 0, 1) or not shutil.which("tesseract"):
        return None
    with _FITZ_LOCK, fitz.open(pdf_path) as pdf:
        png = pdf[page_no - 1].get_pixmap(dpi=150, colorspace=fitz.csGRAY).tobytes("png")
    try:
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "3"], input=png,
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return sum(1 for c in r.stdout.decode("utf8", "ignore") if c.isalnum())


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


def _layouts(text: str, pages: list[int], sizes: list[tuple[float, float]]) -> list[dict]:
    """逐页取版面：prunedResult（块框/行框等云端原始结构）+ 云端页像素尺寸 + 提交页 pt 尺寸。
    _parse_result 已验证结构，这里只搬运；缺 prunedResult 记 None（restore 时据此报缺，不伪造）。"""
    out: list[dict] = []
    for ln in text.split("\n"):
        ln = ln[:-1] if ln.endswith("\r") else ln
        if not ln.strip():
            continue
        res = json.loads(ln)["result"]
        for it, dp in zip(res["layoutParsingResults"], res["dataInfo"]["pages"]):
            d = it if isinstance(it, dict) else {}
            out.append({"width_px": dp.get("width"), "height_px": dp.get("height"),
                        "pruned_result": d.get("prunedResult") if d else None,
                        "markdown": d.get("markdown"), "outputImages": d.get("outputImages"),
                        "inputImage": d.get("inputImage")})
    for lay, p, (w, h) in zip(out, pages, sizes):
        lay.update(page=p, pdf_w_pt=w, pdf_h_pt=h)
    return out


def save_images(d: Path, lay: dict, session: Any = None) -> dict:
    """把 lay["markdown"]["images"]（相对路径 -> URL）逐个下载到 d/img/<相对路径>。
    拒绝绝对路径和 ..；下载失败只记录不抛。返回 {相对路径: 本地相对路径(相对 d) 或 "ERR: ..."}。
    outputImages 是可视化图，不下载（URL 留在 JSONL 与 pNNNN.json 里）。"""
    md = lay.get("markdown")
    imgs = md.get("images") if isinstance(md, dict) else None
    res: dict[str, str] = {}
    if not isinstance(imgs, dict) or not imgs:
        return res
    sess = session if session is not None else _new_session()
    base = (Path(d) / "img").resolve()
    for rel, url in imgs.items():
        rel_s = str(rel)
        parts = rel_s.replace("\\", "/").split("/")
        if (not rel_s or rel_s.startswith(("/", "\\")) or ".." in parts or re.match(r"^[A-Za-z]:", rel_s)
                or "\x00" in rel_s):
            res[rel_s] = "ERR: 不安全的路径"
            continue
        dest = (base / rel_s).resolve()
        if base != dest and base not in dest.parents:
            res[rel_s] = "ERR: 不安全的路径"
            continue
        try:
            r = sess.get(url, timeout=120)
            if r.status_code != 200:
                res[rel_s] = f"ERR: HTTP {r.status_code}"
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            res[rel_s] = f"img/{rel_s}"
        except Exception as e:
            res[rel_s] = f"ERR: {type(e).__name__}: {e}"[:200]
    return res


def save_layout(root: Any, key: str, page: int, meta: dict, *, download_images: bool = False,
                session: Any = None) -> None:
    """把云端版面落盘：<root>/layout/<key>/pNNNN.json + 整个任务的原始 JSONL <root>/layout/<key>/jobs/<job_id>.jsonl。
    OCR 一次就要把版面存下来，后续还原排版/对照原页不再重跑 OCR（2026-11-24 Vol21 教训）。"""
    lay, raw = meta.get("_layout"), meta.get("_raw_jsonl")
    if lay is None or raw is None:
        return
    d = Path(root) / "layout" / key
    (d / "jobs").mkdir(parents=True, exist_ok=True)
    job = str(meta.get("job_id") or "nojob")
    jf = d / "jobs" / f"{job}.jsonl"
    if not jf.exists():
        jf.write_text(raw, encoding="utf-8")
    rec = {**lay, "key": key, "job_id": job, "trace_id": meta.get("trace_id"), "model": meta.get("model"),
           "raw_jsonl": f"jobs/{job}.jsonl"}
    if download_images:
        # 各页图片同名（imgs/img_in_...）会互相覆盖，所以按页分子目录；images_local 的值相对 <root>/layout/<key>
        sub = f"p{int(page):04d}"
        loc = save_images(d / sub, lay, session)
        rec["images_local"] = {k: (f"{sub}/{v}" if not v.startswith("ERR") else v) for k, v in loc.items()}
    (d / f"p{int(page):04d}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


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
            n = local_ocr_chars(pdf_path, p)
            if n is not None and n < LOCAL_OCR_MIN_CHARS:
                ok[p] = (txt, {"empty_reason": "no_text_local"})  # 云端空 + 本地 OCR 也无字：封面/护页/无字图版
            else:
                failed[p] = "empty_suspect: 云端返回空文本但页面非空白（疑似漏识）" + (
                    f"；本地 OCR 识别出 {n} 字符" if n is not None else "；本地 OCR 不可用")
    return ok, failed


def _attempt(
    session: Any, data: bytes, pdf_path: str, pages: list[int], sizes: list[tuple[float, float]],
    log: Callable[[str], None], stop: threading.Event | None = None, opt: dict | None = None,
) -> tuple[dict[int, tuple[str, dict]], dict[int, str], dict]:
    """提交一次 + 轮询 + 校验。成功返回 (ok, failed, {job_id, trace_id})；块级失败抛异常。
    已有 jobId 后的轮询/下载耗尽或超时 -> kind=job（不重传）；state=failed / 校验不过 -> transient（可重提）。"""
    if stop is not None and stop.is_set():  # 每次 POST 前检查共享停止事件
        raise PaddleStopped("已停止提交（其他块触发配额/配置错误）")
    headers = {"Authorization": f"bearer {_token()}"}
    model = os.environ.get("DOCSTORE_PADDLE_VL_MODEL", "PaddleOCR-VL-1.6")
    r = _net(lambda: session.post(
        URL, headers=headers, data={"model": model, "optionalPayload": json.dumps(OPT if opt is None else opt)},
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
        for lay in _layouts(text, pages, sizes):
            if lay["page"] in ok:
                ok[lay["page"]][1].update(_layout=lay, _raw_jsonl=text)
    except PaddleJobError as e:
        if e.kind == "transient":
            raise PaddleJobError(f"job={job} {e}") from e  # 校验不过：允许重新提交
        raise
    return ok, failed, {"job_id": job, "trace_id": d.get("_traceId"), "model": model}


def run_chunk(
    pdf_path: str, pages: list[int], *, session: Any = None, log: Callable[[str], None] = print,
    chunk_no: int = 1, data: bytes | None = None, stop: threading.Event | None = None,
    out: tuple[dict[int, tuple[str, dict]], dict[int, str]] | None = None, opt: dict | None = None,
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
                o, f, info = _attempt(session, blob, pdf_path, ps, sizes, log, stop, opt=opt)
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

EMPTY_STORM_MIN = EMPTY_STREAK_STOP


def empty_storm(reasons: Any) -> bool:
    """True when a chunk's failures look like a systematic empty-response problem
    (>= EMPTY_STORM_MIN pages and at least half of them 'empty_suspect').  Such a run
    must stop and be checked against the official call rules, not retried blindly."""
    rs = list(reasons)
    n = sum(1 for r in rs if str(r).startswith("empty_suspect"))
    return n >= EMPTY_STORM_MIN and 2 * n >= len(rs)


def empty_streak(pages: Any, failed: dict) -> int:
    """按页序，已提交页中连续 empty_suspect 的最长长度（被其他结果打断则清零）。"""
    best = cur = 0
    for p in sorted(pages):
        if str(failed.get(p, "")).startswith("empty_suspect"):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def run_pages(pdf_path: str, pages: list[int], *, log: Callable[[str], None] = print,
              opt: dict | None = None) -> dict:
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
    if _env_int("DOCSTORE_PADDLE_PRESKIP_BLANK", 1, 0, 1):
        # 本地判定为空白的页不提交（云端照样计额度）；记为 blank，标记 local-blank
        keep = []
        for p in pages:
            if _is_blank(pdf_path, p):
                ok[p] = ("", {"empty_reason": "blank", "job_id": "local-blank"})
            else:
                keep.append(p)
        if len(keep) < len(pages):
            log(f"[paddle] 本地判空白 {len(pages) - len(keep)} 页，不提交")
        pages = keep
    probe_n = PROBE_PAGES if len(pages) > PROBE_PAGES else 0
    chunks, oversize = plan_chunks(pdf_path, pages[:probe_n]) if probe_n else ([], {})
    n_probe = len(chunks)
    rest, over2 = plan_chunks(pdf_path, pages[probe_n:])
    chunks += rest
    failed.update(oversize)
    failed.update(over2)
    stop = threading.Event()
    quota = threading.Event()
    empty = threading.Event()
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
                if empty.is_set():
                    why = "empty_storm: 前面连续空返回，未提交（预案：先核官方要求）"
                raise PaddleStopped(why)
            run_chunk(pdf_path, ps, session=_new_session(), log=log, chunk_no=i, data=data, stop=stop, out=(cok, cfail), opt=opt)
            if empty_storm(cfail.values()) or empty_streak(ps, cfail) >= EMPTY_STREAK_STOP:
                empty.set()
                stop.set()
                why = "empty_storm: 连续空返回，已停止云提交"
                log(f"[paddle] 块 {i} 空返回过多（{len(cfail)} 页），停止提交。请先查官方调用规则，不要反复重跑 OCR。")
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
        # 先试提 PROBE_PAGES 页；连续全空就触发预案，其余页一页都不提交
        futs.extend(ex.submit(work, i, ps, d) for i, (ps, d) in enumerate(chunks[:n_probe], 1))
        for fu in list(futs):
            if not fu.cancelled():
                fu.result()
        futs.extend(ex.submit(work, i, ps, d) for i, (ps, d) in enumerate(chunks[n_probe:], n_probe + 1))
        for fu in futs:
            if not fu.cancelled():
                fu.result()
    if config_errs:
        raise config_errs[0]
    return {"ok": ok, "failed": failed, "quota_hit": quota.is_set(), "empty_storm": empty.is_set()}


# ---------------------------------------------------------------- 单页（降级链用）

def paddle_vl_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    """一页 -> 云端识别 -> 纯文本；复用 run_chunk（1 页块），过同样闸口。dpi 不用。失败抛 PaddleJobError。"""
    ok, failed = run_chunk(pdf_path, [page_no], log=lambda s: None)
    if page_no in ok:
        return ok[page_no][0], None
    raise PaddleJobError(failed.get(page_no, "未知失败"))
