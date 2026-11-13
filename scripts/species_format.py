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
  python3 species_format.py 译文/body_直译初译.md                                           # 自动找 ../src_en/body.txt 核对拉丁名
  python3 species_format.py 译文.md --src 原文.txt                                          # 指定原文（带同样的页码标记）
核对原文：补拉丁名（给只写中文名的种加「（*Latin*）」）前，该拉丁名（或 OCR 近似写法）必须出现在对应原书页的英文原文里，
  否则不补；一个中文名对应多个拉丁写法（OCR 变体）时只取与原文该页一致的那一个，同一处从不并列两个。没有原文时按旧办法（不核对），并提示。
名单来源（可叠加，TSV 优先）：
  --names FILE   TSV：拉丁名<TAB>中文名，# 开头为注释（两列顺序写反也认）
  yiku           默认再按 --domain 去 yiku 查文中斜体双名（*Genus species*），只收 HARD 译名（classify 规则）；--no-yiku 关闭
识别的写法：「中文（*Latin*）」「中文（*Latin*，科…）」「中文 *Latin*」、单独的 *Latin* 或 *G. species*（缩写）、单独的中文名。
不改的情形：中文名后紧跟阶元后缀（索沙蚕属、吻沙蚕科、…类）或落在更长的已知类群名里（longest-match，已知名＝yiku 的属/科/种名＋名单）；
中文名后已跟着别的 *拉丁名*（不叠加第二个括号）；已在括号里的「（欧文虫 *Owenia fusiformis*）」不再套括号；yiku 里还对应非拉丁英文词的通名（如 沙蚕 ↔ sand worm）。
拉丁名后的 [OCR?] 标记保留。
括号里除拉丁名外还有引证、科名、图号、嵌套括号时（「中文（*Latin*，Rouse, 1986）」），同页重复只去掉拉丁名和它的一个分隔符，其余原样保留。
保险：写出前核对改前改后「作者, 年份」引证、所有年份记号、「图 N」引用的多重集必须一致，不一致则该文件中止（退出码 2，不写出）。
局限：只认斜体（*…*）的拉丁名；不认 *Genus species* 后紧跟的命名人（Sars, 1851）。修正是确定性的字符串改写，改完建议复读一遍。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from direct_mode import PAGE_MARK

BACKUP_SUFFIX = ".bak-species"
_CJK = r"一-鿿　-〿＀-￯"
_FAMILY = re.compile(r"科|[A-Za-z]+idae|[A-Za-z]+ida\b")


class NoPageMarkers(ValueError):
    """按页处理却没有页码标记：整篇当一页会误删后面各页的拉丁名，所以拒绝。"""


class CitationLost(ValueError):
    """改写前后「作者, 年份」引证或「图 N」引用的多重集不一致：改写误删了引证，拒绝写出。"""


# 引证与图号的指纹：只比较「改前改后是否一样」，所以宁可多收（所有年份、所有图号），不求精确解析。
_YEAR = r"(?<!\d)(?:1[5-9]\d\d|20\d\d)(?!\d)[a-z]?"
_CITE = re.compile(rf"([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*)(\s+et\s+al\.?)?\s*[,，]?\s*({_YEAR})")
_FIG = re.compile(r"图\s*\d+[A-Za-z]?(?:\s*[–—\-~、，,]\s*\d+[A-Za-z]?)*")


def citation_signature(text: str) -> Counter[tuple[str, ...]]:
    """文本里的（作者, 年份）、所有年份记号、「图 N」引用的多重集（空白不计）。"""
    sig: Counter[tuple[str, ...]] = Counter()
    for author, etal, year in _CITE.findall(text):
        sig[("cite", author, "et al." if etal else "", year)] += 1
    for year in re.findall(_YEAR, text):
        sig[("year", year)] += 1
    for fig in _FIG.findall(text):
        sig[("fig", re.sub(r"\s+", "", fig))] += 1
    return sig


def _fmt_sig(c: Counter[tuple[str, ...]]) -> str:
    return "、".join(" ".join(filter(None, k[1:])) + (f"×{n}" if n > 1 else "") for k, n in sorted(c.items()))


def check_preserved(before: str, after: str) -> None:
    """改写不得增删引证或图号：多重集不同就抛 CitationLost（消息列出少了/多了什么）。"""
    a, b = citation_signature(before), citation_signature(after)
    if a == b:
        return
    lost, extra = a - b, b - a
    raise CitationLost("改写会改动引证/图号：" + (f"丢失 {_fmt_sig(lost)}；" if lost else "")
                       + (f"多出 {_fmt_sig(extra)}；" if extra else ""))


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


# ---------------------------------------------------------------- yiku：已知类群名、通名

_RANK_STEM = re.compile(r"^(.{2,}?)[亚总超]?(?:科|属|目|纲|门|族)$")
_LATIN_EN = re.compile(r"[A-Z][a-z]+(?: [a-z]+)?")            # 属名、双名（后面可带命名人）
_COMMON_EN = re.compile(r"[a-z][a-z' \-]{2,}")                 # 小写开头的英文普通词：sand worm
_ONLY_CJK = re.compile(r"[一-鿿]{2,}")


def _yiku_con(domain: str, con: Any = None, db: str | Path | None = None) -> Any:
    import importlib
    D = importlib.import_module("yiku.db")
    if con is None:
        path = Path(db) if db else D.default_path()
        if not path.exists():
            raise FileNotFoundError(f"找不到 yiku 库 {path}")
        con = D.connect(path)
    return con


def yiku_known_names(con: Any, domain: str = "分类学") -> set[str]:
    """yiku 里已知的中文类群名，供 longest-match 用：拉丁名是属/种名的，或中文名带科属目…后缀的，连同去掉后缀的词干
    （索沙蚕属 → 索沙蚕）。普通术语（鳃、上皮）不收。"""
    known: set[str] = set()
    for en, zh in con.execute("SELECT en, zh FROM terms WHERE domain = ?", (domain,)):
        zh = re.sub(r"[（(].*", "", zh).strip()
        if not _ONLY_CJK.fullmatch(zh):
            continue
        stem = _RANK_STEM.match(zh)
        if stem:
            known.add(zh)
            known.add(stem.group(1))
        elif _LATIN_EN.match(en.strip()):
            known.add(zh)
    return known


def yiku_generic_names(con: Any, domain: str, names: dict[str, str]) -> set[str]:
    """名单里的中文名，若 yiku 里还对应小写开头的英文普通词（沙蚕 ↔ sand worm），视为通名：不给它补种名拉丁名。"""
    generic: set[str] = set()
    for zh in set(names.values()):
        for (en,) in con.execute("SELECT en FROM terms WHERE zh = ? AND domain = ?", (zh, domain)):
            if _COMMON_EN.fullmatch(en.strip()):
                generic.add(zh)
                break
    return generic


def yiku_context(names: dict[str, str], domain: str = "分类学", con: Any = None,
                 db: str | Path | None = None) -> tuple[set[str], set[str]]:
    """(已知类群名, 通名)。取不到 yiku 时抛 FileNotFoundError/ImportError，由调用方决定怎么提示。"""
    con = _yiku_con(domain, con, db)
    return yiku_known_names(con, domain), yiku_generic_names(con, domain, names)


# ---------------------------------------------------------------- 原文核对

_BINOM = re.compile(r"\b([A-Z][a-z]+)\s+([a-z]{3,})\b")


def split_pages(text: str) -> dict[str, str]:
    """按页码标记把带标记的文本切成 {页码标签: 该页文本}；首个标记之前的文字归 ""。同标签的页拼在一起。"""
    pages: dict[str, str] = {}
    marks = list(PAGE_MARK.finditer(text))
    first = text[:marks[0].start()] if marks else text
    pages[""] = first
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages[m.group(1)] = pages.get(m.group(1), "") + "\n" + text[m.end():end]
    return pages


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _on_page(latin: str, page: str, close: bool = False) -> bool:
    """该双名（或其缩写 G. species）是否出现在原文页里；close＝允许 OCR 近似（同属、种加名编辑距离 ≤2，种加名 ≥6 字母）。"""
    g, s = latin.split(" ", 1)
    if not close:
        return bool(re.search(rf"\b(?:{re.escape(g)}|{re.escape(g[0])}\.)\s*{re.escape(s)}\b", page))
    if len(s) < 6:
        return False
    return any(_lev(g2, g) <= 1 and _lev(s2, s) <= 2 and (g2, s2) != (g, s) for g2, s2 in _BINOM.findall(page))


def _verified(latins: list[str], page: str | None) -> list[str]:
    """原文页里有的候选（精确优先，其次 OCR 近似）。page 为 None＝没有原文，不核对，全部算数。"""
    if page is None:
        return list(latins)
    exact = [x for x in latins if _on_page(x, page)]
    return exact or [x for x in latins if _on_page(x, page, close=True)]


# ---------------------------------------------------------------- 单个名字的正则

_OCR = r"(?:\[OCR\?\])?"
# 紧跟中文名的阶元后缀：该词是更高阶元名（吻沙蚕科、索沙蚕属…），不是种名。「属于」「目前」「类似」不算。
_RANK_AFTER = re.compile(r"[亚总超]?(?:科(?![学研])|属(?![于性])|目(?![前的标录镜击测])|纲|门|族)|类(?![似型别比])")


def _lat_alt(latins: list[str]) -> str:
    return "|".join(rf"(?:{re.escape(g)}|{re.escape(g[0])}\.)\s+{re.escape(s)}" for g, s in (x.split(" ", 1) for x in latins))


def _pattern(latins: list[str], zh: str) -> re.Pattern[str]:
    z, alt = re.escape(zh), _lat_alt(latins)
    op, cl = "[（(]", "[）)]"
    fam = rf"(?:{op}(?P<fam_{{}}>[^（）()*]*){cl})?"
    # 括号里除拉丁名外可有引证、科名、图号、嵌套括号（Rouse, 1986）、别的斜体名：只动拉丁名，其余原样（见 _body_without_latin）
    nested = rf"{op}[^（）()]*{cl}"
    return re.compile(
        rf"(?P<A>{z}{op}(?P<pre>(?:[^（）()*]|{nested})*?)\*(?P<lt_a>{alt})\*(?P<ocr_a>{_OCR})"
        rf"(?P<post>(?:[^（）()]|{nested})*?){cl})"                                                           # 中文（*Latin*，科）
        rf"|(?P<D>{z}[ \t]*\*(?P<lt_d>{alt})\*(?P<ocr_d>{_OCR}){fam.format('d')}(?P<rsp_d>[ \t]*))"          # 中文 *Latin*
        rf"|(?P<B>(?P<lsp_b>[ \t]*)\*(?P<lt_b>{alt})\*(?P<ocr_b>{_OCR}){fam.format('b')}(?P<rsp_b>[ \t]*))"   # 单独的 *Latin*
        rf"|(?P<E>{z}(?=[（(]\*|[ \t]*\*[A-Z]))"                                                              # 中文后已跟别的拉丁名
        rf"|(?P<C>{z}{fam.format('c')})"                                                                      # 单独的中文名
    )


def _keeps_space(ch: str) -> bool:
    return bool(ch) and ch != "\n" and not re.match(rf"[{_CJK}]", ch)


def _is_family(s: str | None) -> bool:
    return bool(s and _FAMILY.search(s))


def _with_latin(zh: str, latin: str, fam: str | None, ocr: str = "") -> str:
    """首现的规范写法：科名括注并进去，其他括注原样保留在后面；[OCR?] 留在拉丁名之后。"""
    if fam is not None and _is_family(fam):
        return f"{zh}（*{latin}*{ocr}，{fam}）"
    return f"{zh}（*{latin}*{ocr}）" + (f"（{fam}）" if fam is not None else "")


def _without_latin(zh: str, fam: str | None, ocr: str = "") -> str:
    return zh + ocr + (f"（{fam}）" if fam is not None else "")


_SEP = "，,；;"
_NESTED = re.compile(r"[（(][^（）()]*[）)]")


def _body_without_latin(pre: str, post: str) -> str:
    """括号里拉丁名两侧的内容 pre、post → 去掉拉丁名及其一个分隔符后的括号内文本；其余字符（引证、图号、科名）一概不动。"""
    a, b = pre.rstrip(" \t"), post.lstrip(" \t")
    if a and b:
        if a[-1] in _SEP:
            b = b.lstrip(_SEP + " \t")                          # 保留拉丁名前面那个分隔符
        elif b[0] not in _SEP:
            a += "，"
    return (a + b).strip(" \t" + _SEP)


def _unbracket_drop(zh: str, ocr: str, pre: str, post: str) -> str:
    """同页重复：中文（…*Latin*…）→ 中文（余下内容）；余下恰是一个嵌套括号（Rouse, 1986）时直接接在中文名后，不再套一层。"""
    rest = _body_without_latin(pre, post)
    if not rest:
        return zh + ocr
    if _NESTED.fullmatch(rest):
        return zh + ocr + "（" + rest[1:-1] + "）"
    return zh + ocr + f"（{rest}）"


def _inside_paren(s: str, pos: int) -> bool:
    """pos 处是否在尚未闭合的括号里（只看所在行）。"""
    seg = s[s.rfind("\n", 0, pos) + 1:pos]
    return len(re.findall(r"[（(]", seg)) > len(re.findall(r"[）)]", seg))


def _protected(s: str, start: int, zh: str, longer: list[str]) -> bool:
    """s[start:] 开头的 zh 是否落在某个更长的已知名里（longest-match）。"""
    for p in longer:
        k = p.find(zh)
        while k != -1:
            if start - k >= 0 and s.startswith(p, start - k):
                return True
            k = p.find(zh, k + 1)
    return False


def _full_latin(raw: str, latins: list[str]) -> str:
    """文中斜体拉丁名（可能是 G. species 缩写）→ 名单里对应的完整双名。"""
    g, s = re.split(r"\s+", raw.strip(), maxsplit=1)
    for x in latins:
        xg, xs = x.split(" ", 1)
        if xs == s and (xg == g or (g.endswith(".") and xg.startswith(g[0]))):
            return x
    return latins[0]


def _pick(latins: list[str], text: str, page: str | None) -> str | None:
    """补拉丁名用哪一个：先取原文该页有的；多个时取译文本单元里最先出现的，其次原文里最先出现的。"""
    ok = _verified(latins, page)
    if not ok:
        return None
    if len(ok) == 1:
        return ok[0]

    def where(x: str, hay: str, star: str) -> int:
        g, s = x.split(" ", 1)
        m = re.search(rf"{star}(?:{re.escape(g)}|{re.escape(g[0])}\.)\s*{re.escape(s)}", hay)
        return m.start() if m else 1 << 30
    in_text = [(where(x, text, r"\*"), i, x) for i, x in enumerate(ok)]
    best = min(in_text)
    if best[0] < 1 << 30:
        return best[2]
    if page is not None:
        return min((where(x, page, ""), i, x) for i, x in enumerate(ok))[2]
    return ok[0]


def _fix_group(text: str, zh: str, latins: list[str], label: str, changes: list[Change], page: str | None,
               longer: list[str]) -> str:
    """一个单元里一个中文名（可对应多个拉丁写法）：第一次出现规范为「中文（*Latin*）」，之后只留中文。"""
    state = {"first": True}
    pick = _pick(latins, text, page)

    def repl(m: re.Match[str]) -> str:
        src = m.group(0)
        s = m.string
        if m.group("B") is None and (_protected(s, m.start(), zh, longer) or _RANK_AFTER.match(s, m.start() + len(zh))):
            return src                                        # 更高阶元名的一部分：不是种
        first = state["first"]
        if m.group("E"):                                      # 中文名后已有别的拉丁名：不叠加；这一处算本页的首现
            state["first"] = False
            return src
        inside = _inside_paren(s, m.start())
        if m.group("A"):
            state["first"] = False
            latin = _full_latin(m.group("lt_a"), latins)
            pre, post, ocr = m.group("pre"), m.group("post"), m.group("ocr_a")
            if first:
                new, kind = f"{zh}（{pre}*{latin}*{ocr}{post}）", "expand-latin"
            else:
                new, kind = _unbracket_drop(zh, ocr, pre, post), "drop-latin"
        elif m.group("D") or m.group("B"):
            if m.group("B"):
                head = s[:m.start("lt_b") - 1].rstrip(" \t")      # 拉丁名紧接在本中文名（或「中文（」）后，却没被 A/D 认出：不动，免得把中文名重复写进括号
                if head.endswith(("（", "(")):
                    head = head[:-1]
                if head.endswith(zh):
                    state["first"] = False
                    return src
            state["first"] = False
            key = "d" if m.group("D") else "b"
            latin = _full_latin(m.group(f"lt_{key}"), latins)
            fam, rsp, ocr = m.group(f"fam_{key}"), m.group(f"rsp_{key}"), m.group(f"ocr_{key}")
            if first and inside:                              # 已在括号里：不再套括号，原样保留
                return src
            lsp = "" if key == "d" else m.group("lsp_b")
            before_ch = s[m.start() - 1] if m.start() > 0 else ""
            after_ch = s[m.end()] if m.end() < len(s) else ""
            lsp = lsp if _keeps_space(before_ch) else ""      # 中文（或行首、行尾）旁不留空格，西文旁保留
            rsp = rsp if _keeps_space(after_ch) else ""
            if first:
                new, kind = _with_latin(zh, latin, fam, ocr), "add-latin"
            else:
                new, kind = _without_latin(zh, fam, ocr), "drop-latin"
            new = lsp + new + rsp
        else:                                                 # C：单独的中文名
            if not first or inside or pick is None:
                return src                                    # 重复；括号里；原文该页没有这个拉丁名：不补
            fam = m.group("fam_c")
            state["first"] = False
            new, kind = _with_latin(zh, pick, fam), "add-latin"
        if new != src:
            changes.append(Change(label, zh, kind, _ctx(s, m.start(), m.end()), _ctx_after(s, m, new)))
        return new

    return _pattern(latins, zh).sub(repl, text)


def _fix_unit(text: str, groups: dict[str, list[str]], label: str, changes: list[Change], page: str | None,
              longer: dict[str, list[str]], generic: set[str]) -> str:
    """一个单元（一页或一条图注）：每个名字第一次出现规范为「中文（*Latin*）」，之后只留中文。"""
    for zh, latins in sorted(groups.items(), key=lambda kv: -len(kv[0])):
        if zh in generic:
            continue
        text = _fix_group(text, zh, latins, label, changes, page, longer[zh])
    return text


def _ctx(s: str, a: int, b: int, w: int = 6) -> str:
    return (s[max(0, a - w):a] + s[a:b] + s[b:b + w]).replace("\n", " ")


def _ctx_after(s: str, m: re.Match[str], new: str, w: int = 6) -> str:
    return (s[max(0, m.start() - w):m.start()] + new + s[m.end():m.end() + w]).replace("\n", " ")


# ---------------------------------------------------------------- 分单元处理

def fix_text(text: str, names: dict[str, str], unit: str = "page", src: str | None = None,
             known: set[str] | None = None, generic: set[str] | None = None) -> tuple[str, list[Change]]:
    """返回 (修正后的文本, 改动列表)。unit：page＝按页码标记分页；paragraph＝每个空行分隔的段（图注）；whole＝整篇一页。
    page 但文中没有页码标记：抛 NoPageMarkers。
    src：英文原文（同样的页码标记）。给了就核对：只有拉丁名出现在对应原书页的原文里才补；没给则不核对。
    known：其他已知中文类群名（属、科、种…），命中落在更长的已知名里就跳过。generic：通名，不补拉丁名。"""
    changes: list[Change] = []
    if not names:
        return text, changes
    groups: dict[str, list[str]] = {}
    for latin, zh in sorted(names.items()):
        groups.setdefault(zh, []).append(latin)
    allk = set(known or ()) | set(groups)
    longer = {zh: sorted((p for p in allk if len(p) > len(zh) and zh in p), key=len, reverse=True) for zh in groups}
    src_pages = split_pages(src) if src is not None else None
    marks = list(PAGE_MARK.finditer(text))
    spans: list[tuple[int, int, str, str | None]] = []       # (起, 止, 标签, 对应原文页标签；None＝整篇原文)
    if unit == "whole":
        spans = [(0, len(text), "全文", None)]
    elif unit == "paragraph":
        pos, n = 0, 0
        for m in list(re.finditer(r"\n[ \t]*\n+", text)) + [None]:
            end = len(text) if m is None else m.start()
            if text[pos:end].strip():
                n += 1
                prev = [mk for mk in marks if mk.start() < pos]
                srclab = (prev[-1].group(1) if prev else "") if marks else None
                spans.append((pos, end, f"段 {n}", srclab))
            if m is not None:
                pos = m.end()
    elif unit == "page":
        if not marks:
            raise NoPageMarkers("文中没有页码标记 <!-- p.N -->")
        bounds = [(0, marks[0].start(), "（首个页码标记之前）", "")]
        for i, m in enumerate(marks):
            bounds.append((m.end(), marks[i + 1].start() if i + 1 < len(marks) else len(text), m.group(1), m.group(1)))
        spans = [(a, b, lab, sl) for a, b, lab, sl in bounds if text[a:b].strip()]
    else:
        raise ValueError(f"unit 只能是 page、paragraph 或 whole：{unit}")
    out, pos = [], 0
    for a, b, lab, srclab in spans:
        page = None if src_pages is None else (src if srclab is None else src_pages.get(srclab, ""))
        out.append(text[pos:a])
        out.append(_fix_unit(text[a:b], groups, lab, changes, page, longer, set(generic or ())))
        pos = b
    out.append(text[pos:])
    return "".join(out), changes


def auto_src(path: str | Path) -> Path | None:
    """译文/body_直译初译.md → 同书的 src_en/body.txt；找不到返回 None。"""
    p = Path(path).resolve()
    for base in (p.parent.parent, p.parent):
        cand = base / "src_en" / (p.name.split("_")[0].split(".")[0] + ".txt")
        if cand.exists():
            return cand
    return None


def auto_unit(path: str | Path) -> str:
    name = Path(path).name.lower()
    return "paragraph" if ("图注" in name or "caption" in name) else "page"


_PAIR = re.compile(r"([\u4e00-\u9fff]{2,12})（\*([A-Z][a-zë]+ [a-z][a-z\-]+)\*")
# 名前常被正则连带吞进的句首虚词（「另见暗蛇潜虫」「为覆瓦哈鳞虫」「检查了微怪鳞虫」）
_LEAD = re.compile(r"^(?:例如|如|即|为|是|与|和|及|另见|见|检查了|研究了|在|对|把|将|其一为|其中)+")


# 种的中文俗名的形状：2–8 个汉字、不含虚词/动词字、以常见通名字结尾。正则会把名前整段从句吞进来
# （「有的位于基部并伸入体腔（*Anaitides mucosa*」），这些捕获不是名字。已由 yiku / --names 确认的名字不套此规则。
_FUNC_CHARS = frozenset("的并有在和与于是为被将及或位伸入等而且从把由该此了着过但则即如见以可也都还已能使所当若")
_VERNACULAR_HEADS = frozenset("虫蚕蚓蛭蛰介螺贝蟹虾鱼蛤蚌蛎蛄蛇蛛蝎蝇蚊蚁蜂蝶蛾星胆参母螅蛸鲸鳗鲨龟蜗蠕蚶蛏蜊蛉")
_VERNACULAR_LEN = (2, 8)


def _looks_like_vernacular(zh: str) -> bool:
    lo, hi = _VERNACULAR_LEN
    return (lo <= len(zh) <= hi and re.fullmatch(r"[\u4e00-\u9fff]+", zh) is not None
            and not _FUNC_CHARS.intersection(zh) and zh[-1] in _VERNACULAR_HEADS)


def _longest_known_suffix(cap: str, known: set[str]) -> str:
    return max((k for k in known if len(k) >= 2 and cap.endswith(k)), key=len, default="")


def _resolve_caps(caps: list[str], known: set[str]) -> str | None:
    """同一拉丁名的若干次捕获 → 中文名；无法确定（一名多译等）返回 None。"""
    hits = [_longest_known_suffix(c, known) for c in caps]
    if any(hits):                                       # 1. 已知中文名（yiku / --names）：取最长的、作为捕获串后缀的
        found = {h for h in hits if h}
        if len(found) != 1:
            return None
        zh = found.pop()
        return zh if all(c.endswith(zh) for c in caps) else None
    clean = [_LEAD.sub("", c) for c in caps]            # 2./3. 未知：先剥句首虚词，再取各次出现的公共后缀
    if min(map(len, clean)) < 2:
        return None
    suf = os.path.commonprefix([c[::-1] for c in clean])[::-1]
    # 公共后缀恰是某一次的整串（「暗蛇潜虫」与「该种暗蛇潜虫」）才算一致；否则要求后缀 ≥3 字，
    # 免得「铜色巢沙蚕」与「另一种沙蚕」被并成「沙蚕」（一名多译，不收）
    if len(suf) < 2 or (suf not in clean and len(suf) < 3):
        return None
    # 走到这里说明捕获串都不以已知名结尾（否则第 1 步已取走），故只能凭形状判断是不是俗名
    return suf if _looks_like_vernacular(suf) else None


def harvest_pairs(text: str, known: set[str] | frozenset[str] | None = None,
                  skipped: dict[str, list[str]] | None = None) -> dict[str, str]:
    """从译文收集「中文名（*Genus species*）」对子。

    正则会连带吞进名前的汉字，故：优先按已知中文名（known＝yiku / --names 的中文名）取最长后缀；
    否则取同一拉丁名各次出现的公共后缀；只出现一次时剥句首虚词（须 ≥2 字）。未经已知名确认的，还须形如俗名
    （2–8 字、不含的/并/有/在…等虚词字、以虫/蚕/蚓/蛭/螺/蟹…结尾），否则是被吞进来的从句，不收。
    一个拉丁名对应互相冲突的中文名、或确定不了名字的，不收；skipped 若给出则记下 {拉丁名: 捕获串}（交人工）。"""
    seen: dict[str, list[str]] = {}
    for zh, latin in _PAIR.findall(text):
        seen.setdefault(latin, []).append(zh)
    out: dict[str, str] = {}
    for latin, caps in seen.items():
        zh = _resolve_caps(caps, set(known or ()))
        if zh:
            out[latin] = zh
        elif skipped is not None:
            skipped[latin] = sorted(set(caps))
    return out


def collect_names(text: str, names_file: str | Path | None = None, yiku_domain: str | None = "分类学",
                  db: str | Path | None = None, skipped: dict[str, list[str]] | None = None) -> dict[str, str]:
    """名单：译文里已写成「中文（*Genus species*）」的对子 → yiku HARD 种名（可关）→ TSV（后者优先）。
    译文自带的对子覆盖经异名匹配得来、yiku 里没有该拉丁名的种（如 暗蛇潜虫 *Podarke obscura*）。"""
    yk = yiku_names(text, yiku_domain, db=db) if yiku_domain else {}
    tsv = load_names(names_file)[0] if names_file else {}
    names = harvest_pairs(text, set(yk.values()) | set(tsv.values()), skipped)
    names.update(yk)
    names.update(tsv)
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
    ap.add_argument("--src", help="英文原文（带同样的页码标记），用来核对拉丁名是否出现在对应原书页；缺省自动找 <书>/src_en/<文件名首段>.txt")
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
            skipped: dict[str, list[str]] = {}
            names = collect_names(text, a.names, None if a.no_yiku else a.domain, skipped=skipped)
        except (FileNotFoundError, ImportError) as exc:
            print(f"{p.name}：取不到 yiku 种名（{exc}）；用 --names 给名单或 --no-yiku", file=sys.stderr)
            return 2
        for latin, caps in skipped.items():
            print(f"{p.name}：*{latin}* 的中文名不确定，未收（{'、'.join(caps)}），请人工核对", file=sys.stderr)
        unit = auto_unit(p) if a.unit == "auto" else a.unit
        src_path = Path(a.src) if a.src else auto_src(p)
        src = src_path.read_text(encoding="utf8") if src_path else None
        if src is None:
            print(f"{p.name}：没有找到英文原文（--src 或 <书>/src_en/），无法核对拉丁名是否出现在对应原书页；按未核对处理", file=sys.stderr)
        known: set[str] = set()
        generic: set[str] = set()
        if not a.no_yiku:
            try:
                known, generic = yiku_context(names, a.domain)
            except (FileNotFoundError, ImportError) as exc:
                print(f"{p.name}：取不到 yiku 类群名（{exc}），longest-match 只用名单内的名字", file=sys.stderr)
        try:
            new, changes = fix_text(text, names, unit, src=src, known=known, generic=generic)
        except NoPageMarkers:
            print(f"{p.name}：没有页码标记 <!-- p.N -->，无法按原书页处理。请从带页码标记的原文重译，或确认整篇只算一页后加 "
                  "--unit whole（整篇只保留第一次的拉丁名，一般不是想要的）", file=sys.stderr)
            return 2
        try:
            check_preserved(text, new)
        except CitationLost as exc:
            print(f"{p.name}：{exc}。本文件中止，未写出；请把该处报给维护者", file=sys.stderr)
            code = 2
            continue
        print(f"{p.name}：名单 {len(names)} 个种，按{ {'page': '页', 'paragraph': '段（每条图注一个单元）', 'whole': '整篇'}[unit] }，"
              f"{'核对原文 ' + src_path.name + '，' if src_path else '未核对原文，'}待改 {len(changes)} 处")
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
