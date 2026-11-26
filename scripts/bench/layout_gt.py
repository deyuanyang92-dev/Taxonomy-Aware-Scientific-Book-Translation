#!/usr/bin/env python3
"""版面评测：由原生 PDF 页生成 GT（规则初标），并把它配准到扫描页（设计 A.3）。

GT 块：{id, role, level, col, order, bbox_pt, bbox_rel, text, italic_words}
  role: heading|body|caption|ref|index|entry|furniture|figtext（figtext=图内文字，评分时忽略）
  text 里斜体用 *...* 标记；italic_words 是斜体词表（评分用）。
规则按 Rouse 2022 的字体表（profile "rouse2022"）：
  Dante 24/18 或 'CHAPTER n' -> heading L1；Dante-Bold >=13 -> L2；Dante-Medium 12 -> L3；
  Dante-(Medium)Italic 12 -> L4；Dante 9 或 FIGURE/TABLE/PLATE 起首 -> caption；SourceSans -> ref；
  Merriweather -> index；Dante-Bold 10 行首 -> entry；Helvetica 页脚、页顶 12pt 行头 -> furniture。
gt_status 恒为 "rule"，经页图人工终审后改 "verified"（本模块不自动改）。

配准：扫描页 Tesseract 词框与原生词按唯一词匹配，RANSAC 拟合相对坐标仿射；残差(扫描像素)中位数 > 3 px
时标 registration_bad，该页不计 IoU 类指标。

用法：python3 scripts/bench/layout_gt.py <native.pdf> <page> [-o gt.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

_FIG = re.compile(r"^\s*(FIGURE|TABLE|PLATE|F\s?I\s?G\s?U\s?R\s?E)\b", re.I)
_IT = re.compile(r"(ital|obl)", re.I)


def is_italic(span: dict) -> bool:
    return bool(span["flags"] & 2) or bool(_IT.search(span["font"]))


def is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def classify_line(text: str, font: str, size: float, bold: bool, italic: bool, y0: float, y1: float, page_h: float,
                  *, run_in_bold: bool = False) -> tuple[str, int | None]:
    """单行 -> (role, level)。"""
    f = font.lower()
    t = text.strip()
    if "helvetica" in f:
        return "furniture", None
    if re.fullmatch(r"\d{1,4}", t) and (y0 < 50 or y1 > page_h - 40):
        return "furniture", None
    if "dante" in f and size >= 11.5 and size <= 12.5 and y1 < 50 and not bold:
        return "furniture", None  # 页顶 12pt 页码/章名行头
    if _FIG.match(t):
        return "caption", None
    if "dante" in f:
        if size >= 17:
            return "heading", 1
        if re.match(r"^CHAPTER\s+\d+", t):
            return "heading", 1
        if bold and size >= 13:
            return "heading", 2
        if size >= 11.5 and "medium" in f and "italic" not in f:
            return "heading", 3
        if size >= 11.5 and "italic" in f:
            return "heading", 4
        if size <= 9.5:
            return "caption", None
        if run_in_bold:
            return "entry", None
        return "body", None
    if "sourcesans" in f:
        return "ref", None
    if "merriweather" in f:
        return "index", None
    return "figtext", None


def _line_markup(spans: list[dict]) -> tuple[str, list[str]]:
    """一行 spans -> (带 *斜体* 的文字, 斜体词)。"""
    out, itw = [], []
    cur_it = False
    buf = ""

    def flush() -> None:
        if not buf:
            return
        if cur_it and buf.strip():
            lead = buf[: len(buf) - len(buf.lstrip())]
            trail = buf[len(buf.rstrip()):]
            out.append(lead + "*" + buf.strip() + "*" + trail)
        else:
            out.append(buf)

    for sp in spans:
        it = is_italic(sp)
        txt = sp["text"]
        if it and txt.strip():
            itw += re.findall(r"\w[\w'’-]*", txt)
        if it != cur_it:
            flush()
            buf, cur_it = "", it
        buf += txt
    flush()
    return "".join(out), itw


def join_lines(lines: list[str]) -> str:
    """行拼段：行末连字符接小写词则去连字符，否则空格。"""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not out:
            out = ln
        elif re.search(r"[A-Za-z]-$", out) and re.match(r"[a-z*]", ln):
            out = out[:-1] + ln
        else:
            out += " " + ln
    return out


def strip_markup(t: str) -> str:
    return t.replace("*", "")


def _bbox_union(bbs: list[list[float]]) -> list[float]:
    return [min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)]


def reading_order(blocks: list[dict], page_w: float) -> list[dict]:
    """通栏块把页面切成横带；带内先左栏后右栏，栏内自上而下。写入 col 与 order。"""
    mid = page_w / 2
    for b in blocks:
        x0, _, x1, _ = b["bbox_pt"]
        b["col"] = -1 if (x0 < mid - 20 and x1 > mid + 20) else (0 if (x0 + x1) / 2 < mid else 1)
    furn = [b for b in blocks if b["role"] == "furniture"]
    blocks = [b for b in blocks if b["role"] != "furniture"]
    full = sorted([b for b in blocks if b["col"] == -1], key=lambda b: b["bbox_pt"][1])
    cuts = [b["bbox_pt"][1] for b in full]

    def band(b: dict) -> int:
        return sum(1 for c in cuts if b["bbox_pt"][1] > c + 0.5) if b["col"] != -1 else cuts.index(b["bbox_pt"][1]) if b["bbox_pt"][1] in cuts else 0

    for b in blocks:
        b["_band"] = band(b)
    blocks.sort(key=lambda b: (b["_band"], 0 if b["col"] == -1 else 1, max(b["col"], 0), b["bbox_pt"][1], b["bbox_pt"][0]))
    for i, b in enumerate(blocks):
        b["order"] = i
        b.pop("_band", None)
    for b in furn:
        b["order"] = -1  # 页眉页脚不入阅读顺序
    return blocks + furn


def _absorb_entries(blocks: list[dict], page_w: float) -> list[dict]:
    """词条首行（粗体 run-in）吸收其后同栏的 body 行，直到下一个词条/标题/其它角色。"""
    out: list[dict] = []
    mid = page_w / 2
    cur: dict | None = None
    for b in blocks:
        col = 0 if (b["bbs"][0][0] + b["bbs"][0][2]) / 2 < mid else 1
        if b["role"] == "entry":
            cur = b
            cur["_col"] = col
            out.append(b)
        elif b["role"] == "body" and cur is not None and cur["_col"] == col:
            cur["lines"] += b["lines"]
            cur["bbs"] += b["bbs"]
            cur["italic_words"] += b["italic_words"]
        else:
            if b["role"] != "body":
                cur = None
            out.append(b)
    for b in out:
        b.pop("_col", None)
    return out


def native_gt(pdf: str, page_no: int) -> dict[str, Any]:
    import fitz
    d = fitz.open(pdf)
    pg = d[page_no - 1]
    W, H = pg.rect.width, pg.rect.height
    raw = pg.get_text("dict")["blocks"]
    blocks: list[dict] = []
    for b in raw:
        if b["type"] != 0:
            continue
        cur: dict | None = None
        for ln in b["lines"]:
            sp = [s for s in ln["spans"] if s["text"].strip()]
            if not sp:
                continue
            main = max(sp, key=lambda s: len(s["text"]))
            text, itw = _line_markup(ln["spans"])
            first = sp[0]
            role, lvl = classify_line(strip_markup(text), main["font"], main["size"], is_bold(main), is_italic(main),
                                      ln["bbox"][1], ln["bbox"][3], H,
                                      run_in_bold=is_bold(first) and ":" in strip_markup(text)[:50])
            if cur is None or (cur["role"], cur["level"]) != (role, lvl):
                if cur:
                    blocks.append(cur)
                cur = {"role": role, "level": lvl, "lines": [], "bbs": [], "italic_words": []}
            cur["lines"].append(text)
            cur["bbs"].append(list(ln["bbox"]))
            cur["italic_words"] += itw
        if cur:
            blocks.append(cur)
    blocks = _absorb_entries(blocks, W)
    out = []
    for i, b in enumerate(blocks):
        bb = _bbox_union(b["bbs"])
        out.append({"id": f"p{page_no:04d}-b{i:02d}", "role": b["role"], "level": b["level"],
                    "bbox_pt": [round(v, 1) for v in bb],
                    "bbox_rel": [round(bb[0] / W, 5), round(bb[1] / H, 5), round(bb[2] / W, 5), round(bb[3] / H, 5)],
                    "text": join_lines(b["lines"]), "italic_words": b["italic_words"]})
    out = reading_order(out, W)
    return {"native_pdf": pdf, "native_page": page_no, "page_w_pt": W, "page_h_pt": H, "gt_status": "rule",
            "blocks": out}


# ---------------- 配准 ----------------

def _fold(w: str) -> str:
    return re.sub(r"[^a-z]", "", w.lower())


def unique_word_pairs(native: list[tuple[str, float, float]], scan: list[tuple[str, float, float]], minlen: int = 5):
    """两边各出现恰好一次、折叠后长度 >= minlen 的词 -> [(nx, ny, sx, sy)]（均为相对坐标中心点）。"""
    def uniq(ws):
        cnt: dict[str, int] = {}
        for w, *_ in ws:
            k = _fold(w)
            cnt[k] = cnt.get(k, 0) + 1
        return {_fold(w): (x, y) for w, x, y in ws if cnt[_fold(w)] == 1 and len(_fold(w)) >= minlen}
    a, b = uniq(native), uniq(scan)
    return [(a[k][0], a[k][1], b[k][0], b[k][1]) for k in a if k in b]


def fit_affine(pairs: list[tuple[float, float, float, float]], *, iters: int = 300, tol: float = 0.01,
               seed: int = 0) -> tuple[np.ndarray, int] | None:
    """RANSAC 拟合 (nx,ny)->(sx,sy) 仿射（2x3）。返回 (M, 内点数) 或 None。tol 为相对坐标。"""
    if len(pairs) < 6:
        return None
    P = np.array(pairs, float)
    X = np.c_[P[:, 0], P[:, 1], np.ones(len(P))]
    Y = P[:, 2:4]
    rng = np.random.default_rng(seed)
    best: np.ndarray | None = None
    for _ in range(iters):
        idx = rng.choice(len(P), 3, replace=False)
        try:
            M, *_ = np.linalg.lstsq(X[idx], Y[idx], rcond=None)
        except np.linalg.LinAlgError:
            continue
        err = np.linalg.norm(X @ M - Y, axis=1)
        inl = err < tol
        if best is None or inl.sum() > best.sum():
            best = inl
    if best is None or best.sum() < 6:
        return None
    M, *_ = np.linalg.lstsq(X[best], Y[best], rcond=None)
    return M.T, int(best.sum())


def apply_affine(M: np.ndarray, bbox: list[float]) -> list[float]:
    """相对坐标框经仿射 -> 外接框。"""
    x0, y0, x1, y1 = bbox
    pts = np.array([[x0, y0, 1], [x1, y0, 1], [x0, y1, 1], [x1, y1, 1]], float)
    q = pts @ M.T
    return [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]


def registration_quality(M: np.ndarray, pairs: list, scan_w_px: int, tol_px: float = 3.0) -> tuple[float, bool]:
    P = np.array(pairs, float)
    q = (np.c_[P[:, 0], P[:, 1], np.ones(len(P))] @ M.T)
    res = np.linalg.norm(q - P[:, 2:4], axis=1) * scan_w_px
    inl = np.sort(res)[: max(6, int(len(res) * 0.6))]  # 只看内点（最好的 60%）
    med = float(np.median(inl))
    return med, med <= tol_px


def tesseract_words(png: str, lang: str = "eng") -> tuple[list[tuple[str, float, float]], tuple[int, int]]:
    """Tesseract TSV -> ([(词, 相对cx, 相对cy)], (w_px, h_px))。"""
    import subprocess
    from PIL import Image
    w, h = Image.open(png).size
    p = subprocess.run(["tesseract", png, "stdout", "-l", lang, "tsv"], capture_output=True, check=True)
    out = []
    for ln in p.stdout.decode("utf-8", "replace").splitlines()[1:]:
        r = ln.split("\t")
        if len(r) >= 12 and r[0] == "5" and r[11].strip():
            x, y, bw, bh = (float(r[6]), float(r[7]), float(r[8]), float(r[9]))
            out.append((r[11], (x + bw / 2) / w, (y + bh / 2) / h))
    return out, (w, h)


def native_words(pdf: str, page_no: int) -> list[tuple[str, float, float]]:
    import fitz
    pg = fitz.open(pdf)[page_no - 1]
    W, H = pg.rect.width, pg.rect.height
    return [(t[4], (t[0] + t[2]) / 2 / W, (t[1] + t[3]) / 2 / H) for t in pg.get_text("words")]


def project_gt(gt: dict, scan_png: str, *, tol_px: float = 3.0) -> dict:
    """把 GT 块框投影到扫描页；失败时回退为同相对坐标并标 registration_bad。"""
    sw, (w, h) = tesseract_words(scan_png)
    pairs = unique_word_pairs(native_words(gt["native_pdf"], gt["native_page"]), sw)
    fit = fit_affine(pairs)
    reg: dict[str, Any] = {"pairs": len(pairs), "scan_size_px": [w, h]}
    if fit is None:
        reg.update({"status": "registration_bad", "reason": "too few matches"})
        M = np.array([[1, 0, 0], [0, 1, 0]], float)
    else:
        M, ninl = fit
        med, ok = registration_quality(M, pairs, w, tol_px)
        reg.update({"inliers": ninl, "median_residual_px": round(med, 2), "status": "ok" if ok else "registration_bad",
                    "affine": [[round(float(v), 6) for v in r] for r in M]})
    for b in gt["blocks"]:
        b["bbox_scan_rel"] = [round(v, 5) for v in apply_affine(M, b["bbox_rel"])]
    gt["registration"] = reg
    return gt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("page", type=int)
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    gt = native_gt(a.pdf, a.page)
    txt = json.dumps(gt, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    else:
        for b in gt["blocks"]:
            print(b["order"], b["col"], b["role"], b["level"], b["bbox_pt"], b["text"][:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
