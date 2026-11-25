#!/usr/bin/env python3
"""从按章抽出的英文原文里分离图注/表注，输出 正文.txt 与 图注.txt。

PDF 双栏抽取时，图注常夹在正文句子中间（甚至一句话的前后两半被图注隔开）。图注要单独另译，
正文要接上被打断的句子，所以先分离、再切块翻译。

规则（2026-11-12 在 Handbook 第4卷 沙蚕科上调通）：
  1. 图注首行匹配 ^(◂ )?(Fig\\.|Table)\\s*\\d+(\\.\\d+)*
  2. 续行条件 =（当前块末行未以句号结束，且不是缩写结尾如「O.F.」「e.g.」「sp.」「fig.」，且块长 < 14 行）
              或（下一行长度 > 100，即宽栏图注）。下一行本身是新图注首行时一律停止。
  3. 正文去连字符断行：行末 - 或软连字符且下一行以小写字母开头，去掉连字符并把词的后半段并回上一行
     （等价于 -\\n(?=[a-z]) 删除，但保留换行，所以正文不会出现被拼成超长的行）。
  4. 图注各行以空格连成一行（行末的 - 多半是真连字符，保留；软连字符去掉）；图注之间空一行；开头的「◂ 」标记去掉。
用法: python3 split_figures.py <章.txt> [-o 输出目录]   缺省输出到 <章>_split/
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

CAPTION_START = re.compile(r"^(◂ )?(Fig\.|Table)\s*\d+(\.\d+)*")
WIDE_LINE = 100        # 下一行超过此长度，视为宽栏图注的续行
MAX_BLOCK_LINES = 14   # 未收句号的图注，最多连续吸收到 14 行
_ABBREV_END = re.compile(r"(?:\b[A-Za-z]|\be\.g|\bi\.e|\bsp|\bspp|\bfig|\bfigs|\bcf|\bvs|\bal|\bpl)\.$", re.I)
_HYPHEN_END = re.compile(r"[-­]$")


def ends_sentence(line: str) -> bool:
    """行末是句号且不是缩写（O.F. / e.g. / sp. / fig. / 单字母缩写）。"""
    s = line.rstrip()
    return s.endswith(".") and not _ABBREV_END.search(s)


def wide_cutoff(lines: list[str]) -> float:
    """「宽行」的长度门槛：不低于 100，且要明显长于本章正文行（取非空行长度中位数的 1.3 倍）。
    双栏书正文行约 57 字符，宽栏图注 > 100，门槛就是 100；单栏书正文行本身就有 110 以上，门槛随之抬高，
    正文行不会被当成宽栏图注。"""
    sizes = [len(ln) for ln in lines if ln.strip()]
    return max(WIDE_LINE, 1.3 * statistics.median(sizes)) if sizes else float(WIDE_LINE)


def _continues(block: list[str], nxt: str, wide: float = WIDE_LINE) -> bool:
    """是否把 nxt 并入当前图注块。末行是句末结束的就停（单栏书的正文行很长，不能因为下一行长就吞进图注）；
    下一行本身是新图注首行也停。其余两种情况续行：
      窄栏：末行未句末结束，且块长不到 14 行；
      宽栏：该图注首行本身是宽行，下一行也是宽行，且末行未句末结束，或末行本身是宽行
            （宽栏长图注的中间行常常恰好以句号收尾，如「…(Horst, 1924).」，不能在那里断开）。"""
    if CAPTION_START.match(nxt):
        return False
    last = block[-1]
    if not ends_sentence(last):
        if len(block) < MAX_BLOCK_LINES:
            return True
        return len(block[0]) > wide and len(nxt) > wide
    return len(block[0]) > wide and len(last) > wide and len(nxt) > wide


def dehyphenate(lines: list[str]) -> list[str]:
    """行末连字符 + 下一行小写开头：去掉连字符，下一行的首个词片段并回上一行，其余留在原行。"""
    out: list[str] = []
    for ln in lines:
        if out and _HYPHEN_END.search(out[-1]) and ln[:1].islower():
            m = re.match(r"\S+", ln)
            assert m
            out[-1] = out[-1][:-1] + m.group()
            ln = ln[m.end():].lstrip()
            if not ln:
                continue
        out.append(ln)
    return out


def _join_caption(block: list[str]) -> str:
    """各行以空格连成一行。图注里行末的 - 多半是真连字符（如 Crescent-shaped），不去；只去软连字符。"""
    text = ""
    for ln in (x.strip() for x in block):
        if text.endswith("\u00ad"):
            text = text[:-1] + ln
        else:
            text = f"{text} {ln}" if text else ln
    return re.sub(r"^◂ ", "", text).replace("\u00ad", "")


def split_figures(text: str) -> tuple[str, list[str]]:
    """返回 (正文, 图注列表)。"""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    body: list[str] = []
    captions: list[str] = []
    wide = wide_cutoff(lines)
    i = 0
    while i < len(lines):
        if not CAPTION_START.match(lines[i]):
            body.append(lines[i])
            i += 1
            continue
        block = [lines[i]]
        i += 1
        while i < len(lines) and _continues(block, lines[i], wide):
            block.append(lines[i])
            i += 1
        captions.append(_join_caption(block))
    body = [ln.replace("\u00ad", "") for ln in dehyphenate(body)]  # 行末软连字符已并词；其余零散的不可见软连字符删掉
    # 删图注后留下的连续空行压成一个
    squeezed: list[str] = []
    for ln in body:
        if not ln.strip() and squeezed and not squeezed[-1].strip():
            continue
        squeezed.append(ln)
    return "\n".join(squeezed).strip("\n") + "\n", captions


def caption_id(text: str) -> str:
    """Stable id from the caption label: 'Fig. 3.' -> 'fig-3', 'Table 2.1' -> 'table-2.1'."""
    m = re.match(r"^(?:◂ )?(Fig\.|Table)\s*(\d+(?:\.\d+)*)", text.strip())
    if not m:
        return ""
    return f"{'fig' if m.group(1).startswith('Fig') else 'table'}-{m.group(2)}"


def split_blocks(blocks: list[dict], max_gap: float = 1.0, x_tol: float = 6.0,
                 max_chars: int = 1500) -> tuple[list[dict], list[dict]]:
    """Caption boundaries from block geometry (issue #18).

    ``blocks``: reading order, each ``{"id", "text", "bbox": (x0, y0, x1, y1)}``.
    A caption starts at a block whose text matches CAPTION_START and takes the
    following blocks only while they are geometrically the same caption: the
    previous caption block did not end a sentence, the vertical gap is at most
    ``max_gap`` line heights, and the left edge matches within ``x_tol`` pt.
    Anything else, e.g. an indented body paragraph, stays body.  Returns
    (body blocks, captions); a caption is ``{"id", "blocks", "bbox", "text",
    "chars", "oversize"}`` and carries the union bbox so a figure can share
    the id.  ``oversize`` marks captions longer than ``max_chars``.
    """
    body: list[dict] = []
    captions: list[dict] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if not CAPTION_START.match(b["text"].strip()):
            body.append(b)
            i += 1
            continue
        group = [b]
        i += 1
        while i < len(blocks):
            nxt, last = blocks[i], group[-1]
            if CAPTION_START.match(nxt["text"].strip()) or ends_sentence(last["text"]):
                break
            lines = max(1, len(last["text"].splitlines()))
            line_h = (last["bbox"][3] - last["bbox"][1]) / lines
            gap = nxt["bbox"][1] - last["bbox"][3]
            if gap > max_gap * line_h or abs(nxt["bbox"][0] - group[0]["bbox"][0]) > x_tol:
                break
            group.append(nxt)
            i += 1
        text = _join_caption([g["text"] for g in group])
        bbox = (min(g["bbox"][0] for g in group), min(g["bbox"][1] for g in group),
                max(g["bbox"][2] for g in group), max(g["bbox"][3] for g in group))
        captions.append({"id": caption_id(text), "blocks": [g["id"] for g in group], "bbox": bbox,
                         "text": text, "chars": len(text), "oversize": len(text) > max_chars})
    return body, captions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="分离英文原文中的图注/表注，输出 正文.txt 与 图注.txt")
    ap.add_argument("src", help="按章抽出的英文原文 .txt")
    ap.add_argument("-o", "--outdir", default=None, help="输出目录，缺省 <章>_split/")
    a = ap.parse_args(argv)
    src = Path(a.src)
    out = Path(a.outdir) if a.outdir else src.with_name(src.stem + "_split")
    out.mkdir(parents=True, exist_ok=True)
    body, captions = split_figures(src.read_text(encoding="utf8", errors="replace"))
    (out / "正文.txt").write_text(body, encoding="utf8")
    (out / "图注.txt").write_text("\n\n".join(captions) + ("\n" if captions else ""), encoding="utf8")
    print(f"图注 {len(captions)} 条，正文 {len(body.splitlines())} 行 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
