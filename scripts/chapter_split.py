#!/usr/bin/env python3
"""章节感知切分与按章报告（issue #2）。

流程（全部确定性，不调模型）：
  1. detect   从 PDF 书签 → 印刷目录页 → 页首标题行 三路探测章边界，写可审阅的计划 chapter_plan.json
  2. preview  打印计划（章、起止页、来源、置信度）；人工改 JSON 里的 start/end/title，设 "confirmed": true
  3. split    按计划把页标记 Markdown 切成 chapters/<NN-slug>/src.md（页标记、图表/图注、参考文献原样保留，
              章与章按页首尾相接，拼回等于原文）
  4. report   各章译完后（translate_corpus.py --chapters 或 fast_book chapters），汇总每章报告
              chapters/<id>/chapter_report.md 与全书问题表 chapter_issues.csv / book_issues.md：
              每条问题带 章、源 PDF 页、段 ID；缺页/失败块/critical 人审项在章与书两级都列出
  5. assemble 把审过的章按计划序拼成 book_assembled.md，并生成目录（contents list）；DOCX/PDF 排版交给
              booklayout（对齐 JSON → DOCX/PDF），本脚本只产带目录的合并 Markdown

用法：
  python3 scripts/chapter_split.py detect  SRC.md [--pdf BOOK.pdf] [--level 1] -o chapter_plan.json
  python3 scripts/chapter_split.py preview chapter_plan.json
  python3 scripts/chapter_split.py split   SRC.md chapter_plan.json -o WORK/chapters
  python3 scripts/chapter_split.py report  WORK chapter_plan.json
  python3 scripts/chapter_split.py assemble WORK chapter_plan.json -o book_assembled.md

计划不确定（来源仅为标题行/单章回退、或目录页偏移无法验证）时 needs_review=true；translate_corpus.py
--chapters 遇到 needs_review 且未 confirmed 会停下，让人先改计划。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

PAGE_RE = re.compile(r"^\s*<!--\s*PDF p\.(\d+)\b")
HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:CHAPTER|Chapter|KAPITEL|Kapitel|CAPÍTULO|Capítulo|CAPITULO|Chapitre|CHAPITRE|Caput|CAPUT|Глава|ГЛАВА"
    r"|第\s*[0-9一二三四五六七八九十百]+\s*章)\s*[0-9IVXLC一二三四五六七八九十百]*[.:：\s]?.*$")
# 目录行：标题 + 点线/空白 + 页码
TOC_LINE_RE = re.compile(r"^\s*(?P<title>[^\d\s][^\n]*?[A-Za-z一-鿿][^\n]*?)\s*(?:\.{2,}|·{2,}|\s{2,}|\s)\s*(?P<page>\d{1,4})\s*$")
ROMAN_RE = re.compile(r"^[ivxlc]+$", re.I)


# ------------------------------------------------------------------ 页
def md_pages(text: str) -> dict[int, str]:
    """{pdf_page: 含页标记行的文本}；首个标记前的前言并入第 0 页。"""
    out: dict[int, list[str]] = {}
    cur = 0
    for ln in text.split("\n"):
        m = PAGE_RE.match(ln)
        if m:
            cur = int(m.group(1))
            out.setdefault(cur, [])
        out.setdefault(cur, []).append(ln)
    return {p: "\n".join(v) for p, v in out.items() if p or any(x.strip() for x in v)}


def _slug(s: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "-", s, flags=re.U).strip("-").lower()
    return (s or "chapter")[:40]


# ------------------------------------------------------------------ 探测
def bookmarks_from_pdf(pdf: Path, level: int = 1) -> list[tuple[str, int]]:
    """PDF 书签（fitz get_toc），取指定层级；返回 [(标题, pdf 页)]。"""
    import fitz  # type: ignore[import-untyped]
    doc = fitz.open(str(pdf))
    try:
        return [(t.strip(), int(p)) for lv, t, p in doc.get_toc() if lv == level and p >= 1]
    finally:
        doc.close()


def contents_from_pages(pages: dict[int, str], scan: int = 30) -> list[tuple[str, int]]:
    """在前 scan 页里解析印刷目录：连续 >=3 行「标题 ...... 页码」的那页/相邻页视为目录。返回 [(标题, 印刷页码)]。"""
    best: list[tuple[str, int]] = []
    for p in sorted(pages)[:scan]:
        rows: list[tuple[str, int]] = []
        for ln in pages[p].split("\n"):
            m = TOC_LINE_RE.match(ln)
            if m and not ROMAN_RE.match(m["page"]) and not PAGE_RE.match(ln):
                rows.append((m["title"].strip(" .·"), int(m["page"])))
        if len(rows) >= 3:
            if best and rows and rows[0][1] >= best[-1][1]:
                best += rows                         # 目录跨页：页码单调延续
            elif not best:
                best = rows
    # 去掉页码回退（正文引用等噪声）
    out: list[tuple[str, int]] = []
    for t, n in best:
        if not out or n >= out[-1][1]:
            out.append((t, n))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", s, flags=re.U).lower()


def toc_offset(entries: list[tuple[str, int]], pages: dict[int, str]) -> tuple[int, float]:
    """印刷页码 → PDF 页的偏移：对每条目在 printed+offset 页首 12 行找标题，取众数。返回 (偏移, 验证比例)。"""
    from collections import Counter
    votes: Counter[int] = Counter()
    for title, printed in entries:
        key = _norm(title)[:24]
        if len(key) < 4:
            continue
        for p, txt in pages.items():
            head = _norm("\n".join(txt.split("\n")[1:13]))
            if key in head and p >= printed:
                votes[p - printed] += 1
    if not votes:
        return 0, 0.0
    off, n = votes.most_common(1)[0]
    return off, n / max(1, len(entries))


def headings_from_pages(pages: dict[int, str]) -> list[tuple[str, int]]:
    out = []
    for p in sorted(pages):
        for ln in pages[p].split("\n")[1:8]:             # 页首几行
            if HEADING_RE.match(ln):
                out.append((ln.strip(" #"), p))
                break
    return out


def _chapters(entries: list[tuple[str, int]], first: int, last: int, source: str,
              confidence: str) -> list[dict[str, Any]]:
    ents = sorted({p: t for t, p in entries}.items())          # 同页多条只留一条
    if not ents:
        return []
    chs: list[dict[str, Any]] = []
    starts = [(p, t) for p, t in ents]
    if starts[0][0] > first:                                    # 前言/封面并入「front」章
        starts.insert(0, (first, "Front matter"))
    for i, (p, t) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else last
        chs.append({"id": f"{i + 1:02d}-{_slug(t)}", "title": t, "start": p, "end": end,
                    "source": source if t != "Front matter" else "inferred", "confidence": confidence})
    return chs


def build_plan(src: Path, pdf: Path | None = None, level: int = 1) -> dict[str, Any]:
    """探测顺序：书签 → 印刷目录 → 页首标题行 → 单章回退。不确定则 needs_review=true。"""
    pages = md_pages(Path(src).read_text(encoding="utf-8"))
    nums = sorted(p for p in pages if p)
    if not nums:
        raise ValueError(f"{src} 没有 <!-- PDF p.N --> 页标记")
    first, last = nums[0], nums[-1]
    notes: list[str] = []
    chs: list[dict[str, Any]] = []
    if pdf is not None:
        try:
            bm = [(t, p) for t, p in bookmarks_from_pdf(pdf, level) if first <= p <= last]
        except Exception as exc:  # noqa: BLE001
            bm = []
            notes.append(f"书签读取失败：{exc}")
        if len(bm) >= 2:
            chs = _chapters(bm, first, last, "bookmarks", "high")
    if not chs:
        toc = contents_from_pages(pages)
        if len(toc) >= 3:
            off, frac = toc_offset(toc, pages)
            notes.append(f"目录 {len(toc)} 条，页码偏移 {off:+d}，标题验证比例 {frac:.0%}")
            ents = [(t, n + off) for t, n in toc if first <= n + off <= last]
            if len(ents) >= 2:
                chs = _chapters(ents, first, last, "contents", "high" if frac >= 0.6 else "low")
    if not chs:
        hd = headings_from_pages(pages)
        if len(hd) >= 2:
            chs = _chapters(hd, first, last, "headings", "low")
            notes.append("仅按页首标题行探测，需人工确认")
    if not chs:
        chs = [{"id": "01-book", "title": "Whole book", "start": first, "end": last,
                "source": "single", "confidence": "low"}]
        notes.append("未探测到章边界，回退为单章")
    needs = any(c["confidence"] == "low" for c in chs)
    plan = {"source": str(src), "first_page": first, "last_page": last, "chapters": chs,
            "needs_review": needs, "confirmed": False, "notes": notes}
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    """章必须按页序首尾相接、不重叠、覆盖 first..last。"""
    chs = plan["chapters"]
    if not chs:
        raise ValueError("计划没有章")
    ids = [c["id"] for c in chs]
    if len(set(ids)) != len(ids):
        raise ValueError("章 id 重复")
    exp = plan["first_page"]
    for c in chs:
        if c["start"] != exp or c["end"] < c["start"]:
            raise ValueError(f"章 {c['id']} 页范围 {c['start']}-{c['end']} 与前章不衔接（应从 {exp} 起）")
        exp = c["end"] + 1
    if exp - 1 != plan["last_page"]:
        raise ValueError(f"计划只覆盖到 p.{exp - 1}，原文到 p.{plan['last_page']}")


def load_plan(p: Path) -> dict[str, Any]:
    plan = json.loads(Path(p).read_text(encoding="utf-8"))
    validate_plan(plan)
    return plan


def save_plan(plan: dict[str, Any], p: Path) -> None:
    Path(p).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def preview(plan: dict[str, Any]) -> str:
    lines = [f"{c['id']}\tp.{c['start']}-{c['end']}\t{c['source']}/{c['confidence']}\t{c['title']}"
             for c in plan["chapters"]]
    lines.append(f"needs_review={plan['needs_review']} confirmed={plan.get('confirmed')} "
                 + "; ".join(plan.get("notes", [])))
    return "\n".join(lines)


# ------------------------------------------------------------------ 切分
def split_md(src: Path, plan: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """写 outdir/<id>/src.md；页文本逐字原样（含页标记、图表、图注、参考文献）。返回 {id: 路径}。"""
    validate_plan(plan)
    pages = md_pages(Path(src).read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for i, c in enumerate(plan["chapters"]):
        keep = [p for p in sorted(pages) if c["start"] <= p <= c["end"] or (i == 0 and p == 0)]
        body = "".join(pages[p].rstrip("\n") + "\n" for p in keep)
        f = Path(outdir) / c["id"] / "src.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
        out[c["id"]] = f
    return out


# ------------------------------------------------------------------ 报告
def _segment_of(checked: str, page: int, needle: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from transqa.segments import segments_from_pages
    if not needle:
        return ""
    for s in segments_from_pages(checked):
        if s.page == page and needle[:60] in s.text:
            return s.id
    return ""


def chapter_issues(work: Path, ch: dict[str, Any]) -> dict[str, Any]:
    """汇总一章：缺页、失败块、critical 人审项、qa 阻断问题；每条带章/页/段 ID。"""
    d = Path(work) / "chapters" / ch["id"]
    src = d / "src.md"
    checked_p = d / "checked.md"
    rows: list[dict[str, Any]] = []
    src_pages = sorted(p for p in md_pages(src.read_text(encoding="utf-8")) if p) if src.exists() else []
    checked = checked_p.read_text(encoding="utf-8") if checked_p.exists() else ""
    have = sorted(p for p in md_pages(checked) if p) if checked else []
    status = "done" if checked and (d / "report.md").exists() else ("missing" if not checked else "partial")

    def add(kind: str, sev: str, page: Any, seg: str, msg: str) -> None:
        rows.append({"chapter": ch["id"], "kind": kind, "severity": sev, "pdf_page": page,
                     "segment": seg, "message": msg})

    for p in sorted(set(src_pages) - set(have)):
        add("missing_page", "critical", p, "", f"译文缺 PDF p.{p}")
    f = d / "check_failed.json"
    if f.exists():
        for m in json.loads(f.read_text(encoding="utf-8")):
            add("failed_segment", "major", "", "", str(m))
    q = d / "human_review_queue.csv"
    if q.exists():
        with open(q, encoding="utf-8", newline="") as fp:
            for r in csv.DictReader(fp):
                pg = int(r["pdf_page"]) if str(r.get("pdf_page", "")).isdigit() else None
                seg = ""
                if pg and checked:                  # 建议改动未落实时译文里是 old；已落实则是 new
                    seg = (_segment_of(checked, pg, r.get("old", "")) or _segment_of(checked, pg, r.get("new", "")))
                add("human_review", r.get("severity") or "major", pg or "", seg,
                    f"{r.get('reason', '')} | old={r.get('old', '')[:60]}")
    qa = d / "qa_issues.json"
    if qa.exists():
        for it in json.loads(qa.read_text(encoding="utf-8")):
            if it.get("severity") in ("critical", "major"):
                add(it.get("code", "qa"), it["severity"], it.get("page") or "", it.get("segment") or "",
                    it.get("message", ""))
    return {"id": ch["id"], "title": ch["title"], "start": ch["start"], "end": ch["end"], "status": status,
            "pages_src": len(src_pages), "pages_done": len(have), "issues": rows}


def report(work: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """写每章 chapter_report.md、全书 chapter_issues.csv 与 book_issues.md；返回汇总。"""
    work = Path(work)
    chs = [chapter_issues(work, c) for c in plan["chapters"]]
    all_rows = [r for c in chs for r in c["issues"]]
    for c in chs:
        d = work / "chapters" / c["id"]
        d.mkdir(parents=True, exist_ok=True)
        crit = [r for r in c["issues"] if r["severity"] == "critical"]
        lines = [f"# {c['id']} — {c['title']}", "", f"页 p.{c['start']}-{c['end']}；状态 {c['status']}；"
                 f"页 {c['pages_done']}/{c['pages_src']}；问题 {len(c['issues'])}（critical {len(crit)}）", ""]
        lines += [f"- [{r['severity']}] {r['kind']} p.{r['pdf_page']} {r['segment']} {r['message']}"
                  for r in c["issues"]]
        (d / "chapter_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(work / "chapter_issues.csv", "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["chapter", "kind", "severity", "pdf_page", "segment", "message"])
        w.writeheader()
        w.writerows(all_rows)
    summ = ["# 全书章级问题汇总", "", "| 章 | 状态 | 页 | 问题 | critical |", "|---|---|---|---|---|"]
    for c in chs:
        n_c = sum(1 for r in c["issues"] if r["severity"] == "critical")
        summ.append(f"| {c['id']} | {c['status']} | {c['pages_done']}/{c['pages_src']} | {len(c['issues'])} | {n_c} |")
    (work / "book_issues.md").write_text("\n".join(summ) + "\n", encoding="utf-8")
    return {"chapters": chs, "issues": len(all_rows),
            "critical": sum(1 for r in all_rows if r["severity"] == "critical"),
            "incomplete": [c["id"] for c in chs if c["status"] != "done"]}


# ------------------------------------------------------------------ 合并
def assemble(work: Path, plan: dict[str, Any], out: Path) -> Path:
    """按计划序拼各章 checked.md，前置目录；有章未完成则拒绝（不拼半成品）。"""
    work = Path(work)
    missing = [c["id"] for c in plan["chapters"] if not (work / "chapters" / c["id"] / "checked.md").exists()]
    if missing:
        raise ValueError(f"以下章尚无 checked.md，拒绝合并：{missing}")
    toc = ["# Contents", ""] + [f"- [{c['title']}](#{_slug(c['title'])}) — p.{c['start']}" for c in plan["chapters"]]
    parts = ["\n".join(toc) + "\n"]
    for c in plan["chapters"]:
        body = (work / "chapters" / c["id"] / "checked.md").read_text(encoding="utf-8").rstrip("\n")
        parts.append(f"\n<a id=\"{_slug(c['title'])}\"></a>\n\n{body}\n")
    Path(out).write_text("".join(parts), encoding="utf-8")
    return Path(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("src")
    d.add_argument("--pdf")
    d.add_argument("--level", type=int, default=1)
    d.add_argument("-o", "--out", default="chapter_plan.json")
    sub.add_parser("preview").add_argument("plan")
    s = sub.add_parser("split")
    s.add_argument("src")
    s.add_argument("plan")
    s.add_argument("-o", "--out", required=True)
    r = sub.add_parser("report")
    r.add_argument("work")
    r.add_argument("plan")
    asm = sub.add_parser("assemble")
    asm.add_argument("work")
    asm.add_argument("plan")
    asm.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        plan = build_plan(Path(a.src), Path(a.pdf) if a.pdf else None, a.level)
        save_plan(plan, Path(a.out))
        print(preview(plan))
    elif a.cmd == "preview":
        print(preview(load_plan(Path(a.plan))))
    elif a.cmd == "split":
        plan = load_plan(Path(a.plan))
        if plan.get("needs_review") and not plan.get("confirmed"):
            print("计划需人工确认：改 JSON 后设 confirmed=true", file=sys.stderr)
            return 2
        for k, v in split_md(Path(a.src), plan, Path(a.out)).items():
            print(k, v)
    elif a.cmd == "report":
        res = report(Path(a.work), load_plan(Path(a.plan)))
        print(f"章 {len(res['chapters'])}；问题 {res['issues']}（critical {res['critical']}）；未完成 {res['incomplete']}")
        return 1 if res["critical"] or res["incomplete"] else 0
    else:
        print(assemble(Path(a.work), load_plan(Path(a.plan)), Path(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
