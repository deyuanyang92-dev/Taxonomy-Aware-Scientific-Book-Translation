#!/usr/bin/env python3
"""标题中英对照：中文译文的标题后补上原文英文标题（Title Case），如「### 体被」→「### 体被（Integument）」。不调模型。

英文标题（原文 body.txt）：前后各有空行（或页码标记行）的短行——全大写（INTEGUMENT）或 Title Case（Extracellular Matrix），
  不以句号、逗号结尾；也认 Markdown # 行。中文标题：以 # 开头的行。
对齐：按出现顺序一一对应。中文里常有原文没有的结构标题（# 总题、## 一、正文）：从最深的标题级别往浅的方向，找到
  「标题数恰与英文标题数相等」的最大范围；找不到就整体不对齐（报告英文标题数与中文标题数，不改），由人工处理。
只给不含任何拉丁字母的中文标题补括注；已有英文（如「细胞外基质（Extracellular matrix）」）的不动。
  heading_bilingual.py --en body.txt --zh 译文.md [--fix] [-o 另存]
默认只报告（dry-run）；--fix 原地写回并备份 *.bak-heading。退出码 1＝有英文标题没对上。"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKUP_SUFFIX = ".bak-heading"
SMALL = {"a", "an", "the", "of", "and", "in", "on", "for", "to", "with", "or", "by", "vs", "at", "from", "as", "de", "la"}


@dataclass
class EnHeading:
    text: str
    rank: int        # 1＝全大写，2＝Title Case，其余＝Markdown # 个数
    line: int


@dataclass
class ZhHeading:
    text: str
    level: int
    line: int        # 0 起的行号
    raw: str


@dataclass
class Proposal:
    line: int
    zh_line: str
    new: str
    en: str


@dataclass
class Aligned:
    proposals: list[Proposal] = field(default_factory=list)
    unaligned_en: list[EnHeading] = field(default_factory=list)
    unaligned_zh: list[ZhHeading] = field(default_factory=list)
    mismatch: str = ""
    fixed_text: str = ""


def _is_title(s: str) -> bool:
    words = s.split()
    if not (1 <= len(words) <= 10) or len(s) < 4 or s[-1] in ".,;:" or not s[0].isupper():
        return False
    return all(re.fullmatch(r"[A-Za-z][A-Za-z'’\-()]*", w) and (w[0].isupper() or w in SMALL) for w in words)


def _is_caps(s: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", s)
    return (len(letters) >= 3 and s == s.upper() and bool(re.fullmatch(r"[A-Z][A-Z0-9 ,;:'’&()\-–/]{2,78}", s))
            and not re.fullmatch(r"[IVXLC ]+", s))


def english_headings(text: str) -> list[EnHeading]:
    lines = text.split("\n")
    blank = lambda i: i < 0 or i >= len(lines) or not lines[i].strip() or lines[i].strip().startswith("<!--")  # noqa: E731
    out: list[EnHeading] = []
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith("<!--"):
            continue
        md = re.match(r"(#{1,6})\s+(.+)", s)
        if md:
            out.append(EnHeading(md.group(2).strip(), len(md.group(1)), i))
        elif blank(i - 1) and blank(i + 1) and (_is_caps(s) or _is_title(s)):
            out.append(EnHeading(re.sub(r"\s+", " ", s), 1 if _is_caps(s) else 2, i))
    return out


def title_case(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    if s != s.upper():
        return s
    words = []
    for n, w in enumerate(s.split(" ")):
        if w.lower() in SMALL and n:
            words.append(w.lower())
        elif len(w) <= 3 and w.lower() not in SMALL:
            words.append(w)                                   # DNA、RNA 之类短缩写保持大写
        else:
            words.append("-".join(p[:1] + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def zh_headings(md: str) -> list[ZhHeading]:
    out: list[ZhHeading] = []
    fence = False
    for i, raw in enumerate(md.split("\n")):
        if raw.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", raw)
        if m and not re.match(r"待定术语|术语决策", m.group(2)):
            out.append(ZhHeading(m.group(2), len(m.group(1)), i, raw))
    return out


def align(en_text: str, zh_text: str) -> Aligned:
    E, Z = english_headings(en_text), zh_headings(zh_text)
    res = Aligned(fixed_text=zh_text)
    chosen: list[ZhHeading] | None = None
    for lv in sorted({z.level for z in Z}):
        sub = [z for z in Z if z.level >= lv]
        if len(sub) == len(E):
            chosen = sub
            break
    if not E or chosen is None:
        res.unaligned_en, res.unaligned_zh = E, Z
        res.mismatch = f"英文标题 {len(E)} 个，中文标题 {len(Z)} 个，按级别取舍后仍对不上数；未对齐，请人工处理"
        return res
    res.unaligned_zh = [z for z in Z if z not in chosen]
    lines = zh_text.split("\n")
    for e, z in zip(E, chosen):
        if re.search(r"[A-Za-z]", z.text):
            continue
        new = f"{'#' * z.level} {z.text}（{title_case(e.text)}）"
        res.proposals.append(Proposal(z.line, z.raw, new, e.text))
        lines[z.line] = new
    res.fixed_text = "\n".join(lines)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="中文标题后补英文标题（Title Case）；默认只报告")
    ap.add_argument("--en", required=True, help="英文原文（如 body.txt）")
    ap.add_argument("--zh", required=True, help="中文译文 .md")
    ap.add_argument("--fix", action="store_true", help="写回（原地并备份 .bak-heading）")
    ap.add_argument("-o", "--out", help="另存为（不动 --zh）")
    a = ap.parse_args(argv)
    zh_path = Path(a.zh)
    zh = zh_path.read_text(encoding="utf8")
    res = align(Path(a.en).read_text(encoding="utf8"), zh)
    for p in res.proposals:
        print(f"L{p.line + 1}: {p.zh_line.strip()} → {p.new}")
    if res.mismatch:
        print(res.mismatch)
    for e in res.unaligned_en:
        print(f"未对齐英文标题（原文第 {e.line + 1} 行）：{e.text}")
    for z in res.unaligned_zh:
        print(f"未对齐中文标题（第 {z.line + 1} 行，无对应英文标题）：{z.raw.strip()}")
    print(f"标题：建议补括注 {len(res.proposals)} 个，未对齐英文 {len(res.unaligned_en)} 个、中文 {len(res.unaligned_zh)} 个")
    if a.out:
        Path(a.out).write_text(res.fixed_text, encoding="utf8")
    elif a.fix and res.fixed_text != zh:
        bak = zh_path.with_name(zh_path.name + BACKUP_SUFFIX)
        if not bak.exists():
            bak.write_text(zh, encoding="utf8")
        zh_path.write_text(res.fixed_text, encoding="utf8")
    return 1 if res.unaligned_en else 0


if __name__ == "__main__":
    sys.exit(main())
