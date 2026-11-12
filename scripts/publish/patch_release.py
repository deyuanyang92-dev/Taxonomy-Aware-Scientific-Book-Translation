# -*- coding: utf-8 -*-
"""成品快速修订：给定替换表（旧 -> 新），对已发布的 docx / PDF 做定点替换，不必重排整本书。

替换表：UTF-8 的 TSV，每行「旧<TAB>新」；空行和以 # 开头的行忽略。

docx：遍历 word/ 下全部 XML（正文、页眉页脚、脚注尾注、批注），按 <w:t> 文本节点替换。
  同一段落内、被拆在多个 run 里的文字也能命中（制表符、换行、段落边界不跨）：新文字放进命中范围的第一个 run
  （沿用它的格式），其余 run 里被命中的部分删去。报告每条的替换次数，其中跨 run 的单独计数，0 次即「未命中」。

PDF：只在「新旧字数相同，且新字的字形已在同一个嵌入字体子集里」时用 PyMuPDF 原地改文本串里的字形编码
  （读字体的 ToUnicode 反查编码，并核对字体程序里该编码确有轮廓；只处理 2 字节编码的 Type0/Identity-H 字体，即 Word 导出的中文 PDF）。
  还要求新旧字都是全角字（汉字等，宽度相同），否则排版会错位。字数不同、子集里没有新字、命中不到单个文本串时，
  一律不改，提示「请用 word_render 由改后 docx 重渲染」。

用法:
    python3 -X utf8 patch_release.py <书.docx|书.pdf> <替换表.tsv> [-o 输出文件] [--dry] [--pages 5-8,613]
  缺省输出 <原名>_patched.<扩展名>；--dry 只报告次数不写文件。
  Windows 上的 Python 务必加 -X utf8（否则打印生僻字会因 GBK 崩溃）。
一条都没替换时不写输出文件。原件只读，输出一律写到 -o 指定的副本。
退出码: 0 全部命中；1 有未命中或被拒绝的条目（或一条都没替换）；2 参数错误。
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import struct
import sys
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

REDO_HINT = "请用 word_render 由改后 docx 重渲染"


@dataclass
class Result:
    old: str
    new: str
    count: int = 0
    cross: int = 0          # 其中跨 run（docx）/ 跨文本串（PDF）的次数
    note: str = ""          # 被拒绝或未命中的原因
    detail: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.count > 0 and not self.note


def read_table(path: Path) -> list[tuple[str, str]]:
    pairs = []
    for n, line in enumerate(path.read_text(encoding="utf8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.rstrip("\r\n").split("\t")
        if len(cells) < 2 or not cells[0]:
            raise ValueError(f"{path.name} 第 {n} 行不是「旧<TAB>新」：{line!r}")
        pairs.append((cells[0], cells[1]))
    return pairs


# ---------------------------------------------------------------- docx

_XML_TOKEN = re.compile(
    r"<w:t(?P<attrs>(?:\s[^>]*)?)>(?P<text>[^<]*)</w:t>"
    r"|(?P<brk><w:p[\s>/]|</w:p>|<w:tab\s*/>|<w:br\b[^>]*/>|<w:cr\s*/>|<w:noBreakHyphen\s*/>)"
)


def replace_in_texts(texts: list[str], old: str, new: str) -> tuple[int, int]:
    """在一串相邻文本节点上做替换，返回 (总次数, 其中跨节点次数)。texts 原地修改。"""
    if not old:
        return 0, 0
    total = cross = 0
    pos = 0
    while True:
        full = "".join(texts)
        i = full.find(old, pos)
        if i < 0:
            return total, cross
        j = i + len(old)
        spans = []
        off = 0
        for k, t in enumerate(texts):
            lo, hi = off, off + len(t)
            off = hi
            if hi <= i or lo >= j:
                continue
            spans.append((k, max(i, lo) - lo, min(j, hi) - lo))
        k0, a0, b0 = spans[0]
        texts[k0] = texts[k0][:a0] + new + texts[k0][b0:]
        for k, a, b in spans[1:]:
            texts[k] = texts[k][:a] + texts[k][b:]
        total += 1
        cross += len(spans) > 1
        pos = i + len(new)


def _patch_xml_part(xml: str, pairs: list[tuple[str, str]], results: list[Result]) -> str:
    # 把文本节点按段落/制表符/换行切成若干段，每段内的节点连起来匹配
    segments: list[list[re.Match[str]]] = [[]]
    for m in _XML_TOKEN.finditer(xml):
        if m.group("brk"):
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(m)
    new_text: dict[int, str] = {}
    for seg in segments:
        if not seg:
            continue
        texts = [html.unescape(m.group("text")) for m in seg]
        orig = list(texts)
        for res, (old, new) in zip(results, pairs):
            n, c = replace_in_texts(texts, old, new)
            res.count += n
            res.cross += c
        for m, t0, t1 in zip(seg, orig, texts):
            if t0 != t1:
                new_text[m.start()] = t1
    if not new_text:
        return xml
    out, last = [], 0
    for m in _XML_TOKEN.finditer(xml):
        if m.start() not in new_text:
            continue
        t = new_text[m.start()]
        attrs = m.group("attrs")
        if t != t.strip() and "xml:space" not in attrs:
            attrs += ' xml:space="preserve"'
        out.append(xml[last:m.start()])
        out.append(f"<w:t{attrs}>{escape(t)}</w:t>")
        last = m.end()
    out.append(xml[last:])
    return "".join(out)


def patch_docx(src: Path, dst: Path | None, pairs: list[tuple[str, str]]) -> list[Result]:
    results = [Result(o, n) for o, n in pairs]
    with zipfile.ZipFile(src) as zin:
        parts: dict[str, bytes] = {}
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                xml = data.decode("utf8")
                patched = _patch_xml_part(xml, pairs, results)
                if patched != xml:
                    data = patched.encode("utf8")
            parts[info.filename] = data
        if dst is not None and any(r.count for r in results):  # 一条都没替换就不写文件
            tmp = dst.with_name(dst.name + ".part")
            with zipfile.ZipFile(tmp, "w") as zout:
                for info in zin.infolist():
                    zi = zipfile.ZipInfo(info.filename, info.date_time)
                    zi.compress_type = info.compress_type
                    zi.external_attr = info.external_attr
                    zout.writestr(zi, parts[info.filename])
            tmp.replace(dst)
    for r in results:
        if r.count == 0:
            r.note = "未命中"
    return results


# ---------------------------------------------------------------- PDF

_PDF_TOKEN = re.compile(
    rb"(?P<ws>\s+)|(?P<comment>%[^\r\n]*)|(?P<dict><<|>>)|(?P<hex><[0-9A-Fa-f\s]*>)|(?P<lit>\()"
    rb"|(?P<arr>[\[\]])|(?P<name>/[^\s/<>\[\]()%{}]*)|(?P<num>[+-]?(?:\d+\.?\d*|\.\d+))"
    rb"|(?P<op>[A-Za-z'\"*][A-Za-z0-9'\"*]*)|(?P<other>.)",
    re.S,
)


def parse_tounicode(cmap: bytes) -> dict[int, str]:
    """解析 ToUnicode CMap（2 字节编码），返回 编码 -> 单个 Unicode 字符。"""
    out: dict[int, str] = {}

    def u(hexs: bytes) -> str:
        try:
            return bytes.fromhex(hexs.decode()).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return ""

    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            if len(a) == 4 and len(u(b)) == 1:
                out[int(a, 16)] = u(b)
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cmap, re.S):
        for lo, hi, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", blk):
            if len(lo) != 4:
                continue
            a, b = int(lo, 16), int(hi, 16)
            if rest.startswith(b"["):
                dsts = re.findall(rb"<([0-9A-Fa-f]+)>", rest)
                for k, d in zip(range(a, b + 1), dsts):
                    if len(u(d)) == 1:
                        out[k] = u(d)
            else:
                base = u(rest[1:-1])
                if len(base) == 1:
                    for k in range(a, b + 1):
                        out[k] = chr(ord(base) + k - a)
    return out


def _is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def truetype_glyph_checker(font: bytes) -> Callable[[int], bool]:
    """TrueType 字体程序里某个 GID 是否有轮廓（子集化后被删的字形在 loca 里长度为 0；GID 0 即 .notdef，拒绝）。
    解析不了（CFF、损坏）时一律返回 False，宁可拒绝也不替换成空白字形。"""
    try:
        n_tables = struct.unpack(">H", font[4:6])[0]
        tables = {font[12 + 16 * i:16 + 16 * i]: struct.unpack(">II", font[20 + 16 * i:28 + 16 * i]) for i in range(n_tables)}
        head, maxp, loca = tables[b"head"][0], tables[b"maxp"][0], tables[b"loca"][0]
        long_loca = struct.unpack(">h", font[head + 50:head + 52])[0] == 1
        n_glyphs = struct.unpack(">H", font[maxp + 4:maxp + 6])[0]
        size = 4 if long_loca else 2
        offs = struct.unpack(f">{n_glyphs + 1}{'I' if long_loca else 'H'}", font[loca:loca + size * (n_glyphs + 1)])
    except (KeyError, struct.error):
        return lambda gid: False
    return lambda gid: 1 <= gid < n_glyphs and offs[gid + 1] > offs[gid]  # GID 0 是 .notdef，不算


@dataclass
class FontMap:
    code2uni: dict[int, str]
    uni2code: dict[str, int]
    glyph_ok: Callable[[int], bool]


def _font_maps(doc, page, cache: dict[int, FontMap | None] | None = None) -> dict[str, FontMap]:
    """页面资源名 -> 字体映射。同一字体对象全书共用，按 xref 缓存，避免每页重复解析字体程序。"""
    cache = {} if cache is None else cache
    maps: dict[str, FontMap] = {}
    for xref, _ext, ftype, _base, name, enc, _ref in page.get_fonts(full=True):
        if ftype != "Type0" or "Identity" not in str(enc):
            continue
        if xref not in cache:
            cache[xref] = None
            k, v = doc.xref_get_key(xref, "ToUnicode")
            if k == "xref":
                c2u = parse_tounicode(doc.xref_stream(int(v.split()[0])) or b"")
                u2c: dict[str, int] = {}
                for c, ch in sorted(c2u.items()):
                    u2c.setdefault(ch, c)
                cache[xref] = FontMap(c2u, u2c, _glyph_checker(doc, xref))
        fm = cache[xref]
        if fm is not None:
            maps[name] = fm
    return maps


def _first_descendant(doc, type0_xref: int) -> int:
    """Type0 字体的后代 CIDFont 的 xref。DescendantFonts 可能是内联数组，也可能是指向数组对象的间接引用
    （Word 导出的 PDF 就是后者：/DescendantFonts 17 0 R，17 号对象是 [ 18 0 R ]）。"""
    kind, val = doc.xref_get_key(type0_xref, "DescendantFonts")
    if kind == "xref":
        val = doc.xref_object(int(val.split()[0]), compressed=True)
    m = re.search(r"(\d+)\s+0\s+R", val) if kind in ("xref", "array") else None
    if not m:
        raise ValueError("DescendantFonts 解析不了")
    return int(m.group(1))


def _glyph_checker(doc, type0_xref: int) -> Callable[[int], bool]:
    """字符编码 -> CID -> GID -> 字形有轮廓，整条链都过才算「子集里有这个字」。
    Type0 -> CIDFontType2 -> FontDescriptor -> FontFile2；CID 经 CIDToGIDMap 转 GID（/Identity 时相等，
    也可能是一个流：每个 CID 对应 2 字节 GID）；GID 0 是 .notdef，一律不要。
    ToUnicode 常按整个字体生成，不能当作「子集里有这个字」的证据，所以必须看字体程序本身。"""
    try:
        desc = _first_descendant(doc, type0_xref)
        k, v = doc.xref_get_key(desc, "FontDescriptor")
        fd = int(v.split()[0]) if k == "xref" else 0
        k, v = doc.xref_get_key(fd, "FontFile2")
        if k != "xref":
            return lambda code: False
        check = truetype_glyph_checker(doc.xref_stream(int(v.split()[0])) or b"")
        k, v = doc.xref_get_key(desc, "CIDToGIDMap")
        if k == "xref":
            table = doc.xref_stream(int(v.split()[0])) or b""
            return lambda code: 2 * code + 2 <= len(table) and check(int.from_bytes(table[2 * code:2 * code + 2], "big"))
        if k == "name" and v != "/Identity":
            return lambda code: False
        return check
    except (ValueError, IndexError, RuntimeError):
        return lambda code: False


@dataclass
class _Seg:
    start: int      # 十六进制串（含尖括号）在内容流中的起止
    end: int
    font: str
    codes: list[int]


def _show_units(data: bytes, state: dict) -> list[list[_Seg]]:
    """扫描内容流，返回每个 Tj/TJ/'/\" 算子里的十六进制串（2 字节编码）。state 跨流保持当前字体和 q/Q 栈。"""
    units: list[list[_Seg]] = []
    pending: list[_Seg] = []
    last_name = ""
    pos = 0
    while pos < len(data):
        m = _PDF_TOKEN.match(data, pos)
        if not m:
            break
        pos = m.end()
        kind = m.lastgroup
        if kind == "lit":  # 跳过字面串（含转义和嵌套括号）
            depth, i = 1, pos
            while i < len(data) and depth:
                c = data[i:i + 1]
                if c == b"\\":
                    i += 1
                elif c == b"(":
                    depth += 1
                elif c == b")":
                    depth -= 1
                i += 1
            pos = i
        elif kind == "name":
            last_name = m.group().decode("latin1")[1:]
        elif kind == "hex":
            raw = re.sub(rb"\s", b"", m.group()[1:-1])
            if len(raw) % 4 == 0 and state["font"]:
                codes = [int(raw[i:i + 4], 16) for i in range(0, len(raw), 4)]
                pending.append(_Seg(m.start(), m.end(), state["font"], codes))
        elif kind == "op":
            op = m.group().decode("latin1")
            if op == "Tf":
                state["font"] = last_name
            elif op == "q":
                state["stack"].append(state["font"])
            elif op == "Q" and state["stack"]:
                state["font"] = state["stack"].pop()
            elif op in ("Tj", "TJ", "'", '"') and pending:
                units.append(pending)
            elif op == "BI":  # 内联图像：跳到 EI，避免二进制数据被当成算子
                e = re.compile(rb"\sEI(?=\s|$)").search(data, pos)
                pos = e.end() if e else len(data)
            pending = []
    return units


def _hex(codes: list[int]) -> bytes:
    return b"<" + "".join(f"{c:04x}" for c in codes).encode() + b">"


def _patch_pdf_page(doc, page, pairs, results, dry: bool, cache: dict[int, FontMap | None] | None = None) -> int:
    maps = _font_maps(doc, page, cache)
    if not maps:
        return 0
    state: dict = {"font": "", "stack": []}
    changed = 0
    for cx in page.get_contents():
        data = bytearray(doc.xref_stream(cx) or b"")
        edits: list[tuple[int, int, bytes]] = []
        before = changed
        for unit in _show_units(bytes(data), state):
            fm = maps.get(unit[0].font)
            if not fm or any(s.font != unit[0].font for s in unit):
                continue
            flat = [(si, ci) for si, s in enumerate(unit) for ci in range(len(s.codes))]
            text = "".join(fm.code2uni.get(unit[si].codes[ci], "�") for si, ci in flat)
            for res, (old, new) in zip(results, pairs):
                if res.note or not old or len(old) != len(new):
                    continue
                i = text.find(old)
                while i >= 0:
                    chars = list(zip(old, new))
                    lack = [n for _o, n in chars if _o != n and (n not in fm.uni2code or not fm.glyph_ok(fm.uni2code[n]))]
                    if lack:
                        res.note = f"第 {page.number + 1} 页：新字「{lack[0]}」字形不在嵌入字体子集中，{REDO_HINT}"
                        break
                    if any(not (_is_wide(o) and _is_wide(n)) for o, n in chars if o != n):
                        res.note = f"第 {page.number + 1} 页：含非全角字，替换后字宽不同会错位，{REDO_HINT}"
                        break
                    for k, (o, n) in enumerate(chars):
                        if o != n:
                            si, ci = flat[i + k]
                            unit[si].codes[ci] = fm.uni2code[n]
                    text = text[:i] + new + text[i + len(old):]
                    res.count += 1
                    res.cross += len({flat[i + k][0] for k in range(len(old))}) > 1
                    changed += 1
                    i = text.find(old, i + len(new))
            for s in unit:
                edits.append((s.start, s.end, _hex(s.codes)))
        if changed > before and not dry:
            for a, b, repl in edits:
                data[a:b] = repl  # 十六进制串定长替换，偏移不变
            doc.update_stream(cx, bytes(data))
    return changed


def _scan(doc, pairs: list[tuple[str, str]], pages: set[int] | None, dry: bool,
          cache: dict[int, FontMap | None]) -> list[Result]:
    results = [Result(o, n) for o, n in pairs]
    for r in results:
        if len(r.old) != len(r.new):
            r.note = f"新旧字数不同，{REDO_HINT}"
    first_chars = {o[0] for o, n in pairs if o and len(o) == len(n)}
    for page in doc:
        if pages is not None and page.number + 1 not in pages:
            continue
        if not first_chars or not any(c in page.get_text() for c in first_chars):
            continue  # 页面文本里连旧字的首字都没有，不可能命中
        _patch_pdf_page(doc, page, pairs, results, dry=dry, cache=cache)
    return results


def patch_pdf(src: Path, dst: Path | None, pairs: list[tuple[str, str]], pages: set[int] | None = None) -> list[Result]:
    """pages：只处理这些页（1 起）。dst 为 None 只统计。

    每一条替换要么全书（所选页内）都改，要么都不改：先只读扫描一遍，任何一处新字字形不在嵌入字体里的条目整条拒绝，
    避免成品里新旧写法混杂；再对通过的条目改写。原件只读：改写在临时副本上增量保存，至少替换了一处才改名为 dst，
    一处都没替换则不产生输出文件。"""
    import fitz  # PyMuPDF

    cache: dict[int, FontMap | None] = {}
    with fitz.open(src) as probe:
        plan = _scan(probe, pairs, pages, True, cache)
    for r in plan:
        if r.note:
            r.count = r.cross = 0
        elif r.count == 0:
            r.note = f"未在单个文本串内命中（可能跨行、跨字体或不在内容流中），{REDO_HINT}"
    if dst is None or not any(r.count for r in plan):
        return plan
    accepted = [(r.old, r.new) for r in plan if r.count]
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, tmp)
    doc = fitz.open(tmp)
    try:
        done = {(r.old, r.new): r for r in _scan(doc, accepted, pages, False, cache)}
        for r in plan:
            if (r.old, r.new) in done:
                r.count, r.cross = done[(r.old, r.new)].count, done[(r.old, r.new)].cross
        try:
            doc.saveIncr()
        except (ValueError, RuntimeError):  # 不能增量保存（如加密）时整体重写
            full = tmp.with_name(tmp.name + "2")
            doc.save(full, garbage=0, deflate=True)
            doc.close()
            full.replace(tmp)
        else:
            doc.close()
        tmp.replace(dst)
    finally:
        if not doc.is_closed:
            doc.close()
        tmp.unlink(missing_ok=True)
    return plan


# ---------------------------------------------------------------- 命令行

def report(results: list[Result]) -> bool:
    all_ok = True
    for r in results:
        if r.ok:
            extra = f"，其中跨 run/文本串 {r.cross} 处" if r.cross else ""
            print(f"OK    {r.old} -> {r.new}：{r.count} 处{extra}")
        else:
            all_ok = False
            print(f"未改  {r.old} -> {r.new}：{r.note or '未命中'}")
    return all_ok


def parse_pages(spec: str) -> set[int]:
    pages: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        pages.update(range(int(lo), int(hi or lo) + 1))
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="对 docx/PDF 成品做定点替换（替换表 旧<TAB>新）")
    ap.add_argument("file", help=".docx 或 .pdf")
    ap.add_argument("table", help="替换表 TSV")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--dry", action="store_true", help="只报告次数，不写文件")
    ap.add_argument("--pages", default=None, help="PDF：只处理这些页，如 613 或 5-8,613（1 起）")
    a = ap.parse_args(argv)
    src = Path(a.file)
    ext = src.suffix.lower()
    if ext not in (".docx", ".pdf"):
        print("只支持 .docx 和 .pdf", file=sys.stderr)
        return 2
    try:
        pairs = read_table(Path(a.table))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    dst = None if a.dry else Path(a.output) if a.output else src.with_name(f"{src.stem}_patched{src.suffix}")
    if dst is not None and dst.resolve() == src.resolve():
        print("输出不能覆盖原文件", file=sys.stderr)
        return 2
    if ext == ".docx":
        results = patch_docx(src, dst, pairs)
    else:
        results = patch_pdf(src, dst, pairs, parse_pages(a.pages) if a.pages else None)
    ok = report(results)
    replaced = any(r.count for r in results)
    if dst is not None and replaced:
        print(f"已写 {dst}")
    elif dst is not None:
        print("没有任何条目被替换，未写出输出文件", file=sys.stderr)
    if ext == ".pdf" and not ok:
        print(f"提示：未改的条目{REDO_HINT}")
    return 0 if ok and (replaced or a.dry or not results) else 1


if __name__ == "__main__":
    sys.exit(main())
