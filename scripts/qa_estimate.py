#!/usr/bin/env python3
"""全书质检的运行前估算与默认开启的预算上限（#42）。

按字符数（len(str)，不是 UTF-8 字节）估算：选定页 = 原文、译文两边都有且非空的页。
估算 = 两遍 check（按块调用）+ 复核（每块一次）+ 一遍对齐检测（按页调用）。
常量按 2026-11-19 的 40 页日译英「冷缓存」实测校准（术语表改动使前缀缓存失效；文本量 34,482 token）：
  check  30 次调用，输入量 138,444（缓存读 60%），输出 5,540，billable 62,583
  verify 12 次调用，输入量  43,038（缓存读 88%），输出 4,403，billable 10,310
  align  36 次调用，输入量  55,810（缓存读 87%），输出 1,269，billable  9,412；合计 82,305。
同数据另两次：植入译文那次 77,157（与 cold 同时跑，缓存部分命中）；干净基线热跑 45,010（缓存全命中）。
所以取冷跑作为估算基准：预算上限要的是上界，缓存命中只会让实际更低（热跑约为估算的一半）。
输入量 = 文本 token（按 te.estimate_tokens）× 该阶段读文本的遍数 + 调用次数 × 每次固定开销（系统提示词 + 术语表）。
计费口径与 token_economy.billable 相同：非缓存输入 + 输出 + 缓存读/50。

用法：
  python3 qa_estimate.py src.md tgt.md [-o 工作目录]    # 打印估算；给 -o 时写 qa_estimate.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_translate as at  # noqa: E402
import token_economy as te  # noqa: E402

# 常量取自上面 docstring 的冷跑实测；按阶段分开（三个阶段的缓存命中与输出比相差很大）。
CACHE_SHARE = {"check": 0.60, "verify": 0.88, "align": 0.87}     # 输入量中走缓存读的比例
# 每次调用的固定开销（输入 token）：check = (138,444 − 2×34,482) / 28 个计划调用；
# verify 的文本是整块、固定部分由 3,586–3,872/调用 减去每块文本 2,463 得约 1,200；align = (55,810 − 34,482) / 40 页。
# 开销随术语表大小变化（check 的固定部分里术语表是大头），术语表很大的书应上调。
OVERHEAD_TOKENS_PER_CALL = {"check": 2480, "verify": 1200, "align": 530}
OUT_RATIO = {"check": 0.040, "verify": 0.102, "align": 0.023}    # 输出 / 输入量
DEFAULT_MULTIPLE = 2.0
CACHE_DIVISOR = 50                               # 与 token_economy.billable 同口径


def _stage(in_tokens: float, stage: str) -> tuple[float, float]:
    """返回 (billable_tokens, usd)。in_tokens 是该阶段全部调用的输入量（含缓存读）。"""
    share = CACHE_SHARE[stage]
    cached = in_tokens * share
    fresh = in_tokens - cached
    out = in_tokens * OUT_RATIO[stage]
    billable = fresh + out + cached / CACHE_DIVISOR
    p = at.DS_PRICE
    usd = (fresh * p["in"] + cached * p["cache"] + out * p["out"]) / 1e6
    return billable, usd


def estimate(src_pg: dict[int, str], tgt_pg: dict[int, str], *, passes: int = 2, align: bool = True,
             chunk_pages: int = 3, multiple: float = DEFAULT_MULTIPLE) -> dict[str, Any]:
    both = sorted(p for p in set(src_pg) & set(tgt_pg) if src_pg[p].strip() and tgt_pg[p].strip())
    missing_tgt = sorted(p for p in src_pg if p not in tgt_pg and src_pg[p].strip())
    missing_src = sorted(p for p in tgt_pg if p not in src_pg and tgt_pg[p].strip())
    text_tokens = sum(te.estimate_tokens(src_pg[p]) + te.estimate_tokens(tgt_pg[p]) for p in both)
    chars_src = sum(len(src_pg[p]) for p in both)
    chars_tgt = sum(len(tgt_pg[p]) for p in both)
    chunks = math.ceil(len(both) / chunk_pages) if both else 0
    # 每阶段 (调用次数, 读文本的遍数)：check 每遍都读全文；复核每块一次、读该块全文（上界：实测 12–14 / 14 块）；对齐每页一次
    plan = {"check": (chunks * passes, passes)}
    if chunks * passes:
        plan["verify"] = (chunks, 1)
    if align and both:
        plan["align"] = (len(both), 1)
    stages: dict[str, dict[str, Any]] = {}
    usd = 0.0
    for name, (calls, reads) in plan.items():
        b, u = _stage(reads * text_tokens + calls * OVERHEAD_TOKENS_PER_CALL[name], name)
        stages[name] = {"calls": calls, "billable_tokens": int(b), "usd": round(u, 4)}
        usd += u
    bt = sum(v["billable_tokens"] for v in stages.values())
    return {
        "pages": len(both), "pages_missing_in_tgt": missing_tgt, "pages_missing_in_src": missing_src,
        "chars_src": chars_src, "chars_tgt": chars_tgt,
        "calls": sum(v["calls"] for v in stages.values()), "billable_tokens": bt, "usd": round(usd, 4),
        "stages": stages, "multiple": multiple, "budget_tokens": int(bt * multiple),
    }


def write_estimate(work: Path, est: dict[str, Any]) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    out = work / "qa_estimate.json"
    out.write_text(json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def arm_budget(est: dict[str, Any], *, multiple: float | None = None, override_tokens: int | None = None) -> int:
    """设置进程内预算上限并返回。优先级：override_tokens > multiple × billable_tokens > est['budget_tokens']。"""
    if override_tokens is not None:
        limit = int(override_tokens)
    elif multiple is not None:
        limit = int(est["billable_tokens"] * multiple)
    else:
        limit = int(est["budget_tokens"])
    te.set_budget(limit)
    return limit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="全书质检的运行前估算（按字符）")
    ap.add_argument("src")
    ap.add_argument("tgt")
    ap.add_argument("-o", "--work", default="")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--multiple", type=float, default=DEFAULT_MULTIPLE)
    a = ap.parse_args(argv)
    est = estimate(at.pages(Path(a.src).read_text(encoding="utf-8")),
                   at.pages(Path(a.tgt).read_text(encoding="utf-8")), passes=a.passes, multiple=a.multiple)
    if a.work:
        write_estimate(Path(a.work), est)
    print(json.dumps(est, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
