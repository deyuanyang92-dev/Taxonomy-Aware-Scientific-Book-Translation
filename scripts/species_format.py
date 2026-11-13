#!/usr/bin/env python3
"""种名格式检查与自动修正（用户规则 2026-11-13，见 skill/domains/分类学.md 第 2 节）：

  有权威中文名的种，按「原书页」计：每页第一次出现写「中文名（*Genus species*）」，
  同页再出现只写中文名；换页后第一次出现再写一次拉丁名。
  没有权威中文名的种只写拉丁名，本脚本一概不碰（只处理名单里有中文名的种）。

页码来自译文里的页码标记行 `<!-- p.13 -->`（初译时由原文带入、译者原样保留；见 direct_mode.PAGE_MARK）。
图注文件没有页码，按「每条图注一个单元」处理（--unit paragraph，文件名含「图注」或 caption 时自动选用）。

用法：
  python3 species_format.py 译文_正文.md 译文_图注.md --names species_names.tsv          # 只报告，有待改处退出码 1
  python3 species_format.py 译文_正文.md --names species_names.tsv --fix                  # 先备份 *.bak-species 再写回
  python3 species_format.py 译文.md --names n.tsv --no-yiku -o 修正后.md                  # 另存，不备份
名单来源（可叠加，TSV 优先）：
  --names FILE   TSV：拉丁名<TAB>中文名，# 开头为注释（两列顺序写反也认）
  yiku           默认再按 --domain 去 yiku 查文中斜体双名（*Genus species*），只收 HARD 译名（classify 规则）；--no-yiku 关闭
识别的写法：「中文（*Latin*）」「中文（*Latin*，科…）」「中文 *Latin*」、单独的 *Latin* 或 *G. species*（缩写）、单独的中文名。
局限：只认斜体（*…*）的拉丁名；中文名按字面匹配（名单里的中文名不应是别的词的一部分）；
不认 *Genus species* 后紧跟的命名人（Sars, 1851）。修正是确定性的字符串改写，改完建议复读一遍。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from direct_mode import PAGE_MARK

BACKUP_SUFFIX = ".bak-species"
_CJK = r"一-鿿　-〿＀-￯"
_FAMILY = re.compile(r"科|[A-Za-z]+idae|[A-Za-z]+ida\b")


class NoPageMarkers(ValueError):
    """按页处理却没有页码标记：整篇当一页会误删后面各页的拉丁名，所以拒绝。"""


@dataclass
class Change:
    unit: str      # 页码（页码标记里的标签）或「段 N」
    name: str      # 中文名
    kind: str      # add-latin | drop-latin | expand-latin
    before: str
    after: str

    def line(self) -> str:
        what = {"add-latin": "首现补/规范拉丁名", "drop-latin": "同页重复，去拉丁名",
                "expand-latin": "首现缩写属名展开"}[self.kind]
        page = f"p.{self.unit}" if re.fullmatch(r"[0-9A-Za-z.\-]+", self.unit) else self.unit
        return f"[{page}] {self.name}：{what}：「{self.before}」→「{self.after}」"


# ---------------------------------------------------------------- 名单

def load_names(path: str | Path) -> tuple[dict[str, str], list[str]]:
    """TSV（制表符或逗号分隔）：拉丁名、中文名。返回 ({拉丁名: 中文名}, 无法解析的行)。"""
    names: dict[str, str] = {}
    bad: list[str] = []
    for ln in Path(path).read_text(encoding="utf8").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in re.split(r"\t|[,，]", ln, maxsplit=1)]
        if len(cells) == 2 and re.search(r"[一-鿿]", cells[0]) and not re.search(r"[一-鿿]", cells[1]):
            cells.reverse()
        if len(cells) == 2 and re.fullmatch(r"[A-Z][a-z]+ [a-z]+", cells[0]) and re.search(r"[一-鿿]", cells[1]):
            names[cells[0]] = re.sub(r"[（(].*", "", cells[1]).strip()
        else:
            bad.append(ln)
    return names, bad


def italic_binomials(text: str) -> list[str]:
    """文中斜体的完整双名 *Genus species*（不含缩写、sp.、cf.）。"""
    return sorted(set(re.findall(r"\*([A-Z][a-z]+ [a-z]{2,})\*", text)))


def yiku_names(text: str, domain: str = "分类学", con: Any = None, db: str | Path | None = None) -> dict[str, str]:
    """文中斜体双名里，yiku 按 HARD 规则（classify）给出唯一中文名的种。con 缺省打开默认库（YIKU_DB 或 ~/.yiku/yiku.db）。"""
    import importlib
    D = importlib.import_module("yiku.db")   # 不写 from yiku import：从仓库根跑 mypy 时 yiku/ 目录会被当成命名空间包
    classify_mod = importlib.import_module("yiku.classify")
    HARD, classify = classify_mod.HARD, classify_mod.classify
    if con is None:
        path = Path(db) if db else D.default_path()
        if not path.exists():
            raise FileNotFoundError(f"找不到 yiku 库 {path}")
        con = D.connect(path)
    fb = D.resolve_fallback(domain, None)
    out: dict[str, str] = {}
    for latin in italic_binomials(text):
        hits = D.candidates(con, latin, domain, None, fb)
        cls = classify(hits) if hits else None
        if cls is not None and cls.kind == HARD and cls.zh:
            out[latin] = re.sub(r"[（(].*", "", cls.zh).strip()
    return out


# ---------------------------------------------------------------- 单个名字的正则

def _latin(latin: str) -> str:
    g, s = latin.split(" ", 1)
    return rf"\*(?:{re.escape(g)}|{re.escape(g[0])}\.)\s+{re.escape(s)}\*"


def _pattern(latin: str, zh: str) -> re.Pattern[str]:
    z, lat = re.escape(zh), _latin(latin)
    op, cl = "[（(]", "[）)]"
    fam = rf"(?:{op}(?P<fam_{{}}>[^（）()*]*){cl})?"
    return re.compile(
        rf"(?P<A>{z}{op}(?P<pre>[^（）()*]*?){lat}(?P<post>[^（）()*]*){cl})"       # 中文（*Latin*，科）
        rf"|(?P<D>{z}[ \t]*{lat}{fam.format('d')}(?P<rsp_d>[ \t]*))"              # 中文 *Latin*
        rf"|(?P<B>(?P<lsp_b>[ \t]*){lat}{fam.format('b')}(?P<rsp_b>[ \t]*))"       # 单独的 *Latin*
        rf"|(?P<C>{z}{fam.format('c')})"                                          # 单独的中文名
    )


def _keeps_space(ch: str) -> bool:
    return bool(ch) and ch != "\n" and not re.match(rf"[{_CJK}]", ch)


def _is_family(s: str | None) -> bool:
    return bool(s and _FAMILY.search(s))


def _with_latin(zh: str, latin: str, fam: str | None) -> str:
    """首现的规范写法：科名括注并进去，其他括注原样保留在后面。"""
    if fam is not None and _is_family(fam):
        return f"{zh}（*{latin}*，{fam}）"
    return f"{zh}（*{latin}*）" + (f"（{fam}）" if fam is not None else "")


def _without_latin(zh: str, fam: str | None) -> str:
    return zh + (f"（{fam}）" if fam is not None else "")


def _fix_unit(text: str, names: dict[str, str], label: str, changes: list[Change]) -> str:
    """一个单元（一页或一条图注）：每个名字第一次出现规范为「中文（*Latin*）」，之后只留中文。"""
    for latin, zh in sorted(names.items(), key=lambda kv: -len(kv[1])):
        state = {"first": True}

        def repl(m: re.Match[str], latin: str = latin, zh: str = zh, state: dict[str, bool] = state) -> str:
            src = m.group(0)
            first = state["first"]
            state["first"] = False
            if m.group("A"):
                pre, post = m.group("pre"), m.group("post")
                if first:
                    new = f"{zh}（{pre}*{latin}*{post}）"
                    kind = "expand-latin"
                else:
                    rest = "，".join(x for x in (pre.strip(" ，,；;"), post.strip(" ，,；;")) if x)
                    new, kind = (f"{zh}（{rest}）" if rest else zh), "drop-latin"
            elif m.group("D") or m.group("B"):
                key = "d" if m.group("D") else "b"
                fam, rsp = m.group(f"fam_{key}"), m.group(f"rsp_{key}")
                lsp = "" if key == "d" else m.group("lsp_b")
                before_ch = m.string[m.start() - 1] if m.start() > 0 else ""
                after_ch = m.string[m.end()] if m.end() < len(m.string) else ""
                lsp = lsp if _keeps_space(before_ch) else ""   # 中文（或行首、行尾）旁不留空格，西文旁保留
                rsp = rsp if _keeps_space(after_ch) else ""
                if first:
                    new, kind = _with_latin(zh, latin, fam), "add-latin"
                else:
                    new, kind = _without_latin(zh, fam), "drop-latin"
                new = lsp + new + rsp
            else:                                          # C：单独的中文名
                fam = m.group("fam_c")
                if first:
                    new, kind = _with_latin(zh, latin, fam), "add-latin"
                else:
                    return src
            if new != src:
                changes.append(Change(label, zh, kind, _ctx(m.string, m.start(), m.end()), _ctx_after(m.string, m, new)))
            return new

        text = _pattern(latin, zh).sub(repl, text)
    return text


def _ctx(s: str, a: int, b: int, w: int = 6) -> str:
    return (s[max(0, a - w):a] + s[a:b] + s[b:b + w]).replace("\n", " ")


def _ctx_after(s: str, m: re.Match[str], new: str, w: int = 6) -> str:
    return (s[max(0, m.start() - w):m.start()] + new + s[m.end():m.end() + w]).replace("\n", " ")


# ---------------------------------------------------------------- 分单元处理

def fix_text(text: str, names: dict[str, str], unit: str = "page") -> tuple[str, list[Change]]:
    """返回 (修正后的文本, 改动列表)。unit：page＝按页码标记分页；paragraph＝每个空行分隔的段（图注）；whole＝整篇一页。
    page 但文中没有页码标记：抛 NoPageMarkers。"""
    changes: list[Change] = []
    if not names:
        return text, changes
    spans: list[tuple[int, int, str]] = []
    if unit == "whole":
        spans = [(0, len(text), "全文")]
    elif unit == "paragraph":
        pos, n = 0, 0
        for m in list(re.finditer(r"\n[ \t]*\n+", text)) + [None]:
            end = len(text) if m is None else m.start()
            if text[pos:end].strip():
                n += 1
                spans.append((pos, end, f"段 {n}"))
            if m is not None:
                pos = m.end()
    elif unit == "page":
        marks = list(PAGE_MARK.finditer(text))
        if not marks:
            raise NoPageMarkers("文中没有页码标记 <!-- p.N -->")
        bounds = [(0, marks[0].start(), "（首个页码标记之前）")]
        for i, m in enumerate(marks):
            bounds.append((m.end(), marks[i + 1].start() if i + 1 < len(marks) else len(text), m.group(1)))
        spans = [(a, b, lab) for a, b, lab in bounds if text[a:b].strip()]
    else:
        raise ValueError(f"unit 只能是 page、paragraph 或 whole：{unit}")
    out, pos = [], 0
    for a, b, lab in spans:
        out.append(text[pos:a])
        out.append(_fix_unit(text[a:b], names, lab, changes))
        pos = b
    out.append(text[pos:])
    return "".join(out), changes


def auto_unit(path: str | Path) -> str:
    name = Path(path).name.lower()
    return "paragraph" if ("图注" in name or "caption" in name) else "page"


def collect_names(text: str, names_file: str | Path | None = None, yiku_domain: str | None = "分类学",
                  db: str | Path | None = None) -> dict[str, str]:
    """名单：yiku HARD 种名（可关）再叠加 TSV（TSV 优先）。"""
    names: dict[str, str] = {}
    if yiku_domain:
        names.update(yiku_names(text, yiku_domain, db=db))
    if names_file:
        got, _bad = load_names(names_file)
        names.update(got)
    return names


# ---------------------------------------------------------------- 命令行

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="有中文名的种：按原书页规范拉丁名（首现「中文（*拉丁*）」，同页再现只写中文）")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--names", help="TSV：拉丁名<TAB>中文名")
    ap.add_argument("--no-yiku", action="store_true", help="不去 yiku 查 HARD 种名，只用 --names")
    ap.add_argument("--domain", default="分类学", help="yiku 领域")
    ap.add_argument("--unit", choices=["auto", "page", "paragraph", "whole"], default="auto",
                    help="auto＝文件名含「图注」/caption 按段落（每条图注一个单元），否则按页码标记；whole＝整篇当一页（不推荐）")
    ap.add_argument("--fix", action="store_true", help="写回文件（先备份为 <文件>.bak-species，已有备份不覆盖）")
    ap.add_argument("-o", "--out", help="另存为（只能配单个输入文件；不备份）")
    a = ap.parse_args(argv)
    if a.out and len(a.files) != 1:
        ap.error("-o 只能配一个输入文件")
    code = 0
    for f in a.files:
        p = Path(f)
        text = p.read_text(encoding="utf8")
        try:
            names = collect_names(text, a.names, None if a.no_yiku else a.domain)
        except (FileNotFoundError, ImportError) as exc:
            print(f"{p.name}：取不到 yiku 种名（{exc}）；用 --names 给名单或 --no-yiku", file=sys.stderr)
            return 2
        unit = auto_unit(p) if a.unit == "auto" else a.unit
        try:
            new, changes = fix_text(text, names, unit)
        except NoPageMarkers:
            print(f"{p.name}：没有页码标记 <!-- p.N -->，无法按原书页处理。请从带页码标记的原文重译，或确认整篇只算一页后加 "
                  "--unit whole（整篇只保留第一次的拉丁名，一般不是想要的）", file=sys.stderr)
            return 2
        print(f"{p.name}：名单 {len(names)} 个种，按{ {'page': '页', 'paragraph': '段（每条图注一个单元）', 'whole': '整篇'}[unit] }，"
              f"待改 {len(changes)} 处")
        for c in changes:
            print("  " + c.line())
        if not changes:
            continue
        if a.out:
            Path(a.out).write_text(new, encoding="utf8")
            print(f"  已另存 {a.out}")
        elif a.fix:
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
