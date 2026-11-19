#!/usr/bin/env python3
"""人工复核队列闸口：把 auto_translate.py 产出的 human_review_queue.csv 中「编辑已认可」的行落实进最终译文。
用法: python3 apply_review_queue.py <译文.md> <队列.csv|.jsonl> [--src 原文.md --sl bg --tl en] [--dry] [--log 审计.jsonl]
队列列: pdf_page, old, new, reason（沿用 human_review_queue.csv）+ 编辑填写的 decision（accept/reject，空=待定）、
  rationale（accept 必填）、allow（可选，分号分隔白名单：numbers; names; refs; citations）。
闸口（同 apply_issues.py 的思路，且按页限定）:
  - 只处理 decision=accept；reject、待定行只计数不动文本；accept 没有 rationale 一律拒绝。
  - old 必须在所述 PDF 页内恰好出现 1 次（匹配 0 或多次均拒绝）；old 与 new 不得含 <!-- 页标记 -->。
  - 数字、斜体学名、图/表/版引用、引文（作者+年份）在 old 与 new 中必须一致，除非 allow 明确列出该类。
  - 幂等：已落实的行（new 已在页内而 old 不在，或加性改动）跳过。
  - 写回前对改动后的全文重跑 transqa（需 --src）；出现新的 critical/major 则整批不写回，退出码 1。
  - 审计日志 <译文>.review_apply.jsonl 每行一条（applied/skipped/rejected/pending/bad），含 rationale。
有拒绝行或 QA 新增阻断时退出码 1。"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from apply_issues import ITALIC, already_applied  # noqa: E402
from transqa.core import numbers  # noqa: E402

from transqa import check_all as _check_all  # noqa: E402

PAGE_LINE = re.compile(r"^<!-- PDF p\.(\d+)\b.*$", re.M)
FIG_REF = re.compile(r"\b(?:Figs?|Tabs?|Pls?|Plates?|Tables?|Figuras?|Fig\.|Lám|Taf|Abb|Рис|Табл)\.?\s*\d+[a-zA-Z]?"
                     r"(?:\s*[-–,]\s*\d+[a-zA-Z]?)*", re.I)
CITATION = re.compile(r"[A-ZÀ-Ý][\w'’\-]+(?:\s+(?:et al\.|&|and|y|und)\s*[A-ZÀ-Ý]?[\w'’\-]*)?,?\s*\(?\d{4}[a-z]?\)?")
FACT_CLASSES = ("numbers", "names", "refs", "citations")


@dataclass
class Result:
    ok: int = 0
    rejected: int = 0
    pending: int = 0
    bad: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    qa_new: list[str] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)


def page_spans(text: str) -> dict[int, tuple[int, int]]:
    ms = list(PAGE_LINE.finditer(text))
    return {int(m.group(1)): (m.start(), ms[i + 1].start() if i + 1 < len(ms) else len(text)) for i, m in enumerate(ms)}


def facts(t: str) -> dict[str, Counter[str]]:
    return {"numbers": Counter(numbers(t)), "names": Counter(ITALIC.findall(t)),
            "refs": Counter(re.sub(r"\s+", " ", m.group(0).lower()) for m in FIG_REF.finditer(t)),
            "citations": Counter(re.sub(r"\s+", " ", m.group(0)) for m in CITATION.finditer(t))}


def changed_facts(old: str, new: str) -> list[str]:
    fo, fn = facts(old), facts(new)
    return [c for c in FACT_CLASSES if fo[c] != fn[c]]


def read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".jsonl", ".json"):
        return [{k: "" if v is None else str(v) for k, v in json.loads(x).items()}
                for x in path.read_text(encoding="utf8").splitlines() if x.strip()]
    with path.open(newline="", encoding="utf8") as f:
        return list(csv.DictReader(f, delimiter="\t" if path.suffix.lower() == ".tsv" else ","))


def _blocking(src_md: str, tgt: str, sl: str, tl: str) -> list[str]:
    return [str(i.message) for i in _check_all(src_md, tgt, sl, tl) if i.blocking]


def apply(target: pathlib.Path, queue: pathlib.Path, *, src: pathlib.Path | None = None, sl: str = "und",
          tl: str = "en", dry: bool = False, log: pathlib.Path | None = None) -> Result:
    res = Result()
    text = target.read_text(encoding="utf8")
    cur = text
    for ln, r in enumerate(read_rows(queue), 2):
        dec = (r.get("decision") or "").strip().lower()
        old, new = r.get("old") or "", r.get("new") or ""
        rec: dict[str, Any] = {"row": ln, "pdf_page": r.get("pdf_page"), "decision": dec, "old": old[:80], "new": new[:80],
                               "rationale": r.get("rationale", ""), "time": datetime.datetime.now().isoformat(timespec="seconds")}

        def bad(msg: str, rec: dict[str, Any] = rec, ln: int = ln) -> None:
            res.bad.append((ln, msg))
            rec.update(status="bad", why=msg)
            res.log.append(rec)

        if dec in ("", "pending"):
            res.pending += 1
            res.log.append({**rec, "status": "pending"})
            continue
        if dec == "reject":
            res.rejected += 1
            res.log.append({**rec, "status": "rejected"})
            continue
        if dec != "accept":
            bad(f"decision 只能是 accept/reject：{dec!r}")
            continue
        if not (r.get("rationale") or "").strip():
            bad("accept 必须写 rationale")
            continue
        try:
            page = int(str(r.get("pdf_page")).strip())
        except ValueError:
            bad(f"pdf_page 无效：{r.get('pdf_page')!r}")
            continue
        spans = page_spans(cur)
        if page not in spans:
            bad(f"页 {page} 不在译文中")
            continue
        a, b = spans[page]
        ptxt = cur[a:b]
        if old == new:
            bad("新旧相同")
            continue
        if "<!--" in old or "<!--" in new:
            bad("old/new 不得含页标记或注释 <!-- -->")
            continue
        if already_applied(ptxt, old, new):
            res.skipped.append((ln, f"已应用，跳过：{new[:40]}"))
            res.log.append({**rec, "status": "skipped"})
            continue
        n = ptxt.count(old)
        if n != 1:
            bad(f"PDF 第 {page} 页匹配 {n} 次：{old[:40]}")
            continue
        allow = {x.strip() for x in re.split(r"[;,；]", r.get("allow") or "") if x.strip()}
        lost = [c for c in changed_facts(old, new) if c not in allow]
        if lost:
            bad(f"改动了事实类内容 {lost}（需 allow 白名单明确列出）")
            continue
        cur = cur[:a] + ptxt.replace(old, new, 1) + cur[b:]
        res.ok += 1
        res.log.append({**rec, "status": "applied", "allow": sorted(allow)})
    if res.ok and src is not None:
        s = src.read_text(encoding="utf8")
        before = set(_blocking(s, text, sl, tl))
        res.qa_new = [m for m in _blocking(s, cur, sl, tl) if m not in before]
        if res.qa_new:
            res.ok = 0
            cur = text
            for x in res.log:
                if x["status"] == "applied":
                    x["status"] = "bad"
                    x["why"] = "QA 新增阻断，整批未写回"
    if not dry:
        if cur != text:
            target.write_text(cur, encoding="utf8")
        lp = log or pathlib.Path(str(target) + ".review_apply.jsonl")
        with lp.open("a", encoding="utf8") as w:
            for x in res.log:
                w.write(json.dumps(x, ensure_ascii=False) + "\n")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("queue")
    ap.add_argument("--src", help="原文 md；给了就在写回前后各跑一次 transqa，新增阻断则不写回")
    ap.add_argument("--sl", default="und")
    ap.add_argument("--tl", default="en")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    res = apply(pathlib.Path(a.target), pathlib.Path(a.queue), src=pathlib.Path(a.src) if a.src else None,
                sl=a.sl, tl=a.tl, dry=a.dry, log=pathlib.Path(a.log) if a.log else None)
    print(f"应用 {res.ok}，拒绝(decision) {res.rejected}，待定 {res.pending}，闸口拒绝 {len(res.bad)}，"
          f"已应用跳过 {len(res.skipped)}" + (" (dry)" if a.dry else ""))
    for ln, m in res.bad:
        print(f"  行{ln}: {m}")
    for m in res.qa_new:
        print(f"  QA 新增阻断: {m}")
    return 1 if (res.bad or res.qa_new) else 0


if __name__ == "__main__":
    sys.exit(main())
