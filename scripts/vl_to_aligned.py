"""PaddleOCR-VL 版面 jsonl -> booklayout 对齐 JSON（零模型）。

用法：python3 scripts/vl_to_aligned.py <jsonl目录 pNNNN.jsonl> <页图目录 pNNNN.png> <输出目录> [--chapter KEY]
输出：aligned.json（译文字段待填）、source_figure_audit.json、source_figure_crops/。
refine(aligned) 可在填完译文后再跑：去掉图版字母块（A、B C D）、把目录/索引页 content 块拆成逐条 index 块。
2026-11-22 Fauna Ibérica Vol.41 试点：VL 把图版字母标成 figure_title/doc_title，导致 qa bad_captions；
索引页 content 是一整段带引导点的文字，booklayout 报 lost_markers(walled_paragraph)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAP = {"text": "body", "abstract": "body", "reference_content": "ref", "content": "index",
       "paragraph_title": "heading", "doc_title": "heading", "figure_title": "caption",
       "vision_footnote": "body", "footnote": "body", "display_formula": "body"}
SKIP = {"header", "footer", "number", "image", "header_image", "footer_image", "aside_text", "seal"}
KEYLINE = re.compile(
    r"^\s*(?:\d+['’]?\.|[•·▪●–—-])\s.*(?:\.{3,}|…|(?:\.\s){3,})"  # 标记 + 引导点
    r"|^.*\S\.{2,}\s*\d{1,3}['’]?\s*$"  # 续行：无标记，引导点 + 页码/条号结尾
    r"|^\s*(?:\d+['’]?\.|[•·▪●–—-])\s.*\(p\.\s*\d+\)\s*$")  # 无引导点的 (p. N) 目标
LEADER = re.compile(r"\s*(?:[.…·]\s*){2,}\s*(?=\S+(?:\s\S+){0,6}\s*$)")
SKIPKEY = {"paragraph_title", "doc_title", "figure_title", "image"}


def norm_key(src: str, zh: str) -> str:
    """译文引导点统一为 ' ..... '；译文丢了引导点时按原文补上。"""
    ms = list(LEADER.finditer(zh))
    if ms:
        m = ms[-1]
        return zh[:m.start()].rstrip() + " ..... " + zh[m.end():].strip()
    ms = list(LEADER.finditer(src))
    if ms:
        return zh.rstrip() + " ..... " + src[ms[-1].end():].strip()
    return zh


FIGLABEL = re.compile(r"^\s*(?:Figs?\.?|Figuras?|L[aá]m(?:ina)?s?\.?|Pl(?:ate)?s?\.?)\s*\d", re.I)
BINOMIAL = re.compile(r"^\s*[A-Z][a-z]+\s+(?:\([A-Z][a-z]+\)\s+)?[a-z]{3,}\b")
PANEL = re.compile(r"^\(?[A-Za-z]{1,2}\)?(?:[\s,.-]+\(?[A-Za-z]{1,2}\)?){0,12}[.]?$")


def is_panel_letters(text: str) -> bool:
    t = text.strip()
    return bool(t) and len(t) <= 40 and bool(PANEL.match(t)) and not re.search(r"[a-z]{3}", t)


def convert(jsonl_dir: Path, png_dir: Path, out: Path, chapter: str = "Book") -> dict:
    from PIL import Image
    (out / "source_figure_crops").mkdir(parents=True, exist_ok=True)
    pages, figs = [], []
    for f in sorted(jsonl_dir.glob("p*.jsonl")):
        m = re.search(r"p(\d+)", f.name)
        if not m:
            continue
        p = int(m.group(1))
        pr = json.loads(f.read_text(encoding="utf-8").splitlines()[0])["result"]["layoutParsingResults"][0]["prunedResult"]
        im = Image.open(png_dir / f"p{p:04d}.png")
        sx, sy = im.width / pr["width"], im.height / pr["height"]
        blocks, k = [], 0
        for b in pr["parsing_res_list"]:
            lab = b["block_label"]
            x0, y0, x1, y1 = b["block_bbox"]
            if lab == "image":
                k += 1
                fn = f"source_figure_crops/fig_source_p{p:03d}_{k:02d}.png"
                im.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))).save(out / fn)
                figs.append({"source_pdf_page": p, "source_label": str(k), "crop": fn})
                continue
            txt = b["block_content"].strip()
            if lab in SKIP or not txt:
                continue
            d = {"role": MAP.get(lab, "body"), "text": txt, "y0": y0, "label": lab}
            if d["role"] == "heading":
                d["level"] = 2
            blocks.append(d)
        pages.append({"page": p, "chapter": chapter, "kind": "chapter", "blocks": blocks})
    (out / "aligned.json").write_text(json.dumps({"pages": pages}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "source_figure_audit.json").write_text(json.dumps({"figures": figs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"pages": pages, "figures": figs}


def refine(aligned: dict) -> dict:
    """去图版字母块；label=content 的整块按行拆成逐条块（原文与译文行数一致才拆）；
    半数以上行是检索表条目（编号 + 引导点 + 目标）的块记为 role=key，并统一译文引导点。"""
    for pg in aligned["pages"]:
        nb: list[dict] = []
        for b in pg["blocks"]:
            lab = b.get("label")
            if lab in ("figure_title", "doc_title") and is_panel_letters(b["text"]):
                continue
            if lab == "figure_title" and not FIGLABEL.match(b["text"]):
                if BINOMIAL.match(b["text"]):  # 学名行不是图注
                    nb.append({**b, "role": "body"})
                    continue
                if nb and nb[-1].get("role") == "caption":  # 图注续行并回上一块
                    nb[-1] = {**nb[-1], "text": nb[-1]["text"] + " " + b["text"],
                              "translation": (nb[-1].get("translation") or "") + (b.get("translation") or "")}
                    continue
            if lab in SKIPKEY - {"image"} and lab != "figure_title":
                nb.append(b)
                continue
            tl, zl = b["text"].split("\n"), (b.get("translation") or b["text"]).split("\n")
            is_key = sum(bool(KEYLINE.match(t)) for t in tl) * 2 >= len(tl)
            if lab != "content" and not is_key:
                nb.append(b)
                continue
            if len(tl) != len(zl):
                nb.append({**b, "role": "key"} if is_key and len(tl) == 1 else b)
                continue
            role = "key" if is_key else "index"
            for i, (t, z) in enumerate(zip(tl, zl)):
                if t.strip():
                    nb.append({**b, "role": role, "text": t, "translation": norm_key(t, z) if role == "key" else z, "y0": b["y0"] + i})
        pg["blocks"] = nb
    return aligned


ARABIC = re.compile("[" + chr(0x600) + "-" + chr(0x6FF) + "]+")
LATIN_TOKEN = re.compile("[A-Za-z" + chr(0xC0) + "-" + chr(0x17F) + chr(0x600) + "-" + chr(0x6FF) + "]{4,}")


def fix_arabic(aligned: dict) -> dict:
    """VL 把拉丁字母误识为阿拉伯字形（Protoارicia → Protoaricia）：用全书其他位置出现的同形词唯一匹配来还原；
    匹配不唯一就保留并计入 aligned["arabic_unresolved"]，不猜。"""
    vocab: set[str] = set()
    for pg in aligned["pages"]:
        for b in pg["blocks"]:
            for fld in ("text", "translation"):
                vocab.update(t for t in LATIN_TOKEN.findall(b.get(fld) or "") if not ARABIC.search(t))
    unresolved: list[str] = []

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        if not ARABIC.search(tok):
            return tok
        parts = ARABIC.split(tok)
        pat = re.compile("^" + ".{1,3}".join(re.escape(x) for x in parts) + "$")
        hits = {w for w in vocab if pat.match(w)}
        if len(hits) == 1:
            return hits.pop()
        unresolved.append(tok)
        return tok

    for pg in aligned["pages"]:
        for b in pg["blocks"]:
            for fld in ("text", "translation"):
                if b.get(fld):
                    b[fld] = LATIN_TOKEN.sub(repl, b[fld])
    aligned["arabic_unresolved"] = sorted(set(unresolved))
    return aligned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl_dir"), ap.add_argument("png_dir"), ap.add_argument("out")
    ap.add_argument("--chapter", default="Book")
    a = ap.parse_args(argv)
    r = convert(Path(a.jsonl_dir), Path(a.png_dir), Path(a.out), a.chapter)
    print(f"pages={len(r['pages'])} blocks={sum(len(p['blocks']) for p in r['pages'])} figures={len(r['figures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
