#!/usr/bin/env python3
"""版面评测：原生版/扫描版对页（设计 docs/superpowers/specs/2026-11-26-fast-relayout-design.md A.2）。

扫描件分段拼接、夹图版，页偏移不固定，所以按文字对页：折叠后长度 >=4 的词做 Jaccard，
最大者须 >= min_sim 且 >= ratio 倍第二名，否则标 ambiguous / none，不硬配。

用法：
  python3 scripts/bench/layout_pair.py match <native.pdf> <scan_pages_dir> [--pages 16,25,...]
  python3 scripts/bench/layout_pair.py sample -o docs/ocr_eval/layout_sample.tsv
<scan_pages_dir> 是 docstore 页 JSON 目录（pNNNN.json，含 text 字段）；缺页时可用 --tesseract 现场 OCR。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROUSE_NATIVE = "/mnt/p/翻译-译作/Rouse2022_Annelida/原书/Rouse2022_Annelida_专著全本.pdf"
GREG_SCAN = "/mnt/p/翻译-译作/Handbook_Annelida/Greg_Annelida_2022.pdf"
GREG_PAGES = "/mnt/p/翻译-译作/参考资料/_资料库/pages/Greg_Annelida"
_WORD = re.compile(r"[a-z]{4,}")

# 参考文献页(400/500)曾试配：扫描版参考文献分页与原生版不同（Jaccard 0.27-0.33，首条目不同），
# 页面内容不对等，不能当 GT，故不入样本；该层改为词条页与另一章首页。
# 分层选页（原生页号）。依据：PyMuPDF 字体统计（Dante 24/18 章名、Bold 14 节标题、Medium 12 小节标题、
# 图+图注 Dante 9、SourceSans 8.7 参考文献、Bold 10 词条、PLATE 起首）。选好后用页图人工复核。
STRATA: list[tuple[str, int]] = [
    ("chapter_first", 16), ("chapter_first", 100),
    ("body_headings", 13), ("body_headings", 19), ("body_headings", 30), ("body_headings", 50),
    ("figure_caption", 17), ("figure_caption", 25), ("figure_caption", 60),
    ("glossary", 339), ("glossary", 340), ("chapter_first", 200),
    ("front", 6),
    ("plate", 586), ("plate", 589),
    ("body_headings", 120),
]


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def match_pages(native: dict[int, str], scan: dict[int, str], *, min_sim: float = 0.2,
                ratio: float = 2.0, min_words: int = 8) -> dict[int, dict]:
    """native/scan: 页号 -> 文字。返回 页号 -> {scan, sim, second, status: ok|ambiguous|none|short}。"""
    sw = {i: words(t) for i, t in scan.items()}
    out: dict[int, dict] = {}
    for n, t in native.items():
        a = words(t)
        if len(a) < min_words:
            out[n] = {"scan": None, "sim": 0.0, "second": 0.0, "status": "short"}
            continue
        sc = sorted(((jaccard(a, b), i) for i, b in sw.items()), reverse=True)[:2]
        if not sc:
            out[n] = {"scan": None, "sim": 0.0, "second": 0.0, "status": "none"}
            continue
        s1, i1 = sc[0]
        s2 = sc[1][0] if len(sc) > 1 else 0.0
        if s1 < min_sim:
            st = "none"
        elif s1 < ratio * s2:
            st = "ambiguous"
        else:
            st = "ok"
        out[n] = {"scan": i1, "sim": round(s1, 3), "second": round(s2, 3), "status": st}
    return out


def native_texts(pdf: str, pages: list[int]) -> dict[int, str]:
    import fitz
    d = fitz.open(pdf)
    return {p: d[p - 1].get_text() for p in pages}


def docstore_texts(pages_dir: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for f in sorted(Path(pages_dir).glob("p*.json")):
        m = re.match(r"p(\d+)\.json$", f.name)
        if m:
            out[int(m.group(1))] = json.loads(f.read_text(encoding="utf-8")).get("text", "")
    return out


def tesseract_texts(pdf: str, pages: list[int], dpi: int = 100) -> dict[int, str]:
    import subprocess
    out: dict[int, str] = {}
    for p in pages:
        png = subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-png", "-singlefile", pdf, "-"],
                             capture_output=True, check=True).stdout
        t = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng"], input=png, capture_output=True, check=True)
        out[p] = t.stdout.decode("utf-8", "replace")
    return out


def printed_page(text: str) -> str:
    """页眉/页脚里的印刷页码（首或末几行里的纯数字）；找不到返回空串。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:3] + lines[-3:]:
        m = re.fullmatch(r"(\d{1,3})", ln)
        if m:
            return m.group(1)
    return ""


HEADER = ["book", "native_pdf", "native_page", "scan_pdf", "scan_page", "printed_page", "stratum", "sim", "second", "status"]


def build_sample(native_pdf: str = ROUSE_NATIVE, scan_pdf: str = GREG_SCAN, scan_dir: str = GREG_PAGES,
                 strata: list[tuple[str, int]] | None = None, book: str = "Rouse2022") -> list[dict]:
    strata = strata or STRATA
    nat = native_texts(native_pdf, [p for _, p in strata])
    scan = docstore_texts(scan_dir)
    m = match_pages(nat, scan)
    rows = []
    for st, p in strata:
        r = m[p]
        rows.append({"book": book, "native_pdf": native_pdf, "native_page": p, "scan_pdf": scan_pdf,
                     "scan_page": r["scan"] or "", "printed_page": printed_page(nat[p]), "stratum": st,
                     "sim": r["sim"], "second": r["second"], "status": r["status"]})
    return rows


def write_tsv(rows: list[dict], path: str) -> None:
    lines = ["\t".join(HEADER)] + ["\t".join(str(r[h]) for h in HEADER) for r in rows]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_tsv(path: str) -> list[dict]:
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
        if ln.strip():
            rows.append(dict(zip(HEADER, ln.split("\t"))))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="生成固定样本表")
    s.add_argument("-o", "--out", default="docs/ocr_eval/layout_sample.tsv")
    m = sub.add_parser("match", help="任意原生页对扫描页")
    m.add_argument("native_pdf")
    m.add_argument("scan_pages_dir")
    m.add_argument("--pages", required=True, help="逗号分隔原生页号")
    a = ap.parse_args(argv)
    if a.cmd == "sample":
        rows = build_sample()
        write_tsv(rows, a.out)
        bad = [r for r in rows if r["status"] != "ok"]
        print(f"wrote {a.out}: {len(rows)} rows, non-ok {len(bad)}")
        for r in bad:
            print("  ", r["native_page"], r["stratum"], r["status"], r["sim"], r["second"])
        return 0
    pages = [int(x) for x in a.pages.split(",")]
    res = match_pages(native_texts(a.native_pdf, pages), docstore_texts(a.scan_pages_dir))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
