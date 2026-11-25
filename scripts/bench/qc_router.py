"""纯 CPU 在线质检特征 + 路由 + 金标校准（日文 Imajima 评测集）。

用法：python scripts/bench/qc_router.py [--tags ppocrv6_medium_200,ppocrv5_server_200_raw]
读：test-ocr/runs/<tag>/cache/*/*/pNNNN.json（行框+文本+置信度）、metrics.json（金标指标）、原 PDF（内存渲染 200dpi）。
写：test-ocr/runs/qc_audit/<tag>/qc_per_page.csv 与 test-ocr/runs/qc_audit/<tag>.md（精简报告）。
只用 numpy/cv2/PyMuPDF，不占 GPU，不打印 OCR 原文（局部 diff 仅在 --diff 时写入文件）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import cv2
import fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TO = ROOT / "test-ocr"
IMJ = Path("/mnt/p/翻译-译作/日本-imajima")
PDF = {2001: IMJ / "Imajima 2001（环形动物 多毛类 II）无标本信息.pdf",
       2007: IMJ / "Imajima 2007（环形动物 多毛类 III）无标本信息.pdf",
       2009: IMJ / "Imajima 2009（环动形物 多毛类 I）无标本信息.pdf"}
DPI = 200
DIAC = set("áéíóúñüöäßàèâêôçÁÉÍÓÚÑÜÖÄ")


# ---------- 适配层：各引擎 → 统一 rows[(poly4, text, conf)] ----------
def load_ppocr(tag: str, vol: int, page: int):
    fs = list((TO / "runs" / tag / "cache").glob(f"*/*/p{page:04d}.json"))
    # cache 目录以 PDF 路径哈希区分卷；用宽度+卷无法区分时，按 PDF 页数试配
    for f in fs:
        d = json.loads(f.read_text(encoding="utf-8"))
        if f.parent.parent.name == _vol_hash(tag).get(vol):
            return [(np.array(r[0], float), r[1], float(r[2])) for r in d["rows"]], d["width"]
    return None, None


_HASH: dict[str, dict[int, str]] = {}


def _vol_hash(tag: str) -> dict[int, str]:
    """cache 子目录哈希→卷：用每卷独有页号集合（manifest 里的页）判定。"""
    if tag in _HASH:
        return _HASH[tag]
    man = list(csv.DictReader(open(TO / "manifest.csv", encoding="utf-8")))
    pages: dict[int, set[int]] = {}
    for m in man:
        pages.setdefault(int(m["vol"]), set()).add(int(m["page"]))
    out: dict[int, str] = {}
    for h in (TO / "runs" / tag / "cache").iterdir():
        have = {int(p.stem[1:]) for p in h.glob("*/p*.json")}
        for v, ps in pages.items():
            if have == ps:
                out[v] = h.name
    _HASH[tag] = out
    return out


# ---------- 5 维特征 ----------
def conf_feats(rows):
    c = np.array([r[2] for r in rows]) if rows else np.array([0.0])
    n = np.array([max(len(r[1]), 1) for r in rows]) if rows else np.array([1])
    return dict(
        n_lines=len(rows), conf_mean=c.mean(), conf_charw=float((c * n).sum() / n.sum()),
        conf_p10=float(np.percentile(c, 10)), conf_p05=float(np.percentile(c, 5)), conf_min=float(c.min()),
        low_conf_line_ratio=float((c < 0.85).mean()), very_low_line_ratio=float((c < 0.75).mean()))


def render_gray(vol: int, page: int):
    doc = fitz.open(PDF[vol])
    pix = doc[page - 1].get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    doc.close()
    return img


def missed_ink(img, rows, pad=4):
    """未落入任何 OCR 框的「文字尺度」墨水像素 / 版心总文字墨水像素。"""
    h, w = img.shape
    bw = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 15)
    m = int(0.03 * min(h, w))  # 页边黑边
    bw[:m] = 0; bw[-m:] = 0; bw[:, :m] = 0; bw[:, -m:] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    # 文字尺度：高宽均在 [4, 120] px(200dpi≈0.5–15mm)；滤噪点、长线框、大插图块
    keep = np.zeros(n, bool)
    cw, ch, ca = st[:, 2], st[:, 3], st[:, 4]
    keep[1:] = (ca[1:] >= 12) & (cw[1:] <= 120) & (ch[1:] <= 120) & (np.maximum(cw[1:], ch[1:]) >= 4)
    ink = keep[lab]
    cover = np.zeros((h, w), np.uint8)
    for poly, _t, _c in rows:
        cv2.fillPoly(cover, [poly.astype(np.int32)], 1)
    cover = cv2.dilate(cover, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    tot = int(ink.sum())
    return float((ink & (cover == 0)).sum() / tot) if tot else 0.0, tot


def geom(rows):
    bb = []
    for p, t, _c in rows:
        x0, y0 = p[:, 0].min(), p[:, 1].min()
        x1, y1 = p[:, 0].max(), p[:, 1].max()
        bb.append((x0, y0, x1, y1, t))
    return bb


def order_and_vertical(bb, width):
    jumps = alt = overlap = 0
    for a, b in zip(bb, bb[1:]):
        hh = max(a[3] - a[1], 1)
        if b[1] < a[1] - 2 * hh:  # 上跳
            # 合法换栏：新行在右/左半页另一侧
            if abs(b[0] - a[0]) < 0.25 * width:
                jumps += 1
        ix = min(a[2], b[2]) - max(a[0], b[0])
        iy = min(a[3], b[3]) - max(a[1], b[1])
        if ix > 0 and iy > 0.6 * min(a[3] - a[1], b[3] - b[1]):
            overlap += 1
    side = [0 if (b[0] + b[2]) / 2 < width / 2 else 1 for b in bb]
    alt = sum(1 for s, t in zip(side, side[1:]) if s != t)
    n = max(len(bb) - 1, 1)
    tall = np.mean([(b[3] - b[1]) / max(b[2] - b[0], 1) > 1.8 for b in bb]) if bb else 0
    short = np.mean([len(b[4].strip()) <= 2 for b in bb]) if bb else 0
    return dict(back_jump_ratio=jumps / n, col_alt_ratio=alt / n, overlap_ratio=overlap / n,
                tall_box_ratio=float(tall), short2_ratio=float(short))


def indent_feats(bb, width):
    x0 = np.array([b[0] for b in bb]) if bb else np.array([0.0])
    xs = np.sort(x0)
    # 间距 > 1.5% 页宽 即新档；统计含 >=3 行的档
    cl, cur = [], [xs[0]]
    for v in xs[1:]:
        if v - cur[-1] > 0.015 * width:
            cl.append(cur); cur = [v]
        else:
            cur.append(v)
    cl.append(cur)
    big = [c for c in cl if len(c) >= 3]
    lead = np.mean([bool(re.match(r"^\s*([0-9]+[.．]|[0-9]+[a-z]|[—―－ー・·])", b[4])) for b in bb]) if bb else 0
    return dict(indent_levels=len(big), lead_marker_ratio=float(lead))


def char_feats(rows):
    txt = "".join(r[1] for r in rows) or " "
    weird = sum(1 for ch in txt if unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cn") or ch == "�")
    weird += len(re.findall(r"[^\w\s]{4,}", txt))
    words = re.findall(r"[A-Za-z0-9]+", txt)
    mixed = sum(1 for w in words if re.search(r"[A-Za-z]", w) and re.search(r"\d", w) and len(w) >= 3)
    lines = [r[1].strip() for r in rows]
    frag = np.mean([len(t) <= 3 and not re.fullmatch(r"[0-9]+|[0-9]+[a-z]?[.．]?", t) for t in lines]) if lines else 0
    return dict(weird_char_ratio=weird / len(txt), short_frag_ratio=float(frag),
                mixed_alnum_anomaly=mixed / max(len(words), 1),
                diacritic_density=sum(ch in DIAC for ch in txt) / len(txt))


# ---------- 路由 ----------
THR = dict(p10=0.85, low_ratio=0.15, missed=0.12, tall=0.15, back=0.10, frag=0.30, very_low=0.05)


def route(f, thr=THR):
    esc, patch = [], []
    if f["conf_p10"] < thr["p10"]: esc.append("conf_p10")
    if f["low_conf_line_ratio"] > thr["low_ratio"]: esc.append("low_ratio")
    if f["missed_ink_ratio"] > thr["missed"]: esc.append("FLAG_MISSED_TEXT")
    if f["tall_box_ratio"] > thr["tall"]: esc.append("FLAG_VERTICAL_MISMATCH")
    if f["back_jump_ratio"] > thr["back"]: esc.append("FLAG_ORDER_SUSPECT")
    if f["short_frag_ratio"] > thr["frag"]: esc.append("short_frag")
    if f["very_low_line_ratio"] > 0 and not esc: patch.append("very_low_lines")
    if f["indent_levels"] >= 3 and f["lead_marker_ratio"] > 0.1: patch.append("FLAG_INDENT_KEY")
    act = "ESCALATE_PAGE" if esc else ("PATCH_BLOCK" if patch else "PASS")
    return act, esc + patch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default="ppocrv6_medium_200,ppocrv5_server_200_raw,ppocrv5_mobile_200")
    a = ap.parse_args()
    man = list(csv.DictReader(open(TO / "manifest.csv", encoding="utf-8")))
    img_cache: dict[tuple, np.ndarray] = {}
    for tag in a.tags.split(","):
        met = json.loads((TO / "runs" / tag / "metrics.json").read_text())["pages"]
        out = TO / "runs/qc_audit" / tag
        out.mkdir(parents=True, exist_ok=True)
        recs = []
        for m in man:
            key = m["id"]
            if key not in met:
                key = f'{m["id"]}__{m["set"]}'
            if key not in met:
                continue
            vol, page = int(m["vol"]), int(m["page"])
            rows, width = load_ppocr(tag, vol, page)
            if rows is None:
                print("缺缓存", tag, key); continue
            k = (vol, page)
            if k not in img_cache:
                img_cache.clear(); img_cache[k] = render_gray(vol, page)  # 用完即释放上一页
            img = img_cache[k]
            assert img.shape[1] == width, (key, img.shape, width)
            bb = geom(rows)
            f = {"page_id": key, "set": m["set"], "page_type": m["type"], "gold_source": m["gold_source"]}
            f.update(conf_feats(rows))
            f["missed_ink_ratio"], f["ink_px"] = missed_ink(img, rows)
            f.update(order_and_vertical(bb, width)); f.update(indent_feats(bb, width)); f.update(char_feats(rows))
            f["route_action"], rs = route(f)
            f["reasons"] = "|".join(rs)
            g = met[key]
            f.update(cer=g["cer_norm"], order_gap=g["order_gap"], len_ratio=g["len_ratio"], n_gold=g["n_gold"])
            recs.append(f)
        if not recs:
            continue
        cols = list(recs[0])
        with open(out / "qc_per_page.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, cols); w.writeheader(); w.writerows(
                {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in recs)
        print(tag, len(recs), "页 →", out / "qc_per_page.csv")


if __name__ == "__main__":
    sys.exit(main())
