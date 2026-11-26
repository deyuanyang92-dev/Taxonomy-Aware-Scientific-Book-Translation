"""PaddleOCR 云 OCR 批处理（由项目脚本 _PaddleOCR/paddle_batch.py 迁入，2026-11-25）。

调用 docstore.engines.paddle_vl.run_pages：每块 <=100 页、<=45 MB，块内逐页校验，云端随机 500 自动重提，白页标 blank。
每个入库页同时把云端版面（prunedResult/markdown/图片/原始 JSONL）存到 out/layout/<rel>/，后续还原排版不再重跑 OCR。

用法（在工作目录下；--root 默认当前目录，--src 默认 root 的上一级）：
  python -m docstore.ocr_batch manifest            # 扫描全部 PDF，写 manifest.tsv
  python -m docstore.ocr_batch run [--limit N] [--workers 6]   # 断点续跑
  python -m docstore.ocr_batch report              # 汇总进度，写 失败清单.txt
  python -m docstore.ocr_batch preflight 文件 [页]  # 空返回页对照官方要求核对（本地，不耗额度）
  python -m docstore.ocr_batch unblock 文件 页...   # 核对后放行，再多 1 次提交
  python -m docstore.ocr_batch backfill-layout [--limit N] [--dry-run]  # 旧 job 补取版面（只 GET，不提交）
也可用 docstore ocr-batch <子命令>。

产物（root 下，格式与旧脚本完全一致，可直接续用）：
  out/<原相对路径>.json   每页文本 + 元数据 + layout 路径
  out/<原相对路径>.md     按页拼接文本，页间有 <!-- page N --> 标记
  out/layout/<rel>/pNNNN.json、jobs/<job_id>.jsonl、pNNNN/img/...   每页云端版面
  done.tsv failed.tsv quota.json pages_ledger.tsv 失败清单.txt 空返回_已停跑.txt unblock.tsv backfill_layout.tsv
  logs/run_*.log
"""
from __future__ import annotations

import argparse
import csv
import time as _time
import datetime as dt
import faulthandler
import json
import os
import re
import signal
import sys
import threading
import time
import types
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import fitz

from .engines import paddle_vl

DAILY_CAP = int(os.environ.get("PADDLE_DAILY_CAP", "29000"))  # 用户账号每日 30000 页，留余量
STOP_HOUR = int(os.environ.get("PADDLE_STOP_HOUR", "24"))     # 24 = 不设停跑窗口
MODEL = os.environ.get("DOCSTORE_PADDLE_VL_MODEL", "PaddleOCR-VL-1.6")
MAX_TRIES = 3          # 同一页最多尝试次数，超过则永久列入失败清单
# 官方限制（docs/ocr_eval/paddle_aistudio_api_official.md §2）
OFFICIAL_MAX_UPLOAD = 50 * 1024 * 1024
OFFICIAL_MAX_PAGES = 1000
OFFICIAL_MAX_IMAGE = 10 * 1024 * 1024
QC_MIN_LAYER = 200     # 文本层字符数 >= 此值才做「OCR 字数 vs 文本层」比对
QC_MIN_RATIO = 0.25    # OCR 字符数 < 文本层 × 此比例 -> 判疑似漏识
FAILED_HDR = ["time", "file", "page", "reason"]
_lock = threading.RLock()  # 必须可重入：process() 持锁时会调 log()（再取同一把锁），Lock 会死锁
_log_fh: Any = None


@dataclass
class Paths:
    root: Path
    src: Path

    @classmethod
    def make(cls, root: str | Path | None = None, src: str | Path | None = None) -> "Paths":
        r = Path(root or ".").resolve()
        return cls(r, Path(src).resolve() if src else r.parent)

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.tsv"

    @property
    def done(self) -> Path:
        return self.root / "done.tsv"

    @property
    def failed(self) -> Path:
        return self.root / "failed.tsv"

    @property
    def quota(self) -> Path:
        return self.root / "quota.json"

    @property
    def report(self) -> Path:
        return self.root / "失败清单.txt"

    @property
    def halt(self) -> Path:  # 存在即不再提交；先按里面的核对结果处理，再删除本文件
        return self.root / "空返回_已停跑.txt"

    @property
    def unblock(self) -> Path:  # 用户核对后放行的 文件/页（每次放行只多给 1 次提交）
        return self.root / "unblock.tsv"

    @property
    def ledger(self) -> Path:
        return self.root / "pages_ledger.tsv"

    @property
    def backfill(self) -> Path:
        return self.root / "backfill_layout.tsv"


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with _lock:
        print(line, flush=True)
        if _log_fh:
            _log_fh.write(line + "\n")
            _log_fh.flush()


def append_tsv(path: Path, row: list, header: list) -> None:
    with _lock:
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            if new:
                w.writerow(header)
            w.writerow(row)


def read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _atomic_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


# ---------------------------------------------------------------- manifest

def cmd_manifest(p: Paths, a: Any) -> None:
    pdfs = sorted(f for f in p.src.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"
                  and p.root not in f.parents)
    rows = []
    for i, f in enumerate(pdfs, 1):
        rel = str(f.relative_to(p.src))
        try:
            with fitz.open(f) as d:
                if d.needs_pass:
                    raise RuntimeError("加密 PDF")
                n = d.page_count
                chars = sum(len("".join(d[k].get_text().split())) for k in range(min(n, 5)))
            rows.append([rel, n, f.stat().st_size, 1 if chars >= 30 * min(n, 5) else 0, ""])
        except Exception as e:  # 打不开的也列出，run 时记失败
            rows.append([rel, 0, f.stat().st_size, 0, f"打不开: {e}"[:200]])
        if i % 200 == 0:
            print(f"manifest {i}/{len(pdfs)}", flush=True)
    with open(p.manifest, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["file", "pages", "bytes", "text_layer", "error"])
        w.writerows(rows)
    tot = sum(r[1] for r in rows)
    print(f"PDF {len(rows)} 份，共 {tot} 页；有文本层 {sum(r[3] for r in rows)} 份；打不开 {sum(1 for r in rows if r[4])} 份")


# ---------------------------------------------------------------- QC（防云端返回空白/残缺）

def _nchars(s: str) -> int:
    return len("".join(s.split()))


def qc_pages(src: Path, ok: dict) -> dict[int, str]:
    """对云端已通过 paddle_vl 闸口的页再做一道独立检查，返回 {页: 原因}（这些页不入库，等待重跑）。
    1) 空文本且 empty_reason 不是 blank/image_only -> 拒；
    2) 原 PDF 有文本层(>=200 字符)而 OCR 字符数 < 25% -> 疑似漏识；
    3) 文本层很长但 OCR 为空 -> 同上。"""
    bad: dict[int, str] = {}
    with fitz.open(src) as d:
        for n, (txt, meta) in ok.items():
            er = meta.get("empty_reason")
            o = _nchars(txt)
            if o == 0 and er not in paddle_vl.EMPTY_OK_REASONS:
                bad[n] = "qc_empty: 空文本且无 blank/image_only 依据"
                continue
            layer = _nchars(d[n - 1].get_text())
            if layer >= QC_MIN_LAYER and o < layer * QC_MIN_RATIO:
                bad[n] = f"qc_short: OCR {o} 字符 < 文本层 {layer} 字符的 {QC_MIN_RATIO:.0%}"
    return bad


# qc_short 补救：关闭版面检测后 PP 不再按 footnote 等标签丢弃脚注（服务端默认 markdown_ignore_labels 含 footnote）。
# 输出为纯文本（无版面结构），只用于 qc_short 页的补救，meta["ocr_opt"]="layout_off" 标记来源。
LAYOUT_OFF_OPT = {"useLayoutDetection": False, "promptLabel": "ocr"}


def _layout_fallback_locked(p: Paths, src: Path, rel: str, res: dict, qc_bad: dict[int, str],
                             log: Callable[[str], None]) -> tuple[int, int]:
    """返回 (执行前剩余额度, 实际占用页数)。额度预留在锁内完成；耗时的无版面重提在锁外执行。
    2026-11-26 根因：原先整段 layout_fallback 在 _lock 内运行，重提（远程 OCR，单块可达 30 分钟）期间
    所有线程的 log() 都阻塞在 _lock 上，表现为每约 50 分钟整体卡死约 37 分钟（watchdog.log 24 次）。"""
    n_cand = sum(1 for r in qc_bad.values() if r.startswith("qc_short"))
    with _lock:
        remaining = DAILY_CAP - quota_today(p)
        n_cand = min(n_cand, max(remaining, 0))
        if n_cand:
            quota_add(p, n_cand)  # 预留，防止并发线程超额
    used = layout_fallback(None, src, rel, res, qc_bad, n_cand, log)  # p=None：不再二次计额
    return remaining, used


def layout_fallback(p: Paths | None, src: Path, rel: str, res: dict, qc_bad: dict[int, str],
                    remaining: int, log: Callable[[str], None]) -> int:
    """对 qc_short 页用 LAYOUT_OFF_OPT 重提（最多 remaining 页），通过 qc 的结果并入 res["ok"] 并从 qc_bad 移除。
    返回实际提交页数（计入当日额度）。额度不足或无 qc_short 时不提交。"""
    cand = sorted(n for n, r in qc_bad.items() if r.startswith("qc_short"))[:max(remaining, 0)]
    if not cand:
        return 0
    if p is not None:
        quota_add(p, len(cand))
    log(f"  [{rel}] qc_short 无版面重提 {len(cand)} 页")
    try:
        fres = paddle_vl.run_pages(str(src), cand, log=log, opt=LAYOUT_OFF_OPT)
    except Exception as e:
        log(f"  [{rel}] 无版面重提整体失败: {type(e).__name__}: {e}"[:300])
        return len(cand)
    fbad = qc_pages(src, fres["ok"])
    for n, (txt, meta) in fres["ok"].items():
        if n in fbad:
            continue
        res["ok"][n] = (txt, {**meta, "ocr_opt": "layout_off"})
        qc_bad.pop(n, None)
    log(f"  [{rel}] 无版面重提：通过 {len(cand) - len(fbad)} 页，仍拒 {len(fbad)} 页")
    return len(cand)


def unblocked_pages(p: Paths) -> dict[tuple[str, str], str]:
    return {(u["file"], u["page"]): u["time"] for u in read_tsv(p.unblock)}


def tries_by_page(p: Paths) -> dict[tuple[str, str], int]:
    c: dict[tuple[str, str], int] = {}
    unblocked = unblocked_pages(p)
    for f in read_tsv(p.failed):
        if f["reason"].startswith(("quota", "transient", "已停止", "cancelled", "empty_storm")) or "12001" in f["reason"]:
            continue  # 配额/排队/被停止不是页本身的问题，不占 3 次重试名额
        k = (f["file"], f["page"])
        if f["reason"].startswith("empty_suspect"):
            # 空返回不自动重提（用户 2026-11-24/25：先核对官方要求，盲目重试只烧额度）。
            # 用户用 unblock 放行后，放行时间之前的空返回记录不再计数。
            if f["time"] >= unblocked.get(k, ""):
                c[k] = MAX_TRIES
            continue
        c[k] = c.get(k, 0) + 1
    return c


def _ink_frac(pg: Any) -> float:
    s = pg.get_pixmap(dpi=30, colorspace=fitz.csGRAY).samples
    if not s:
        return 0.0
    base = sorted(s[:: max(1, len(s) // 4000)])
    med = base[len(base) // 2]
    return sum(1 for b in s if abs(b - med) > 40) / len(s)


def preflight(p: Paths, rel: str, pages: list[int]) -> list[dict]:
    """空返回页对照官方要求逐项核对（纯本地，不耗额度）。每页一行：各项检查与是否违规。"""
    src = p.src / rel
    rows: list[dict] = []
    size = src.stat().st_size
    with fitz.open(str(src)) as pdf:
        file_issues = []
        if size == 0:
            file_issues.append("空文件(官方 10001)")
        if pdf.needs_pass or pdf.is_encrypted:
            file_issues.append("加密 PDF")
        if pdf.page_count > OFFICIAL_MAX_PAGES:
            file_issues.append(f"整份 {pdf.page_count} 页 > 官方建议 {OFFICIAL_MAX_PAGES}")
        for n in pages:
            pg = pdf[n - 1]
            w, h = pg.rect.width, pg.rect.height
            imgs = pg.get_images(full=True)
            big = 0
            for im in imgs:
                try:
                    big = max(big, len(pdf.extract_image(im[0])["image"]))
                except Exception:
                    pass
            one = paddle_vl._build_pdf(str(src), [n])
            issues = list(file_issues)
            if len(one) > OFFICIAL_MAX_UPLOAD:
                issues.append(f"单页 PDF {len(one)} B > 官方 50 MB")
            if big > OFFICIAL_MAX_IMAGE:
                issues.append(f"页内图片 {big} B > 官方单图 10 MB")
            if not imgs and not pg.get_text().strip() and not pg.get_drawings():
                issues.append("页面无图片、无文本、无矢量：实为空页")
            if min(w, h) < 72 or max(w, h) / max(1, min(w, h)) > 5:
                issues.append(f"页面尺寸异常 {w:.0f}x{h:.0f} pt")
            rows.append({"file": rel, "page": n, "w_pt": round(w), "h_pt": round(h), "images": len(imgs),
                         "max_image_bytes": big, "page_pdf_bytes": len(one), "ink_frac": round(_ink_frac(pg), 4),
                         "issues": "；".join(issues) or "未见违反官方要求"})
    return rows


def halt(p: Paths, rel: str, pages: list[int], why: str) -> None:
    """空返回风暴：写停跑文件 + 官方要求核对结果；之后 run 一律不提交，直到用户删除 halt 文件。"""
    try:
        rows = preflight(p, rel, pages[:20])
    except Exception as e:  # 核对本身失败也要停
        rows = [{"file": rel, "page": "-", "issues": f"preflight 出错: {e}"}]
    lines = [f"{dt.datetime.now():%F %T} 停跑：{why}", f"文件 {rel}，空返回页 {len(pages)} 页：{pages[:50]}",
             "处理顺序：1) 看下表是否违反官方要求（大小/页数/图片/加密/空页）；2) 查 token、模型名、请求参数是否符合官方文档；",
             "3) 用 1 页小样确认；4) 确认后删除本文件；需要重提的页用「python -m docstore.ocr_batch --root . unblock 文件 页...」放行（每次只多 1 次）。", ""]
    lines += ["\t".join(f"{k}={v}" for k, v in r.items()) for r in rows]
    p.halt.write_text("\n".join(lines) + "\n")
    log(f"空返回风暴，已停跑并写 {p.halt.name}")


# ---------------------------------------------------------------- quota

def quota_today(p: Paths) -> int:
    q = json.loads(p.quota.read_text()) if p.quota.exists() else {}
    return int(q.get(str(dt.date.today()), 0))


def quota_add(p: Paths, n: int) -> None:
    with _lock:
        q = json.loads(p.quota.read_text()) if p.quota.exists() else {}
        k = str(dt.date.today())
        q[k] = int(q.get(k, 0)) + n
        p.quota.write_text(json.dumps(q, indent=1))


def past_stop_time() -> bool:
    now = dt.datetime.now()  # 本机时区 CST = 北京时间
    return STOP_HOUR <= now.hour < 18


# ---------------------------------------------------------------- run

class Stop(Exception):
    pass


stop_evt = threading.Event()
_PAGE_KEYS = ("model", "job_id", "trace_id", "chunk", "empty_reason", "seconds")


def process(p: Paths, rel: str, pages_total: int) -> None:
    if stop_evt.is_set():
        return
    src = p.src / rel
    jpath = p.out / (rel + ".json")
    prev: dict[str, Any] = json.loads(jpath.read_text()) if jpath.exists() else {"file": rel, "pages": {}}
    tries = tries_by_page(p)
    if p.halt.exists():
        stop_evt.set()
        return
    if tries.get((rel, "ALL"), 0) >= MAX_TRIES:
        return
    want = [n for n in range(1, pages_total + 1)
            if str(n) not in prev["pages"] and tries.get((rel, str(n)), 0) < MAX_TRIES]
    if not want:
        return
    with _lock:
        remaining = DAILY_CAP - quota_today(p)
        if remaining <= 0:
            stop_evt.set()
            log(f"当日额度已满 {DAILY_CAP}，停止提交新文件")
            return
        if len(want) > remaining:
            # 末段：只提交剩余额度能容纳的前 N 页（其余明日续跑），把当日额度用满，而不是整份跳过/整轮停
            log(f"当日额度仅余 {remaining} 页，{rel} 只提交前 {remaining} 页（共待办 {len(want)}），之后停止")
            want = want[:remaining]
            stop_evt.set()
        quota_add(p, len(want))
    t0 = time.time()
    try:
        res = paddle_vl.run_pages(str(src), want, log=lambda m: log(f"  [{rel}] {m}"))
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"[:300]
        if isinstance(e, paddle_vl.PaddleQuotaError) or "12001" in reason or "429" in reason:
            stop_evt.set()
        log(f"整份失败 {rel}: {reason}")
        append_tsv(p.failed, [_now_iso(), rel, "ALL", reason], FAILED_HDR)
        return
    qc_bad = qc_pages(src, res["ok"])
    if any(r.startswith("qc_short") for r in qc_bad.values()):
        remaining, used = _layout_fallback_locked(p, src, rel, res, qc_bad, log)
        if remaining - used <= 0:
            stop_evt.set()
    for n, reason in sorted(qc_bad.items()):
        append_tsv(p.failed, [_now_iso(), rel, n, reason], FAILED_HDR)
        log(f"  [{rel}] QC 拒收第 {n} 页: {reason}")
    for n, (txt, meta) in res["ok"].items():
        if n in qc_bad:
            continue
        layout = _save_page_layout(p, rel, n, meta)
        prev["pages"][str(n)] = {"text": txt, **{k: meta.get(k) for k in _PAGE_KEYS}, "layout": layout,
                                 **({"ocr_opt": meta["ocr_opt"]} if meta.get("ocr_opt") else {})}
    for n, reason in sorted(res["failed"].items()):
        append_tsv(p.failed, [_now_iso(), rel, n, reason], FAILED_HDR)
    if res.get("quota_hit"):
        stop_evt.set()
    if res.get("empty_storm"):
        stop_evt.set()
        halt(p, rel, sorted(n for n, r in res["failed"].items() if str(r).startswith("empty_suspect")),
             "paddle_vl.empty_storm：同一块空返回过多")
    prev.update(source=str(src), model=MODEL, page_count=pages_total, updated=_now_iso())
    jpath.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(jpath, prev)
    _write_md(p, rel, prev, pages_total)
    got = len(prev["pages"])
    append_tsv(p.done, [_now_iso(), rel, pages_total, got, pages_total - got, MODEL, round(time.time() - t0, 1)],
               ["time", "file", "pages", "ok_pages", "failed_pages", "model", "seconds"])
    log(f"完成 {rel}: {got}/{pages_total} 页，失败 {len(res['failed'])} 页，{time.time() - t0:.0f}s")


def _save_page_layout(p: Paths, rel: str, n: int, meta: dict, session: Any = None) -> str | None:
    """落版面；返回相对 out 的路径，无版面或失败返回 None（不影响文本入库）。"""
    if meta.get("_layout") is None:
        return None
    try:
        paddle_vl.save_layout(p.out, rel, n, meta, download_images=True, session=session)
    except Exception as e:
        log(f"  [{rel}] 第 {n} 页版面保存失败: {type(e).__name__}: {e}"[:300])
        return None
    lp = f"layout/{rel}/p{n:04d}.json"
    return lp if (p.out / lp).exists() else None


def _write_md(p: Paths, rel: str, j: dict, pages_total: int) -> None:
    md = "\n\n".join(f"<!-- page {n} -->\n{j['pages'][str(n)]['text']}"
                     for n in range(1, pages_total + 1) if str(n) in j["pages"])
    (p.out / (rel + ".md")).write_text(md)


EMPTY_AUDIT_N = int(os.environ.get("PADDLE_EMPTY_AUDIT_N", "100"))  # 未解决的空返回页（判为有内容）达到此数，自动审计并停跑
EMPTY_AUDIT_HDR = ["file", "page", "verdict", "local_chars"]


def judge_empty(src: str, n: int) -> tuple[str, int | None]:
    """空返回页本地判定（不耗额度）。blank=本地判空白；no_text_local=本地 OCR 无字；content=页面有内容，疑似 PP 漏识。"""
    if paddle_vl._is_blank(src, n):
        return "blank", None
    c = paddle_vl.local_ocr_chars(src, n)
    if c is not None and c < paddle_vl.LOCAL_OCR_MIN_CHARS:
        return "no_text_local", c
    return "content", c


def apply_empty_judgement(p: Paths) -> list[tuple[str, int, str, int | None]]:
    """对未解决的 empty_suspect 页做本地判定；判为空白/无字的直接写入 out（不再重提）。返回全部判定结果。"""
    by: dict[str, list[int]] = {}
    for x in read_tsv(p.failed):
        if x["reason"].startswith("empty_suspect") and x["page"] != "ALL":
            by.setdefault(x["file"], []).append(int(x["page"]))
    results: list[tuple[str, int, str, int | None]] = []
    for rel, pgs in by.items():
        jp = p.out / (rel + ".json")
        if not jp.exists():
            continue
        j = json.loads(jp.read_text())
        changed = False
        for n in sorted(set(pgs)):
            if str(n) in j["pages"]:
                continue
            verdict, c = judge_empty(str(p.src / rel), n)
            results.append((rel, n, verdict, c))
            if verdict != "content":
                j["pages"][str(n)] = {"text": "", "model": MODEL, "job_id": "reclassified-" + verdict,
                                      "trace_id": None, "chunk": None, "empty_reason": verdict, "seconds": None}
                changed = True
        if changed:
            _atomic_json(jp, j)
            _write_md(p, rel, j, j["page_count"])
    return results


def cmd_reclassify(p: Paths, a: Any) -> None:
    """用修正后的空白判定（泛黄纸容忍）重判历史 empty_suspect：现在判为空白的，直接记 blank，不再重提。"""
    results = apply_empty_judgement(p)
    fixed = sum(1 for r in results if r[2] != "content")
    log(f"reclassify: {fixed} 页由 empty_suspect 改判为 blank / no_text_local（本地判空白或本地 OCR 无字）")


def empty_audit(p: Paths, threshold: int = EMPTY_AUDIT_N) -> int:
    """空返回审计：本地判定并修正空白页；仍判为有内容的页写 empty_audit.tsv。
    有内容的页数 >= threshold 时写 halt 文件停跑（不再提交），明细见 empty_audit.tsv。返回有内容的页数。"""
    results = apply_empty_judgement(p)
    content = [r for r in results if r[2] == "content"]
    with open(p.root / "empty_audit.tsv", "w", newline="") as fh:
        cw = csv.writer(fh, delimiter="\t")
        cw.writerow(EMPTY_AUDIT_HDR)
        for rel, n, verdict, c in results:
            cw.writerow([rel, n, verdict, "" if c is None else c])
    log(f"empty_audit: 判定 {len(results)} 页，有内容 {len(content)} 页（阈值 {threshold}）")
    if len(content) >= threshold:
        # 自动诊断：对这些页跑 preflight（页尺寸、图片字节/格式、文本层、墨迹、issues），明细写 empty_diag.tsv
        by: dict[str, list[int]] = {}
        for rel, n, _v, _c in content:
            by.setdefault(rel, []).append(n)
        diag: list[dict] = []
        for rel, pgs in by.items():
            for row in preflight(p, rel, sorted(pgs)):
                diag.append({"file": rel, **row})
        keys = sorted({k for d in diag for k in d}, key=lambda k: (k != "file", k))
        with open(p.root / "empty_diag.tsv", "w", newline="") as fh:
            dw = csv.DictWriter(fh, fieldnames=keys, delimiter="\t", extrasaction="ignore")
            dw.writeheader()
            dw.writerows(diag)
        p.halt.write_text("\n".join([
            f"空返回审计：{len(content)} 页判为有内容却返回空文本（阈值 {threshold}），疑似 PP 漏识或请求格式问题。",
            "已停止提交。明细见 empty_audit.tsv，自动诊断见 empty_diag.tsv；查明并修复后删除本文件再 run。",
        ]) + "\n")
        log(f"空返回审计超过阈值，已停跑并写 {p.halt.name}")
    return len(content)


def cmd_empty_audit(p: Paths, a: Any) -> None:
    n = empty_audit(p, a.threshold)
    print(f"有内容的空返回页: {n}")


_IMPORT_TS = _time.time()


def stale_code_files() -> list[str]:
    """本进程导入后源码又被改过 → 进程仍是旧代码（2026-11-25：旧 run 缺版面重提修复，QC 短页无补救）。"""
    here = Path(__file__).resolve().parent
    files = [here / "ocr_batch.py", here / "engines" / "paddle_vl.py"]
    return [f.name for f in files if f.exists() and f.stat().st_mtime > _IMPORT_TS]


def cmd_run(p: Paths, a: Any) -> None:
    global _log_fh
    stale = stale_code_files()
    if stale and not os.environ.get("DOCSTORE_ALLOW_STALE"):
        raise SystemExit(f"拒绝启动：源码已改动 {stale}，本进程是旧代码。请等旧 run 结束或停掉后重启（cron loop 会自动用新代码）。")
    os.environ["DOCSTORE_PADDLE_VL_MODEL"] = MODEL
    p.logs.mkdir(exist_ok=True)
    _log_fh = open(p.logs / f"run_{dt.datetime.now():%Y%m%d_%H%M%S}.log", "a")
    if not p.manifest.exists():
        sys.exit("先运行 manifest")
    empty_audit(p)
    if p.halt.exists():
        log(f"存在 {p.halt.name}：空返回待核对官方要求，不提交。核对完删除该文件再跑")
        sys.exit(4)
    if past_stop_time() and not a.ignore_window:
        log("当前在 09:00–18:00 之间，不运行（--ignore-window 可强制）")
        return
    rows = read_tsv(p.manifest)
    for r in rows:
        if r["error"]:
            jpath = p.out / (r["file"] + ".json")
            if not jpath.exists():
                append_tsv(p.failed, [_now_iso(), r["file"], "ALL", r["error"]], FAILED_HDR)
    todo = []
    tries = tries_by_page(p)
    for r in rows:
        n = int(r["pages"])
        if r["error"] or n == 0:
            continue
        jpath = p.out / (r["file"] + ".json")
        have = len(json.loads(jpath.read_text())["pages"]) if jpath.exists() else 0
        if have < n and tries.get((r["file"], "ALL"), 0) < MAX_TRIES:
            todo.append((r["file"], n, int(r["text_layer"])))
    todo.sort(key=lambda x: (x[2], x[1]))  # 扫描件优先，小文件优先
    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        log("无待处理文件")
        cmd_report(p, a)
        sys.exit(3)
    log(f"模型 {MODEL}；待处理 {len(todo)} 份 {sum(t[1] for t in todo)} 页；今日已提交 {quota_today(p)} 页，上限 {DAILY_CAP}")
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {}
        it = iter(todo)
        for t in it:
            futs[ex.submit(process, p, t[0], t[1])] = t[0]
            if len(futs) >= a.workers * 2:
                break
        while futs:
            for f in as_completed(list(futs)):
                rel = futs.pop(f)
                try:
                    f.result()
                except Exception:
                    log(f"意外错误 {rel}: {traceback.format_exc()[-500:]}")
                    append_tsv(p.failed, [_now_iso(), rel, "ALL", "意外错误，见日志"], FAILED_HDR)
                if past_stop_time() and not a.ignore_window:
                    if not stop_evt.is_set():
                        log("到 09:00，停止提交新文件")
                    stop_evt.set()
                if not stop_evt.is_set():
                    nxt = next(it, None)
                    if nxt:
                        futs[ex.submit(process, p, nxt[0], nxt[1])] = nxt[0]
                break
    cmd_report(p, a)


# ---------------------------------------------------------------- report

def ledger(p: Paths, rows: list[dict]) -> None:
    """逐页账本 pages_ledger.tsv：每个文件一行，页数 = ok + blank + image_only + missing，缺页列出页号和原因。"""
    fails: dict[tuple[str, str], str] = {}
    for x in read_tsv(p.failed):
        fails[(x["file"], x["page"])] = x["reason"]
    with open(p.ledger, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["file", "pages", "ok", "blank", "image_only", "missing", "missing_pages", "reasons", "balanced"])
        for r in rows:
            n = int(r["pages"])
            jp = p.out / (r["file"] + ".json")
            pg = json.loads(jp.read_text())["pages"] if jp.exists() else {}
            blank = sum(1 for v in pg.values() if v.get("empty_reason") == "blank")
            img = sum(1 for v in pg.values() if v.get("empty_reason") in ("image_only", "no_text_local"))
            ok = len(pg) - blank - img
            miss = [q for q in range(1, n + 1) if str(q) not in pg]
            why = sorted({fails.get((r["file"], str(q)), fails.get((r["file"], "ALL"), r["error"] or "尚未处理"))[:80]
                          for q in miss})
            w.writerow([r["file"], n, ok, blank, img, len(miss), ",".join(map(str, miss[:50])), " | ".join(why),
                        int(ok + blank + img + len(miss) == n)])


def page_meta_missing(v: dict) -> bool:
    """云端页必须有 model 和 job_id。本地判空白的页（job_id=local-blank, empty_reason=blank）不提交，不算缺失。"""
    if v.get("job_id") == "local-blank" and v.get("empty_reason") == "blank":
        return False
    return not v.get("model") or not v.get("job_id")


def audit(p: Paths) -> list[str]:
    """独立复核已落盘结果：页数、空文本无依据、模型缺失、md 与 json 不一致、json 损坏。out/layout/ 下的版面文件不在此列。"""
    issues: list[str] = []
    mf = {r["file"]: int(r["pages"]) for r in read_tsv(p.manifest)}
    for jp in p.out.rglob("*.json"):
        rel = str(jp.relative_to(p.out))[:-5]
        if rel.startswith("layout/") and rel not in mf:
            continue
        try:
            j = json.loads(jp.read_text())
        except Exception as e:
            issues.append(f"{rel}: json 损坏 {e}")
            continue
        pg = j.get("pages", {})
        n = mf.get(rel)
        if n is None:
            issues.append(f"{rel}: 不在 manifest")
        elif j.get("page_count") != n:
            issues.append(f"{rel}: 页数 {j.get('page_count')} != manifest {n}")
        for k, v in pg.items():
            if not (1 <= int(k) <= (n or 10**9)):
                issues.append(f"{rel}: 页号 {k} 越界")
            if page_meta_missing(v):
                issues.append(f"{rel}: 第{k}页缺 model/job_id")
            if not str(v.get("text", "")).strip() and v.get("empty_reason") not in paddle_vl.EMPTY_OK_REASONS:
                issues.append(f"{rel}: 第{k}页空文本无依据")
        mdp = p.out / (rel + ".md")
        if not mdp.exists() or mdp.read_text().count("<!-- page ") != len(pg):
            issues.append(f"{rel}: md 缺失或页数与 json 不符")
    return issues


def run_status(p: Paths) -> str:
    """report 第一行：run 进程是否在跑、最新 run 日志修改时间、停跑文件是否存在。读 /proc，不用 pgrep -f。"""
    me = os.getpid()
    pids: list[str] = []
    try:
        entries = [e for e in os.listdir("/proc") if e.isdigit()]
    except OSError:
        entries = []
    for e in entries:
        if int(e) == me:
            continue
        try:
            raw = Path(f"/proc/{e}/cmdline").read_bytes()
        except OSError:
            continue
        argv = [x for x in raw.decode("utf-8", "replace").split("\0") if x]
        cmd = " ".join(argv)
        if "paddle_batch.py run" in cmd or (("ocr_batch" in cmd or "ocr-batch" in cmd) and "run" in argv
                                             and not any(x in ("pytest", "py.test") or x.endswith("pytest") for x in argv)):
            pids.append(e)
    logs = sorted(p.logs.glob("run_*.log"), key=lambda f: f.stat().st_mtime) if p.logs.exists() else []
    last = (f"{dt.datetime.fromtimestamp(logs[-1].stat().st_mtime):%F %T}（{logs[-1].name}）" if logs else "无")
    return (f"run 进程：{'在跑 pid ' + ','.join(pids) if pids else '未运行'}；最新 run 日志修改 {last}；"
            f"停跑文件 {p.halt.name}：{'存在' if p.halt.exists() else '无'}")


def cmd_report(p: Paths, a: Any) -> None:
    print(run_status(p))
    st = empty_status(p)
    print(f"空返回监控：未解决 {st['unresolved']} 页，今日新增 {st['new_today']} 页（阈值 {st['threshold']}）"
          + (" ← 预警，见 logs/alerts.log" if empty_alert_line(p) else ""))
    rows = read_tsv(p.manifest)
    tot_files = len(rows)
    tot_pages = sum(int(r["pages"]) for r in rows)
    full = part = none = got_pages = 0
    for r in rows:
        jpath = p.out / (r["file"] + ".json")
        have = len(json.loads(jpath.read_text())["pages"]) if jpath.exists() else 0
        got_pages += have
        if have and have >= int(r["pages"]):
            full += 1
        elif have:
            part += 1
        else:
            none += 1
    issues = audit(p)
    ledger(p, rows)
    # 失败页：只列目前仍缺的（之后重跑成功的不再列）
    still = []
    for f in read_tsv(p.failed):
        jpath = p.out / (f["file"] + ".json")
        pages = json.loads(jpath.read_text())["pages"] if jpath.exists() else {}
        if (f["page"] == "ALL" and not pages) or (f["page"] != "ALL" and f["page"] not in pages):
            still.append(f)
    seen = {}
    for f in still:
        seen[(f["file"], f["page"])] = f
    lines = [f"PaddleOCR 批处理进度 {dt.datetime.now():%Y-%m-%d %H:%M}（模型 {MODEL}）",
             f"PDF {tot_files} 份 / {tot_pages} 页：全部完成 {full} 份，部分 {part} 份，未开始 {none} 份；已得 {got_pages} 页",
             f"今日已提交 {quota_today(p)} 页（上限 {DAILY_CAP}）",
             f"质检抽查：{len(issues)} 项问题" + ("（见下）" if issues else "，通过"),
             f"仍失败 {len(seen)} 条（文件/页；空返回页不自动重提，需 preflight 核对后 unblock；其他页试满 {MAX_TRIES} 次不再自动重试）：", ""]
    for i in issues[:200]:
        lines.append("QC问题\t" + i)
    for (fl, pg), f in sorted(seen.items()):
        lines.append(f"{fl}\t第{pg}页\t{f['reason']}")
    p.report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:4]))
    print(f"失败清单：{p.report}（{len(seen)} 条）")


def cmd_preflight(p: Paths, a: Any) -> None:
    pages = a.pages or sorted({int(f["page"]) for f in read_tsv(p.failed)
                               if f["file"] == a.file and f["page"].isdigit() and f["reason"].startswith("empty_suspect")})
    if not pages:
        sys.exit(f"{a.file} 没有空返回页记录；请给页码")
    for r in preflight(p, a.file, pages):
        print("\t".join(f"{k}={v}" for k, v in r.items()))


def cmd_unblock(p: Paths, a: Any) -> None:
    now = _now_iso()
    for q in a.pages:
        append_tsv(p.unblock, [now, a.file, q], ["time", "file", "page"])
    print(f"已放行 {a.file} {len(a.pages)} 页，各多 1 次提交")


# ---------------------------------------------------------------- backfill-layout（旧 job 补取版面；只 GET，绝不 POST）

BF_HDR = ["job_id", "file", "pages", "status", "note"]
_LOG_JOB = re.compile(r"\[(.+)\] \[paddle\] 块(\d+) 页(\S+) 通过 \d+/\d+ [\d.]+s job=(\d+)")


def parse_label(label: str) -> list[int]:
    """paddle_vl._label 的反解析："5" / "1-5" / "1,3,7" / "1-5,7"（容错：任意混合）。"""
    out: list[int] = []
    for part in label.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
        else:
            raise ValueError(f"无法解析页标签: {label!r}")
    return out


def parse_run_logs(p: Paths) -> dict[str, tuple[str, list[int]]]:
    """{job_id: (rel, 提交页列表)}，来自 logs/run_*.log 的 '块N 页LABEL 通过 a/b ... job=ID' 行。"""
    res: dict[str, tuple[str, list[int]]] = {}
    if not p.logs.exists():
        return res
    for lf in sorted(p.logs.glob("run_*.log")):
        try:
            text = lf.read_text(errors="replace")
        except OSError:
            continue
        for ln in text.splitlines():
            m = _LOG_JOB.search(ln)
            if not m:
                continue
            try:
                res[m.group(4)] = (m.group(1), parse_label(m.group(3)))
            except ValueError:
                continue
    return res


class _Throttled:
    """包装 requests.Session：所有 GET 之间至少间隔 interval 秒（跨线程）。"""

    def __init__(self, session: Any, interval: float = 0.2):
        self.s, self.interval, self._t, self._l = session, interval, 0.0, threading.Lock()

    def get(self, *args: Any, **kw: Any) -> Any:
        with self._l:
            wait = self._t + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._t = time.monotonic()
        return self.s.get(*args, **kw)


def _fetch_job(session: Any, job: str) -> tuple[str, str]:
    """返回 (status, jsonl 文本或说明)。status: ok / expired / not_done / error。网络错误重试 3 次。"""
    headers = {"Authorization": f"bearer {paddle_vl._token()}"}
    last = ""
    for att in range(3):
        try:
            r = session.get(f"{paddle_vl.URL}/{job}", headers=headers, timeout=60)
            body = paddle_vl._body(r)
            if r.status_code == 400 or str(body.get("code")) == "11002":
                return "expired", f"HTTP {r.status_code} code={body.get('code')}"
            if r.status_code != 200:
                last = f"查询 HTTP {r.status_code}"
                if r.status_code in (401, 403, 429):
                    return "error", last
                time.sleep(1 + att)
                continue
            d = body.get("data")
            if not isinstance(d, dict):
                return "error", f"查询响应无 data: {str(body)[:100]}"
            if d.get("state") != "done":
                return "not_done", f"state={d.get('state')}"
            url = (d.get("resultUrl") or {}).get("jsonUrl") if isinstance(d.get("resultUrl"), dict) else None
            if not url:
                return "error", "done 但无 jsonUrl"
            rr = session.get(url, timeout=120)
            if rr.status_code != 200:
                if rr.status_code in (400, 403, 404):
                    return "expired", f"下载 HTTP {rr.status_code}"
                last = f"下载 HTTP {rr.status_code}"
                time.sleep(1 + att)
                continue
            return "ok", rr.text
        except Exception as e:  # requests 网络错误
            last = f"{type(e).__name__}: {e}"[:150]
            time.sleep(1 + att)
    return "error", last


def _jsonl_results(text: str) -> list[dict]:
    out: list[dict] = []
    for ln in text.split("\n"):
        ln = ln[:-1] if ln.endswith("\r") else ln
        if ln.strip():
            out.extend(json.loads(ln)["result"]["layoutParsingResults"])
    return out


def _norm(s: str) -> str:
    return "".join(str(s).split())


def _lib_pages_by_job(p: Paths) -> dict[str, dict[str, dict[int, dict]]]:
    """{job_id: {rel: {页: 记录}}}：只含有 job_id、且缺 layout（或 layout 文件不存在）的页。"""
    res: dict[str, dict[str, dict[int, dict]]] = {}
    for jp in p.out.rglob("*.json"):
        rel = str(jp.relative_to(p.out))[:-5]
        if rel.startswith("layout/"):
            continue
        try:
            j = json.loads(jp.read_text())
        except Exception:
            continue
        for k, v in j.get("pages", {}).items():
            job = v.get("job_id")
            if not job or not str(job).isdigit():
                continue  # reclassified-blank 等无云端 job
            lay = v.get("layout")
            if lay and (p.out / lay).exists():
                continue
            res.setdefault(str(job), {}).setdefault(rel, {})[int(k)] = v
    return res


def _locate_by_text(lib: dict[int, dict], results: list[dict]) -> list[int] | None:
    """日志无此 job 时：库中该 job 的页（按页号）与 JSONL 各页 clean_md 文本顺序匹配，全部唯一匹配且数量相等才返回页列表。"""
    texts = [_norm(paddle_vl.clean_md(((r.get("markdown") or {}).get("text")) or "")) for r in results]
    if len(lib) != len(texts):
        return None
    pgs = sorted(lib)
    for pg, t in zip(pgs, texts):
        if not t or texts.count(t) != 1 or _norm(lib[pg].get("text", "")) != t:
            return None
        if sum(1 for q in pgs if _norm(lib[q].get("text", "")) == t) != 1:
            return None
    return pgs


def _backfill_one(p: Paths, session: Any, job: str, libjob: dict[str, dict[int, dict]],
                  logmap: dict[str, tuple[str, list[int]]], dry: bool) -> tuple[str, str, str, str]:
    """返回 (file, pages标签, status, note)。"""
    rels = sorted(libjob)
    rel = rels[0]
    lib = libjob[rel]
    if len(rels) > 1:
        return rel, "", "mismatch", f"job 对应多个文件 {rels}"
    status, body = _fetch_job(session, job)
    if status != "ok":
        return rel, "", status, body
    try:
        results = _jsonl_results(body)
    except Exception as e:
        return rel, "", "error", f"JSONL 解析失败 {e}"[:150]
    pages: list[int] | None = None
    src_note = "log"
    if job in logmap:
        lrel, pages = logmap[job]
        if lrel != rel:
            return rel, "", "mismatch", f"日志文件名 {lrel} != 库 {rel}"
    else:
        pages = _locate_by_text(lib, results)
        src_note = "text"
        if pages is None:
            return rel, "", "unmapped", f"日志无此 job，文本顺序匹配失败（库 {len(lib)} 页，JSONL {len(results)} 页）"
    label = paddle_vl._label(pages) if pages else ""
    if len(results) != len(pages):
        return rel, label, "mismatch", f"JSONL {len(results)} 页 != 提交页 {len(pages)}"
    if not set(lib) <= set(pages):
        return rel, label, "mismatch", f"库中页 {sorted(set(lib) - set(pages))} 不在提交页内"
    idx = {pg: i for i, pg in enumerate(pages)}
    for pg, rec in sorted(lib.items()):
        cloud = _norm(paddle_vl.clean_md(((results[idx[pg]].get("markdown") or {}).get("text")) or ""))
        if cloud != _norm(rec.get("text", "")):
            return rel, label, "text_mismatch", f"第 {pg} 页云端文本与库不一致"
    src = p.src / rel
    sizes = paddle_vl._page_sizes(str(src), pages)
    lays = paddle_vl._layouts(body, pages, sizes)
    if dry:
        return rel, label, "ok", f"dry-run 映射({src_note}) 库中待补 {sorted(lib)}，JSONL {len(results)} 页"
    jp = p.out / (rel + ".json")
    written: dict[int, str] = {}
    for pg in sorted(lib):
        rec = lib[pg]
        meta = {"_layout": lays[idx[pg]], "_raw_jsonl": body, "job_id": job,
                "trace_id": rec.get("trace_id"), "model": rec.get("model")}
        lp = _save_page_layout(p, rel, pg, meta, session=session)
        if lp is None:
            return rel, label, "error", f"第 {pg} 页版面写盘失败"
        written[pg] = lp
    with _lock:  # 多 job 同文件：重读后再写，避免互相覆盖
        j = json.loads(jp.read_text())
        for pg, lp in written.items():
            j["pages"][str(pg)]["layout"] = lp
        _atomic_json(jp, j)
    return rel, label, "ok", f"补 {len(written)} 页版面({src_note})"


def cmd_backfill_layout(p: Paths, a: Any, session: Any = None) -> list[tuple[str, str, str, str, str]]:
    """对 out/**/*.json 中有 job_id、无 layout 的页，按 job 补取版面。只 GET 查询与下载，绝不 POST。"""
    sess = _Throttled(session if session is not None else paddle_vl._new_session(), 0.2)
    done_ok = {r["job_id"] for r in read_tsv(p.backfill) if r["status"] == "ok"}
    libs = _lib_pages_by_job(p)
    logmap = parse_run_logs(p)
    jobs = [j for j in sorted(libs) if j not in done_ok]
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"待补 job {len(jobs)} 个（库中缺版面的 job 共 {len(libs)}，已 ok 跳过 {len(libs) - len(jobs) if not a.limit else '-'}）"
          f"{'  [dry-run：不写盘]' if a.dry_run else ''}")
    results: list[tuple[str, str, str, str, str]] = []

    def one(job: str) -> tuple[str, str, str, str, str]:
        try:
            rel, label, status, note = _backfill_one(p, sess, job, libs[job], logmap, a.dry_run)
        except Exception as e:
            rel, label, status, note = sorted(libs[job])[0], "", "error", f"{type(e).__name__}: {e}"[:200]
        if not a.dry_run:
            append_tsv(p.backfill, [job, rel, label, status, note], BF_HDR)
        return job, rel, label, status, note

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(jobs)))) as ex:
        for r in ex.map(one, jobs):
            results.append(r)
            print("\t".join(r))
    cnt: dict[str, int] = {}
    for r in results:
        cnt[r[3]] = cnt.get(r[3], 0) + 1
    print("汇总：" + "，".join(f"{k} {v}" for k, v in sorted(cnt.items())))
    return results


# ---------------------------------------------------------------- CLI

# ---------------------------------------------------------------- loop / watchdog（替代 nightly.sh、watchdog.sh）

LOOP_ROUNDS = int(os.environ.get("DOCSTORE_OCR_LOOP_ROUNDS", "6"))
WATCHDOG_STALE_S = int(os.environ.get("DOCSTORE_OCR_WATCHDOG_STALE_S", "1800"))


def _lock_path(p: Paths) -> Path:
    return p.root / ".lock"


def cmd_loop(p: Paths, a: Any) -> None:
    """定时入口（cron 每小时调用）：文件锁防重入；最多 LOOP_ROUNDS 轮 run；无待办、空返回停跑、额度将满即停；末尾写 状态.txt。
    全天运行（不受 09–18 窗口限制）。锁文件内写 pid，供 watchdog 使用。"""
    import fcntl
    p.logs.mkdir(exist_ok=True)
    fh = open(_lock_path(p), "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("已有 loop 实例在跑，本次退出")
        return
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    try:
        for i in range(1, LOOP_ROUNDS + 1):
            log(f"loop 第 {i}/{LOOP_ROUNDS} 轮")
            try:
                cmd_run(p, types.SimpleNamespace(limit=None, workers=a.workers, ignore_window=True))
                rc = 0
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
            if rc in (3, 4):
                log(f"loop 结束：退出码 {rc}（{'无待办' if rc == 3 else '空返回停跑'}）")
                break
            if quota_today(p) + 100 > DAILY_CAP:
                log(f"loop 结束：今日已提交 {quota_today(p)}，距上限 {DAILY_CAP} 不足一批")
                break
        cmd_report(p, a)
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def empty_status(p: Paths) -> dict:
    """只读统计空返回监控：未解决的 empty_suspect 页（failed.tsv 中、out/ 里仍无结果）、其中今日新增的页数。"""
    today = dt.date.today().isoformat()
    cache: dict[str, dict] = {}
    unresolved = new_today = 0
    seen: set[tuple[str, int]] = set()
    for x in read_tsv(p.failed):
        if not (x["reason"].startswith("empty_suspect") and x["page"].isdigit()):
            continue
        key = (x["file"], int(x["page"]))
        if key in seen:
            continue
        seen.add(key)
        if x["file"] not in cache:
            jp = p.out / (x["file"] + ".json")
            cache[x["file"]] = json.loads(jp.read_text())["pages"] if jp.exists() else {}
        if str(key[1]) in cache[x["file"]]:
            continue  # 已判空白/无字或已有结果
        unresolved += 1
        if x["time"].startswith(today):
            new_today += 1
    return {"unresolved": unresolved, "new_today": new_today, "threshold": EMPTY_AUDIT_N}


EMPTY_WARN_NEW = int(os.environ.get("DOCSTORE_OCR_EMPTY_WARN_NEW", "20"))


def empty_alert_line(p: Paths) -> str | None:
    """超过预警线返回一行告警文字，否则 None。预警线：未解决 >= 阈值一半，或今日新增 >= DOCSTORE_OCR_EMPTY_WARN_NEW。"""
    st = empty_status(p)
    if st["unresolved"] >= st["threshold"] // 2 or st["new_today"] >= EMPTY_WARN_NEW:
        return (f"【空返回预警】未解决 {st['unresolved']} 页（阈值 {st['threshold']}），今日新增 {st['new_today']} 页；"
                f"处理：python3 -m docstore.ocr_batch --root . empty-audit（判定+诊断 empty_diag.tsv）")
    return None


def cmd_watchdog(p: Paths, a: Any) -> None:
    """卡死检测（cron 每 10 分钟）：锁中 pid 存活且最新 run 日志超过 WATCHDOG_STALE_S 秒无更新 → SIGUSR1 转储栈，再终止。"""
    import signal as _sig
    alert = empty_alert_line(p)
    if alert:  # 空返回预警：写告警文件（每次检查都写，便于查看）
        with open(p.logs / "alerts.log", "a") as al:
            al.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {alert}\n")
    lk = _lock_path(p)
    if not lk.exists() or not lk.read_text().strip():
        return
    pid = int(lk.read_text().strip())
    try:
        os.kill(pid, 0)
    except OSError:
        return  # 进程已不在
    logs = sorted(p.logs.glob("run_*.log"), key=lambda x: x.stat().st_mtime)
    if not logs:
        return
    stale = time.time() - logs[-1].stat().st_mtime
    if stale <= WATCHDOG_STALE_S:
        return
    with open(p.logs / "watchdog.log", "a") as wl:
        wl.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} 卡死: pid {pid} 日志 {int(stale // 60)} 分钟无更新，转储并终止\n")
    os.kill(pid, _sig.SIGUSR1)
    time.sleep(5)
    for sig in (_sig.SIGTERM, _sig.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            break
        time.sleep(3)


def cmd_page(p: Paths, a: Any) -> None:
    """单页核对（提交 1 页，计 1 页额度）：渲染页面 PNG，并保存 PP 返回文本，便于比对图与识别结果。"""
    src = p.src / a.file
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"p{a.page:04d}.png"
    render_page(src, a.page, png, a.dpi)
    res = paddle_vl.run_pages(str(src), [a.page], log=lambda m: log(f"  [{a.file}] {m}"))
    text = res["ok"].get(a.page, ("", {}))[0]
    meta = res["ok"].get(a.page, ("", {}))[1]
    txt = out_dir / f"p{a.page:04d}.pp.md"
    txt.write_text(text, encoding="utf-8")
    print(f"png={png}\npp_text={txt}\npp_chars={len(text)}\nfailed={res['failed'].get(a.page, '')}\nmeta={meta}")


def render_page(src: Path, page: int, png: Path, dpi: int = 110) -> None:
    """渲染单页为 PNG（1 基页码）。"""
    d = fitz.open(str(src))
    try:
        d[page - 1].get_pixmap(dpi=dpi).save(str(png))
    finally:
        d.close()


def add_arguments(ap: argparse.ArgumentParser) -> None:
    """加 --root/--src 与各子命令（docstore ocr-batch 与 python -m docstore.ocr_batch 共用）。"""
    ap.add_argument("--root", dest="ocr_root", help="工作目录（out/ logs/ manifest.tsv 所在），默认当前目录")
    ap.add_argument("--src", dest="ocr_src", help="PDF 根目录，默认 root 的上一级")
    sub = ap.add_subparsers(dest="ocr_cmd", required=True)
    sub.add_parser("manifest", help="扫描全部 PDF，写 manifest.tsv").set_defaults(ocr_fn=cmd_manifest)
    s = sub.add_parser("run", help="断点续跑")
    s.add_argument("--limit", type=int, help="最多处理多少份（试点用）")
    s.add_argument("--workers", type=int, default=6, help="同时处理的文件数（每份内部另有分块并发）")
    s.add_argument("--ignore-window", action="store_true", help="忽略 09:00–18:00 停跑窗口")
    s.set_defaults(ocr_fn=cmd_run)
    sub.add_parser("report", help="汇总进度，写 失败清单.txt").set_defaults(ocr_fn=cmd_report)
    s = sub.add_parser("loop", help="定时入口：文件锁 + 最多若干轮 run + 末尾 report（替代 nightly.sh）")
    s.add_argument("--workers", type=int, default=4)
    s.set_defaults(ocr_fn=cmd_loop)
    sub.add_parser("watchdog", help="卡死检测并终止 run（替代 watchdog.sh）").set_defaults(ocr_fn=cmd_watchdog)
    s = sub.add_parser("page", help="单页核对：渲染 PNG + 保存 PP 文本（提交 1 页）")
    s.add_argument("file")
    s.add_argument("page", type=int)
    s.add_argument("--out-dir", default="check")
    s.add_argument("--dpi", type=int, default=110)
    s.set_defaults(ocr_fn=cmd_page)
    sub.add_parser("reclassify", help="重判历史空返回为空白页").set_defaults(ocr_fn=cmd_reclassify)
    s = sub.add_parser("empty-audit", help="空返回审计：本地判定，有内容的页达阈值则停跑")
    s.add_argument("--threshold", type=int, default=EMPTY_AUDIT_N)
    s.set_defaults(ocr_fn=cmd_empty_audit)
    s = sub.add_parser("preflight", help="空返回页对照官方要求逐项核对（本地，不耗额度）")
    s.add_argument("file")
    s.add_argument("pages", nargs="*", type=int)
    s.set_defaults(ocr_fn=cmd_preflight)
    s = sub.add_parser("unblock", help="核对后放行空返回页，再多 1 次提交")
    s.add_argument("file")
    s.add_argument("pages", nargs="+")
    s.set_defaults(ocr_fn=cmd_unblock)
    s = sub.add_parser("backfill-layout", help="旧 job 补取版面（只 GET 查询与下载，不提交）")
    s.add_argument("--limit", type=int, help="最多处理多少个 job")
    s.add_argument("--dry-run", action="store_true", help="只查询并打印映射，不写盘、不写 backfill_layout.tsv")
    s.set_defaults(ocr_fn=cmd_backfill_layout)


def dispatch(a: argparse.Namespace) -> int:
    p = Paths.make(a.ocr_root, a.ocr_src)
    p.logs.mkdir(exist_ok=True)
    # watchdog 发 SIGUSR1 时把所有线程栈写到 logs/stack_dump.txt，用于查明卡死根因
    faulthandler.register(signal.SIGUSR1, file=open(p.logs / "stack_dump.txt", "a"), all_threads=True)
    a.ocr_fn(p, a)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m docstore.ocr_batch", description="PaddleOCR 云 OCR 批处理")
    add_arguments(ap)
    return dispatch(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
