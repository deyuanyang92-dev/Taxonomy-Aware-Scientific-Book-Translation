#!/usr/bin/env python3
"""合并被页码标记切开的句子（用户规则 2026-11-13）：一句话不得被 `<!-- p.N -->` 切成两段。

标记前一段没有句末标点（。！？…；闭括号/引号只有紧跟在句末标点之后才算收尾），标记后第一段是普通段落，
就把两段并成一段，标记移到合并段之后：

  …Gelder 与 Tyler（1986）并未观察到 ⏎⏎ <!-- p.34 --> ⏎⏎ 神经成分与腺细胞之间的突触。
  →  …Gelder 与 Tyler（1986）并未观察到神经成分与腺细胞之间的突触。 ⏎⏎ <!-- p.34 -->

不合并：标题（#）、图注（图N / **图N）、表格（|）、列表项、整段加粗的小标题；两个标记之间没有文字的、标记之后没有段落的也不动。
标记之间连续多个时一起移到合并段之后。species_format 按标记分页，合并后后半句归入前一页，标记仍在两页内容之间。

用法：
  python3 join_page_breaks.py 译文.md [更多文件]        # 只报告，有待合并处退出码 1
  python3 join_page_breaks.py 译文.md --fix             # 先备份 <文件>.bak-joinpages 再写回；已有备份不覆盖
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from direct_mode import PAGE_MARK

BACKUP_SUFFIX = ".bak-joinpages"
_SEP = re.compile(r"(\n[ \t]*\n+)")
_OCR_TAIL = re.compile(r"(?:\[OCR\?\])+$")
_TERMINAL = "。！？…!?.;；"          # 句末标点（分号也算：已写完一个分句且作者有意收住）
_CLOSERS = "）」』”’〕】)]\"'"
_CAPTION = re.compile(r"^\s*(?:\*\*)?图\s*\d")
_LIST_ITEM = re.compile(r"^\s*(?:[-+*]\s|\d+[.)、]\s)")
_BOLD_ONLY = re.compile(r"^\s*\*\*[^*\n]+\*\*\s*$")


@dataclass
class Join:
    marker: str      # 被移动的页码标记的标签
    before: str      # 前一段结尾
    after: str       # 后一段开头

    def line(self) -> str:
        return f"[p.{self.marker}] 并段：「…{self.before}」＋「{self.after}…」，标记移到合并段之后"


def is_marker(block: str) -> bool:
    return bool(PAGE_MARK.fullmatch(block.strip())) if block.strip() else False


def ends_sentence(par: str) -> bool:
    """段落是否以句末标点收尾（允许其后跟闭括号/引号和 [OCR?] 标记）。"""
    s = _OCR_TAIL.sub("", par.rstrip())
    if not s:
        return True
    if s[-1] in _TERMINAL:
        return True
    i = len(s)
    while i > 0 and s[i - 1] in _CLOSERS:
        i -= 1
    return 0 < i < len(s) and s[i - 1] in "。！？…!?."


def _first_line(block: str) -> str:
    return block.lstrip("\n").split("\n", 1)[0]


def _is_plain(block: str, *, as_head: bool) -> bool:
    """能参与合并的普通段落。as_head＝作为前半（不能是列表项/整段加粗的小标题），否则作为后半（不能是列表项）。"""
    first = _first_line(block)
    if not block.strip() or first.lstrip().startswith(("#", "|", ">", "<!--")):
        return False
    if _CAPTION.match(first) or _LIST_ITEM.match(first):
        return False
    return not (as_head and _BOLD_ONLY.match(block.strip()))


def _glue(head: str, tail: str) -> str:
    head, tail = head.rstrip(), tail.lstrip()
    if re.search(r"[A-Za-z]\*$", head) and re.match(r"\*[A-Za-z]", tail):    # *Genus*⏎页⏎*species*：并成同一段斜体
        return head[:-1] + " " + tail[1:]
    if re.search(r"[A-Za-z0-9]$", head) and tail.startswith(("与 ", "和 ", "及 ")):   # 本文西文名与连词间惯用空格：Gelder 与 Tyler
        return head + " " + tail
    if re.search(r"[A-Za-z0-9*)\]]$", head) and re.match(r"[A-Za-z0-9*(\[]", tail):
        return head + " " + tail
    return head + tail


def _label(block: str) -> str:
    m = PAGE_MARK.search(block)
    return m.group(1) if m else "?"


def join_text(text: str) -> tuple[str, list[Join]]:
    """返回 (合并后的文本, 合并记录)。幂等。只重写被合并处的分隔符（统一成一个空行），其余原样。"""
    body = text.rstrip()
    trailing = text[len(body):]
    parts = _SEP.split(body)                   # 块、分隔符交替
    blocks = parts[0::2]
    seps = parts[1::2] + [""]                  # seps[i]＝blocks[i] 之后的分隔符
    out: list[tuple[str, str]] = []
    joins: list[Join] = []
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        sep_after = seps[i]
        i += 1
        markers: list[str] = []
        if not is_marker(cur) and _is_plain(cur, as_head=True):
            while not ends_sentence(cur):          # 一句话可能跨好几页：能并就继续并
                j = i
                while j < len(blocks) and is_marker(blocks[j]):
                    j += 1
                if j == i or j >= len(blocks) or not _is_plain(blocks[j], as_head=False):
                    break
                for m in blocks[i:j]:
                    joins.append(Join(_label(m), cur.rstrip()[-12:].replace("\n", " "), blocks[j].lstrip()[:12].replace("\n", " ")))
                markers += blocks[i:j]
                cur, sep_after = _glue(cur, blocks[j]), seps[j]
                i = j + 1
        if markers:
            out.append((cur, "\n\n"))
            out += [(m, "\n\n") for m in markers[:-1]]
            out.append((markers[-1], sep_after))
        else:
            out.append((cur, sep_after))
    return "".join(b + s for b, s in out) + trailing, joins


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="合并被页码标记 <!-- p.N --> 切开的句子，标记移到合并段之后（默认只报告）")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fix", action="store_true", help="写回文件（先备份为 <文件>.bak-joinpages，已有备份不覆盖）")
    a = ap.parse_args(argv)
    code = 0
    for f in a.files:
        p = Path(f)
        text = p.read_text(encoding="utf8")
        new, joins = join_text(text)
        print(f"{p.name}：待并段 {len(joins)} 处")
        for j in joins:
            print("  " + j.line())
        if not joins:
            continue
        if a.fix:
            bak = p.with_name(p.name + BACKUP_SUFFIX)
            if not bak.exists():
                shutil.copy2(p, bak)
            p.write_text(new, encoding="utf8")
            print(f"  已写回 {p}（原件备份 {bak.name}）")
        else:
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
