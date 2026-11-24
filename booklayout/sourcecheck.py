"""source-check：成品文字与原书扫描页的独立核对（不用大模型）。

做法（2026-11-25，Fauna Ibérica Vol.21 前 50 页：成品排版数据来自 VL-OCR，qa/check/gate 全过，
但 Sonnet 看图核出约 100 处错字、5 处漏文；VL 还会改写词句，如 especie→superficie）：

1. 原书逐页 pdftoppm（-cropbox）→ tesseract TSV，得到带置信度和坐标的词、行。
2. 成品 PDF 用 pdftotext 抽字，去掉书眉/页码，行末连字符拼回。
3. 两边折叠（小写、去重音、去标点）后的词序列做全局对齐（difflib）。
4. 判定：
   - missing：原书一行（≥3 个长度≥3 的字母词、平均置信度≥阈值）大部分词在成品里对不上，
     且整行也不在成品别处（在别处 = moved）。
   - 词级差异（对齐上的同位词、写法不同，含只差重音）：按 aspell 西班牙语词典 + WoRMS 学名判哪边像真词：
       output_error  原书词是真词、成品词不是；
       tess_noise    成品词是真词、原书 OCR 词不是（Tesseract 自己错，不报）；
       conflict      两边都是真词（VL 改写的典型：especie/superficie、parápodo/parápodos）；
       review        两边都不是（数字、罕见学名等）。
   每个待看项按 Tesseract 行坐标从 300 dpi 原图裁小图，人工或便宜模型只看小图。
5. ok = 没有 missing/moved/output_error/conflict，且 review 都在 --accepted 列表里。gate 用 --source-check 接入。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import difflib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
DEFAULT_WORMS = Path(os.environ.get("BOOKLAYOUT_GENERA_DB", "/root/.specimen_inventory/worms_cache.sqlite"))
MIN_LINE_CONF = 70.0
MISSING_FRACTION = 0.5


def fold(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower())
    return "".join(c for c in w if not unicodedata.combining(c))


@dataclass
class SrcTok:
    text: str
    page: int
    line: int
    conf: float
    box: tuple[int, int, int, int]


@dataclass
class SrcLine:
    page: int
    line: int
    text: str
    conf: float
    box: tuple[int, int, int, int]
    toks: list[int] = field(default_factory=list)


@dataclass
class Lexicon:
    words: frozenset[str] = frozenset()          # 带重音小写词形
    names: frozenset[str] = frozenset()          # 学名各部分，小写原写法
    seen: dict[str, int] = field(default_factory=dict)  # 原书 Tesseract 高置信词频（区分大小写）

    def real(self, w: str) -> bool:
        lw = w.lower()
        if lw in self.words or lw in self.names:
            return True
        # 句首大写、全大写标题词
        return lw.capitalize() != w and lw in self.words


# ---------- 资源 ----------

def load_spanish(lang: str = "es") -> frozenset[str]:
    try:
        dump = subprocess.run(["aspell", "-d", lang, "dump", "master"], capture_output=True, text=True, check=True).stdout
        exp = subprocess.run(["aspell", "-l", lang, "expand"], input=dump, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return frozenset()
    return frozenset(w.lower() for w in exp.split() if w.isalpha())


def load_names(path: Path | None = DEFAULT_WORMS, extra: Iterable[str] = ()) -> frozenset[str]:
    out: set[str] = {w.lower() for w in extra}
    if path and Path(path).exists():
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for (vn,) in db.execute("SELECT DISTINCT valid_name FROM worms_taxa"):
                for part in (vn or "").split():
                    if part.isalpha():
                        out.add(part.lower())
            try:
                for (au,) in db.execute("SELECT DISTINCT authority FROM worms_taxa"):
                    for part in TOKEN.findall(au or ""):
                        if part[:1].isupper():
                            out.add(part.lower())
            except sqlite3.Error:
                pass
        finally:
            db.close()
    return frozenset(out)


# ---------- 原书 OCR ----------

def ocr_page(source_pdf: Path, page: int, cache: Path, lang: str, dpi: int) -> Path:
    tsv = cache / f"p{page:04d}.tsv"
    if tsv.exists() and tsv.stat().st_size:
        return tsv
    png = cache / f"p{page:04d}"
    subprocess.run(["pdftoppm", "-cropbox", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile",
                    "-png", str(source_pdf), str(png)], check=True)
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    subprocess.run(["tesseract", f"{png}.png", str(tsv.with_suffix("")), "-l", lang, "tsv"],
                   check=True, capture_output=True, env=env)
    return tsv


def read_tsv(tsv: Path, page: int, furniture: list[re.Pattern[str]],
             toks: list[SrcTok], lines: list[SrcLine]) -> None:
    rows: dict[tuple[int, int, int], list[list[str]]] = {}
    for raw in tsv.read_text(encoding="utf-8").splitlines()[1:]:
        r = raw.split("\t")
        if len(r) < 12 or r[0] != "5" or not r[11].strip():
            continue
        rows.setdefault((int(r[2]), int(r[3]), int(r[4])), []).append(r)
    blocks: dict[int, list[list[list[str]]]] = {}
    for key in sorted(rows):
        blocks.setdefault(key[0], []).extend(split_columns(rows[key]))
    ordered: list[list[list[str]]] = []
    for blk in blocks.values():
        ordered.extend(order_columns(blk))
    pending: SrcTok | None = None
    for ws in ordered:
        text = " ".join(w[11] for w in ws)
        if any(p.search(text) for p in furniture):
            continue
        x0 = min(int(w[6]) for w in ws)
        y0 = min(int(w[7]) for w in ws)
        x1 = max(int(w[6]) + int(w[8]) for w in ws)
        y1 = max(int(w[7]) + int(w[9]) for w in ws)
        confs = [float(w[10]) for w in ws if float(w[10]) >= 0]
        ln = SrcLine(page, len(lines), text, sum(confs) / len(confs) if confs else 0.0, (x0, y0, x1, y1))
        for n, w in enumerate(ws):
            parts = TOKEN.findall(w[11])
            box = (int(w[6]), int(w[7]), int(w[6]) + int(w[8]), int(w[7]) + int(w[9]))
            for t in parts:
                if pending is not None:          # 行末连字符：despren- / de → desprende
                    pending.text += t
                    pending = None
                    continue
                ln.toks.append(len(toks))
                toks.append(SrcTok(t, page, ln.line, float(w[10]), box))
            if n == len(ws) - 1 and parts and w[11].rstrip().endswith(("-", "¬")) and toks:
                pending = toks[-1]
        lines.append(ln)


def _h(w: list[str]) -> int:
    return int(w[9])


def split_columns(ws: list[list[str]]) -> list[list[list[str]]]:
    """一行里两栏图注被 Tesseract 读成同一行时，按大间隙切开。"""
    if len(ws) < 2:
        return [ws]
    hs = sorted(_h(w) for w in ws)
    gap_min = 2.0 * max(hs[len(hs) // 2], 8)
    out: list[list[list[str]]] = [[ws[0]]]
    for prev, cur in zip(ws, ws[1:]):
        if int(cur[6]) - (int(prev[6]) + int(prev[8])) > gap_min:
            out.append([])
        out[-1].append(cur)
    return out


def order_columns(segs: list[list[list[str]]]) -> list[list[list[str]]]:
    """同一块内有并排栏时，先左栏各行、再右栏各行。"""
    xs = sorted({int(s[0][6]) for s in segs})
    if len(segs) < 2 or len(xs) < 2:
        return segs
    span = xs[-1] - xs[0]
    if span < 200:
        return segs
    mid = xs[0] + span / 2
    left = [s for s in segs if int(s[0][6]) < mid]
    right = [s for s in segs if int(s[0][6]) >= mid]
    if not left or not right or len(right) < 2:
        return segs
    return left + right


# ---------- 成品 ----------

def output_tokens(pdf: Path, furniture: list[re.Pattern[str]]) -> tuple[list[str], list[int]]:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    npages = int(re.search(r"Pages:\s+(\d+)", info).group(1))  # type: ignore[union-attr]
    words: list[str] = []
    pages: list[int] = []
    for p in range(1, npages + 1):
        txt = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), str(pdf), "-"],
                             capture_output=True, text=True, check=True).stdout
        keep = [ln for ln in txt.splitlines() if ln.strip() and not any(f.search(ln.strip()) for f in furniture)]
        body = re.sub(r"(\w)-\n\s*(\w)", r"\1\2", "\n".join(keep))
        for t in TOKEN.findall(body):
            words.append(t)
            pages.append(p)
    return words, pages


def aligned_tokens(aligned: Path, furniture: list[re.Pattern[str]]
                   ) -> tuple[list[str], list[int], list[dict[str, Any]]]:
    """Output tokens straight from the aligned JSON (OCR stage, before typesetting).

    Each token carries a ref {block_id, start, end} into that block's `translation`, so a fix can be
    patched at the exact character span.  Whole lines matching `furniture` (folios, running heads) are skipped.
    """
    data = json.loads(Path(aligned).read_text(encoding="utf-8"))
    words: list[str] = []
    pages: list[int] = []
    refs: list[dict[str, Any]] = []
    for pg in data["pages"]:
        for blk in pg["blocks"]:
            text = blk.get("translation") or ""
            pos = 0
            for line in text.splitlines(keepends=True):
                if not any(f.search(line.strip()) for f in furniture):
                    for m in TOKEN.finditer(line):
                        words.append(m.group())
                        pages.append(int(pg["page"]))
                        refs.append({"block_id": blk.get("block_id"), "start": pos + m.start(), "end": pos + m.end()})
                pos += len(line)
    return words, pages, refs


def running_head_patterns(metadata: dict[str, Any]) -> list[re.Pattern[str]]:
    pats = [re.compile(r"^\d{1,4}$")]
    for key in ("running_left", "running_right"):
        head = (metadata.get(key) or "").strip()
        if head:
            pats.append(re.compile(r"^(\d{1,4}\s+)?" + re.escape(head) + r"(\s+\d{1,4})?$"))
    return pats


# ---------- 比对 ----------

def _id(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


OCR_CONFUSIONS = (("b", "h"), ("h", "b"), ("c", "e"), ("e", "c"), ("l", "i"), ("i", "l"), ("n", "u"), ("u", "n"),
                  ("rn", "m"), ("m", "rn"), ("li", "h"), ("h", "li"), ("cl", "d"), ("d", "cl"), ("a", "o"), ("o", "a"),
                  ("t", "f"), ("f", "t"))


def name_variant(word: str, names: frozenset[str]) -> str | None:
    """word 按一处 OCR 易混字符替换后成为已知学名部分时，返回该学名部分。"""
    for a, b in OCR_CONFUSIONS:
        start = word.find(a)
        while start != -1:
            cand = word[:start] + b + word[start + len(a):]
            if cand in names:
                return cand
            start = word.find(a, start + 1)
    return None


def classify(src: str, out: str, lex: Lexicon) -> str:
    s_ok, o_ok = lex.real(src), lex.real(out)
    if not s_ok and not o_ok and lex.seen.get(src, 0) >= 2 and lex.seen.get(out, 0) == 0:
        return "output_error"   # 原书 OCR 里多次高置信读到 src、从未读到 out（领域词不在词典时）
    if s_ok and not o_ok:
        return "output_error"
    if o_ok and not s_ok:
        return "tess_noise"
    if s_ok and o_ok:
        return "conflict"
    return "review"


def compare(src_toks: list[SrcTok], src_lines: list[SrcLine], out_words: list[str], out_pages: list[int],
            lex: Lexicon, min_conf: float = MIN_LINE_CONF,
            refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not lex.seen:
        for t in src_toks:
            if t.conf >= 85:
                lex.seen[t.text] = lex.seen.get(t.text, 0) + 1
    a = [fold(t.text) for t in src_toks]
    b = [fold(w) for w in out_words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched: dict[int, int] = {}
    items: list[dict[str, Any]] = []

    def word_item(i: int, j: int) -> None:
        s, o = src_toks[i].text, out_words[j]
        if s == o or s.lower() == o.lower():
            return
        kind = classify(s, o, lex)
        t = src_toks[i]
        items.append({"id": _id(t.page, t.line, s, o, j), "type": kind, "src_page": t.page, "out_page": out_pages[j],
                      "source": s, "output": o, "conf": round(t.conf, 1), "box": t.box,
                      "context": _ctx(src_toks, i), "ref": refs[j] if refs else None})

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                matched[i1 + k] = j1 + k
                word_item(i1 + k, j1 + k)      # 折叠后相同、写法不同：重音/ñ 差异
        elif tag == "replace" and (i2 - i1) == (j2 - j1) and (i2 - i1) <= 3:
            for k in range(i2 - i1):
                matched[i1 + k] = j1 + k
                s_tok, o_w = src_toks[i1 + k].text, out_words[j1 + k]
                if src_toks[i1 + k].conf >= min_conf or (lex.real(s_tok) and not lex.real(o_w)):
                    word_item(i1 + k, j1 + k)     # 低置信但读成真词、成品非词：仍报
        elif tag == "replace" and (i2 - i1) <= 3 and (j2 - j1) <= 3:
            s = " ".join(t.text for t in src_toks[i1:i2])
            o = " ".join(out_words[j1:j2])
            t = src_toks[i1]
            if fold(s.replace(" ", "")) == fold(o.replace(" ", "")) and s.replace(" ", "") == o.replace(" ", ""):
                pass                              # 只差空格：pdftotext/Tesseract 的切分差异
            elif t.conf >= min_conf:
                kind = classify_phrase(src_toks[i1:i2], out_words[j1:j2], lex)
                items.append({"id": _id(t.page, t.line, s, o, j1), "type": kind, "src_page": t.page,
                              "out_page": out_pages[j1], "source": s, "output": o, "conf": round(t.conf, 1),
                              "box": t.box, "context": _ctx(src_toks, i1)})
            for k in range(i2 - i1):
                matched[i1 + k] = j1
    # 两边 OCR 读得一样也可能都错（斜体 h→b：krohnii→krobnii）：词典外的词若按 OCR 易混字符改一处即成已知学名，
    # 报 name_suspect，交人看图。
    flagged: set[str] = set()
    for i, j in matched.items():
        o = out_words[j]
        lo = o.lower().strip(".,;:()")
        if len(lo) < 5 or not o[:1].islower() or not lo.isalpha() or lex.real(lo) or lo in flagged or src_toks[i].text.lower().strip(".,;:()") != lo:
            continue
        hit = name_variant(lo, lex.names)
        if hit:
            flagged.add(lo)
            t = src_toks[i]
            items.append({"id": _id(t.page, t.line, t.text, o, j), "type": "name_suspect", "src_page": t.page,
                          "out_page": out_pages[j], "source": t.text, "output": o, "suggest": hit,
                          "conf": round(t.conf, 1), "box": t.box, "context": _ctx(src_toks, i),
                          "ref": refs[j] if refs else None})
    page_text: dict[int, list[str]] = {}
    for w, p in zip(b, out_pages):
        page_text.setdefault(p, []).append(w)

    def expected_page(first_tok: int) -> int | None:
        for k in range(first_tok, -1, -1):
            if k in matched:
                return out_pages[matched[k]]
        return None

    src_page_toks: dict[int, list[int]] = {}
    for k, t in enumerate(src_toks):
        src_page_toks.setdefault(t.page, []).append(k)
    for ln in src_lines:
        long = [k for k in ln.toks if len(src_toks[k].text) >= 3 and src_toks[k].text.isalpha()]
        if len(long) < 3 or ln.conf < min_conf:
            continue
        miss = [k for k in long if k not in matched]
        if len(miss) / len(long) < MISSING_FRACTION:
            continue
        phrase = " ".join(fold(src_toks[k].text) for k in ln.toks)
        cand = {out_pages[matched[k]] for k in src_page_toks.get(ln.page - 1, []) + src_page_toks.get(ln.page, [])
                + src_page_toks.get(ln.page + 1, []) if k in matched}
        exp = expected_page(ln.toks[0])
        if exp is not None:
            cand.add(exp)
        near_pages = sorted({q for p in cand for q in (p - 1, p, p + 1)})
        near = " ".join(w for p in near_pages for w in page_text.get(p, []))
        kind = "moved" if phrase and phrase in near else "missing"
        items.append({"id": _id(ln.page, ln.line, ln.text), "type": kind, "src_page": ln.page, "out_page": None,
                      "source": ln.text, "output": "", "conf": round(ln.conf, 1), "box": ln.box, "context": ln.text})
    counts: dict[str, int] = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    return {"ratio": round(sm.ratio(), 4), "src_tokens": len(a), "out_tokens": len(b), "counts": counts,
            "items": items}


def classify_phrase(src: list[SrcTok], out: list[str], lex: Lexicon) -> str:
    s_ok = all(lex.real(t.text) for t in src)
    o_ok = all(lex.real(w) for w in out)
    if s_ok and not o_ok:
        return "output_error"
    if o_ok and not s_ok:
        return "tess_noise"
    return "conflict" if s_ok else "review"


def _ctx(toks: list[SrcTok], i: int, n: int = 6) -> str:
    return " ".join(t.text for t in toks[max(0, i - n):i + n + 1])


BLOCKING = ("missing", "moved", "output_error", "conflict", "name_suspect")


def verdict(report: dict[str, Any], accepted: set[str]) -> tuple[bool, dict[str, int]]:
    open_: dict[str, int] = {}
    for it in report["items"]:
        if it["type"] == "tess_noise" or it["id"] in accepted:
            continue
        if it["type"] in BLOCKING or it["type"] == "review":
            open_[it["type"]] = open_.get(it["type"], 0) + 1
    return not open_, open_


def crop_items(source_pdf: Path, items: list[dict[str, Any]], crops: Path, dpi: int) -> None:
    crops.mkdir(parents=True, exist_ok=True)
    for it in items:
        if it["type"] == "tess_noise":
            continue
        x0, y0, x1, y1 = it["box"]
        pad = int(dpi * 0.15)
        dest = crops / f"p{it['src_page']:04d}_{it['type']}_{it['id']}"
        subprocess.run(["pdftoppm", "-cropbox", "-r", str(dpi), "-f", str(it["src_page"]), "-l", str(it["src_page"]),
                        "-x", str(max(0, x0 - pad * 4)), "-y", str(max(0, y0 - pad)), "-W", str(x1 - x0 + pad * 8),
                        "-H", str(y1 - y0 + pad * 2), "-singlefile", "-png", str(source_pdf), str(dest)],
                       check=False, capture_output=True)
        it["crop"] = f"{dest}.png"


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.extend(range(int(a), int(b or a) + 1))
    return pages


def run(args: argparse.Namespace) -> dict[str, Any]:
    work = Path(args.work)
    cache = work / "tesseract"
    cache.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(args.pages)
    furn_src = [re.compile(p) for p in (args.source_furniture or [])] + [re.compile(r"^\W*\d{1,4}\W*$")]
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        tsvs = list(ex.map(lambda p: ocr_page(args.source_pdf, p, cache, args.lang, args.dpi), pages))
    toks: list[SrcTok] = []
    lines: list[SrcLine] = []
    for p, tsv in zip(pages, tsvs):
        read_tsv(tsv, p, furn_src, toks, lines)
    meta = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else {}
    furn_out = running_head_patterns(meta) + [re.compile(p) for p in (args.output_furniture or [])]
    refs = None
    if args.aligned:
        words, opages, refs = aligned_tokens(args.aligned, furn_out)
    else:
        words, opages = output_tokens(args.pdf, furn_out)
    lex = Lexicon(load_spanish(args.dict_lang), load_names(args.worms, _extra_names(args.names)))
    report = compare(toks, lines, words, opages, lex, args.min_conf, refs)
    if not args.no_crops:
        crop_items(args.source_pdf, report["items"], work / "crops", args.dpi)
    accepted = set(json.loads(Path(args.accepted).read_text(encoding="utf-8"))) if args.accepted else set()
    ok, open_ = verdict(report, accepted)
    report.update({"ok": ok, "open": open_, "pages": [pages[0], pages[-1]], "source_pdf": str(args.source_pdf),
                   "pdf": str(args.pdf) if args.pdf else None, "aligned": str(args.aligned) if args.aligned else None, "lang": args.lang, "dictionary_words": len(lex.words),
                   "name_words": len(lex.names)})
    order = {"missing": 0, "moved": 1, "output_error": 2, "conflict": 3, "name_suspect": 4, "review": 5, "tess_noise": 6}
    report["items"].sort(key=lambda it: (order[it["type"]], it["src_page"]))
    return report


def _extra_names(paths: list[str] | None) -> list[str]:
    out: list[str] = []
    for p in paths or []:
        out.extend(TOKEN.findall(Path(p).read_text(encoding="utf-8")))
    return out


def cmd_source_check(args: argparse.Namespace) -> int:
    if bool(args.pdf) == bool(args.aligned):
        print("error: give exactly one of --pdf and --aligned")
        return 2
    report = run(args)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {k: report[k] for k in ("ok", "open", "counts", "ratio", "src_tokens", "out_tokens")}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report["ok"] else 1


def add_parser(sub: Any) -> None:
    sc = sub.add_parser("source-check", help="check a typeset PDF against the scanned source pages "
                                             "(independent Tesseract OCR + dictionary/WoRMS triage; no LLM)")
    sc.add_argument("--source-pdf", type=Path, required=True, help="scanned original book")
    sc.add_argument("--pages", required=True, help="source PDF pages, e.g. 1-50 or 1-4,6-50")
    sc.add_argument("--pdf", type=Path, help="typeset output PDF (final gate)")
    sc.add_argument("--aligned", type=Path, help="aligned JSON instead of a PDF (OCR-stage fence; items carry "
                                                 "block/char refs for source-fix)")
    sc.add_argument("--metadata", type=Path, help="build metadata (running heads are dropped from the output text)")
    sc.add_argument("--work", type=Path, required=True, help="cache dir for Tesseract TSV and crops")
    sc.add_argument("--out", type=Path, required=True)
    sc.add_argument("--lang", default="spa", help="tesseract languages (default spa)")
    sc.add_argument("--dict-lang", default="es", help="aspell dictionary (default es)")
    sc.add_argument("--worms", type=Path, default=DEFAULT_WORMS, help="local WoRMS cache sqlite")
    sc.add_argument("--names", action="append", help="extra name list file(s): authors, taxa")
    sc.add_argument("--source-furniture", action="append",
                    help="regex for source running heads/folios to skip (repeatable)")
    sc.add_argument("--output-furniture", action="append", help="extra regex for output lines to skip")
    sc.add_argument("--accepted", type=Path, help="JSON list of item ids already reviewed and accepted")
    sc.add_argument("--min-conf", type=float, default=MIN_LINE_CONF)
    sc.add_argument("--dpi", type=int, default=300)
    sc.add_argument("--jobs", type=int, default=4)
    sc.add_argument("--no-crops", action="store_true")
    sc.set_defaults(func=cmd_source_check)
