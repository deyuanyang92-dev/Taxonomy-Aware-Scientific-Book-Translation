#!/usr/bin/env python3
"""正文与图注切分检查（草稿前必做，只报告不改文件）：找出混进正文流的图注残段和没接上的图注尾巴。

用法: split_check.py <body.txt> <captions.txt>
  逐段（空行分段；<!-- p.N --> 页码标记忽略，行号仍是文件真实行号）检查，打印 `文件:行号: [类型] 段首`，有可疑段退出码 1。

类型：
  abbr-key             正文段内 ≥3 个「缩写, 词;」对（图内缩写键串）
  scale-bar            正文段前 200 字符含 Scale bar（段长 < 1500）
  caption-start        正文段以「Fig. N.」「Figs 3A–C.」起首（图注）；「Fig. 3 shows」这类正文句不算
  abbr-key-start       正文段以「缩写, 词;」起首（图注缩写键的开头）
  hyphen-continuation  正文前一段以连字号结尾、本段小写起首（断词或图注尾巴）
  caption-hyphen-end   图注段以连字号结尾（尾巴没并入）
  bare-caption         图注段只有「Fig. N.」没有说明文字（紧随的若不是 Fig. 起首的段，说明文字可能被分到了下一段）

规则移植自 Harrison 1992 解剖学工程的 build_unit（2026-11-14），不含任何具体书目的路径。"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MARK = re.compile(r"<!--\s*p\.\w+\s*-->")
ABBR = re.compile(r"\b[a-zA-Z]{1,6}, [a-z][a-zA-Z \-]{1,30};")
ABBR_START = re.compile(r"^[a-zA-Z]{1,6}, [a-z][a-zA-Z \-]{1,30};")
CAPTION_START = re.compile(r"^Figs?\.? ?\d+[A-Za-z]?(?:\s*[-–,&]\s*\d*[A-Za-z]?)*\s*\.")
FIG_START = re.compile(r"^Figs?\.? ?\d")
BARE_LABEL = re.compile(r"Figs?\.? ?\d+[.\-–\d, ]*\.?")
OCR_TAIL = re.compile(r"(?:\[OCR\?\])+$")


@dataclass(frozen=True)
class Suspect:
    file: str      # body | captions
    line: int      # 段首所在的文件行号（从 1 起）
    kind: str
    detail: str
    text: str      # 段首约 80 字符

    def line_str(self, path: str = "") -> str:
        return f"{path or self.file}:{self.line}: [{self.kind}] {self.detail}｜{self.text}"


def paragraphs(text: str) -> list[tuple[int, str]]:
    """[(段首行号, 去掉页码标记并压成单行的段文字)]；只含标记的段丢弃。"""
    out: list[tuple[int, str]] = []
    cur: list[str] = []
    start = 0
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if line.strip() == "":
            if cur:
                out.append((start, " ".join(cur)))
                cur = []
            continue
        bare = MARK.sub("", line).strip()
        if bare == "":
            continue
        if not cur:
            start = i
        cur.append(bare)
    if cur:
        out.append((start, " ".join(cur)))
    return out


def _snip(s: str) -> str:
    return s[:80].replace("\t", " ")


def check_text(body: str, captions: str) -> list[Suspect]:
    found: list[Suspect] = []
    bp = paragraphs(body)
    for i, (ln, p) in enumerate(bp):
        def add(kind: str, detail: str, ln: int = ln, p: str = p) -> None:
            found.append(Suspect("body", ln, kind, detail, _snip(p)))
        if len(ABBR.findall(p)) >= 3:
            add("abbr-key", "段内 ≥3 个「缩写, 词;」对，像图注缩写键，应移入 captions")
        elif "Scale bar" in p[:200] and len(p) < 1500:
            add("scale-bar", "含 Scale bar，像图注，应移入 captions")
        elif CAPTION_START.match(p):
            add("caption-start", "以「Fig. N.」起首，是图注，应移入 captions")
        elif ABBR_START.match(p):
            add("abbr-key-start", "以「缩写, 词;」起首，像图注缩写键的开头")
        elif i > 0 and p[:1].islower() and OCR_TAIL.sub("", bp[i - 1][1]).rstrip().endswith("-"):
            add("hyphen-continuation", "前一段以连字号结尾、本段小写起首：合并（去连字号）或移入图注")
    cp = paragraphs(captions)
    for i, (ln, p) in enumerate(cp):
        nxt = cp[i + 1][1] if i + 1 < len(cp) else ""
        if BARE_LABEL.fullmatch(p):
            more = "；紧随的段不是 Fig. 起首，说明文字可能被分到了下一段" if nxt and not FIG_START.match(nxt) else "；后面没有说明文字"
            found.append(Suspect("captions", ln, "bare-caption", "只有图号" + more, _snip(p)))
        elif OCR_TAIL.sub("", p).rstrip().endswith("-"):
            found.append(Suspect("captions", ln, "caption-hyphen-end", "图注以连字号结尾，尾巴可能没并入", _snip(p[-80:])))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="正文/图注切分检查；有可疑段退出码 1，文件缺失退出码 2")
    ap.add_argument("body")
    ap.add_argument("captions")
    a = ap.parse_args(argv)
    paths = {"body": Path(a.body), "captions": Path(a.captions)}
    for name, p in paths.items():
        if not p.is_file():
            print(f"找不到 {name} 文件：{p}", file=sys.stderr)
            return 2
    found = check_text(paths["body"].read_text(encoding="utf8"), paths["captions"].read_text(encoding="utf8"))
    for s in found:
        print(s.line_str(str(paths[s.file])))
    print(f"可疑段 {len(found)} 处")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
