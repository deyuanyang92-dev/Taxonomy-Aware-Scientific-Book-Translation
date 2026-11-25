"""确定性修正与检查（不调模型）。"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from typing import Any

from .ir import KeyIR

NBSP = "\xa0"
_FW = {ord(c): ord("0") + i for i, c in enumerate("０１２３４５６７８９")}
_BINOM = re.compile(r"(?<![A-Za-z])([A-Z][a-z]+) ([a-z]{3,})(?![A-Za-z])")
_LATIN = re.compile(r"[A-Z][a-z]+(?:[ \xa0][a-z]{3,})?")


def fix_text(s: str) -> str:
    s = s.translate(_FW).replace(chr(0x3000), "")
    s = re.sub(r"[ \xa0]+(?=[.…·]{2,}\s*$)", "", s)
    s = re.sub(r"[ \t]+$", "", s)
    return _BINOM.sub(lambda m: m.group(1) + NBSP + m.group(2), s)


def fix_ir(ir: KeyIR) -> KeyIR:
    for c in ir.couplets:
        for ld in c.leads:
            ld.text = fix_text(ld.text)
            ld.target = fix_text(ld.target)
            ld.name_zh = fix_text(ld.name_zh)
    ir.heading = fix_text(ir.heading)
    return ir


def renumber(ir: KeyIR) -> tuple[KeyIR, dict[int, int]]:
    """DFS 自 1 起按出现顺序重编号；jump 目标与 backref 同步。未被到达的偶句接在后面。"""
    by_num = {c.num: c for c in ir.couplets}
    mapping: dict[int, int] = {}

    def visit(n: int) -> None:
        if n in mapping or n not in by_num:
            return
        mapping[n] = len(mapping) + 1
        for ld in by_num[n].leads:
            if ld.kind == "jump" and ld.target.isdigit():
                visit(int(ld.target))

    if ir.couplets:
        visit(ir.couplets[0].num)
    for c in ir.couplets:
        visit(c.num)
    for c in ir.couplets:
        for ld in c.leads:
            if ld.kind == "jump" and ld.target.isdigit() and int(ld.target) in mapping:
                ld.target = str(mapping[int(ld.target)])
        if c.backref is not None and c.backref in mapping:
            c.backref = mapping[c.backref]
    for c in ir.couplets:
        c.num = mapping[c.num]
    return ir, mapping


def latin_of(target: str) -> str:
    m = _LATIN.search(target)
    return m.group(0).replace(NBSP, " ") if m else ""


def yiku_lookup(latin: str) -> str | None:
    """yiku lookup <name> --domain 分类学；只取状态为“已核”的行里的中文名。解析失败返回 None。"""
    try:
        r = subprocess.run(["yiku", "lookup", latin, "--domain", "分类学"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if "已核" in line:
            m = re.search(r"[一-鿿][一-鿿·]*", line.replace("已核", ""))
            if m:
                return m.group(0)
    return None


# 去向只剩阶元词、缺中文名本体，如「亚科 Harmothoinae」（Imajima 2001 译文，2026-11-23 样张发现）
_BARE_RANK = re.compile(r"^(?:亚科|科|亚属|属|族|亚族|目|亚目)[\s\xa0]+(?=[A-Z])")


def add_zh_names(ir: KeyIR, lookup: Callable[[str], str | None] = yiku_lookup) -> tuple[KeyIR, list[str]]:
    """补去向中文名：只取 yiku 已核；查不到列入 missing，不拟名。残缺的「亚科 X」先去掉阶元词再查。"""
    missing: list[str] = []
    for c in ir.couplets:
        for ld in c.leads:
            if ld.kind == "taxon" and _BARE_RANK.match(ld.target):
                ld.target = _BARE_RANK.sub("", ld.target)
            if ld.kind != "taxon" or ld.name_zh:
                continue
            lat = latin_of(ld.target)
            if not lat:
                continue
            zh = lookup(lat)
            if zh:
                ld.name_zh = zh
            elif lat not in missing:
                missing.append(lat)
    return ir, missing


def check(ir: KeyIR) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(code: str, sev: str, detail: str) -> None:
        out.append({"code": code, "severity": sev, "detail": detail})

    nums = [c.num for c in ir.couplets]
    for n in sorted({n for n in nums if nums.count(n) > 1}):
        add("S3", "critical", f"重号 {n}")
    refs: dict[int, int] = {}
    for c in ir.couplets:
        if len(c.leads) != 2:
            add("S1", "major", f"偶句 {c.num} 有 {len(c.leads)} 条分支")
        for ld in c.leads:
            if ld.kind == "jump":
                if not ld.target.isdigit() or int(ld.target) not in nums:
                    add("S2", "critical", f"偶句 {c.num} 死链 -> {ld.target}")
                else:
                    t = int(ld.target)
                    if t <= c.num:
                        add("S2", "major", f"偶句 {c.num} 前指/自指 -> {t}")
                    refs[t] = refs.get(t, 0) + 1
            elif ld.kind == "none" or not ld.target:
                add("L7", "major", f"偶句 {c.num} 分支缺去向")
            if ld.kind == "taxon" and _BARE_RANK.match(ld.target):
                add("D1", "major", f"偶句 {c.num} 去向中文名残缺（只有阶元词）: {ld.target}")
            s = ld.text + ld.target
            if any("０" <= ch <= "９" for ch in s):
                add("T2", "major", f"偶句 {c.num} 全角数字")
            if chr(0x3000) in s:
                add("U+3000", "major", f"偶句 {c.num} 含 U+3000")
    for n in nums:
        if n != nums[0]:
            k = refs.get(n, 0)
            if k == 0:
                add("S3", "major", f"孤立号 {n}")
            elif k > 1:
                add("S3", "major", f"号 {n} 被引用 {k} 次")
    return out
