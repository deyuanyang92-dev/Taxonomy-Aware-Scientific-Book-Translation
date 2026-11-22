"""抽样让第二个模型（deepseek-flash）核对 aligned.json 的译文：漏译、误译、数字、拉丁名被改。
用法：python3 scripts/vl_proofread.py aligned.json --usage-file U --out report.json [--n 40] [--seed 1]
只抽 body/ref/key/caption 块；结果 verdict: ok|minor|error。"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_engines as E  # noqa: E402

SYS = ("你是分类学翻译核译员。下面是若干 {i, es, zh}：西班牙语原文与中文译文。逐条判断译文：漏译、误译、数字/图号/页码被改、"
       "拉丁学名或作者年份被改、术语明显错。只输出 JSON 数组，每条 {\"i\":编号,\"verdict\":\"ok|minor|error\",\"issue\":\"一句话，ok 则空\"}。"
       "minor=措辞不佳但意思对；error=意思错、漏句或数字/学名错。不要输出其他文字。")


def sample(aligned: dict, n: int, seed: int) -> list[dict]:
    cand = [{"page": p["page"], "role": b["role"], "es": b["text"], "zh": b.get("translation") or ""}
            for p in aligned["pages"] for b in p["blocks"]
            if b["role"] in ("body", "ref", "key", "caption") and len(b["text"]) >= 25]
    random.Random(seed).shuffle(cand)
    return cand[:n]


def parse(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    return json.loads(m.group(0)) if m else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("aligned"), ap.add_argument("--usage-file", required=True), ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=40), ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    items = sample(json.loads(Path(a.aligned).read_text(encoding="utf-8")), a.n, a.seed)
    out: list[dict] = []
    for k in range(0, len(items), 10):
        chunk = items[k:k + 10]
        user = json.dumps([{"i": k + j, "es": c["es"], "zh": c["zh"]} for j, c in enumerate(chunk)], ensure_ascii=False)
        raw, _u = E.call("deepseek-flash", SYS, user, max_tokens=4000, tag="proofread", usage_file=a.usage_file)
        try:
            verd = {v["i"]: v for v in parse(raw)}
        except (ValueError, KeyError, TypeError):
            verd = {}
        for j, c in enumerate(chunk):
            v = verd.get(k + j, {})
            out.append({**c, "verdict": v.get("verdict", "unchecked"), "issue": v.get("issue", "")})
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(dict(Counter(o["verdict"] for o in out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
