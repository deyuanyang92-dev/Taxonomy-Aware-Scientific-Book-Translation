#!/usr/bin/env python3
"""版面评测引擎适配器：各引擎输出 -> engine_page.json（相对坐标 0-1）。

engine_page: {"engine","seconds","blocks":[{"bbox_rel","role","level","text","order","italic_words"}]}
role 取 layout_gt 的角色名：heading/body/caption/ref/furniture/figtext。
level 仅在引擎自带层级时给；infer_levels() 按块高给出启发式层级（评测里作为 "+高度" 变体单列）。

用法：
  python3 scripts/bench/layout_adapters.py tesseract <page.png> -o engine_page.json
  python3 scripts/bench/layout_adapters.py paddle-cloud <cloud_layout.json> -o engine_page.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PADDLE_ROLE = {
    "doc_title": ("heading", 1), "paragraph_title": ("heading", None), "text": ("body", None),
    "content": ("body", None), "abstract": ("body", None), "aside_text": ("body", None),
    "figure_title": ("caption", None), "figure_caption": ("caption", None), "table_title": ("caption", None),
    "chart_title": ("caption", None), "caption": ("caption", None),
    "header": ("furniture", None), "footer": ("furniture", None), "number": ("furniture", None),
    "header_image": ("furniture", None), "footer_image": ("furniture", None), "footnote": ("body", None),
    "reference": ("ref", None), "reference_content": ("ref", None),
    "image": ("figtext", None), "chart": ("figtext", None), "table": ("figtext", None), "seal": ("figtext", None),
    "formula": ("body", None), "algorithm": ("body", None), "vision_footnote": ("body", None),
}


def paddle_blocks(layout: dict, *, engine: str = "paddle-cloud-vl") -> dict[str, Any]:
    """云端/本地 PaddleOCR-VL 的 pruned_result.parsing_res_list -> engine_page。"""
    pr = layout.get("pruned_result") or layout
    W = float(layout.get("width_px") or pr.get("width") or 1)
    H = float(layout.get("height_px") or pr.get("height") or 1)
    blocks = []
    for k, b in enumerate(pr.get("parsing_res_list") or []):
        x0, y0, x1, y1 = b["block_bbox"]
        role, lvl = PADDLE_ROLE.get(b.get("block_label", ""), ("body", None))
        o = b.get("block_order")
        blocks.append({"bbox_rel": [x0 / W, y0 / H, x1 / W, y1 / H], "role": role, "level": lvl,
                       "label": b.get("block_label"), "text": b.get("block_content") or "",
                       "order": o if isinstance(o, int) else 10_000 + k, "italic_words": []})
    return {"engine": engine, "blocks": blocks}


def infer_levels(blocks: list[dict], tol: float = 0.15) -> list[dict]:
    """heading 块按高度（每行）聚类，高者层级小。返回新块列表（不改原件）。"""
    out = [dict(b) for b in blocks]
    hs = []
    for b in out:
        if b["role"] == "heading":
            n = max(1, round(len(b.get("text", "")) / max(1, 45 * (b["bbox_rel"][2] - b["bbox_rel"][0]) / 0.4)))
            hs.append((b["bbox_rel"][3] - b["bbox_rel"][1]) / n)
    if not hs:
        return out
    tiers: list[float] = []
    for h in sorted(hs, reverse=True):
        if not tiers or h < tiers[-1] * (1 - tol):
            tiers.append(h)
    i = 0
    for b in out:
        if b["role"] == "heading":
            h = hs[i]
            i += 1
            b["level"] = 1 + min(range(len(tiers)), key=lambda t: abs(tiers[t] - h))
    return out


def tesseract_words_px(png: str, lang: str = "eng") -> tuple[list[dict], int, int]:
    r = subprocess.run(["tesseract", png, "stdout", "-l", lang, "--psm", "3", "tsv"], capture_output=True, check=True)
    rows = list(csv.DictReader(io.StringIO(r.stdout.decode("utf-8", "replace")), delimiter="\t", quoting=csv.QUOTE_NONE))
    W = max((int(x["left"]) + int(x["width"]) for x in rows if x["level"] == "1"), default=1)
    H = max((int(x["top"]) + int(x["height"]) for x in rows if x["level"] == "1"), default=1)
    ws = [x for x in rows if x["level"] == "5" and x["text"].strip() and float(x["conf"]) >= 0]
    return ws, W, H


def fill_text(engine_page: dict, png: str) -> dict:
    """纯版面引擎（只有框）：用 tesseract 词按中心点落入框填文字，框内按行（top 聚类）再按 left 排序。"""
    ws, W, H = tesseract_words_px(png)
    for b in engine_page["blocks"]:
        x0, y0, x1, y1 = (b["bbox_rel"][0] * W, b["bbox_rel"][1] * H, b["bbox_rel"][2] * W, b["bbox_rel"][3] * H)
        inside = [w for w in ws if x0 <= int(w["left"]) + int(w["width"]) / 2 <= x1 and y0 <= int(w["top"]) + int(w["height"]) / 2 <= y1]
        inside.sort(key=lambda w: (round(int(w["top"]) / 12), int(w["left"])))  # 12 px 行带，足够区分 150 dpi 行距
        b["text"] = " ".join(w["text"] for w in inside)
    return engine_page


def tesseract_page(png: str, lang: str = "eng", psm: int = 3) -> dict[str, Any]:
    """tesseract TSV -> 块（block_num 级），标题=行高明显大于页内正文中位数的块。"""
    t = time.time()
    r = subprocess.run(["tesseract", png, "stdout", "-l", lang, "--psm", str(psm), "tsv"], capture_output=True, check=True)
    sec = time.time() - t
    rows = list(csv.DictReader(io.StringIO(r.stdout.decode("utf-8", "replace")), delimiter="\t", quoting=csv.QUOTE_NONE))
    W = max((int(x["left"]) + int(x["width"]) for x in rows if x["level"] == "1"), default=1)
    H = max((int(x["top"]) + int(x["height"]) for x in rows if x["level"] == "1"), default=1)
    by: dict[int, list[dict]] = {}
    for x in rows:
        if x["level"] == "5" and x["text"].strip() and float(x["conf"]) >= 0:
            by.setdefault(int(x["block_num"]), []).append(x)
    info = []
    for bn, ws in sorted(by.items()):
        x0 = min(int(w["left"]) for w in ws)
        y0 = min(int(w["top"]) for w in ws)
        x1 = max(int(w["left"]) + int(w["width"]) for w in ws)
        y1 = max(int(w["top"]) + int(w["height"]) for w in ws)
        lines: dict[tuple, list[str]] = {}
        for w in ws:
            lines.setdefault((w["par_num"], w["line_num"]), []).append(w["text"])
        nl = len(lines)
        info.append({"bn": bn, "bb": [x0, y0, x1, y1], "text": "\n".join(" ".join(v) for v in lines.values()),
                     "lh": (y1 - y0) / nl, "nl": nl})
    body_lh = sorted(i["lh"] for i in info if i["nl"] >= 3) or sorted(i["lh"] for i in info) or [1]
    med = body_lh[len(body_lh) // 2]
    blocks = []
    for k, i in enumerate(info):
        x0, y0, x1, y1 = i["bb"]
        is_h = i["nl"] <= 3 and i["lh"] > 1.3 * med
        furn = (y1 < 0.06 * H or y0 > 0.94 * H) and len(i["text"]) < 40
        role = "furniture" if furn else ("heading" if is_h else "body")
        blocks.append({"bbox_rel": [x0 / W, y0 / H, x1 / W, y1 / H], "role": role, "level": None,
                       "text": i["text"], "order": k, "italic_words": []})
    return {"engine": "tesseract", "seconds": round(sec, 2), "blocks": blocks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engine", choices=["tesseract", "paddle-cloud"])
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--levels", action="store_true", help="加高度启发式层级（引擎名加 +h）")
    a = ap.parse_args(argv)
    if a.engine == "tesseract":
        res = tesseract_page(a.src)
    else:
        j = json.loads(Path(a.src).read_text(encoding="utf-8"))
        res = paddle_blocks(j.get("layout", j))
        res["seconds"] = j.get("seconds")
    if a.levels:
        res["blocks"] = infer_levels(res["blocks"])
        res["engine"] += "+h"
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
