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
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
LEADMARK = re.compile(r"^\s*(?:\d+['’]?\.|[•·▪●–—-])\s")  # 检索表条目号/续支记号
KEYHEAD = re.compile(r"^\s*(?:Clave|Key|Chave|Clé|Schlüssel)\b.{0,80}$", re.I)  # 「Clave de géneros」：表题，不是条目
OPEN_LEADER = re.compile(r"(?:\.{2,}|…)\s*\.?\s*$")  # 条目以引导点结尾，目标被 VL 拆到下一块


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


def load_pruned(f: Path) -> dict:
    """一页版面：云 API 原始 `pNNNN.jsonl`，或 docstore save_layout 落盘的 `pNNNN.json`（含 pruned_result）。"""
    txt = f.read_text(encoding="utf-8")
    if f.suffix == ".json":
        j = json.loads(txt)
        return (j.get("layout") or j)["pruned_result"] if "pruned_result" not in j else j["pruned_result"]
    return json.loads(txt.splitlines()[0])["result"]["layoutParsingResults"][0]["prunedResult"]


def layout_files(d: Path, pages: set[int] | None = None) -> dict[int, Path]:
    """版面目录 -> {页号: 文件}；同页两种格式都有时取 .jsonl（原始任务输出）。"""
    out: dict[int, Path] = {}
    for f in sorted(d.glob("p*.json*")):
        m = re.fullmatch(r"p(\d+)\.jsonl?", f.name)
        if m and (pages is None or int(m.group(1)) in pages):
            p = int(m.group(1))
            if p not in out or f.suffix == ".jsonl":
                out[p] = f
    return dict(sorted(out.items()))


def page_image(src: Path, p: int, dpi: int = 200):
    """页图：目录下的 pNNNN.png，或直接从原件 PDF 按 CropBox 渲染（双页 MediaBox 的扫描本只取版面页）。"""
    from PIL import Image
    if src.suffix.lower() != ".pdf":
        return Image.open(src / f"p{p:04d}.png")
    import fitz
    with fitz.open(src) as doc:
        pix = doc[p - 1].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def parse_pages(spec: str | None) -> set[int] | None:
    """'1-50,52' -> {1..50, 52}；None 表示全部。"""
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


TEXT_LABELS = {"text", "abstract", "paragraph_title", "doc_title", "figure_title", "reference_content", "content",
               "vision_footnote", "footnote", "display_formula"}
BODY_MIN_CHARS = 120  # 字号参照：正文块至少这么多字
SIZE_TOL = 1.12  # 标题字号最大/最小比低于此值视为同一层
# 标题文字规则（设计 B.1 level_source=taxon）：章/部/附录/术语表等一级；全大写行也是一级
_H1_WORDS = re.compile(r"^(?:CHAPTER|PART|APPENDIX|CAP[IÍ]TULO|ANEXO|GLOSSARY|INDEX|REFERENCES|CONTENTS|PREFACE|"
                       r"ACKNOWLEDGEMENTS?|INTRODUCTION|BIBLIOGRAPHY|ILLUSTRATION CREDITS)\b", re.I)
_NUMBERED = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+\S")


def number_depth(text: str) -> int | None:
    """编号深度：'3 Anatomy' 1，'3.2 Gut' 2，'3.2.1 Foregut' 3；无编号 None。"""
    m = _NUMBERED.match(text.split("\n")[0])
    return min(4, m.group(1).count(".") + 1) if m else None


def _mostly_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) >= 0.9


def heading_rule_level(text: str, label: str | None = None) -> tuple[int, str] | None:
    """编号深度 > 标题文字规则（章/科目阶元/全大写）> 引擎 doc_title；都不适用则 None（交给字号聚类）。"""
    t = " ".join(text.split())
    d = number_depth(text)
    if d:
        return d, "number"
    first = text.strip().split("\n")[0].strip()
    if _H1_WORDS.match(first) or _mostly_caps(first):
        return 1, "taxon"
    try:
        # 不直接用 taxon_level：它把任何「大写词 + 小写词」当双名法，英文标题 "General features" 会被判成种名 3 级
        from booklayout.headings import _KEY, _RANK1, _RANK2, _SPECIES_HEAD
    except ImportError:  # 脱离仓库用时只剩上面的规则
        _RANK1 = _RANK2 = _KEY = _SPECIES_HEAD = None
    if _RANK1 is not None:
        if _RANK1.match(t):
            return 1, "taxon"
        if _RANK2.match(t):
            return 2, "taxon"
        if _SPECIES_HEAD.match(t.replace("*", "")) or _KEY.match(t):
            return 3, "taxon"
    if label == "doc_title":
        return 1, "engine"
    return None


def kmeans_tiers(vals: list[float], k: int = 3, iters: int = 50) -> list[float]:
    """一维 k 均值，返回从大到小排序的簇中心；值太少或几乎等大时簇数自动减少。"""
    xs = sorted(vals)
    if not xs:
        return []
    k = max(1, min(k, len(set(round(v, 2) for v in xs))))
    if k > 1 and xs[-1] / xs[0] < SIZE_TOL:
        k = 1
    cs = [xs[int((len(xs) - 1) * (i + 0.5) / k)] for i in range(k)]
    for _ in range(iters):
        groups: list[list[float]] = [[] for _ in cs]
        for v in xs:
            groups[min(range(len(cs)), key=lambda i: abs(cs[i] - v))].append(v)
        new = [statistics.fmean(g) if g else c for g, c in zip(groups, cs)]
        if new == cs:
            break
        cs = new
    cs = sorted(set(round(c, 6) for c in cs), reverse=True)
    # 相邻簇中心比低于 SIZE_TOL 视为同层，合并
    merged = [cs[0]]
    for c in cs[1:]:
        if merged[-1] / c >= SIZE_TOL:
            merged.append(c)
    return merged


def _size_ratio(bbox: list[float], text: str, body_unit: float) -> float | None:
    """字号代理：sqrt(框面积/字数) 相对本页正文同一量；两者受同一缩放影响，所以是比值。"""
    n = len(text.replace("\n", ""))
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if n < 2 or w <= 0 or h <= 0 or body_unit <= 0:
        return None
    return ((w * h / n) ** 0.5) / body_unit


def assign_heading_levels(pages: list[dict], base: int = 2, max_level: int = 4) -> dict:
    """标题层级 = 编号深度 + 文字规则 + 字高聚类（组合，设计 B.1 优先级 number > taxon > font > engine）。
    规则命中的标题直接定级；其余标题按全书字号比（相对本页正文）一维聚类，大的层级小，从 base 起。
    写 block["level"]、block["level_source"]；返回统计。"""
    sizes: list[tuple[dict, float]] = []
    stat = {"number": 0, "taxon": 0, "engine": 0, "font": 0, "unsized": 0}
    for pg in pages:
        body = [(b["src"]["bbox"], b["text"]) for b in pg["blocks"] if b.get("label") in ("text", "abstract") and len(b["text"]) >= BODY_MIN_CHARS]
        units = [((bb[2] - bb[0]) * (bb[3] - bb[1]) / len(t)) ** 0.5 for bb, t in body]
        unit = statistics.median(units) if units else 0.0
        pg["_body_unit"] = unit
    doc_units = [pg["_body_unit"] for pg in pages if pg["_body_unit"] > 0]
    doc_unit = statistics.median(doc_units) if doc_units else 0.0
    for pg in pages:
        for b in pg["blocks"]:
            if b.get("role") != "heading":
                continue
            r = heading_rule_level(b["text"], b.get("label"))
            if r and r[1] in ("number", "taxon"):
                b["level"], b["level_source"] = r
                stat[r[1]] += 1
                continue
            ratio = _size_ratio(b["src"]["bbox"], b["text"], pg["_body_unit"] or doc_unit)
            if ratio is None:
                b["level"], b["level_source"] = (r if r else (base, "engine"))
                stat["engine" if not r else r[1]] += 1
                stat["unsized"] += 1
                continue
            b["src"]["size_ratio"] = round(ratio, 3)
            sizes.append((b, ratio))
    tiers = kmeans_tiers([r for _, r in sizes])
    for b, ratio in sizes:
        i = min(range(len(tiers)), key=lambda t: abs(tiers[t] - ratio))
        b["level"], b["level_source"] = min(max_level, base + i), "font"
        stat["font"] += 1
    for pg in pages:
        pg.pop("_body_unit", None)
    stat["tiers"] = [round(t, 3) for t in tiers]
    return stat


def tesseract_text(im, box: tuple[int, int, int, int], lang: str = "eng", psm: int = 6) -> str:
    """云端返回空文本块时，对该框裁图用本机 Tesseract 补字；没有 tesseract 返回空串。"""
    exe = shutil.which("tesseract")
    if not exe:
        return ""
    crop = im.crop(box)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "c.png"
        crop.save(p)
        r = subprocess.run([exe, str(p), "stdout", "-l", lang, "--psm", str(psm)], capture_output=True, timeout=120)
    return re.sub(r"\s*\n\s*", " ", r.stdout.decode("utf-8", "replace")).strip() if r.returncode == 0 else ""


def convert(jsonl_dir: Path, png_dir: Path, out: Path, chapter: str = "Book", pages_sel: set[int] | None = None,
            engine: str = "paddleocr-vl", heading_levels: str = "flat", tess_fallback: bool = True,
            tess_lang: str = "eng", label_map: dict[str, str] | None = None,
            image_labels: tuple[str, ...] = ("image",)) -> dict:
    """png_dir 可以是页图目录，也可以是原件 PDF（见 page_image）。
    输出 aligned/2：块带 src{origin=ocr, engine, page, bbox(版面坐标 px), label}；
    heading_levels="auto" 时标题层级由 assign_heading_levels 组合推断（默认 flat：全部 2 级，同旧行为）；
    文本块云端返回空文本时，用本机 Tesseract 裁图补字（src.empty=true, src.fallback=tesseract），补不出则不入块、记入页的 empty_blocks。"""
    (out / "source_figure_crops").mkdir(parents=True, exist_ok=True)
    pages, figs = [], []
    for p, f in layout_files(jsonl_dir, pages_sel).items():
        pr = load_pruned(f)
        im = page_image(png_dir, p)
        sx, sy = im.width / pr["width"], im.height / pr["height"]
        blocks, k, empties = [], 0, []
        for b in pr["parsing_res_list"]:
            lab = b["block_label"]
            x0, y0, x1, y1 = (json.loads(b["block_bbox"]) if isinstance(b["block_bbox"], str) else b["block_bbox"])
            if lab in image_labels:
                k += 1
                fn = f"source_figure_crops/fig_source_p{p:03d}_{k:02d}.png"
                im.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))).save(out / fn)
                figs.append({"source_pdf_page": p, "source_label": str(k), "crop": fn})
                continue
            txt = (b.get("block_content") or "").strip()
            if lab in SKIP and lab not in image_labels:
                continue
            src = {"origin": "ocr", "engine": engine, "page": p, "bbox": [x0, y0, x1, y1], "label": lab}
            if not txt:
                if lab not in TEXT_LABELS:
                    continue
                src["empty"] = True
                if tess_fallback:
                    txt = tesseract_text(im, (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)), tess_lang)
                if not txt:
                    empties.append({"label": lab, "bbox": [x0, y0, x1, y1]})
                    continue
                src["fallback"] = "tesseract"
            d = {"role": (label_map or MAP).get(lab, "body"), "text": txt, "y0": y0, "label": lab, "src": src}
            if d["role"] == "heading":
                d["level"] = 2
                d["level_source"] = "engine"
            blocks.append(d)
        pg = {"page": p, "chapter": chapter, "kind": "chapter", "size_px": [pr["width"], pr["height"]], "blocks": blocks}
        if empties:
            pg["empty_blocks"] = empties
        pages.append(pg)
    stat = assign_heading_levels(pages) if heading_levels == "auto" else None
    assign_block_ids({"pages": pages})
    doc = {"schema": "aligned/2", "source": {"kind": "scan", "engine": engine}, "pages": pages}
    if stat:
        doc["heading_levels"] = stat
    (out / "aligned.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "source_figure_audit.json").write_text(json.dumps({"figures": figs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"pages": pages, "figures": figs, "heading_levels": stat}


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
            if lab == "content" and not any(LEADMARK.match(t) for t in tl):
                is_key = False  # 目录行「Género X ..... 49」也有引导点+页码，但没有条目号
            if lab != "content" and not is_key:
                nb.append(b)
                continue
            if len(tl) != len(zl):
                nb.append({**b, "role": "key"} if is_key and len(tl) == 1 else b)
                continue
            role = "key" if is_key else "index"
            for i, (t, z) in enumerate(zip(tl, zl)):
                if t.strip() and role == "key" and KEYHEAD.match(t) and not LEADER.search(t):
                    nb.append({**b, "role": "heading", "level": 2, "text": t, "translation": z, "y0": b["y0"] + i})
                elif t.strip():
                    nb.append({**b, "role": role, "text": t, "translation": norm_key(t, z) if role == "key" else z, "y0": b["y0"] + i})
        pg["blocks"] = merge_caption_columns(fold_key_targets(nb))
    return aligned


CAPLABEL = re.compile(r"^\s*(?:Fig(?:s|ura|uras)?|Tabla|L[áa]m(?:ina)?)\.?\s*\d+", re.I)
CAP_ROW_PX = 12  # 同一图注排成几栏时，各栏首行 y0 相差不超过此值（450 dpi 页上约 0.7 mm）


def merge_caption_columns(blocks: list[dict]) -> list[dict]:
    """多栏图注并成一块 caption；图内文字去掉。
    VL 把「Fig. 1. 标题 | 说明 | 说明」三栏图注切成并排的几块（有的标 caption，有的标 body），
    qa 报 bad_captions，排版里图注成了正文（Fauna 25 卷 p11、p21、p23、p29、p43、p44）。
    规则：以「Fig./Tabla N」开头的块带头；其后 y0 差 <= CAP_ROW_PX 的块（至多 3 栏）并入，按版面顺序拼接。
    同页后面有「Fig. N」图注时，前面不带图号的短 caption 块是图内标注（已在图像里），丢弃。"""
    out: list[dict] = []
    i = 0
    has_label_later = [any(CAPLABEL.match(x.get("text") or "") for x in blocks[k + 1:]) for k in range(len(blocks))]
    while i < len(blocks):
        b = blocks[i]
        text = b.get("text") or ""
        if b.get("role") == "caption" and not CAPLABEL.match(text) and has_label_later[i] and len(text) < 150:
            i += 1
            continue
        if CAPLABEL.match(text) and b.get("role") in ("caption", "body"):
            cols = [b]
            j = i + 1
            while j < len(blocks) and len(cols) < 3 and blocks[j].get("role") in ("caption", "body") \
                    and abs(blocks[j].get("y0", 0) - b.get("y0", 0)) <= CAP_ROW_PX \
                    and not CAPLABEL.match(blocks[j].get("text") or "") \
                    and not BINOMIAL.match(blocks[j].get("text") or ""):
                cols.append(blocks[j])
                j += 1
            join = lambda key: " ".join(re.sub(r"\s+", " ", c.get(key) or "").strip() for c in cols).strip()
            out.append({**b, "role": "caption", "text": join("text"), "translation": join("translation")})
            i = j
            continue
        out.append(b)
        i += 1
    return out


def fold_key_targets(blocks: list[dict]) -> list[dict]:
    """检索表条目以引导点收尾、目标（「Autolytinae (p. 447)」）被 VL 拆成下一个短正文块：并回条目。"""
    out: list[dict] = []
    for b in blocks:
        t = b["text"].strip()
        prev = out[-1] if out else None
        if (prev is not None and prev.get("role") == "key" and b.get("role") == "body" and "\n" not in t
                and len(t) <= 60 and not LEADMARK.match(t) and OPEN_LEADER.search(prev["text"])):
            tr = (b.get("translation") or t).strip()
            out[-1] = {**prev, "text": OPEN_LEADER.sub("", prev["text"]).rstrip() + " ..... " + t,
                       "translation": OPEN_LEADER.sub("", prev.get("translation") or prev["text"]).rstrip() + " ..... " + tr}
            continue
        out.append(b)
    return out


# VL 把上标写成 LaTeX：「M $ ^{a} $ Ángeles」（Fauna 21 卷 p4、p45）。西文序数上标
# a/o 还原为 ª/º 并贴住前字；其他上标改为 <sup>…</sup>，由 booklayout 排成上标。
LATEX_SUP = re.compile(r"\s*\$\s*\^\{\s*([^{}$]{1,8}?)\s*\}\s*\$|\\textsuperscript\{\s*([^{}$]{1,8}?)\s*\}")
ORDINAL = {"a": chr(0xAA), "o": chr(0xBA)}


def fix_latex_superscripts(text: str) -> str:
    def repl(m: re.Match) -> str:
        sup = m.group(1) or m.group(2)
        return ORDINAL.get(sup) or f"<sup>{sup}</sup>"

    return LATEX_SUP.sub(repl, text)


def source_only(aligned: dict) -> dict:
    """原文排版：每块 translation = text，再 refine，最后编块号。"""
    for pg in aligned["pages"]:
        for b in pg["blocks"]:
            b["text"] = fix_latex_superscripts(b.get("text") or "")
    for pg in aligned["pages"]:
        for b in pg["blocks"]:
            b["translation"] = b["text"]
    return assign_block_ids(refine(aligned))


def assign_block_ids(aligned: dict) -> dict:
    """块号 pNNN_bKK（booklayout normalize / patch-blocks 按块号改）。"""
    for pg in aligned["pages"]:
        for i, b in enumerate(pg["blocks"]):
            b["block_id"] = f"p{pg['page']:03d}_b{i:02d}"
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
    ap.add_argument("--pages", default=None, help="只转这些页，如 1-50")
    ap.add_argument("--engine", default="paddleocr-vl", help="写入 src.engine")
    ap.add_argument("--heading-levels", choices=["flat", "auto"], default="flat",
                    help="auto=编号深度+文字规则+字高聚类推层级（level_source 记来源）；flat=全部 2 级（旧行为）")
    ap.add_argument("--no-tess-fallback", action="store_true", help="云端空文本块不用 Tesseract 补字")
    ap.add_argument("--source-only", action="store_true",
                    help="原文排版（不翻译）：译文字段填原文，并跑 refine（去图版字母、拆目录/检索表行）")
    ap.add_argument("--no-spellfix", action="store_true", help="跳过 VL 拼写纠错（默认开启，见 scripts/vl_spellfix.py）")
    ap.add_argument("--tess-dir", default=None, help="Tesseract 第二读数目录（tNNNN_{L,R}.txt）；给了才启用 Tesseract 证据")
    ap.add_argument("--spellfix-llm", action="store_true", help="疑点交 DeepSeek flash 裁（须折扣时段，走 llm_engines 预算闸）")
    a = ap.parse_args(argv)
    r = convert(Path(a.jsonl_dir), Path(a.png_dir), Path(a.out), a.chapter, parse_pages(a.pages), engine=a.engine,
                heading_levels=a.heading_levels, tess_fallback=not a.no_tess_fallback)
    if a.source_only:
        al = source_only(json.loads((Path(a.out) / "aligned.json").read_text(encoding="utf-8")))
        (Path(a.out) / "aligned.json").write_text(json.dumps(al, ensure_ascii=False, indent=1), encoding="utf-8")
        r["pages"] = al["pages"]
    if not a.no_spellfix:
        import vl_spellfix
        args = [str(Path(a.out) / "aligned.json"), "--inplace", "--out", str(Path(a.out) / "spellfix")]
        if a.tess_dir:
            # vl_spellfix 按 <tess-root>/<aligned 上级目录名>/ 找读数；这里直接指定单目录
            args += ["--tess-root", str(Path(a.tess_dir).parent), "--tess-name", Path(a.tess_dir).name]
        if a.spellfix_llm:
            args.append("--llm")
        vl_spellfix.main(args)
    print(f"pages={len(r['pages'])} blocks={sum(len(p['blocks']) for p in r['pages'])} figures={len(r['figures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
