"""PDF 检查：L3 去向右缘、L5 行尾空白、L6 偶句同页、L8 右折行边界统一。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

from .ir import KeyIR
from .layout import channel_mm, dest_text
from .profile import Profile

PT = 72 / 25.4
_DOTS = re.compile(r"\.{4,}")


def _norm(s: str) -> str:
    return re.sub(r"[\s\xa0\u2060*.]+", "", s)


def _lines(page: fitz.Page) -> list[list[tuple[float, float, float, float, str]]]:
    ws = sorted(page.get_text("words"), key=lambda w: (round(w[1] / 3), w[0]))
    lines: list[list[tuple[float, float, float, float, str]]] = []
    ykey: list[float] = []
    for w in ws:
        y = (w[1] + w[3]) / 2
        for i, yk in enumerate(ykey):
            if abs(y - yk) < 3:
                lines[i].append((w[0], w[1], w[2], w[3], w[4]))
                break
        else:
            ykey.append(y)
            lines.append([(w[0], w[1], w[2], w[3], w[4])])
    for ln in lines:
        ln.sort()
    order = sorted(range(len(lines)), key=lambda i: ykey[i])
    return [lines[i] for i in order]


def verify_pdf(pdf: Path, irs: list[KeyIR], profile: Profile | None = None) -> list[dict[str, Any]]:
    profile = profile or Profile()
    issues: list[dict[str, Any]] = []

    def add(code: str, pg: int, detail: str, sev: str = "major") -> None:
        issues.append({"code": code, "severity": sev, "page": pg, "detail": detail})

    doc = fitz.open(str(pdf))
    fs = profile.font_size
    ch = channel_mm(irs, profile) * PT
    leader_lines: list[tuple[int, str, list[Any]]] = []
    for pi, page in enumerate(doc, 1):
        right = (page.rect.width + profile.text_w_mm * PT) / 2
        cl = right - ch
        lines = _lines(page)
        for li, ln in enumerate(lines):
            text = "".join(w[4] for w in ln)
            has_leader = any(_DOTS.search(w[4]) for w in ln)
            if has_leader:
                leader_lines.append((pi, _norm(text), ln))
                if abs(ln[-1][2] - right) > 1.5:
                    add("L3", pi, f"去向右端 {ln[-1][2]:.1f} 距版心右缘 {right:.1f}: {text[-20:]}")
                if _DOTS.match(ln[0][4]) or (len(ln) > 1 and _DOTS.match(ln[0][4])):
                    prev = lines[li - 1] if li else None
                    if prev and ln[0][1] - prev[0][3] < 1.5 * fs:
                        ptxt = "".join(w[4] for w in prev)
                        if not _DOTS.search(ptxt) and prev[-1][2] < cl - 2 * fs:
                            add("L5", pi, f"点线行前一行留白尾巴 (右端 {prev[-1][2]:.1f} < {cl - 2 * fs:.1f}): {ptxt[-15:]}")
            elif profile.overflow == "wrap":
                for w in ln:
                    if w[2] > cl + 1 and w[0] < cl:
                        add("L8", pi, f"正文行右端 {w[2]:.1f} 超过通道左界 {cl:.1f}: {text[:20]}")
                        break
    # 去向文本须出现在引导线所在行行尾（L3/L7：不得折断）
    ptr = 0
    for ir in irs:
        for c in ir.couplets:
            for ld in c.leads:
                want = _norm(dest_text(ld, profile))
                for j in range(ptr, min(ptr + 3, len(leader_lines))):
                    if leader_lines[j][1].endswith(want):
                        ptr = j + 1
                        break
                else:
                    pg = leader_lines[ptr][0] if ptr < len(leader_lines) else 0
                    add("L3", pg, f"偶句 {c.num} 去向 {want!r} 未在引导线行行尾(折断或缺失)")
    # L6：偶句两分支同页
    # 全文按字符位置顺序找（不按页找：短分支的前 12 字可能在同页前文出现，2026-11-23 keys_2007 偶句 13 误报）
    texts = [_norm(p.get_text()) for p in doc]
    full = "".join(texts)
    ends = [sum(len(t) for t in texts[: i + 1]) for i in range(len(texts))]
    pos = 0
    for ki, ir in enumerate(irs):
        for ci, c in enumerate(ir.couplets):
            pgs = []
            for ld in c.leads:
                key = _norm(re.sub(r"\*", "", ld.text))[:12]
                at = full.find(key, pos) if key else -1
                if at >= 0:
                    pgs.append(next(i for i, e in enumerate(ends) if at < e) + 1)
                    pos = at + len(key)
            if len(set(pgs)) > 1:
                add("L6", pgs[0], f"偶句 {c.num} 两分支跨页 {pgs}")
                issues[-1]["at"] = [ki, ci]
    return issues



_SKIP = set(" \t\xa0*.") | {chr(0x2060)}


def _char_lines(doc: Any) -> list[list[tuple[str, float, float]]]:
    """全文逐字符按行：[(字符, x0, x1)]，行按页序、y 序。"""
    out: list[list[tuple[str, float, float]]] = []
    for page in doc:
        rows: list[tuple[float, list[tuple[str, float, float]]]] = []
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    for ch in sp["chars"]:
                        y = (ch["bbox"][1] + ch["bbox"][3]) / 2
                        for yy, row in rows:
                            if abs(yy - y) < 3:
                                row.append((ch["c"], ch["bbox"][0], ch["bbox"][2]))
                                break
                        else:
                            rows.append((y, [(ch["c"], ch["bbox"][0], ch["bbox"][2])]))
        rows.sort(key=lambda r: r[0])
        out.extend(sorted(r, key=lambda c: c[1]) for _, r in rows)
    return out


def leader_gaps(pdf: Path, irs: list[KeyIR], profile: Profile | None = None) -> dict[int, dict[int, float]]:
    """量每条分支去向所在行的点线长度（pt）：{表序号: {表内分支平铺序号: 长度}}。找不到的分支不列。

    点线长度 = 去向首字左端 − 去向前最后一个非点、非空白字符的右端；该行只有点线和去向（L5(B) 第二行）时
    取去向首字左端 − 行首。按字符坐标量，不受点与去向粘成一个词的影响。
    """
    profile = profile or Profile()
    lines = _char_lines(fitz.open(str(pdf)))
    out: dict[int, dict[int, float]] = {}
    ptr = 0
    for ki, ir in enumerate(irs):
        out[ki] = {}
        flat = 0
        for c in ir.couplets:
            for ld in c.leads:
                want = _norm(dest_text(ld, profile))
                for j in range(ptr, min(ptr + 6, len(lines))):
                    ln = lines[j]
                    if not want or not _norm("".join(ch[0] for ch in ln)).endswith(want):
                        continue
                    n, k = 0, len(ln)
                    while k > 0 and n < len(want):
                        k -= 1
                        if ln[k][0] not in _SKIP:
                            n += 1
                    t = k - 1
                    while t >= 0 and ln[t][0] in " .…·" + chr(0xa0) + chr(0x2060):
                        t -= 1
                    out[ki][flat] = ln[k][1] - (ln[t][2] if t >= 0 else ln[0][1])
                    ptr = j + 1
                    break
                flat += 1
    return out
