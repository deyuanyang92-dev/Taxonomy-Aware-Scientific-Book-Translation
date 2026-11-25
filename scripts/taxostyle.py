#!/usr/bin/env python3
"""分类学阶元体例（斜体/正体）确定性审计，0 token。

两类输入，共用一套逐 token 判定（issue #34、#20）：

1. ``compare``：对齐 JSON 的每个块，原文（``text``，斜体用 ``*...*``）与译文（``translation``）
   逐 token 比对。错误码：
     source_italic_translation_roman   原文属/种名斜体，译文正体（丢失斜体）
     translation_roman_expected_italic 译文里的学名为正体（原文里没有该名的斜体依据），warning
     translation_italic_expected_roman 译文把科级及以上、sp./cf./aff. 等限定语、命名人+年份排成斜体
     name_partial_italic               学名一半斜体一半正体
     unclassified_capitalised          斜体里孤立的大写词，词典里查不到阶元，送人工复核（info）
     source_family_italic_accepted      原书科名斜体（如 Fauna Ibérica），体例 profile 记为已知偏离（info）
   译文是否应斜体由阶元规则判定，不因原文也斜体而放行。
2. ``audit``：渲染后的 DOCX（run 的 italic，含表格）或 PDF（span 的 flags/字体名）单看体例：
     name_roman / name_partial_italic / qualifier_italic / higher_taxon_italic / authority_italic
   PDF 里含 Type3 字体的页只能报告「不可安全扫描」，不会静默跳过。

体例 profile（--profile）：zoology（默认，科级及以上正体）；source（不查科级，仅查学名与限定语）。
参考文献块（role=ref）、书名刊名斜体不报；整条斜体的长图注交给 italic_check 的 caption.allitalic。

用法：
  taxostyle.py compare <aligned.json> [--report out.json] [--profile zoology] [--no-worms]
  taxostyle.py audit <交付.docx|交付.pdf> [--report out.json] [--profile zoology] [--no-worms]
退出码：有 error 级问题 1，否则 0。report 的 ``ok`` 字段可直接交给 ``booklayout gate --style-report``。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import italic_check as ic  # noqa: E402
import taxoformat as tf  # noqa: E402

PROFILES = ("zoology", "source")

QUALIFIER = re.compile(
    r"(?<![A-Za-z])(?:sp\.\s*nov\.|gen\.\s*nov\.|n\.\s*sp\.|n\.\s*gen\.|spp?\.|cf\.|aff\.|var\.|subsp\.|ssp\.)")
HIGHER = re.compile(r"(?<![A-Za-z])[A-Z][a-z]+(?:idae|inae|oidea|iformia)(?![A-Za-z])")
AUTHORITY = re.compile(
    r"(?<![A-Za-z])[A-Z][\w'’-]+(?:\s+(?:and|&|et|y|与|和)\s+[A-Z][\w'’-]+|\s+et\s+al\.)?"
    r",?\s*\(?(?:1[6-9]\d\d|20\d\d)[a-z]?\)?")
CAP_WORD = re.compile(r"[A-Z][a-z]{3,}")
RANKS = {"idae": "family", "inae": "subfamily", "oidea": "superfamily", "iformia": "order"}
_ITALIC_FONT = re.compile(r"(?:Italic|Oblique|Ital\b|Ita$|-It$|-Kursiv|Slanted)", re.I)


@dataclass
class StyleIssue:
    code: str
    severity: str          # error | warning | info
    where: str
    token: str
    rank: str              # name | qualifier | family | authority | ...
    observed: str          # italic | roman | mixed
    expected: str          # italic | roman | review
    evidence: str
    page: int | None = None
    block_id: str | None = None
    start: int = 0


@dataclass
class Tok:
    start: int
    end: int
    text: str
    rank: str
    expected: str


def parse_md(s: str) -> tuple[str, list[bool]]:
    """Markdown 斜体 -> (纯文本, 每字符是否斜体)。``**`` 粗体标记去掉，``\\*`` 为字面星号。"""
    s = s.replace("**", "")
    out: list[str] = []
    flags: list[bool] = []
    it = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "*":
            out.append("*")
            flags.append(it)
            i += 2
            continue
        if c == "*":
            it = not it
        else:
            out.append(c)
            flags.append(it)
        i += 1
    return "".join(out), flags


def observed_style(flags: list[bool], text: str, a: int, b: int) -> str:
    idx = [i for i in range(a, b) if text[i].isascii() and text[i].isalpha()]
    if not idx:
        return "roman"
    n = sum(flags[i] for i in idx)
    return "italic" if n == len(idx) else "roman" if n == 0 else "mixed"


def font_is_italic(font: str, flags: int) -> bool:
    return bool(flags & 2) or bool(_ITALIC_FONT.search(unicodedata.normalize("NFKC", font or "")))


def _after_ok(text: str, end: int) -> bool:
    return end >= len(text) or not (text[end].isascii() and text[end].isalpha())


def scan(text: str, lex: tf.Lexicon, profile: str = "zoology") -> list[Tok]:
    """按阶元规则抽出需要判体例的 token，并给出期望体例。"""
    toks: list[Tok] = []
    for a, b, found in ic._name_matches(text, lex):
        if _after_ok(text, b):
            toks.append(Tok(a, b, found, "name", "italic"))
    taken = [(t.start, t.end) for t in toks]

    def free(a: int, b: int) -> bool:
        return not any(a < y and x < b for x, y in taken)

    for m in QUALIFIER.finditer(text):
        toks.append(Tok(m.start(), m.end(), m.group(0), "qualifier", "roman"))
    if profile == "zoology":
        for m in HIGHER.finditer(text):
            if m.group(0) not in lex.genera and free(m.start(), m.end()):
                suffix = next(s for s in RANKS if m.group(0).endswith(s))
                toks.append(Tok(m.start(), m.end(), m.group(0), RANKS[suffix], "roman"))
    for m in AUTHORITY.finditer(text):
        first = m.group(0).split()[0].strip(",")
        if first not in lex.genera and free(m.start(), m.end()):
            toks.append(Tok(m.start(), m.end(), m.group(0), "authority", "roman"))
    return sorted(toks, key=lambda t: t.start)


def _unclassified(text: str, flags: list[bool], toks: list[Tok], lex: tf.Lexicon) -> list[Tok]:
    out: list[Tok] = []
    i = 0
    while i < len(text):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < len(text) and flags[j]:
            j += 1
        run = text[i:j].strip()
        off = i + (len(text[i:j]) - len(text[i:j].lstrip()))
        if CAP_WORD.fullmatch(run) and run not in lex.genera and not tf._is_english_word(run, lex.english) \
                and not any(t.start <= off < t.end for t in toks) and not HIGHER.fullmatch(run):
            out.append(Tok(off, off + len(run), run, "unclassified", "review"))
        i = j
    return out


def _issue(code: str, sev: str, t: Tok, observed: str, where: str, evidence: str, **kw) -> StyleIssue:
    return StyleIssue(code, sev, where, t.text, t.rank, observed, t.expected, evidence, start=t.start, **kw)


def check_styled(text: str, flags: list[bool], lex: tf.Lexicon, where: str,
                 profile: str = "zoology") -> list[StyleIssue]:
    """渲染稿/单侧文本：只看自身体例是否符合阶元规则。"""
    issues: list[StyleIssue] = []
    toks = scan(text, lex, profile)
    for t in toks:
        obs = observed_style(flags, text, t.start, t.end)
        if t.rank == "name":
            if obs == "roman":
                issues.append(_issue("name_roman", "error", t, obs, where, "WoRMS/文本词典属名，应斜体"))
            elif obs == "mixed":
                issues.append(_issue("name_partial_italic", "error", t, obs, where, "学名只有部分斜体"))
        elif obs != "roman":
            code = {"qualifier": "qualifier_italic", "authority": "authority_italic"}.get(t.rank, "higher_taxon_italic")
            ev = {"qualifier": "sp./cf./aff. 等限定语应正体", "authority": "命名人与年份应正体"}.get(
                t.rank, f"{t.rank} 级及以上名称按 zoology profile 应正体（词尾规则）")
            issues.append(_issue(code, "error", t, obs, where, ev))
    return issues


def compare_block(source: str, translation: str, lex: tf.Lexicon, where: str, role: str = "body",
                  profile: str = "zoology", page: int | None = None,
                  block_id: str | None = None) -> list[StyleIssue]:
    if role == "ref":
        return []
    s_text, s_flags = parse_md(source)
    t_text, t_flags = parse_md(translation)
    letters = [f for c, f in zip(t_text, t_flags) if not c.isspace()]
    if role == "caption" and len(letters) > 30 and sum(letters) / len(letters) >= 0.9:
        return []  # 整条斜体图注交给 italic_check 的 caption.allitalic
    s_toks = scan(s_text, lex, profile)
    s_italic_names = {t.text for t in s_toks
                      if t.rank == "name" and observed_style(s_flags, s_text, t.start, t.end) == "italic"}
    issues: list[StyleIssue] = []
    for t in scan(t_text, lex, profile):
        obs = observed_style(t_flags, t_text, t.start, t.end)
        if t.rank == "name":
            if obs == "italic":
                continue
            if obs == "mixed":
                issues.append(_issue("name_partial_italic", "error", t, obs, where, "学名只有部分斜体"))
            elif t.text in s_italic_names:
                issues.append(_issue("source_italic_translation_roman", "error", t, obs, where,
                                     "原文该学名斜体，译文丢失斜体"))
            else:
                issues.append(_issue("translation_roman_expected_italic", "warning", t, obs, where,
                                     "词典属名在译文为正体，原文无斜体依据"))
        elif obs != "roman":
            ev = {"qualifier": "限定语（sp./cf./aff./var.）依 ICZN 惯例正体", "authority": "命名人与年份应正体"}.get(
                t.rank, f"{t.rank} 级名称，zoology profile 正体（不因原文斜体而放行）")
            issues.append(_issue("translation_italic_expected_roman", "error", t, obs, where, ev))
    for t in _unclassified(t_text, t_flags, scan(t_text, lex, profile), lex):
        issues.append(_issue("unclassified_capitalised", "info", t, "italic", where,
                             "斜体大写词无法判定阶元，人工复核，不自动改"))
    if profile == "zoology":
        t_italic = {x.text for x in scan(t_text, lex, profile) if x.rank in RANKS.values()
                    and observed_style(t_flags, t_text, x.start, x.end) != "roman"}
        for t in s_toks:
            if t.rank in RANKS.values() and t.text not in t_italic \
                    and observed_style(s_flags, s_text, t.start, t.end) == "italic":
                issues.append(_issue("source_family_italic_accepted", "info", t, "italic", where,
                                     "原书科名斜体，译文按 ICZN 惯例正体：profile 已知偏离，不重复报错"))
    for i in issues:
        i.page, i.block_id = page, block_id
    return issues


def _summary(issues: list[StyleIssue], **extra) -> dict:
    errors = sum(i.severity == "error" for i in issues)
    return {"ok": errors == 0, "errors": errors,
            "warnings": sum(i.severity == "warning" for i in issues),
            "infos": sum(i.severity == "info" for i in issues),
            "issues": [asdict(i) for i in issues], **extra}


def _lexicon(texts: list[str], worms: bool, genera: list[str] | None = None) -> tf.Lexicon:
    return tf.build_lexicon(texts, extra_genera=genera,
                            genera_db=tf.DEFAULT_GENERA_DB if worms else None)


def compare_aligned(path: Path, lex: tf.Lexicon | None = None, profile: str = "zoology",
                    worms: bool = True, genera: list[str] | None = None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = [(p.get("page"), b) for p in data.get("pages", []) for b in p.get("blocks", [])]
    lex = lex or _lexicon([b.get("translation") or "" for _p, b in blocks]
                          + [b.get("text") or "" for _p, b in blocks], worms, genera)
    issues: list[StyleIssue] = []
    for page, b in blocks:
        if not b.get("translation"):
            continue
        bid = b.get("block_id")
        issues += compare_block(b.get("text") or "", b["translation"], lex, f"p{page}/{bid}",
                                b.get("role") or "body", profile, page, bid)
    return _summary(issues, source=str(path), profile=profile, blocks=len(blocks))


def _styled_paragraphs(path: Path):
    from docx import Document
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    in_refs = False
    for i, el in enumerate(doc.element.body.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"), 1):
        par = Paragraph(el, doc)
        text = par.text.strip()
        if re.fullmatch(r"(?:References?|Bibliography|Literature [Cc]ited|参考文献)", text):
            in_refs = True
            continue
        if in_refs and par.style is not None and par.style.name.startswith("Heading") and text:
            in_refs = False
        pstyle_italic = bool(par.style.font.italic) if par.style is not None else False
        chars: list[str] = []
        flags: list[bool] = []
        for r in par.runs:
            it = r.italic
            if it is None and r.style is not None:
                it = r.style.font.italic
            it = pstyle_italic if it is None else bool(it)
            chars.extend(r.text)
            flags.extend([it] * len(r.text))
        yield i, "".join(chars), flags, in_refs


def audit_docx(path: Path, lex: tf.Lexicon | None = None, profile: str = "zoology",
               worms: bool = True, genera: list[str] | None = None) -> dict:
    paras = list(_styled_paragraphs(path))
    lex = lex or _lexicon(["\n".join(t for _i, t, _f, _r in paras)], worms, genera)
    issues: list[StyleIssue] = []
    for i, text, flags, in_refs in paras:
        if in_refs or not text.strip():
            continue
        issues += check_styled(text, flags, lex, f"{path.name}:p{i}", profile)
    return _summary(issues, source=str(path), profile=profile, paragraphs=len(paras))


def audit_pdf(path: Path, lex: tf.Lexicon | None = None, profile: str = "zoology",
              worms: bool = True, genera: list[str] | None = None) -> dict:
    import fitz

    doc = fitz.open(str(path))
    lines: list[tuple[int, str, list[bool]]] = []
    unscannable: list[dict] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        t3 = [f[3] or f[4] for f in page.get_fonts() if f[2] == "Type3"]
        if t3:
            unscannable.append({"page": pno + 1, "reason": "Type3 字体，无可靠文本/字体信息", "fonts": t3})
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                chars: list[str] = []
                flags: list[bool] = []
                for s in line["spans"]:
                    txt = unicodedata.normalize("NFKC", s["text"])
                    chars.extend(txt)
                    flags.extend([font_is_italic(s["font"], s["flags"])] * len(txt))
                if "".join(chars).strip():
                    lines.append((pno + 1, "".join(chars), flags))
    doc.close()
    lex = lex or _lexicon(["\n".join(t for _p, t, _f in lines)], worms, genera)
    issues: list[StyleIssue] = []
    for pno, text, flags in lines:
        for it in check_styled(text, flags, lex, f"{path.name}:p{pno}", profile):
            it.page = pno
            issues.append(it)
    return _summary(issues, source=str(path), profile=profile, lines=len(lines),
                    unscannable_pages=unscannable)


def audit(path: Path, **kw) -> dict:
    ext = path.suffix.lower()
    if ext == ".docx":
        return audit_docx(path, **kw)
    if ext == ".pdf":
        return audit_pdf(path, **kw)
    raise ValueError("只支持 .docx 和 .pdf")


def _print(rep: dict, report: Path | None) -> None:
    for i in rep["issues"]:
        if i["severity"] != "info":
            print(f"{i['severity']}\t{i['code']}\t{i['where']}\t{i['token']}\t"
                  f"observed={i['observed']} expected={i['expected']}")
    print(f"errors={rep['errors']} warnings={rep['warnings']} infos={rep['infos']}", file=sys.stderr)
    for u in rep.get("unscannable_pages", []):
        print(f"不可安全扫描 p{u['page']}: {u['reason']}", file=sys.stderr)
    if report:
        report.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("compare", "audit"):
        p = sub.add_parser(cmd)
        p.add_argument("file", type=Path)
        p.add_argument("--report", type=Path)
        p.add_argument("--profile", choices=PROFILES, default="zoology")
        p.add_argument("--no-worms", action="store_true", help="不加载 WoRMS 属名库，只用文本里的学名")
        p.add_argument("--genera", default="", help="补充属名，逗号分隔（配合 --no-worms）")
    a = ap.parse_args(argv)
    extra = [g.strip() for g in a.genera.split(",") if g.strip()]
    if a.cmd == "compare":
        rep = compare_aligned(a.file, profile=a.profile, worms=not a.no_worms, genera=extra)
    else:
        try:
            rep = audit(a.file, profile=a.profile, worms=not a.no_worms, genera=extra)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    _print(rep, a.report)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
