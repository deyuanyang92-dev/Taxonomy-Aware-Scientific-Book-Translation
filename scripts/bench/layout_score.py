#!/usr/bin/env python3
"""版面评测打分（设计 docs/superpowers/specs/2026-11-26-fast-relayout-design.md A.3）。

输入：GT（layout_gt.native_gt/project_gt 的 dict）+ 引擎输出（engine_page.json：
  {"engine","seconds","blocks":[{"bbox_rel":[x0,y0,x1,y1],"role","level","text","order","italic_words"}]}，
  坐标为相对页宽高的 0-1）。
指标：block_recall/precision/f1（文字相似度>=0.5 且 IoU>=0.3 才算配上）、role_macro_f1（粗角色）、
  heading_level_acc（引擎给了 level 的才计，另报 n）、order_tau（配上块的 Kendall tau）、
  col_interleave（相邻阅读序块左右栏交替率）、text_bag_f1（全页字符袋 F1）、cer（全页按阅读序）、
  italic_f1（斜体词）、seconds。

用法：
  python3 scripts/bench/layout_score.py score <gt.json> <engine_page.json>
  python3 scripts/bench/layout_score.py ledger <engine> <set> <metric> <value> <cost> <source>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_score  # noqa: E402

COARSE = {"heading": "heading", "body": "body", "entry": "body", "ref": "body", "index": "body",
          "caption": "caption", "furniture": "furniture", "figtext": "figure", "figure": "figure"}
LEDGER = Path(__file__).resolve().parents[2] / "docs" / "ocr_eval" / "LEDGER.tsv"


def coarse(role: str | None) -> str:
    return COARSE.get(role or "", "body")


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def clean(t: str) -> str:
    return re.sub(r"[\*_]", "", t or "")


def text_sim(a: str, b: str) -> float:
    return ocr_score.bag_f1(ocr_score.norm(clean(a)), ocr_score.norm(clean(b)))


def match_blocks(gt: list[dict], pred: list[dict], *, min_text: float = 0.5, min_iou: float = 0.3) -> list[tuple[int, int]]:
    """最优指派（匈牙利）；只保留文字相似度与 IoU 都达标的对。返回 (gt 下标, pred 下标)。"""
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    if not gt or not pred:
        return []
    S = np.zeros((len(gt), len(pred)))
    for i, g in enumerate(gt):
        for j, p in enumerate(pred):
            u = iou(g["_bb"], p["bbox_rel"])
            t = text_sim(g["text"], p.get("text", ""))
            S[i, j] = (0.5 * u + 0.5 * t) if (u >= min_iou and t >= min_text) else 0.0
    r, c = linear_sum_assignment(-S)
    return [(int(i), int(j)) for i, j in zip(r, c) if S[i, j] > 0]


def inter_area(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def area(a: list[float]) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def overlap_roles(gtb: list[dict], pred: list[dict], thr: float = 0.5) -> dict[str, Any]:
    """粒度无关的角色评分：每个 GT 块取交叠面积最大的预测块（交叠须占 GT 或预测面积 >= thr），
    角色一致算对。GT 按原生 PDF 文本块切，预测按段切，块级配对会因粒度不同被冤枉，故另设此项。
    返回 role_acc（按字数加权）、cover（有预测块覆盖的 GT 块比例）、各角色召回。"""
    tot = ok = cov = 0.0
    per: dict[str, list[int]] = {}
    for g in gtb:
        w = max(1, len(clean(g["text"])))
        best, ba = None, 0.0
        for p in pred:
            a = inter_area(g["_bb"], p["bbox_rel"])
            if a > ba and (a / area(g["_bb"]) >= thr or a / max(area(p["bbox_rel"]), 1e-9) >= thr):
                best, ba = p, a
        hit = best is not None and coarse(best.get("role")) == coarse(g["role"])
        tot += w
        ok += w * hit
        cov += w * (best is not None)
        r = per.setdefault(coarse(g["role"]), [0, 0])
        r[0] += int(hit)
        r[1] += 1
    return {"role_acc": round(ok / tot, 3) if tot else None, "cover": round(cov / tot, 3) if tot else None,
            "role_recall": {k: round(v[0] / v[1], 3) for k, v in per.items()}}


def kendall_tau(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    s = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            s += (x * y > 0) - (x * y < 0)
    return s / (n * (n - 1) / 2)


def col_interleave(pred_ordered: list[dict]) -> float | None:
    """相邻阅读序块在左右栏间来回跳的比例（半栏块才计）；0 最好。"""
    cols = []
    for p in pred_ordered:
        x0, _, x1, _ = p["bbox_rel"]
        if x1 - x0 < 0.6:
            cols.append(0 if (x0 + x1) / 2 < 0.5 else 1)
    if len(cols) < 3:
        return None
    flips = sum(1 for a, b in zip(cols, cols[1:]) if a != b)
    return max(0.0, (flips - 1)) / (len(cols) - 1)  # 理想双栏只翻一次


def _f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0


def italic_f1(gt_words: list[str], pred_words: list[str]) -> float | None:
    if not gt_words:
        return None
    from collections import Counter
    g, p = Counter(w.lower() for w in gt_words), Counter(w.lower() for w in pred_words)
    tp = sum((g & p).values())
    return _f1(tp, sum(p.values()) - tp, sum(g.values()) - tp)


def score_layout(gt: dict, eng: dict) -> dict[str, Any]:
    blocks = [dict(b) for b in gt["blocks"]]
    for b in blocks:
        b["_bb"] = b.get("bbox_scan_rel") or b["bbox_rel"]
    furn = [b for b in blocks if b["role"] == "furniture"]
    gtb = [b for b in blocks if b["role"] != "furniture"]  # 页眉页脚不计块配对（引擎常丢弃）
    pred = [p for p in eng.get("blocks", []) if coarse(p.get("role")) != "furniture"]
    pairs = match_blocks(gtb, pred)
    m = len(pairs)
    rec, prec = (m / len(gtb) if gtb else 0.0), (m / len(pred) if pred else 0.0)
    res: dict[str, Any] = {"engine": eng.get("engine", ""), "gt_blocks": len(gtb), "pred_blocks": len(pred), "matched": m,
                           "block_recall": round(rec, 3), "block_precision": round(prec, 3),
                           "block_f1": round(2 * rec * prec / (rec + prec), 3) if rec + prec else 0.0}
    ov = overlap_roles(gtb, pred)
    res.update({"role_acc": ov["role_acc"], "cover": ov["cover"], "caption_recall": ov["role_recall"].get("caption"),
                "figure_recall": ov["role_recall"].get("figure"), "body_recall": ov["role_recall"].get("body")})
    # 粗角色宏 F1（未配上的 GT 块算该角色 FN，未配上的预测块算其角色 FP）
    mg = {i for i, _ in pairs}
    mp = {j for _, j in pairs}
    f1s = []
    for role in sorted({coarse(b["role"]) for b in gtb} | {coarse(p.get("role")) for p in pred}):
        tp = sum(1 for i, j in pairs if coarse(gtb[i]["role"]) == role and coarse(pred[j].get("role")) == role)
        fn = sum(1 for i, g in enumerate(gtb) if coarse(g["role"]) == role) - tp
        fp = sum(1 for j, p in enumerate(pred) if coarse(p.get("role")) == role) - tp
        f1s.append(_f1(tp, fp, fn))
    res["role_macro_f1"] = round(sum(f1s) / len(f1s), 3) if f1s else 0.0
    # 标题：只按文字配（不要求块框一致，各引擎合并/拆分粒度不同）；找到=最相似预测块文字相似度>=0.6 且角色为标题
    gh = [b for b in gtb if b["role"] == "heading"]
    found, lvl_ok, lvl_n = 0, 0, 0
    for g in gh:
        best, bs = None, 0.0
        for p in pred:
            s = text_sim(g["text"], p.get("text", ""))
            if s > bs:
                best, bs = p, s
        if best is not None and bs >= 0.6 and coarse(best.get("role")) == "heading":
            found += 1
            if best.get("level"):
                lvl_n += 1
                lvl_ok += int(best["level"] == g["level"])
    res["gt_headings"] = len(gh)
    res["headings_found"] = found
    res["heading_recall"] = round(found / len(gh), 3) if gh else None
    res["heading_level_n"] = lvl_n
    res["heading_level_acc"] = round(lvl_ok / lvl_n, 3) if lvl_n else None  # 仅在已找到且引擎给了层级的标题上
    res["heading_level_strict"] = round(lvl_ok / len(gh), 3) if gh else None  # 漏找/无层级都算错
    # 阅读序
    po = [p for p in sorted(pred, key=lambda p: p.get("order", 0))]
    tau = kendall_tau([gtb[i]["order"] for i, _ in pairs], [pred[j].get("order", j) for _, j in pairs])
    res["order_tau"] = round(tau, 3) if tau is not None else None
    ci = col_interleave(po)
    res["col_interleave"] = round(ci, 3) if ci is not None else None
    # 全页文字
    gtxt = "\n".join(clean(b["text"]) for b in sorted(gtb, key=lambda b: b["order"]))
    ptxt = "\n".join(clean(p.get("text", "")) for p in po)
    sp = ocr_score.score_page(gtxt, ptxt)
    res["cer"] = round(sp["cer_norm"], 3)
    res["bag_f1"] = round(1 - sp["bag_err"], 3)
    gi = [w for b in gtb for w in b.get("italic_words", [])]
    pi = [w for p in pred for w in (p.get("italic_words") or re.findall(r"\*([^*]+)\*", p.get("text", "")) and
                                    [x for s in re.findall(r"\*([^*]+)\*", p.get("text", "")) for x in s.split()])]
    f = italic_f1(gi, pi)
    res["italic_f1"] = round(f, 3) if f is not None else None
    res["seconds"] = eng.get("seconds")
    res["furniture_gt"] = len(furn)
    res["registration"] = (gt.get("registration") or {}).get("status", "none")
    return res


def append_ledger(engine: str, set_: str, metric: str, value: Any, cost: Any, source: str, date: str, path: Path = LEDGER) -> None:
    line = "\t".join([date, engine, set_, metric, str(value), str(cost), source]) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def main(argv: list[str]) -> int:
    if argv[:1] == ["score"] and len(argv) == 3:
        gt = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        eng = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(score_layout(gt, eng), ensure_ascii=False, indent=1))
        return 0
    if argv[:1] == ["ledger"] and len(argv) == 7:
        import datetime
        append_ledger(*argv[1:7], date=datetime.date.today().isoformat())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
