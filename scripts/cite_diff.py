#!/usr/bin/env python3
"""引文与图号对照（只报告，不修改）：英文原文 vs 中文译文。

用法: cite_diff.py --en body.txt [--en captions.txt ...] --zh 译文.md [--zh 图注译文.md ...] --out cite_diff.tsv
                   [--noise cite_noise.tsv] [--alias alias.tsv] [--zh-stop 正则] [--align]
  比较 (第一作者姓, 年份) 的多重集，以及图号（展开范围，忽略分图字母）的多重集；写 TSV，打印计数。
  退出码：0 没有真差异；1 有真差异；2 参数或文件错误。

先把下列噪声归一，只留真差异：
  * 作者连接词 and / & / 与 / 和 / 及 / 、；et al. / etal. / 等 / 等人；所有格 's / ’s
  * 全角括号逗号（（ ） ， 、 ；）；年份列表 1985, 1988 / 1980a,b / 1980a, 1980b 合并为同年
  * 英文 OCR 断词 Gar-diner（含跨行跨页）、变音符 ü/ö/ø、连字符有无、OCR 的 @ 代 ø、孤立下划线、198 1a
  * 中文稿标题行（首个 # 行，可能含 Barnes & Harrison 1992）、[OCR?] 标记、HTML 注释（含 <!-- p.N -->）、*斜体*
  * 非作者的大写词（In 1980 / Fig. 3 / 月份）
  * 英文 OCR：Fig. 81 实为 Fig. 8I（按英文图注里出现的图号集合判断）
  * 图号：逐词扫描（只吃编号、分图字母、逗号/和/连字符/至），不把后文数字吞成图号
真差异分四类（都计入退出码）：citation 中文缺失/多出；citation-strict 第二作者或年份字母后缀不同
（只在第一作者+年份无差异时报）；figure 图号缺失/多出；figure-strict 分图字母不同。
「变体?」＝同年份、名字相似度 >=0.75（疑似 OCR/拼写），单列、不计入真差异，须人工确认。
已人工核实的残余差异写进 --noise 文件（TSV，列：类型、对象、英文次数、中文次数、原因），次数必须与当前计数完全一致才算
「已确认噪声」，之后若再出现新增差异会重新报警。--noise 缺省取 --out 同目录的 cite_noise.tsv（有则用）。
--alias：两列 TSV（OCR 键<TAB>规范键，均为小写去变音符），把已确认的 OCR 名字变体并到规范名。
--zh-stop：中文稿里匹配该正则（多行模式）的行及之后全部丢弃，用于去文献表（英文原文不含文献表时）。
--align：另打印英中引文序列的顺序对齐，定位插入/删除位置（图注顺序不同时会嘈杂）。

移植自 Harrison 1992 解剖学工程的 cite_diff（2026-11-14），已去掉具体书目的路径、别名表和文献表标题。"""
from __future__ import annotations

import argparse
import collections
import difflib
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

STOP = set("""In At On By Since From After Before During Until Fig Figs Figure Figures Table Tables Plate Pl Vol
No Of For The See Part Chapter Section Page Pp Eq Group Class Order Family Genus Phylum Subclass
January February March April May June July August September October November December
However Recently Similarly Likewise Thus Therefore Hence Moreover Furthermore Finally Instead Also Metazoa
Zootaxa Journal Bulletin Annals Proceedings Transactions""".split())

NAME = r"[A-Z][A-Za-zÀ-ɏ\-'’]*[A-Za-zÀ-ɏ]"
CONN = r"(?:\s+(?:and|&)\s+|\s*[与和及、]\s*)"
ETAL = r"(?:\s*(?:et\s*al\.?|等人|等))"
YEAR = r"(?:1[6-9]|20)\d\d"
CITE_RE = re.compile(
    rf"(?P<n1>{NAME})(?:'s|’s)?"                       # 第一作者
    rf"(?:{CONN}(?P<n2>{NAME}))?"                        # 第二作者（三作者以上只认首个 X and Y）
    rf"(?:'s|’s)?(?P<etal>{ETAL})?\s*[,，]?\s*[（(\[［]?\s*"
    rf"(?P<yl>{YEAR}[a-z]?(?:\s*[,，、;；]\s*(?:{YEAR}[a-z]?|[a-z](?![A-Za-z])))*)")
PANEL = re.compile(r"[A-Za-z](?![a-z])(?:\s*(?:[–—\-]+|[,，、])\s*[A-Z](?![a-z]))*")
NUM = re.compile(r"(\d{1,3})(?!\d)")
SEP = re.compile(r"\s*(?:[–—\-~～至]+|[,，、;；]|and|&|[与和及])\s*(?=\d)")
SEP2 = re.compile(r"\s*(?:[,，、;；]|and|&|[与和及])\s*(?=\d)")
FIG_START = re.compile(r"(?:Figs?\.?|Figures?|图)\s*(?=\d)")

Alias = dict[str, str]


def canon(name: str, alias: Alias | None = None) -> str:
    n = name.replace("’", "'")
    n = re.sub(r"'s$", "", n)
    n = re.sub(r"(?<=[a-z])-(?=[a-z])", "", n)          # OCR 断词 Gar-wood
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.replace("ø", "o").replace("Ø", "O").replace("æ", "ae").replace("ß", "ss")
    n = n.lower().replace("-", "").replace("'", "")
    return (alias or {}).get(n, n)


def cites(t: str, alias: Alias | None = None) -> list[tuple[tuple[str, str], int]]:
    out: list[tuple[tuple[str, str], int]] = []
    for m in CITE_RE.finditer(t):
        if m.group("n1") in STOP:
            continue
        for y in sorted(set(re.findall(YEAR, m.group("yl")))):
            out.append(((canon(m.group("n1"), alias), y), m.start()))
    return out


def cites_strict(t: str, alias: Alias | None = None) -> list[tuple[tuple[str, str, str], int]]:
    """严格层：(第一作者, 第二作者或 *=et al., 年份+字母后缀)。1980a,b 展开为 1980a、1980b。"""
    out: list[tuple[tuple[str, str, str], int]] = []
    for m in CITE_RE.finditer(t):
        if m.group("n1") in STOP:
            continue
        second = canon(m.group("n2"), alias) if m.group("n2") else ("*" if m.group("etal") else "")
        cur = None
        for ym in re.finditer(rf"({YEAR})([a-z]?)|(?<![A-Za-z])([a-z])(?![A-Za-z])", m.group("yl")):
            if ym.group(1):
                cur, letter = ym.group(1), ym.group(2)
            else:
                letter = ym.group(3)
            if cur:
                out.append(((canon(m.group("n1"), alias), second, cur + letter), m.start()))
    return out


def expand_panels(ps: str) -> list[str]:
    """'D,E' -> D,E ; 'D-F' -> D,E,F ; 'A–C' -> A,B,C ; '' -> ['']"""
    if not ps:
        return [""]
    out: list[str] = []
    for part in (x.strip() for x in re.split(r"[,，、]", ps) if x.strip()):
        mm = re.fullmatch(r"([A-Za-z])\s*[–—\-]+\s*([A-Za-z])", part)
        if mm and ord(mm.group(2).upper()) > ord(mm.group(1).upper()):
            out += [chr(c) for c in range(ord(mm.group(1).upper()), ord(mm.group(2).upper()) + 1)]
        else:
            out += [sub[0].upper() for sub in re.split(r"\s*[–—\-]+\s*", part) if sub]
    return out or [""]


def _fig_refs(t: str, caption_nums: set[int] | None) -> list[tuple[int, str, int]]:
    out: list[tuple[int, str, int]] = []
    for m in FIG_START.finditer(t):
        pos = m.end()
        while True:
            mm = NUM.match(t, pos)
            if not mm:
                break
            n = int(mm.group(1))
            pos = mm.end()
            pm = PANEL.match(t, pos)
            panels = ""
            if pm:
                panels = pm.group(0)
                pos = pm.end()
            out.append((n, panels, m.start()))
            sm = SEP.match(t, pos)
            if not sm:
                break
            sep = sm.group(0)
            pos = sm.end()
            if re.search(r"[–—\-~～至]", sep):
                mm2 = NUM.match(t, pos)
                if mm2 and 0 < int(mm2.group(1)) - n < 60:
                    out += [(k, "", m.start()) for k in range(n + 1, int(mm2.group(1)) + 1)]
                    pos = mm2.end()
                    pm = PANEL.match(t, pos)
                    if pm:
                        pos = pm.end()
                    sm2 = SEP2.match(t, pos)
                    if not sm2:
                        break
                    pos = sm2.end()
    fixed = []
    for n, ps, p in out:
        if caption_nums and n >= 10 and n % 10 == 1 and n not in caption_nums and (n // 10) in caption_nums:
            n, ps = n // 10, "I" + ps          # OCR：Fig. 81 = Fig. 8I
        fixed.append((n, ps, p))
    return fixed


def figs(t: str, caption_nums: set[int] | None = None) -> list[tuple[int, int]]:
    """[(图号, 位置)]，范围展开，忽略分图字母。"""
    return [(n, p) for n, _, p in _fig_refs(t, caption_nums)]


def figs_strict(t: str, caption_nums: set[int] | None = None) -> list[tuple[tuple[int, str], int]]:
    """[((图号, 分图字母), 位置)]。"""
    return [((n, lt), p) for n, ps, p in _fig_refs(t, caption_nums) for lt in expand_panels(ps)]


def clean(t: str, zh: bool = False) -> str:
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = t.replace("[OCR?]", "").replace("［OCR?］", "")
    t = t.replace("*", "")
    t = re.sub(r"(?<=[A-Za-z])- (?=[A-Z])", "-", t)                                  # OCR：Voss- Foucart
    if not zh:
        t = re.sub(r"(?<=[A-Za-z])-\s*[_—\-]*\s*(?=[a-z])", "", t)                  # OCR 断词（含跨页）：Jamie-  _—  son
    t = re.sub(r"(?<=[A-Z])@(?=[a-z])", "ø", t)                                      # OCR：N@rrevang
    t = re.sub(r"(?<=\s)_(?=\s)", "", t)                                             # OCR 孤立下划线：and _ Grassle
    t = re.sub(r"(?<=[(,;\s])(1[6-9]\d) (\d)(?=[a-z]?[,;)\s])", r"\1\2", t)          # OCR：198 1a
    return t


def snippet(t: str, pos: int, w: int = 45) -> str:
    return t[max(0, pos - w): pos + w].replace("\n", " ").replace("\t", " ")


def parse_noise(text: str) -> dict[tuple[str, str, str, str], str]:
    out: dict[tuple[str, str, str, str], str] = {}
    for ln in text.splitlines()[1:]:
        c = ln.split("\t")
        if len(c) >= 5:
            out[(c[0], c[1], c[2], c[3])] = c[4]
    return out


def parse_alias(text: str) -> Alias:
    out: Alias = {}
    for ln in text.splitlines():
        c = ln.split("\t")
        if len(c) >= 2 and c[0].strip() and not c[0].startswith("#"):
            out[c[0].strip()] = c[1].strip()
    return out


@dataclass
class Row:
    kind: str       # citation | citation-strict | figure | figure-strict
    obj: str
    en: int
    zh: int
    verdict: str
    en_ctx: str
    zh_ctx: str
    status: str = "real"    # real | variant | noise

    def tsv(self) -> str:
        return "\t".join(map(str, (self.kind, self.obj, self.en, self.zh, self.verdict, self.en_ctx, self.zh_ctx)))


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    n_cite_en: int = 0
    n_cite_zh: int = 0
    n_fig_en: int = 0
    n_fig_zh: int = 0
    EN: str = ""
    ZH: str = ""

    def count(self, kind: str, status: str = "real") -> int:
        return sum(1 for r in self.rows if r.kind == kind and r.status == status)

    @property
    def variants(self) -> int:
        return sum(1 for r in self.rows if r.status == "variant")

    @property
    def noise(self) -> int:
        return sum(1 for r in self.rows if r.status == "noise")

    @property
    def real(self) -> int:
        return sum(1 for r in self.rows if r.status == "real")

    def summary(self) -> str:
        return (f"引文 英文{self.n_cite_en} 中文{self.n_cite_zh} 真差异{self.count('citation')} 变体?{self.variants} "
                f"严格层{self.count('citation-strict')}；图号 英文{self.n_fig_en} 中文{self.n_fig_zh} "
                f"差异{self.count('figure')} 分图字母{self.count('figure-strict')}；已确认噪声{self.noise}；真差异合计 {self.real}")

    def tsv(self) -> str:
        hdr = "类型\t对象\t英文次数\t中文次数\t判定\t英文上下文\t中文上下文\n"
        return hdr + "".join(r.tsv() + "\n" for r in self.rows)


def _ctx(lst: Sequence[tuple[Any, int]], text: str, key: Any, k: int = 3) -> str:
    out: list[str] = []
    for kk, pos in lst:
        if kk == key and len(out) < k:
            out.append(snippet(text, pos))
    return " ‖ ".join(out)


def prepare(en_texts: Iterable[str], zh_texts: Iterable[str], zh_stop: str | None = None) -> tuple[str, str, set[int]]:
    """清洗并拼接。返回 (英文, 中文, 图注图号集合)。"""
    en_clean = [clean(t) for t in en_texts]
    zh_parts = []
    for t in zh_texts:
        t = clean(t, zh=True)
        t = re.sub(r"^# .*\n", "", t, count=1)                       # 标题行常含作者年份
        if zh_stop:
            t = re.split(zh_stop, t, flags=re.M)[0]
        zh_parts.append(t)
    EN, ZH = "\n".join(en_clean), "\n".join(zh_parts)
    cap_nums = {int(x) for x in re.findall(r"(?m)^\s*Fig\.?\s*(\d+)\.", EN)}
    cap_nums |= {int(x) for x in re.findall(r"(?m)^[*\s]*图\s*(\d+)\s*[.．]", ZH)}   # 英文图注缺失而中文据页图补译者
    return EN, ZH, cap_nums


def compare(en_texts: Iterable[str], zh_texts: Iterable[str], *, alias: Alias | None = None,
            noise: dict[tuple[str, str, str, str], str] | None = None, zh_stop: str | None = None) -> Report:
    EN, ZH, cap_nums = prepare(en_texts, zh_texts, zh_stop)
    rep = Report(EN=EN, ZH=ZH)
    ce_l, cz_l = cites(EN, alias), cites(ZH, alias)
    ce, cz = collections.Counter(k for k, _ in ce_l), collections.Counter(k for k, _ in cz_l)
    fe_l, fz_l = figs(EN, cap_nums), figs(ZH)
    fe, fz = collections.Counter(n for n, _ in fe_l), collections.Counter(n for n, _ in fz_l)
    rep.n_cite_en, rep.n_cite_zh = sum(ce.values()), sum(cz.values())
    rep.n_fig_en, rep.n_fig_zh = sum(fe.values()), sum(fz.values())
    rows = rep.rows

    cdiff = {k: (ce.get(k, 0), cz.get(k, 0)) for k in set(ce) | set(cz) if ce.get(k, 0) != cz.get(k, 0)}
    en_only = {k: v[0] - v[1] for k, v in cdiff.items() if v[0] > v[1]}
    zh_only = {k: v[1] - v[0] for k, v in cdiff.items() if v[1] > v[0]}
    paired = []
    for ke in sorted(en_only):
        best = None
        for kz in sorted(zh_only):
            if kz[1] != ke[1] or zh_only[kz] <= 0 or en_only[ke] <= 0:
                continue
            r = difflib.SequenceMatcher(None, ke[0], kz[0]).ratio()
            if r >= 0.75 and (best is None or r > best[0]):
                best = (r, kz)
        if best:
            kz = best[1]
            n = min(en_only[ke], zh_only[kz])
            en_only[ke] -= n
            zh_only[kz] -= n
            paired.append((ke, kz, n))
    for k in sorted(cdiff):
        e, z = cdiff[k]
        if en_only.get(k, 0) > 0:
            rows.append(Row("citation", f"{k[0]}, {k[1]}", e, z, "中文缺失", _ctx(ce_l, EN, k), _ctx(cz_l, ZH, k)))
        elif zh_only.get(k, 0) > 0:
            rows.append(Row("citation", f"{k[0]}, {k[1]}", e, z, "中文多出（疑似增补/幻觉）", _ctx(ce_l, EN, k), _ctx(cz_l, ZH, k)))
    for ke, kz, n in paired:
        rows.append(Row("citation", f"{ke[0]}→{kz[0]}, {ke[1]}", n, n, "变体?（拼写/OCR，须确认）",
                        _ctx(ce_l, EN, ke), _ctx(cz_l, ZH, kz), status="variant"))
    # 严格层：第二作者 / 字母后缀。只报告第一作者+年份层面未报告的差异
    se_l, sz_l = cites_strict(EN, alias), cites_strict(ZH, alias)
    se, sz = collections.Counter(k for k, _ in se_l), collections.Counter(k for k, _ in sz_l)
    for sk in sorted(set(se) | set(sz)):
        e, z = se.get(sk, 0), sz.get(sk, 0)
        if e == z or (sk[0], sk[2][:4]) in cdiff:
            continue
        rows.append(Row("citation-strict", f"{sk[0]} | 第二作者={sk[1] or '-'} | {sk[2]}", e, z,
                        "严格层差异（第二作者/字母后缀，须核对）", _ctx(se_l, EN, sk), _ctx(sz_l, ZH, sk)))
    fse_l, fsz_l = figs_strict(EN, cap_nums), figs_strict(ZH)
    fse, fsz = collections.Counter(k for k, _ in fse_l), collections.Counter(k for k, _ in fsz_l)
    fplain = {k for k in set(fe) | set(fz) if fe.get(k, 0) != fz.get(k, 0)}
    for fk in sorted(set(fse) | set(fsz)):
        e, z = fse.get(fk, 0), fsz.get(fk, 0)
        if e != z and fk[0] not in fplain:
            rows.append(Row("figure-strict", f"Fig. {fk[0]}{fk[1]}", e, z, "分图字母差异（须核对）", _ctx(fse_l, EN, fk), _ctx(fsz_l, ZH, fk)))
    for n in sorted(set(fe) | set(fz)):
        e, z = fe.get(n, 0), fz.get(n, 0)
        if e != z:
            rows.append(Row("figure", f"Fig. {n}", e, z, "中文多出" if z > e else "中文缺失", _ctx(fe_l, EN, n), _ctx(fz_l, ZH, n)))
    for row in rows:
        why = (noise or {}).get((row.kind, row.obj, str(row.en), str(row.zh)))
        if why is not None and row.status == "real":
            row.status, row.verdict = "noise", "已确认噪声：" + why
    return rep


def align_lines(rep: Report, alias: Alias | None = None) -> list[str]:
    EN, ZH = rep.EN, rep.ZH
    cap_nums = prepare([EN], [ZH])[2]
    out = []
    for label, le, lz in (("引文", cites(EN, alias), cites(ZH, alias)), ("图号", figs(EN, cap_nums), figs(ZH))):
        a, b = [k for k, _ in le], [k for k, _ in lz]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            pe = le[i1][1] if i1 < len(le) else len(EN)
            pz = lz[j1][1] if j1 < len(lz) else len(ZH)
            out.append(f"[{label}] {op} EN{a[i1:i2]} -> ZH{b[j1:j2]}\n   EN: {snippet(EN, pe, 70)}\n   ZH: {snippet(ZH, pz, 70)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="英文原文 vs 中文译文：引文 (Author, year) 与图号多重集对照；有真差异退出码 1")
    ap.add_argument("--en", action="append", required=True, metavar="FILE", help="英文原文（正文、图注，可重复）")
    ap.add_argument("--zh", action="append", required=True, metavar="FILE", help="中文译文（可重复）")
    ap.add_argument("--out", required=True, help="输出 TSV")
    ap.add_argument("--noise", default=None, help="已确认噪声 TSV；缺省取 --out 同目录的 cite_noise.tsv（有则用）")
    ap.add_argument("--alias", default=None, help="OCR 名字别名 TSV（两列：OCR 键、规范键）")
    ap.add_argument("--zh-stop", default=None, help="中文稿里匹配此正则（多行）的行起丢弃，用于去文献表")
    ap.add_argument("--align", action="store_true", help="另打印英中引文/图号序列的顺序对齐")
    a = ap.parse_args(argv)
    out = Path(a.out)
    noise_p = Path(a.noise) if a.noise else out.with_name("cite_noise.tsv")
    for p in [*a.en, *a.zh, *([a.alias] if a.alias else []), *([a.noise] if a.noise else [])]:
        if not Path(p).is_file():
            print(f"找不到文件：{p}", file=sys.stderr)
            return 2
    try:
        en_texts = [Path(p).read_text(encoding="utf8") for p in a.en]
        zh_texts = [Path(p).read_text(encoding="utf8") for p in a.zh]
        alias = parse_alias(Path(a.alias).read_text(encoding="utf8")) if a.alias else None
        noise = parse_noise(noise_p.read_text(encoding="utf8")) if noise_p.is_file() else None
        rep = compare(en_texts, zh_texts, alias=alias, noise=noise, zh_stop=a.zh_stop)
    except (OSError, UnicodeDecodeError, re.error) as exc:
        print(f"读取或处理失败：{exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rep.tsv(), encoding="utf8")
    print(rep.summary())
    for r in rep.rows:
        if r.status == "real":
            print(f"  [{r.kind}] {r.obj}  英{r.en}/中{r.zh}  {r.verdict}")
    if a.align:
        print("\n".join(align_lines(rep, alias)))
    return 1 if rep.real else 0


if __name__ == "__main__":
    sys.exit(main())
