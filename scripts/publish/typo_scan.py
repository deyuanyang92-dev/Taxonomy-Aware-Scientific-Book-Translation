# -*- coding: utf-8 -*-
"""成品 DOCX / PDF 错字扫描、字体安全的定点修补与交付闸（issue #24）。

patch_release.py 只会执行「人给的替换表」；本脚本补上「发现」与「写前核字体」：

  scan  扫描成品，输出错字报告（文件、页/段落位置、上下文、观察到的 token、建议 token、规则、置信度、
        能否自动修）。
  fix   只改 auto=true 的条目，其余留在报告里等人工；写出副本，原件只读。

检测规则
  * 替换表（--rules，TSV：错<TAB>对[<TAB>备注]）：置信度 high。
  * 内置：U+FFFD 替换字符、私用区字符（OCR/识别错误，只报告不改）；连续重复中文标点；全角空格 U+3000
    （禁用字符，会影响缩进，只报告）；英文连续重复词（the the，medium，只报告）。
  * 保护区：斜体 run（学名）、命名人+年份（taxostyle.AUTHORITY）、--protect 列表里的词。命中与保护区重叠的
    条目一律不提议，哪怕只差一个字母。

DOCX
  * 遍历 word/ 下所有 XML（正文、表格、图注、页眉页脚、脚注尾注、文本框），按段落/制表符/换行切段；
    同一段里被拆在多个 run 的字也能命中，并带上完整 token 与 run 的字体。
  * 只替换「新旧差异的最小区间」，新字放进差异起点所在的 run（沿用该 run 的格式），跨 run 的多余旧字删去；
    其余 run 的斜体、上下标、字体属性不动。
  * 写前核字体：解析 run → 字符样式 → 段落样式（含 basedOn）→ docDefaults 的 rFonts；汉字查 eastAsia，
    西文查 ascii/hAnsi。字体未声明、主题字体、本机找不到字体文件、字体里没有该字符，一律 auto=false 并说明原因，
    绝不盲写。字符数改变的修正默认不自动做（排版验收可能变），--allow-length-change 才放行。
  * --assume-fonts-ok 跳过字体核查（仅供受控环境/测试）；--font-dir 追加字体目录。

PDF
  * 逐页取文字行（含 bbox）。含 Type3 字体、缺 ToUnicode 的 Type0/TrueType 字体、有图无文字层的页，
    报告为 unscannable，状态是 not_scannable，不当作「无错字」。
  * 原地修只走 patch_release.patch_pdf 的限制：新旧等长、均为全角字、新字形在同一嵌入子集里（该函数在写时核对）；
    其余条目 auto=false，提示「请用 word_render 由改后 docx 重渲染」。

闸：报告的 status 为 clean / typos / not_scannable；ok 仅在 clean 时为 true，
``booklayout gate --style-report <报告.json>`` 可直接接入。已修复后的重扫应为 clean，同一处不会重复报。

用法：
    python3 -X utf8 typo_scan.py scan <书.docx|书.pdf> [--rules typos.tsv] [--protect names.txt] [--report out.json]
    python3 -X utf8 typo_scan.py fix  <书.docx|书.pdf> --rules typos.tsv -o <输出> [--allow-length-change]
  也可经 patch_release.py scan|fix ... 调用。退出码：scan 为 clean 时 0，否则 1；fix 在输出重扫为 clean 时 0。
局限（未确证/需人工）：不做上下文相关的用字判断（的/地/得、同音字）；PDF 的字形可用性只在写入时核对；
版式相关的重排不在本脚本范围（归 booklayout）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import patch_release as pr  # noqa: E402
import taxostyle  # noqa: E402

CanRender = Callable[[str, str], "bool | None"]

REDO = "PDF 原地修仅限等长全角字；请用 word_render 由改后 docx 重渲染 / re-render from the DOCX"
DOUBLE_PUNCT = re.compile(r"([，。；：、！？,.;:!?])\1+")
DOUBLE_WORD = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.I)
LATIN_BEFORE_AUTHORITY = re.compile(
    r"[A-Z][a-z]+(?: [a-z]{3,})?(?=\s+\(?[A-Z][\w'’-]+[^.\n]{0,40}?\b(?:1[6-9]\d\d|20\d\d))")
PUA = re.compile(r"[\ue000-\uf8ff]")

FONT_FILES = {
    "simsun": ["simsun.ttc", "simsun.ttf"], "宋体": ["simsun.ttc"], "nsimsun": ["simsun.ttc"],
    "simhei": ["simhei.ttf"], "黑体": ["simhei.ttf"], "kaiti": ["simkai.ttf"], "simkai": ["simkai.ttf"],
    "楷体": ["simkai.ttf"], "fangsong": ["simfang.ttf"], "simfang": ["simfang.ttf"], "仿宋": ["simfang.ttf"],
    "microsoft yahei": ["msyh.ttc", "msyh.ttf"], "微软雅黑": ["msyh.ttc"],
    "times new roman": ["times.ttf"], "arial": ["arial.ttf"], "calibri": ["calibri.ttf"],
    "cambria": ["cambria.ttc"], "consolas": ["consola.ttf"],
}
FONT_DIRS = [Path("/mnt/c/Windows/Fonts"), Path("C:/Windows/Fonts"), Path.home() / ".fonts",
             Path("/usr/share/fonts")]
_cmap_cache: dict[str, set[int] | None] = {}


@dataclass
class Rule:
    old: str
    new: str
    rule: str = "typo-table"
    confidence: str = "high"
    note: str = ""


def read_rules(path: Path) -> list[Rule]:
    out: list[Rule] = []
    for line in path.read_text(encoding="utf8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        c = line.rstrip("\r\n").split("\t")
        if len(c) < 2 or not c[0]:
            raise ValueError(f"替换表行格式应为「错<TAB>对」：{line!r}")
        out.append(Rule(c[0], c[1], note=c[2] if len(c) > 2 else ""))
    return out


# ---------------------------------------------------------------- 字体

def _is_ea(ch: str) -> bool:
    return ord(ch) >= 0x2E80


def _font_cmap(name: str, font_dirs: list[Path]) -> set[int] | None:
    key = name.lower()
    if key in _cmap_cache:
        return _cmap_cache[key]
    cmap: set[int] | None = None
    for fname in FONT_FILES.get(key, []):
        for d in font_dirs:
            f = d / fname
            if f.exists():
                try:
                    from fontTools.ttLib import TTFont

                    font = TTFont(str(f), fontNumber=0, lazy=True)
                    cmap = set(font.getBestCmap() or {})
                except Exception:  # noqa: BLE001 - 字体损坏就当未知
                    cmap = None
                break
        if cmap is not None:
            break
    _cmap_cache[key] = cmap
    return cmap


def font_can_render(font: str, chars: str, font_dirs: list[Path] | None = None) -> bool | None:
    """True=字体含全部字符；False=缺字；None=无法确定（找不到字体文件）。空串与 ASCII 空白标点恒 True。"""
    need = {c for c in chars if not (c.isascii() and not c.isalnum())}
    if not need:
        return True
    cmap = _font_cmap(font, font_dirs or FONT_DIRS)
    if cmap is None:
        return None
    return all(ord(c) in cmap for c in need)


def _assume_ok(font: str, chars: str) -> bool:
    return True


# ---------------------------------------------------------------- 检测

def _protected(text: str, italic: list[bool], extra: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if italic[i]:
            j = i
            while j < len(text) and italic[j]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    spans += [(m.start(), m.end()) for m in taxostyle.AUTHORITY.finditer(text)]
    # 后面紧跟「命名人, 年份」的拉丁名（即使丢了斜体）也是学名，不提议改
    spans += [(m.start(), m.end()) for m in LATIN_BEFORE_AUTHORITY.finditer(text)]
    for term in extra:
        spans += [(m.start(), m.end()) for m in re.finditer(re.escape(term), text)]
    return spans


@dataclass
class Hit:
    a: int
    b: int
    old: str
    new: str
    rule: str
    confidence: str
    reason: str = ""
    builtin_auto: bool = False


def detect(text: str, italic: list[bool], rules: list[Rule], protect: list[str]) -> list[Hit]:
    prot = _protected(text, italic, protect)

    def blocked(a: int, b: int) -> bool:
        return any(a < y and x < b for x, y in prot)

    hits: list[Hit] = []
    for r in rules:
        for m in re.finditer(re.escape(r.old), text):
            if not blocked(m.start(), m.end()):
                hits.append(Hit(m.start(), m.end(), r.old, r.new, r.rule, r.confidence, r.note))
    for m in re.finditer("\ufffd", text):
        hits.append(Hit(m.start(), m.end(), m.group(0), "", "replacement-char", "high",
                        "替换字符 U+FFFD：原字已丢失，需对照原稿人工补"))
    for m in PUA.finditer(text):
        if not blocked(m.start(), m.end()):
            hits.append(Hit(m.start(), m.end(), m.group(0), "", "private-use-char", "high",
                            "私用区字符（多为识别/转码错误），需人工确认"))
    for m in DOUBLE_PUNCT.finditer(text):
        hits.append(Hit(m.start(), m.end(), m.group(0), m.group(1), "double-punct", "high",
                        "连续重复标点；删字会改变字数，须重排验收"))
    for m in re.finditer("\u3000", text):
        hits.append(Hit(m.start(), m.end(), m.group(0), " ", "fullwidth-space", "medium",
                        "全角空格 U+3000 在 Word 编辑标记下显示 □；常用于缩进，改动会影响版式"))
    for m in DOUBLE_WORD.finditer(text):
        if not blocked(m.start(), m.end()):
            hits.append(Hit(m.start(), m.end(), m.group(0), m.group(1), "double-word", "medium",
                            "英文连续重复词（可能是 had had 之类合法用法）"))
    # 去重：同一区间同一规则只留一条
    seen: set[tuple[int, int, str]] = set()
    uniq = []
    for h in sorted(hits, key=lambda h: (h.a, h.b)):
        if (h.a, h.b, h.rule) not in seen:
            seen.add((h.a, h.b, h.rule))
            uniq.append(h)
    return uniq


def _diff(old: str, new: str) -> tuple[int, int, str]:
    """去掉公共前后缀，返回 (起点偏移, 旧差异长度, 新差异文本)。"""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[len(old) - 1 - s] == new[len(new) - 1 - s]:
        s += 1
    return p, len(old) - p - s, new[p:len(new) - s]


def _context(text: str, a: int, b: int, n: int = 8) -> str:
    return text[max(0, a - n):a] + "【" + text[a:b] + "】" + text[b:b + n]


# ---------------------------------------------------------------- DOCX

_ATTR = r'w:%s="([^"]*)"'


def _fonts_of(xml_fragment: str) -> dict[str, str]:
    m = re.search(r"<w:rFonts([^>]*?)/?>", xml_fragment)
    out: dict[str, str] = {}
    if m:
        for key in ("ascii", "hAnsi", "eastAsia", "asciiTheme", "hAnsiTheme", "eastAsiaTheme"):
            mm = re.search(_ATTR % key, m.group(1))
            if mm:
                out[key] = mm.group(1)
    return out


def _italic_of(xml_fragment: str) -> bool | None:
    m = re.search(r'<w:i(?:\s+w:val="([^"]*)")?\s*/>', xml_fragment)
    if not m:
        return None
    return (m.group(1) or "1").lower() not in ("0", "false", "off")


def parse_styles(xml: str) -> dict:
    styles: dict[str, dict] = {}
    for m in re.finditer(r'<w:style\b[^>]*w:styleId="([^"]*)"[^>]*>(.*?)</w:style>', xml, re.S):
        body = m.group(2)
        based = re.search(r'<w:basedOn w:val="([^"]*)"', body)
        styles[m.group(1)] = {"based": based.group(1) if based else None,
                              "fonts": _fonts_of(body), "italic": _italic_of(body)}
    dd = re.search(r"<w:rPrDefault>(.*?)</w:rPrDefault>", xml, re.S)
    styles["__default__"] = {"based": None, "fonts": _fonts_of(dd.group(1)) if dd else {}, "italic": None}
    return styles


def _style_chain(styles: dict, sid: str | None) -> list[dict]:
    out, seen = [], set()
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        out.append(styles[sid])
        sid = styles[sid]["based"]
    return out


def resolve_font(ch: str, run_xml: str, pstyle: str | None, styles: dict) -> tuple[str | None, str]:
    """返回 (字体名|None, 原因)。优先级：run 直写 > 字符样式 > 段落样式 > docDefaults。"""
    rs = re.search(r'<w:rStyle w:val="([^"]*)"', run_xml)
    layers = [{"fonts": _fonts_of(run_xml)}, *_style_chain(styles, rs.group(1) if rs else None),
              *_style_chain(styles, pstyle), styles.get("__default__", {"fonts": {}})]
    name_key, theme_key = ("eastAsia", "eastAsiaTheme") if _is_ea(ch) else ("ascii", "asciiTheme")
    for layer in layers:
        f = layer["fonts"]
        if name_key in f:
            return f[name_key], ""
        if name_key == "ascii" and "hAnsi" in f:
            return f["hAnsi"], ""
        if theme_key in f:
            return None, f"主题字体 {f[theme_key]}，无法确定实际字体"
    return None, "字体未知：run、样式、docDefaults 均未声明"


def _segments(xml: str) -> list[list[re.Match[str]]]:
    segs: list[list[re.Match[str]]] = [[]]
    for m in pr._XML_TOKEN.finditer(xml):
        if m.group("brk"):
            if segs[-1]:
                segs.append([])
        else:
            segs[-1].append(m)
    return [s for s in segs if s]


def _run_xml(xml: str, pos: int) -> str:
    a = max(xml.rfind("<w:r>", 0, pos), xml.rfind("<w:r ", 0, pos))
    return xml[a:pos] if a >= 0 else ""


def _pstyle(xml: str, pos: int) -> str | None:
    a = max(xml.rfind("<w:p>", 0, pos), xml.rfind("<w:p ", 0, pos))
    m = re.search(r'<w:pStyle w:val="([^"]*)"', xml[a:pos]) if a >= 0 else None
    return m.group(1) if m else None


@dataclass
class _Typo:
    part: str
    para: int
    seg: int
    hit: Hit
    context: str
    auto: bool
    reason: str
    new_diff: tuple[int, int, str]


def _scan_part(part: str, xml: str, styles: dict, rules: list[Rule], protect: list[str],
               can_render: CanRender, allow_len: bool) -> list[_Typo]:
    out: list[_Typo] = []
    for si, seg in enumerate(_segments(xml), 1):
        texts = [html.unescape(m.group("text")) for m in seg]
        full = "".join(texts)
        runs = [_run_xml(xml, m.start()) for m in seg]
        italic: list[bool] = []
        for t, rx in zip(texts, runs):
            rs = re.search(r'<w:rStyle w:val="([^"]*)"', rx)
            it = _italic_of(rx)
            if it is None and rs and rs.group(1) in styles:
                it = styles[rs.group(1)]["italic"]
            italic.extend([bool(it)] * len(t))
        for h in detect(full, italic, rules, protect):
            p, olen, new_txt = _diff(h.old, h.new)
            reason, auto = h.reason, True
            if h.rule in ("replacement-char", "private-use-char", "fullwidth-space", "double-word"):
                auto, reason = False, reason or "只报告，不自动改"
            elif len(h.old) != len(h.new) and not allow_len:
                auto, reason = False, (reason + "；" if reason else "") + "字符数改变，默认不自动改（--allow-length-change）"
            if auto:
                # 定位差异起点所在 run，核其字体
                offs, acc = [], 0
                for t in texts:
                    offs.append(acc)
                    acc += len(t)
                pos = h.a + p
                k = max(i for i, o in enumerate(offs) if o <= pos) if full else 0
                k = min(k, len(seg) - 1)
                chars = new_txt
                bad = ""
                for ch in dict.fromkeys(chars):
                    font, why = resolve_font(ch, runs[k], _pstyle(xml, seg[0].start()), styles)
                    if font is None:
                        bad = why
                        break
                    ok = can_render(font, ch)
                    if ok is None:
                        bad = f"字体 {font} 未知：本机找不到字体文件，无法确认含「{ch}」"
                        break
                    if not ok:
                        bad = f"字体 {font} 缺少字符「{ch}」，改后会显示为方框/回退字体"
                        break
                if bad:
                    auto, reason = False, bad
            out.append(_Typo(part, si, si, h, _context(full, h.a, h.b), auto, reason, (h.a + p, olen, new_txt)))
    return out


def _docx_parts(zin: zipfile.ZipFile) -> list[str]:
    return [i.filename for i in zin.infolist() if i.filename.startswith("word/") and i.filename.endswith(".xml")
            and i.filename != "word/styles.xml" and "/theme/" not in i.filename
            and Path(i.filename).name not in ("settings.xml", "fontTable.xml", "numbering.xml",
                                              "webSettings.xml")]


def _row(t: _Typo, file: str) -> dict:
    return {"file": file, "where": f"{t.part}:p{t.para}", "context": t.context,
            "observed": t.hit.old, "proposed": t.hit.new, "rule": t.hit.rule,
            "confidence": t.hit.confidence, "auto": t.auto, "reason": t.reason}


def _report(typos: list[dict], unscannable: list[dict], **extra) -> dict:
    high = [t for t in typos if t["confidence"] == "high"]
    status = "typos" if high else "not_scannable" if unscannable else "clean"
    return {"ok": status == "clean", "status": status, "errors": len(high) + len(unscannable),
            "typos": typos, "unscannable": unscannable, **extra}


def scan_docx(path: Path, rules: list[Rule], protect: list[str] | None = None,
              can_render: CanRender | None = None, allow_length_change: bool = False) -> dict:
    can_render = can_render or font_can_render
    rows: list[dict] = []
    with zipfile.ZipFile(path) as z:
        styles = parse_styles(z.read("word/styles.xml").decode("utf8")) if "word/styles.xml" in z.namelist() \
            else parse_styles("")
        for part in _docx_parts(z):
            xml = z.read(part).decode("utf8")
            for t in _scan_part(part, xml, styles, rules, protect or [], can_render, allow_length_change):
                rows.append(_row(t, path.name))
    return _report(rows, [], file=str(path), kind="docx")


def fix_docx(src: Path, dst: Path, rules: list[Rule], protect: list[str] | None = None,
             can_render: CanRender | None = None, allow_length_change: bool = False) -> dict:
    can_render = can_render or font_can_render
    applied = refused = 0
    new_parts: dict[str, bytes] = {}
    with zipfile.ZipFile(src) as z:
        styles = parse_styles(z.read("word/styles.xml").decode("utf8")) if "word/styles.xml" in z.namelist() \
            else parse_styles("")
        for part in _docx_parts(z):
            xml = z.read(part).decode("utf8")
            typos = _scan_part(part, xml, styles, rules, protect or [], can_render, allow_length_change)
            refused += sum(not t.auto for t in typos)
            todo = [t for t in typos if t.auto]
            if not todo:
                continue
            segs = _segments(xml)
            texts_by_seg = {i: [html.unescape(m.group("text")) for m in seg] for i, seg in enumerate(segs, 1)}
            by_seg: dict[int, list[_Typo]] = {}
            for t in todo:
                by_seg.setdefault(t.seg, []).append(t)
            changed: dict[int, str] = {}
            for si, ts_ in by_seg.items():
                texts = texts_by_seg[si]
                for t in sorted(ts_, key=lambda t: -t.new_diff[0]):
                    start, olen, new = t.new_diff
                    _replace_range(texts, start, start + olen, new)
                    applied += 1
                for m, old_t, new_t in zip(segs[si - 1], texts_by_seg_orig(xml, segs[si - 1]), texts):
                    if old_t != new_t:
                        changed[m.start()] = new_t
            out, last = [], 0
            for m in pr._XML_TOKEN.finditer(xml):
                if m.start() not in changed:
                    continue
                txt = changed[m.start()]
                attrs = m.group("attrs")
                if txt != txt.strip() and "xml:space" not in attrs:
                    attrs += ' xml:space="preserve"'
                out.append(xml[last:m.start()])
                out.append(f"<w:t{attrs}>{pr.escape(txt)}</w:t>")
                last = m.end()
            out.append(xml[last:])
            new_parts[part] = "".join(out).encode("utf8")
        if applied:
            tmp = dst.with_name(dst.name + ".part")
            with zipfile.ZipFile(tmp, "w") as zout:
                for info in z.infolist():
                    zi = zipfile.ZipInfo(info.filename, info.date_time)
                    zi.compress_type = info.compress_type
                    zi.external_attr = info.external_attr
                    zout.writestr(zi, new_parts.get(info.filename, z.read(info.filename)))
            tmp.replace(dst)
    return {"applied": applied, "refused": refused, "written": bool(applied), "output": str(dst)}


def texts_by_seg_orig(xml: str, seg: list[re.Match[str]]) -> list[str]:
    return [html.unescape(m.group("text")) for m in seg]


def _replace_range(texts: list[str], a: int, b: int, new: str) -> None:
    """把拼接文本的 [a,b) 换成 new：新字放进 a 所在 run，其余被覆盖的旧字从各自 run 删去。"""
    spans: list[tuple[int, int, int]] = []
    off = 0
    for k, t in enumerate(texts):
        lo, hi = off, off + len(t)
        off = hi
        if b == a:
            if lo <= a <= hi and not spans:
                spans.append((k, a - lo, a - lo))
            continue
        if hi <= a or lo >= b:
            continue
        spans.append((k, max(a, lo) - lo, min(b, hi) - lo))
    if not spans:
        return
    k0, a0, b0 = spans[0]
    texts[k0] = texts[k0][:a0] + new + texts[k0][b0:]
    for k, x, y in spans[1:]:
        texts[k] = texts[k][:x] + texts[k][y:]


# ---------------------------------------------------------------- PDF

def font_scannable(ftype: str, has_tounicode: bool) -> bool:
    """文字能否可靠抽取：Type3 不行；CID/TrueType 子集缺 ToUnicode 不行；标准 Type1 可以。"""
    if ftype == "Type3":
        return False
    if ftype in ("Type0", "TrueType", "CIDFontType0", "CIDFontType2", "OpenType") and not has_tounicode:
        return False
    return True


def scan_pdf(path: Path, rules: list[Rule], protect: list[str] | None = None) -> dict:
    import fitz

    doc = fitz.open(str(path))
    rows: list[dict] = []
    unscannable: list[dict] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        for f in page.get_fonts(full=True):
            xref, ftype = f[0], f[2]
            has_u = doc.xref_get_key(xref, "ToUnicode")[0] != "null"
            if not font_scannable(ftype, has_u):
                unscannable.append({"page": pno + 1, "font": f[3] or f[4], "type": ftype,
                                    "reason": "Type3 或缺 ToUnicode：抽出的文字不可靠，不能当作没有错字"})
        d = page.get_text("dict")
        if not any(b.get("lines") for b in d["blocks"] if b["type"] == 0) and page.get_images():
            unscannable.append({"page": pno + 1, "font": "", "type": "image",
                                "reason": "有图无文字层（扫描页）"})
        for b in d["blocks"]:
            for line in b.get("lines", []) if b["type"] == 0 else []:
                chars: list[str] = []
                italic: list[bool] = []
                for s in line["spans"]:
                    txt = unicodedata.normalize("NFKC", s["text"])
                    chars.extend(txt)
                    italic.extend([taxostyle.font_is_italic(s["font"], s["flags"])] * len(txt))
                text = "".join(chars)
                for h in detect(text, italic, rules, protect or []):
                    auto = (len(h.old) == len(h.new) > 0 and all(pr._is_wide(c) for c in h.old + h.new)
                            and h.rule == "typo-table")
                    reason = h.reason if auto else (h.reason + "；" if h.reason else "") + REDO
                    rows.append({"file": path.name, "where": f"p{pno + 1}", "page": pno + 1,
                                 "bbox": [round(x, 1) for x in line["bbox"]],
                                 "context": _context(text, h.a, h.b), "observed": h.old,
                                 "proposed": h.new, "rule": h.rule, "confidence": h.confidence,
                                 "auto": auto, "reason": reason})
    doc.close()
    return _report(rows, unscannable, file=str(path), kind="pdf")


def fix_pdf(src: Path, dst: Path, rules: list[Rule], protect: list[str] | None = None) -> dict:
    rep = scan_pdf(src, rules, protect)
    pairs = sorted({(t["observed"], t["proposed"]) for t in rep["typos"] if t["auto"]})
    results = pr.patch_pdf(src, dst, pairs) if pairs else []
    applied = sum(r.count for r in results if r.ok)
    return {"applied": applied, "refused": len(rep["typos"]) - applied, "written": applied > 0,
            "output": str(dst), "notes": [r.note for r in results if r.note]}


# ---------------------------------------------------------------- 命令行

def scan(path: Path, rules: list[Rule], protect: list[str] | None = None,
         can_render: CanRender | None = None, allow_length_change: bool = False) -> dict:
    if path.suffix.lower() == ".docx":
        return scan_docx(path, rules, protect, can_render, allow_length_change)
    if path.suffix.lower() == ".pdf":
        return scan_pdf(path, rules, protect)
    raise ValueError("只支持 .docx 和 .pdf")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="成品 DOCX/PDF 错字扫描与字体安全修补")
    ap.add_argument("cmd", choices=("scan", "fix"))
    ap.add_argument("file", type=Path)
    ap.add_argument("--rules", type=Path, help="替换表 TSV：错<TAB>对[<TAB>备注]")
    ap.add_argument("--protect", type=Path, help="保护词表（每行一词，如学名、人名）")
    ap.add_argument("--report", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--assume-fonts-ok", action="store_true")
    ap.add_argument("--allow-length-change", action="store_true")
    ap.add_argument("--font-dir", type=Path, action="append", default=[])
    a = ap.parse_args(argv)
    try:
        rules = read_rules(a.rules) if a.rules else []
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    protect = [x.strip() for x in a.protect.read_text(encoding="utf8").splitlines() if x.strip()] \
        if a.protect else []
    FONT_DIRS[:0] = a.font_dir
    can_render: CanRender = _assume_ok if a.assume_fonts_ok else font_can_render
    try:
        if a.cmd == "fix":
            if not a.output:
                print("fix 需要 -o 输出路径", file=sys.stderr)
                return 2
            if a.output.resolve() == a.file.resolve():
                print("输出不能覆盖原文件", file=sys.stderr)
                return 2
            if a.file.suffix.lower() == ".docx":
                res = fix_docx(a.file, a.output, rules, protect, can_render, a.allow_length_change)
            else:
                res = fix_pdf(a.file, a.output, rules, protect)
            print(json.dumps(res, ensure_ascii=False))
            target = a.output if res["written"] else a.file
            rep = scan(target, rules, protect, can_render, a.allow_length_change)
        else:
            rep = scan(a.file, rules, protect, can_render, a.allow_length_change)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    for t in rep["typos"]:
        print(f"{'AUTO' if t['auto'] else '人工'}\t{t['confidence']}\t{t['rule']}\t{t['where']}\t"
              f"{t['observed']} -> {t['proposed']}\t{t['context']}"
              + ("" if t["auto"] or not t["reason"] else f"\t[{t['reason']}]"))
    for u in rep["unscannable"]:
        print(f"不可安全扫描 p{u['page']}\t{u['font']}\t{u['reason']}")
    print(f"status={rep['status']} typos={len(rep['typos'])} unscannable={len(rep['unscannable'])}",
          file=sys.stderr)
    if a.report:
        a.report.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
