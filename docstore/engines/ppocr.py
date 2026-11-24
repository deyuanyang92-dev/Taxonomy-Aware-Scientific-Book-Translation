"""PP-OCRv5 引擎（日文、繁体、生僻字）：经常驻子进程调用独立 venv 里的 paddleocr。

环境变量：
- DOCSTORE_PPOCR_PYTHON：装有 paddleocr 的解释器（缺省优先 /root/ocr_eval/venv_gpu，其次 /root/ocr_eval/venv）
- 推荐 --dpi 200：Imajima 日文志书 2 页金标准上，实字错误率 200 dpi 0.08%/1.1%，300 dpi 0.59%/1.4%
  （300 dpi 常丢行末「な」）；GPU 时 --workers 1（每个子进程约占 3.6 GB 显存）
- DOCSTORE_PPOCR_MODEL：PP-OCRv5_server（缺省，准）或 PP-OCRv5_mobile（快）
- DOCSTORE_PPOCR_LANG：auto（缺省；含假名的行 ≥2 成的页按 cp932 字集滤乱码行）/ ja / zh
- DOCSTORE_PPOCR_ADAPTIVE：1（缺省）整页旋转判断 + 低置信页自适应二值化 + 倾角 >0.8° 纠斜；0 关闭
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..layout import order_rows
from .pageimg import page_pixmap

_PROC: subprocess.Popen | None = None
WORKER = Path(__file__).with_name("ppocr_worker.py")


def _proc() -> subprocess.Popen:
    global _PROC
    if _PROC is None or _PROC.poll() is not None:
        gpu = "/root/ocr_eval/venv_gpu/bin/python"  # paddlepaddle-gpu 3.3.1（cu126）：GTX 1660S 上 200 dpi 约 2 s/页，CPU 约 16 s/页
        py = os.environ.get("DOCSTORE_PPOCR_PYTHON") or (gpu if os.path.exists(gpu) else "/root/ocr_eval/venv/bin/python")
        model = os.environ.get("DOCSTORE_PPOCR_MODEL", "PP-OCRv5_server")
        # 不把 docstore 多进程池设的线程上限传给 paddle：OMP_THREAD_LIMIT=8 时 PP-OCRv5 检测漏行
        # （Imajima2007 p.22：45 行→32 行；--workers 2 的 CPU 运行 171 页漏 26% 行框，2026-11-15 复现）
        drop = {"OMP_THREAD_LIMIT", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"}
        env = {k: v for k, v in os.environ.items() if k not in drop}
        env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        _PROC = subprocess.Popen([py, "-u", str(WORKER), model], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        assert _PROC.stdout is not None
        for ln in _PROC.stdout:  # 跳过加载日志，等到 READY
            if ln.strip() == "READY":
                break
        else:
            raise RuntimeError("PP-OCRv5 子进程启动失败")
        atexit.register(_PROC.kill)
    return _PROC


_JA_PAGE = False  # 当前页是否日文（由 _bands 按假名比例设定）
_KANA = re.compile(r"[\u3040-\u30ff]")


def _is_ja_page(rows: list[Any]) -> bool:
    """DOCSTORE_PPOCR_LANG=ja/zh 强制；缺省 auto：含假名的行 ≥ 2 成视为日文页。"""
    lang = os.environ.get("DOCSTORE_PPOCR_LANG", "auto")
    if lang in ("ja", "zh"):
        return lang == "ja"
    texts = [str(r[1]) for r in rows if len(str(r[1])) >= 4]
    return bool(texts) and sum(1 for t in texts if _KANA.search(t)) >= 0.2 * len(texts)


def _cjk_ok(c: str) -> bool:
    try:
        c.encode("cp932")
        return True
    except UnicodeEncodeError:
        return False


def junk_line(t: str) -> bool:
    """插图排线、页边印章被识成的乱码行：emoji、韩文、生僻字多（Imajima2009 每页约 2 行）。
    只对含汉字/假名的行判断：cp932（日文常用字集）外的字符超过 2 成即视为乱码。简体中文书勿用此过滤。"""
    if not _JA_PAGE or not any(ord(c) > 0x2FFF for c in t):
        return False
    return sum(_cjk_ok(c) for c in t) < 0.8 * len(t)


def _box(r: Any) -> tuple[float, float, float, float]:
    xs = [p[0] for p in r[0]]
    ys = [p[1] for p in r[0]]
    return min(xs), min(ys), max(xs), max(ys)


def _keep(r: Any) -> bool:
    """丢弃：插图里的零散字母（≤2 字、非数字非汉字）、符号串、乱码行、低置信行（<0.5）。"""
    t = str(r[1]).strip()
    if re.fullmatch(r"[.．…・\s]*\d{1,3}", t):  # 检索表的「点线+跳转号」（Imajima2009 p.66 的 ...17 曾被误删）
        return True
    good = sum(c.isalnum() for c in t)  # 汉字、假名也算 isalnum
    return (good >= 0.5 * len(t) and (len(t) > 2 or t.isdigit() or any(ord(c) > 0x2FFF for c in t))
            and not junk_line(t) and float(r[2]) >= 0.5)


def _cluster(vals: list[float], tol: float) -> int:
    """vals 中落在同一 ±tol 窗口里的最多个数（栏边对齐程度）。"""
    vals = sorted(vals)
    best = 0
    for v in vals:
        best = max(best, sum(1 for u in vals if abs(u - v) <= tol))
    return best


def is_two_column(rows: list[Any], width: float) -> bool:
    """双栏：左栏行尾、右栏行首各有 ≥5 行对齐在中线附近（±1%）。
    检索表（单栏+点线，右端「属名……跳转号」）的右段起点参差，不会被误判为双栏（Imajima2009 p.66 实测）。"""
    mid = width / 2
    l1 = [_box(r)[2] for r in rows if _box(r)[2] <= mid + 0.02 * width and _box(r)[2] > mid - 0.12 * width]
    r0 = [_box(r)[0] for r in rows if _box(r)[0] >= mid - 0.02 * width and _box(r)[0] < mid + 0.08 * width]
    return _cluster(l1, 0.01 * width) >= 5 and _cluster(r0, 0.01 * width) >= 5


def _lines(rows: list[Any]) -> list[tuple[str, float]]:
    """把同一视觉行（纵向中心落在前一框高度内）的片段按 x 合并成一行。"""
    out: list[list[Any]] = []
    for r in sorted(rows, key=lambda r: (_box(r)[1] + _box(r)[3]) / 2):
        x0, y0, x1, y1 = _box(r)
        yc = (y0 + y1) / 2
        if out:
            _, py0, _, py1 = _box(out[-1][0])
            if py0 <= yc <= py1:
                out[-1].append(r)
                continue
        out.append([r])
    res = []
    for grp in out:
        grp.sort(key=lambda r: _box(r)[0])
        res.append((" ".join(str(r[1]).strip() for r in grp), sum(float(r[2]) for r in grp) / len(grp)))
    return res


def _bands(rows: list[Any], width: float) -> list[tuple[str, float]]:
    """双栏页：跨中线的通栏行把页面切成若干带，带内先左栏后右栏；单栏页：同一视觉行合并后按 y 排。"""
    global _JA_PAGE
    _JA_PAGE = _is_ja_page(rows)
    rows = [r for r in rows if _keep(r)]
    if not is_two_column(rows, width):
        return _lines(rows)
    mid = width / 2
    full, left, right = [], [], []
    for r in rows:
        x0, _, x1, _ = _box(r)
        if x0 < mid - 0.02 * width and x1 > mid + 0.02 * width:
            full.append(r)
        elif x1 <= mid + 0.02 * width:
            left.append(r)
        else:
            right.append(r)
    out: list[tuple[str, float]] = []
    full_sorted = sorted(full, key=lambda r: _box(r)[1])
    cuts = [_box(r)[1] for r in full_sorted] + [float("inf")]
    prev = float("-inf")
    for i, y in enumerate(cuts):
        for col in (left, right):
            out += _lines([r for r in col if prev <= _box(r)[1] < y])
        if i < len(full_sorted):
            out += _lines([full_sorted[i]])
        prev = y
    return out


def rows_to_text(rows: list[Any], width: float | None = None) -> tuple[str, float | None]:
    rows = [r for r in rows if str(r[1]).strip()]
    if not width:
        rows = order_rows(rows)
        lines = [(str(r[1]), float(r[2])) for r in rows]
    else:
        lines = _bands(rows, width)
    text = "\n".join(t for t, _ in lines)
    conf = (sum(c for _, c in lines) / len(lines)) if lines else None
    return text, conf


def _cache_file(pdf_path: str, page_no: int, dpi: int) -> Path:
    """原始行框缓存：<DOCSTORE_PPOCR_CACHE>/<pdf 指纹>/<模型>_<dpi>[_u<unclip>]/pNNNN.json。
    改版面规则只需重排缓存，不必重新 OCR。"""
    st = os.stat(pdf_path)
    fp = hashlib.sha1(f"{os.path.basename(pdf_path)}|{st.st_size}".encode()).hexdigest()[:12]
    model = os.environ.get("DOCSTORE_PPOCR_MODEL", "PP-OCRv5_server")
    unclip = os.environ.get("DOCSTORE_PPOCR_UNCLIP")
    root = Path(os.environ.get("DOCSTORE_PPOCR_CACHE", str(Path.home() / ".cache" / "docstore_ppocr")))
    ver = "_v2" if os.environ.get("DOCSTORE_PPOCR_ADAPTIVE", "1") != "0" else ""  # v2：旋转判断+自适应二值化+纠斜
    extra = os.environ.get("DOCSTORE_PPOCR_PARAMS")  # 调参扫描：参数不同缓存不同
    ptag = "_p" + hashlib.sha1(extra.encode()).hexdigest()[:8] if extra else ""
    return root / fp / f"{model}_{dpi}{'_u' + unclip if unclip else ''}{ptag}{ver}" / f"p{page_no:04d}.json"


def ppocr_rows(pdf_path: str, page_no: int, dpi: int) -> tuple[list[Any], float]:
    """(行框列表, 页宽像素)；有缓存直接读。"""
    cf = _cache_file(pdf_path, page_no, dpi)
    if cf.exists():
        d = json.loads(cf.read_text(encoding="utf-8"))
        return d["rows"], d["width"]
    p = _proc()
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "p.png"
        pix = page_pixmap(pdf_path, page_no, dpi)
        pix.save(str(img))
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write(str(img) + "\n")
        p.stdin.flush()
        out = json.loads(p.stdout.readline() or "null")
    width: float = pix.width
    meta: dict = {}
    if isinstance(out, dict) and "rows" in out:  # 新 worker：{"rows", "width", 可选 rotated/binarized/deskew}
        meta = {k: v for k, v in out.items() if k != "rows"}
        width, out = out.get("width", width), out["rows"]
    if not isinstance(out, list):
        raise RuntimeError(f"PP-OCRv5 识别失败 p{page_no}: {out}")
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps({**meta, "width": width, "rows": out}, ensure_ascii=False), encoding="utf-8")
    return out, width


def save_rows_layout(root: str | Path, key: str, pdf_path: str, pages: list[int], dpi: int) -> int:
    """把本地 PP-OCR 行框（缓存里的 rows）复制进资料库 <root>/layout/<key>/ppocr/pNNNN.json，
    与云版面同处，不依赖 ~/.cache（2026-11-24：版面必须随库保存，避免重复 OCR）。返回写入页数。"""
    d = Path(root) / "layout" / key / "ppocr"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in pages:
        cf = _cache_file(pdf_path, p, dpi)
        if cf.exists():
            (d / f"p{int(p):04d}.json").write_text(cf.read_text(encoding="utf-8"), encoding="utf-8")
            n += 1
    return n


def ppocr_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    rows, width = ppocr_rows(pdf_path, page_no, dpi)
    return rows_to_text(rows, width)
