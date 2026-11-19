#!/usr/bin/env python3
"""斜体审计与更正：误斜体（引证、作者名、中文、夹英文词的学名）、图注整条斜体。

出版惯例（用户 2026-11-17 定）：图注正体、学名斜体。原书 Fauna Ibérica 把整条
图注排成 ITC Garamond Light Italic（Vol. 45 p. 30 caption flags=6），照搬后图注
与学名同体、没有层次，不采用。``caption()`` 已改为正体，本脚本负责在交付稿上
核对并更正：图注正文改正体、学名保持斜体，作者名/引证去斜体。

文献引证自动判别：从参考文献目录（aligned JSON 的 ``ref`` 块，或 DOCX 的
References 节）建立「年份 → 姓氏」「姓氏集合」索引；斜体片段含年份且姓氏在
该年份条目里 → ``citation.italic``（确证）；无年份但姓氏都在文献目录、
且带 and/et al./与 等连词 → 按引证处理（probable）。

检查项：
  italic.cjk           斜体里有汉字
  citation.italic      斜体是参考文献目录里确证的引证（Rouse and Fauchald, 1997）
  italic.author        斜体是作者名，但文献目录里查不到
  italic.mixed         学名夹英语虚词（*Torrea and*）
  caption.allitalic    整条图注都在斜体里（应正体）
  caption.name_roman   图注里的学名被排成正体（应斜体），仅 --caption-names italic 时报
  italic.higher_taxon  科名斜体：原书作者名单里本来就斜体，仅提示
  italic.other         书名、强调等，仅提示

用法：
  italic_check.py md <译文.md ...> [--caption-names italic|roman] [--report out.tsv]
  italic_check.py docx <交付.docx ...> [--fix] [--aligned aligned.json] [--out 输出.docx]
  italic_check.py pdf <原书.pdf> [--pages 20-40]
  italic_check.py rendered <交付.docx|交付.pdf> [--report out.json] [--profile zoology] [--no-worms]
      渲染产物审计（委托 taxostyle.py）：学名应斜体、sp./cf./aff. 与科级名称、命名人+年份应正体；
      DOCX 看 run.italic（含表格），PDF 看 span flags/字体名；有 error 退出码 1。
退出码：md/docx 有 critical/major 问题时 1，否则 0；pdf 只审计，恒 0。
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import taxoformat as tf  # noqa: E402

ITALIC = re.compile(r"(?<!\\)\*(?!\*)(?!\s)([^*\n]*?)(?<!\s)(?<!\\)\*(?!\*)")
HAN = re.compile(r"[⺀-鿿豈-﫿＀-￯]")
CAPTION = re.compile(
    r"^\s*(?:\*\*)?(?:Figs?\.?|L[aá]ms?\.?|Tablas?|Tables?|Plates?|图|表)\s*[\dIVXivx]")
YEAR = re.compile(r"\b(?:1[89]|20)\d{2}[a-z]?\b")
RANK = re.compile(r"\b(?:spp?|cf\.|aff\.|var\.|subsp\.|f\.|n\.\s*sp\.|gen\.\s*n\.|indet\.)")
ABBR = re.compile(r"^[A-Z]\.\s+[a-z][a-z-]+")
FAMILY = re.compile(r"(?:idae|inae|ini|oidea)$")
FUNCTION_WORD = {"and", "or", "of", "the", "in", "with", "from", "between", "to",
                 "for", "on", "by", "as", "y", "e", "与", "和", "及"}
CONNECTOR = {"and", "&", "et", "al.", "y", "e", "与", "和", "及", ","}

LEVELS = {"italic.cjk": "critical", "citation.italic": "major", "italic.author": "major",
          "caption.allitalic": "major", "caption.name_roman": "major",
          "italic.mixed": "major", "italic.higher_taxon": "info",
          "italic.other": "info"}
BAD = {k for k, v in LEVELS.items() if v in ("critical", "major")}
# 可自动去斜体的类别：去斜体后图注/正文的学名仍是斜体，只去掉非学名部分。
FIXABLE = {"citation.italic", "italic.author", "italic.mixed", "italic.cjk"}


@dataclass
class Finding:
    kind: str
    where: str
    text: str

    @property
    def level(self) -> str:
        return LEVELS.get(self.kind, "info")

    def row(self) -> str:
        return f"{self.kind}\t{self.level}\t{self.where}\t{self.text}"


@dataclass
class Refs:
    """参考文献索引：年份 → 该年条目的姓氏；全书姓氏集合。"""
    by_year: dict[str, set[str]] = field(default_factory=dict)
    surnames: set[str] = field(default_factory=set)

    def add(self, entry: str) -> None:
        years = YEAR.findall(entry)
        head = entry.split(str(years[0]))[0] if years else entry[:120]
        names = {t.lower() for t in re.findall(r"[A-Z][a-zà-ÿ'’.-]{2,}", head)}
        self.surnames |= names
        for year in years:
            self.by_year.setdefault(year, set()).update(names)

    def __bool__(self) -> bool:
        return bool(self.by_year or self.surnames)


def load_refs_json(path: Path) -> Refs:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    refs = Refs()
    for page in data.get("pages", []):
        for block in page.get("blocks", []):
            if block.get("role") == "ref":
                refs.add(block.get("translation") or block.get("text") or "")
    return refs


def load_refs_docx(doc) -> Refs:
    refs = Refs()
    started = False
    for par in doc.paragraphs:
        text = par.text.strip()
        if re.fullmatch(r"(?:References?|Bibliography|Literature [Cc]ited|参考文献)", text):
            started = True
            continue
        if started and text:
            if par.style.name.startswith("Heading") and refs:
                break
            refs.add(text)
    return refs


def citation_status(span: str, refs: Refs | None) -> str:
    """'citation'（年份+姓氏在文献目录里）、'probable'（姓氏都在目录里）、'no'。"""
    if not refs:
        return "no"
    years = YEAR.findall(span)
    names = [t.lower() for t in re.findall(r"[A-Z][a-zà-ÿ'’.-]{2,}", span)]
    if years and any(name in refs.by_year.get(y, set()) for y in years for name in names):
        return "citation"
    if names and all(name in refs.surnames for name in names) and (
            years or any(tok in CONNECTOR for tok in span.replace(",", " , ").split())):
        return "probable"
    return "no"


def _name_rx(lex: tf.Lexicon) -> re.Pattern[str] | None:
    if not lex.genera:
        return None
    genera = "|".join(sorted((re.escape(g) for g in lex.genera), key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z])({genera})(?:\s+([a-z][a-z-]{{2,}}))?")


def _name_matches(text: str, lex: tf.Lexicon) -> list[tuple[int, int, str]]:
    """属名/双名匹配（带位置）；属名后跟英语虚词时只取属名本身（*Miura and* → *Miura*）。"""
    rx = _name_rx(lex)
    if not rx:
        return []
    out: list[tuple[int, int, str]] = []
    for m in rx.finditer(text):
        ep = m.group(2)
        end = m.end()
        if ep and (ep.lower() in FUNCTION_WORD or tf._is_english_word(ep, lex.english)):
            end = m.end(1)
        out.append((m.start(), end, text[m.start():end]))
    return out


def _names_in(text: str, lex: tf.Lexicon) -> list[str]:
    return [found for _a, _b, found in _name_matches(text, lex)]


def _is_name(span: str, lex: tf.Lexicon) -> bool:
    """斜体内容是不是学名：属名、双名、三名、缩写属名，可带 sp./cf./var. 等阶元词。"""
    s = RANK.sub(" ", span).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return False
    if ABBR.match(s):
        return True
    m = re.fullmatch(r"([A-Z][a-z-]+)(?:\s+([a-z][a-z-]{1,})(?:\s+([a-z][a-z-]{1,}))?)?", s)
    if not m:
        return False
    genus, ep1, _ep2 = m.groups()
    if ep1 is None:
        return genus in lex.genera
    if (genus, ep1) in lex.binomials:
        return True
    # 属名后跟的是英语虚词（*Torrea and*）：不是学名，是斜体范围跨到了正文。
    if ep1.lower() in FUNCTION_WORD or tf._is_english_word(ep1, lex.english):
        return False
    return genus in lex.genera or tf._epithet_like(ep1)


def _tokens(span: str) -> list[str] | None:
    """切成词；遇到不属于「姓氏/缩写/年份/连词/标点」的词返回 None。"""
    out: list[str] = []
    for raw in span.replace("(", " ").replace(")", " ").split():
        tok = raw.strip(",;:")
        if not tok:
            continue
        if re.fullmatch(r"(?:1[89]|20)\d{2}[a-z]?", tok):
            out.append(tok)
        elif tok in CONNECTOR:
            out.append(tok)
        elif re.fullmatch(r"[A-Z]\.(?:[-\s]?[A-Z]\.)*", tok) or re.fullmatch(r"[A-Z][a-zà-ÿ'’.-]+", tok):
            out.append(tok)
        else:
            return None
    return out


def _is_author(span: str, lex: tf.Lexicon) -> bool:
    """作者名/引证：``Surname, 1997`` / ``Rouse and Fauchald`` / ``Rouse et al.``。"""
    toks = _tokens(span)
    if not toks or len(toks) > 8:
        return False
    surnames = 0
    has_year = False
    has_connector = False
    for tok in toks:
        if re.fullmatch(r"(?:1[89]|20)\d{2}[a-z]?", tok):
            has_year = True
        elif tok in CONNECTOR:
            has_connector = True
        elif tok in lex.genera or FAMILY.search(tok):
            return False
        else:
            surnames += 1
    return surnames >= 1 and (has_year or has_connector)


def classify(span: str, lex: tf.Lexicon, caption: bool, caption_names: str = "italic",
             refs: Refs | None = None) -> str:
    span = span.strip().strip("*").strip()
    if HAN.search(span):
        return "italic.cjk"
    name = _is_name(span, lex)
    if caption and name:
        return "italic.other" if caption_names == "italic" else "caption.name_roman"
    if name:
        return "italic.other"
    words = [w.strip(",;:()") for w in span.split()]
    if any(FAMILY.search(w) for w in words):
        return "italic.higher_taxon"
    if _is_author(span, lex):
        return "citation.italic" if citation_status(span, refs) != "no" else "italic.author"
    funcs = [w for w in words if w.lower() in FUNCTION_WORD]
    toks = [w for w in words if w]
    if funcs and len(toks) <= 6 and any(w in lex.genera or FAMILY.search(w) for w in toks):
        return "italic.mixed"
    return "italic.other"


def check_markdown(name: str, text: str, caption_names: str = "italic",
                   refs: Refs | None = None) -> list[Finding]:
    lex = tf.build_lexicon([text])
    out: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        spans = list(ITALIC.finditer(line))
        if not spans:
            continue
        is_caption = bool(CAPTION.match(line))
        for m in spans:
            kind = classify(m.group(1), lex, is_caption, caption_names, refs)
            out.append(Finding(kind, f"{name}:{i}", m.group(0)))
        if is_caption:
            covered = sum(len(re.sub(r"\s", "", m.group(1))) for m in spans)
            total = len(re.sub(r"\s", "", ITALIC.sub("", line))) + covered
            if total and covered / total >= 0.8:
                out.append(Finding("caption.allitalic", f"{name}:{i}", line.strip()[:120]))
    return out


def _runs(par) -> list[tuple[str, bool]]:
    return [(r.text, bool(r.italic)) for r in par.runs if r.text.strip()]


def check_docx(path: Path, caption_names: str = "italic", refs: Refs | None = None) -> list[Finding]:
    from docx import Document

    doc = Document(str(path))
    refs = refs or load_refs_docx(doc)
    lex = tf.build_lexicon(["\n".join(p.text for p in doc.paragraphs)])
    out: list[Finding] = []
    for i, par in enumerate(doc.paragraphs, 1):
        line = par.text.strip()
        runs = _runs(par)
        if not runs or not line:
            continue
        where = f"{path.name}:p{i}"
        is_caption = bool(CAPTION.match(line))
        for run_text, italic in runs:
            if italic and HAN.search(run_text):
                out.append(Finding("italic.cjk", where, run_text.strip()[:80]))
            if italic and is_caption and caption_names == "roman":
                for name in _names_in(run_text, lex):
                    out.append(Finding("caption.name_roman", where, name[:80]))
            if is_caption and not italic and caption_names == "italic":
                for name in _names_in(run_text, lex):
                    out.append(Finding("caption.name_roman", where, name[:80]))
            if italic and not is_caption:
                kind = classify(run_text, lex, False, caption_names, refs)
                if kind in ("citation.italic", "italic.author", "italic.mixed",
                            "italic.higher_taxon", "italic.cjk"):
                    out.append(Finding(kind, where, run_text.strip()[:80]))
        if is_caption:
            italic_chars = sum(len(t) for t, it in runs if it)
            total = sum(len(t) for t, _ in runs)
            if total and italic_chars / total >= 0.9:
                out.append(Finding("caption.allitalic", where, line[:120]))
    return out


def _split_names(text: str, lex: tf.Lexicon) -> list[tuple[str, bool]]:
    """按学名切段：学名 True（斜体），其余 False（正体）。"""
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for start, end, found in _name_matches(text, lex):
        if start > pos:
            pieces.append((text[pos:start], False))
        pieces.append((found, True))
        pos = end
    if pos < len(text):
        pieces.append((text[pos:], False))
    return pieces


def _replace_run(par, run, pieces: list[tuple[str, bool]]) -> None:
    prev = run._element
    for text, italic in pieces:
        if not text:
            continue
        new = par.add_run(text)
        if run._element.rPr is not None:
            if new._element.rPr is not None:
                new._element.remove(new._element.rPr)
            new._element.insert(0, copy.deepcopy(run._element.rPr))
        new.italic = italic
        prev.addnext(new._element)
        prev = new._element
    run._element.getparent().remove(run._element)


def fix_docx(path: Path, out: Path, caption_names: str = "italic",
             refs: Refs | None = None) -> list[Finding]:
    """去误斜体：图注正体+学名斜体；正文里的引证/作者名/中文/混排去斜体。"""
    from docx import Document

    doc = Document(str(path))
    refs = refs or load_refs_docx(doc)
    lex = tf.build_lexicon(["\n".join(p.text for p in doc.paragraphs)])
    findings: list[Finding] = []
    for i, par in enumerate(doc.paragraphs, 1):
        line = par.text.strip()
        if not line:
            continue
        is_caption = bool(CAPTION.match(line))
        for run in list(par.runs):
            text = run.text
            if not text.strip():
                continue
            italic = bool(run.italic)
            if is_caption:
                # 图注一律重排：正文正体、学名斜体（--caption-names roman 反之）。
                plain = _split_names(text, lex)
                if caption_names == "roman":
                    plain = [(t, not it) for t, it in plain]
                _replace_run(par, run, plain)
                continue
            if not italic:
                continue
            kind = classify(text, lex, False, caption_names, refs)
            if kind in FIXABLE:
                findings.append(Finding(kind, f"{out.name}:p{i}", text.strip()[:80]))
                _replace_run(par, run, _split_names(text, lex))
    doc.save(str(out))
    return findings


def audit_pdf(path: Path, pages: range | None = None) -> list[str]:
    """读原书 PDF 的图注字体，作为排版取舍的依据（不是判错标准）。"""
    import fitz

    doc = fitz.open(str(path))
    lex = tf.build_lexicon([""])
    rx = _name_rx(lex)
    rows: list[str] = []
    for pno in (pages or range(doc.page_count)):
        if pno < 1 or pno > doc.page_count:
            continue
        for block in doc[pno - 1].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                txt = "".join(s["text"] for s in spans).strip()
                if not CAPTION.match(txt):
                    continue
                chars = sum(len(s["text"]) for s in spans)
                italic = sum(len(s["text"]) for s in spans if s["flags"] & 2)
                names = [(s["text"].strip(), bool(s["flags"] & 2), s["font"])
                         for s in spans if rx and rx.fullmatch(s["text"].strip())]
                base = max((s["font"] for s in spans), key=lambda f: sum(
                    len(s["text"]) for s in spans if s["font"] == f))
                rows.append(
                    f"p{pno}\tbase={base}\titalic={italic / chars:.2f}\t{txt[:60]}"
                    + (f"\tnames={names}" if names else ""))
    return rows


def report(findings: list[Finding], path: Path | None) -> None:
    for f in findings:
        print(f.row())
    if path:
        path.write_text("kind\tlevel\twhere\ttext\n"
                        + "\n".join(f.row() for f in findings) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, help_text in (("md", "检查译文 Markdown"), ("docx", "检查/更正交付 DOCX"),
                           ("pdf", "审计原书 PDF 图注字体")):
        p = sub.add_parser(cmd, help=help_text)
        p.add_argument("files", nargs="+", type=Path)
        p.add_argument("--caption-names", choices=("italic", "roman"), default="italic",
                       help="图注里的学名应为 italic（出版惯例，默认）还是 roman")
        p.add_argument("--report", type=Path)
        if cmd == "docx":
            p.add_argument("--fix", action="store_true", help="写出更正后的 DOCX")
            p.add_argument("--out", type=Path, help="更正输出路径（单文件时）")
            p.add_argument("--aligned", type=Path, help="aligned JSON，用其中的 ref 块建文献索引")
        if cmd == "pdf":
            p.add_argument("--pages", help="如 20-40，缺省全书")
    rp = sub.add_parser("rendered", help="审计渲染后 DOCX/PDF 的学名体例（taxostyle）")
    rp.add_argument("files", nargs="+", type=Path)
    rp.add_argument("--report", type=Path)
    rp.add_argument("--profile", choices=("zoology", "source"), default="zoology")
    rp.add_argument("--no-worms", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "rendered":
        import taxostyle

        sub_args = [str(args.files[0]), "--profile", args.profile]
        if args.no_worms:
            sub_args.append("--no-worms")
        if args.report:
            sub_args += ["--report", str(args.report)]
        return taxostyle.main(["audit", *sub_args])

    if args.cmd == "pdf":
        rows: list[str] = []
        for f in args.files:
            pages = None
            if args.pages:
                a, _, b = args.pages.partition("-")
                pages = range(int(a), int(b or a) + 1)
            rows += audit_pdf(f, pages)
        print("\n".join(rows))
        if args.report:
            args.report.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return 0

    refs = load_refs_json(args.aligned) if getattr(args, "aligned", None) else None
    findings: list[Finding] = []
    for f in args.files:
        if args.cmd == "md":
            findings += check_markdown(f.name, f.read_text(encoding="utf-8"),
                                       args.caption_names, refs)
        elif args.fix:
            out = args.out if args.out and len(args.files) == 1 else f.with_name(
                f.stem + "_italic.docx")
            findings += fix_docx(f, out, args.caption_names, refs)
            print(f"已写出 {out}", file=sys.stderr)
        else:
            findings += check_docx(f, args.caption_names, refs)
    report(findings, args.report)
    bad = [f for f in findings if f.level in ("critical", "major")]
    print(f"问题 {len(bad)} 条，提示 {len(findings) - len(bad)} 条", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
