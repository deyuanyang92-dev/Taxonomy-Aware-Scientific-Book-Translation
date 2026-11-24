"""性状表 → 检索表。输入表格（CSV/TSV/XLSX/Markdown 表，或 PDF/图片页经 Datalab 识别），输出多路检索表、审计、编码草稿。

输入格式（见 docs/TABKEY.md）:
  第 1 列 = 分类单元名；第 1 行 = 性状名；其余格 = 状态。
  未知: 空 / ? / n.r. ；不适用: - / NA。 括号 = 非模式材料，与括号外取并集。
  数值列自动识别（含 "3-9"、"40 (40-100)"），按数据空隙自动分箱（--bins）。
  文字列：规范化后的文字即状态；多态用 " | " 或 " / " 分隔；可用 --codebook 合并状态。
  文字列中每个单元名各不相同（未编码的自由文本）默认排除并列出，不参与建表。
"""
from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .audit import audit_pairs
from .build import Node, build, leaves
from .matrix import INAPPLICABLE, UNKNOWN, Character, Matrix, Taxon

UNK_TOK = {"", "?", "n.r.", "n.r", "nr", "not recorded", "unknown"}
NA_TOK = {"-", "--", "na", "n.a.", "n/a", "not applicable"}
SMALL = 6  # 数值列端点取值数 <= SMALL 时不分箱
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").replace("–", "-").replace("—", "-")
    s = s.replace("†", "").replace("\xa0", " ").replace("*", "")
    return re.sub(r"\s+", " ", s).strip()


def kind(cell: str) -> str:
    c = clean(cell).lower()
    if c in UNK_TOK:
        return "unk"
    if c in NA_TOK:
        return "na"
    return "val"


# ---------- 读入 ----------
def md_tables(md: str) -> list[list[list[str]]]:
    tabs, cur = [], []
    for ln in md.splitlines():
        if ln.strip().startswith("|"):
            if re.match(r"^\|[\s:|-]+\|$", ln.strip()):
                continue
            cur.append([clean(c) for c in ln.strip().strip("|").split("|")])
        elif cur:
            tabs.append(cur)
            cur = []
    if cur:
        tabs.append(cur)
    return tabs


def short_name(n: str) -> str:
    return re.sub(r"\s*\(.*$", "", clean(n)).strip()


def merge_halves(tabs: list[list[list[str]]]) -> list[list[str]]:
    """同一张表被分页拆成左右两半（行数相同）时按行序拼接；否则只取最大的表。"""
    tabs = [t for t in tabs if len(t) > 2]
    if not tabs:
        raise ValueError("未识别到表格")
    big = max(len(t) for t in tabs)
    same = [t for t in tabs if len(t) == big]
    out = [list(r) for r in same[0]]
    for t in same[1:]:
        for i, r in enumerate(t):
            a, b = short_name(out[i][0]), short_name(r[0])
            if i > 0 and a.split()[:2][-1:] != b.split()[:2][-1:]:
                raise ValueError(f"左右半表第 {i} 行分类单元不一致: {a!r} / {b!r}")
            if len(b) > len(a):
                out[i][0] = r[0]
            out[i] += r[1:]
    for r in out:
        r[0] = short_name(r[0])
    return out


def load_table(path: Path) -> list[list[str]]:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        import openpyxl
        ws = openpyxl.load_workbook(path, data_only=True).active
        return [[clean(str(c)) if c is not None else "" for c in r] for r in ws.iter_rows(values_only=True)]
    txt = path.read_text("utf-8-sig")
    if suf in (".md", ".markdown"):
        return merge_halves(md_tables(txt))
    delim = "\t" if suf in (".tsv", ".txt") else ","
    return [[clean(c) for c in r] for r in csv.reader(io.StringIO(txt), delimiter=delim)]


def datalab_md(pdf: Path, pages: list[int]) -> str:
    """PDF 指定页（或单张图片）经 Datalab accurate 转 markdown。密钥 ~/.datalab_key。"""
    import fitz
    import requests
    if pdf.suffix.lower() == ".pdf":
        src, sub = fitz.open(pdf), fitz.open()
        for p in pages:
            sub.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        blob, name, mime = sub.tobytes(), "t.pdf", "application/pdf"
    else:
        blob, name, mime = pdf.read_bytes(), pdf.name, "image/png" if pdf.suffix.lower() == ".png" else "image/jpeg"
    h = {"X-API-Key": (Path.home() / ".datalab_key").read_text().strip()}
    j = requests.post("https://www.datalab.to/api/v1/convert", headers=h, files={"file": (name, blob, mime)},
                      data={"mode": "accurate", "output_format": "markdown", "disable_image_extraction": "true"}, timeout=120)
    j.raise_for_status()
    chk, t0 = j.json()["request_check_url"], time.time()
    while time.time() - t0 < 600:
        time.sleep(4)
        r = requests.get(chk, headers=h, timeout=60).json()
        if r.get("status") == "complete":
            return str(r["markdown"])
        if r.get("status") == "failed":
            raise RuntimeError(f"Datalab 失败: {str(r)[:200]}")
    raise TimeoutError("Datalab 超时")


# ---------- 编码 ----------
def nums_of(cell: str) -> tuple[float, float] | None:
    n = [float(x) for x in NUM_RE.findall(clean(cell))]
    return (min(n), max(n)) if n else None


def is_numeric_col(cells: list[str]) -> bool:
    known = [clean(c) for c in cells if kind(c) == "val"]
    if len(known) < 3:
        return False
    ok = sum(1 for c in known if NUM_RE.search(c) and not re.sub(r"[\d.\-;,()\s]", "", c))
    return ok / len(known) >= 0.7


def choose_cuts(ivs: list[tuple[float, float]], nbins: int) -> list[float]:
    """在数据空隙处切：切点 v 使跨越它（lo < v <= hi）的区间尽量少，且两侧尽量均衡。"""
    cands = sorted({lo for lo, _ in ivs} | {hi for _, hi in ivs})
    cuts: list[float] = []
    for _ in range(nbins - 1):
        best = None
        for v in cands:
            if v in cuts or v <= min(c for c, _ in ivs):
                continue
            seg = sorted(cuts + [v])
            lo_b = max([c for c in seg if c < v], default=-1e18)
            hi_b = min([c for c in seg if c > v], default=1e18)
            mids = [(a + b) / 2 for a, b in ivs if lo_b <= (a + b) / 2 < hi_b]
            if not mids:
                continue
            strad = sum(1 for a, b in ivs if a < v <= b)
            imb = abs(sum(1 for m in mids if m < v) - sum(1 for m in mids if m >= v))
            sc = (3 * strad / len(ivs) + imb / len(mids), 0)
            if best is None or sc < best[0]:
                best = (sc, v)
        if best is None:
            break
        cuts.append(best[1])
    return sorted(cuts)


def fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def bin_labels(cuts: list[float]) -> list[str]:
    if not cuts:
        return ["all"]
    labs = [f"<{fmt(cuts[0])}"]
    for a, b in zip(cuts, cuts[1:]):
        labs.append(f"{fmt(a)} to <{fmt(b)}")
    labs.append(f">={fmt(cuts[-1])}")
    return labs


def disc_states(cell: str) -> list[str] | str:
    c = clean(cell)
    k = kind(c)
    if k != "val":
        return UNKNOWN if k == "unk" else INAPPLICABLE
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", c)
    outside, inside = (m.group(1), m.group(2)) if m else (c, "")
    parts: list[str] = []
    if kind(outside) == "val":
        parts += [p.strip().lower() for p in re.split(r"\s+[|/]\s+", outside)]
    if inside and kind(inside) == "val":
        parts += [p.strip().lower() for p in re.split(r"\s+[|/]\s+", inside)]
    return parts or UNKNOWN


@dataclass
class Result:
    matrix: Matrix
    excluded: list[tuple[str, str]] = field(default_factory=list)
    codebook: list[tuple[str, str]] = field(default_factory=list)
    bins: dict[str, list[str]] = field(default_factory=dict)


def _map_states(cname: str, p: list[str], codebook: dict[tuple[str, str], str]) -> list[str] | str:
    """codebook: 原文 -> 状态；'a|b' = 多态；'~' = 丢弃（该格对本性状无信息）。全丢则未知。"""
    out: list[str] = []
    for s in p:
        for x in codebook.get((cname, s), s).split("|"):
            if x.strip() and x.strip() != "~":
                out.append(x.strip())
    return sorted(set(out)) or UNKNOWN


def load_codebook(path: Path | None) -> dict[tuple[str, str], str]:
    if not path:
        return {}
    return {(r["character"], r["raw"]): r["state"] for r in csv.DictReader(path.open(encoding="utf-8-sig")) if r.get("state")}


def avoid_chars(path: Path | None) -> set[str]:
    """codebook 的 key_policy 列为 avoid 的性状（用户规则：不作检索表判断依据，如尾部、环纹、中腹沟）。"""
    if not path:
        return set()
    return {r["character"] for r in csv.DictReader(path.open(encoding="utf-8-sig"))
            if (r.get("key_policy") or "").strip().lower().startswith("avoid")}


def drop_columns(rows: list[list[str]], names: set[str]) -> list[list[str]]:
    keep = [0] + [j for j in range(1, len(rows[0])) if clean(rows[0][j]) not in names]
    return [[r[j] if j < len(r) else "" for j in keep] for r in rows]


def encode(rows: list[list[str]], nbins: int = 3, codebook: dict[tuple[str, str], str] | None = None,
           include_free: bool = False, rel: dict[str, float] | None = None) -> Result:
    codebook, rel = codebook or {}, rel or {}
    hdr, body = rows[0], [r + [""] * (len(rows[0]) - len(r)) for r in rows[1:] if r and clean(r[0])]
    names = [clean(r[0]) for r in body]
    if len(set(names)) != len(names):
        raise ValueError("分类单元名重复: " + ", ".join(n for n in names if names.count(n) > 1))
    res = Result(Matrix([], []))
    chars: list[Character] = []
    cols: list[dict[int, frozenset[int] | str]] = [dict() for _ in names]
    for j in range(1, len(hdr)):
        cname = clean(hdr[j]) or f"col{j}"
        cells = [r[j] for r in body]
        if is_numeric_col(cells):
            ivs = [iv for c in cells if kind(c) == "val" and (iv := nums_of(c))]
            pts = sorted({x for iv in ivs for x in iv})
            if len(pts) <= SMALL:
                cuts, labs = [], [fmt(x) for x in pts]  # 取值很少：每个值各为一个状态，不分箱
            else:
                cuts = choose_cuts(ivs, nbins)
                labs = bin_labels(cuts)
            ci = len(chars)
            chars.append(Character(cname, labs, rel.get(cname, 5.0)))
            res.bins[cname] = labs
            for t, c in enumerate(cells):
                k, iv = kind(c), nums_of(c)
                if k == "unk" or (k == "val" and not iv):
                    cols[t][ci] = UNKNOWN
                elif k == "na":
                    cols[t][ci] = INAPPLICABLE
                elif iv and not cuts:
                    cols[t][ci] = frozenset(i for i, x in enumerate(pts) if iv[0] <= x <= iv[1])
                elif iv:
                    edges = [-1e18] + cuts + [1e18]
                    cols[t][ci] = frozenset(i for i in range(len(labs)) if iv[0] < edges[i + 1] and iv[1] >= edges[i])
            continue
        per = [disc_states(c) for c in cells]
        per = [_map_states(cname, p, codebook) if isinstance(p, list) else p for p in per]
        states = sorted({s for p in per if isinstance(p, list) for s in p})
        res.codebook += [(cname, s) for s in states]
        known = [p for p in per if isinstance(p, list)]
        if len(states) < 2:
            res.excluded.append((cname, "只有 <2 个状态，无区分力"))
            continue
        cnt = {s: sum(1 for p in known if s in p) for s in states}
        single = sum(1 for v in cnt.values() if v == 1)
        if not include_free and len(known) > 2 and single * 2 > len(states) and single >= 2:
            res.excluded.append((cname, f"未编码文字：{len(states)} 个状态中 {single} 个只出现一次。填 codebook 合并状态后重跑，或 --include-free"))
            continue
        ci = len(chars)
        chars.append(Character(cname, states, rel.get(cname, 5.0)))
        for t, p in enumerate(per):
            cols[t][ci] = frozenset(states.index(s) for s in p) if isinstance(p, list) else p
    res.matrix = Matrix(chars, [Taxon(n, v) for n, v in zip(names, cols)])
    return res


# ---------- 输出 ----------
def render_key(m: Matrix, root: Node) -> str:
    order: dict[int, int] = {}
    q = [root]
    nodes: list[Node] = []
    while q:
        nd = q.pop(0)
        if nd.char is None or len(nd.taxa) < 2:
            continue
        order[id(nd)] = len(order) + 1
        nodes.append(nd)
        q += [nd.children[s] for s in sorted(nd.children)]
    lines: list[str] = []
    for nd in nodes:
        assert nd.char is not None
        ch = m.characters[nd.char]
        lines.append(f"{order[id(nd)]}. {ch.name}")
        for s in sorted(nd.children):
            c = nd.children[s]
            if id(c) in order:
                tgt = str(order[id(c)])
            elif len(c.taxa) == 1:
                tgt = m.taxa[c.taxa[0]].name
            else:
                tgt = " | ".join(m.taxa[t].name for t in c.taxa) + " (矩阵无法区分)"
            lines.append(f"   {ch.states[s]} .... {tgt}")
    return "\n".join(lines)


def run(rows: list[list[str]], unknown_all: bool = False, **kw: object) -> tuple[str, dict[str, object], Result]:
    res = encode(rows, **kw)  # type: ignore[arg-type]
    m = res.matrix
    tree = build(m, unknown_all=unknown_all)
    lv = leaves(tree)
    steps: dict[int, list[int]] = {}
    for tx, path in lv:
        for t in tx:
            steps.setdefault(t, []).append(len(path))
    unresolved = [[m.taxa[t].name for t in tx] for tx, _ in lv if len(tx) > 1]
    aud = audit_pairs(m)
    tiers = {k: sum(1 for a in aud if a.tier == k) for k in ("separated", "evidence_gap", "matrix_silent")}
    weak = [f"{m.taxa[a.a].name} / {m.taxa[a.b].name}: 仅 {m.characters[a.separating[0]].name}" for a in aud if a.weak]
    gaps = [f"{m.taxa[a.a].name} / {m.taxa[a.b].name}" for a in aud if a.tier != "separated"]
    rep: dict[str, object] = {
        "taxa": len(m.taxa), "characters_used": [c.name for c in m.characters],
        "excluded": res.excluded, "numeric_bins": res.bins, "unresolved_groups": unresolved,
        "mean_steps": round(sum(min(v) for v in steps.values()) / max(1, len(steps)), 2),
        "pairs": tiers, "weak_pairs": weak, "unseparated_pairs": gaps,
    }
    rep["_tree"] = tree  # 供 to_ir 使用；写 JSON 前剔除
    return render_key(m, tree), rep, res


# ---------- 发表用 IR ----------
def _abbr(name: str) -> str:
    """属名缩写：Amphictene capensis -> A. capensis。"""
    w = name.split(" ", 1)
    return f"{w[0][0]}. {w[1]}" if len(w) == 2 and w[0][:1].isalpha() else name


_QUAL = {"sp", "sp.", "spp.", "cf.", "aff.", "nr.", "n.", "nov."}


def taxon_md(name: str, abbr: bool = False) -> str:
    """去向学名的 markdown：只斜体属名+种加词，命名人、年份、sp./cf. 等限定词正体。"""
    w = name.split()
    if not w:
        return name
    ital: list[str] = []
    rest: list[str] = []
    for i, t in enumerate(w):
        if rest or (i > 0 and (t[:1].isupper() or t[:1] in "(0123456789" or "_" in t)):
            rest.append(t)
        else:
            ital.append(t)
    if abbr and len(ital) >= 2 and ital[0][:1].isalpha():
        ital[0] = ital[0][0] + "."
    if abbr:
        # 多类群并列终点：去掉命名人年份，只留缩写学名（防止去向栏折行，L3）；sp 后的标本号（如 NHM_1244）保留
        rest = [t for t in rest if re.fullmatch(r"[A-Za-z]*_[\w.-]+", t)]
    # 源数据笔误：种加词后多一个点（Avery 2023 DELTA 'Travisia cf. kerguelensis. Ehlers'）
    ital = [t if t.lower() in _QUAL or (j == 0 and len(t) == 2) else t.rstrip(".") for j, t in enumerate(ital)]
    segs: list[str] = []
    run: list[str] = []
    for t in ital:
        if t.lower() in _QUAL:
            if run:
                segs.append("*" + " ".join(run) + "*")
                run = []
            segs.append(t)
        else:
            run.append(t)
    if run:
        segs.append("*" + " ".join(run) + "*")
    return " ".join(segs + rest)


def _char_name(name: str) -> str:
    """DELTA 性状名里的 <注释> 改成圆括号，发表版不出现尖括号。"""
    return re.sub(r"\s*<([^>]*)>", r" (\1)", name).replace("_", " ").strip()


def _lead_text(m: Matrix, ch: int, labels: list[str], bins: dict[str, list[str]]) -> str:
    name = _char_name(m.characters[ch].name)
    lab = " or ".join(labels)
    return f"{name.capitalize()} {lab}" if m.characters[ch].name in bins else f"{name.capitalize()}: {lab}"


def to_ir(m: Matrix, root: Node, bins: dict[str, list[str]], heading: str = "", lang: str = "en") -> object:
    """多路树 -> 二歧偶句 KeyIR：多于两组时拆成链（第二支 = 其余状态）；同去向的状态合并成一支。"""
    from .ir import Couplet, KeyIR, Lead
    cps: list[Couplet] = []

    def tgt(c: Node) -> Lead:
        if c.char is not None and len(c.taxa) > 1:
            return Lead("", "jump", str(emit(c)))
        multi = len(c.taxa) > 1
        # 多类群叶：属名缩写、逗号分隔，防止去向过长被截断（说明见标题）
        names = [taxon_md(m.taxa[t].name, abbr=multi) for t in c.taxa]
        sep = "; " if any("," in n for n in names) else ", "  # 带命名人年份时用分号，免得逗号歧义
        return Lead("", "taxon", sep.join(names))

    def groups(nd: Node) -> list[tuple[list[str], Node]]:
        assert nd.char is not None
        out: dict[object, tuple[list[str], Node]] = {}
        for s in sorted(nd.children):
            c = nd.children[s]
            k: object = id(c) if c.char is not None and len(c.taxa) > 1 else tuple(c.taxa)
            out.setdefault(k, ([], c))[0].append(m.characters[nd.char].states[s])
        return list(out.values())

    def chain(nd: Node, gs: list[tuple[list[str], Node]], back: int | None) -> int:
        assert nd.char is not None
        cp = Couplet(len(cps) + 1, back)
        cps.append(cp)
        a = tgt(gs[0][1])
        a.text = _lead_text(m, nd.char, gs[0][0], bins)
        if len(gs) == 2:
            b = tgt(gs[1][1])
            b.text = _lead_text(m, nd.char, gs[1][0], bins)
        else:
            b = Lead(_lead_text(m, nd.char, [x for g in gs[1:] for x in g[0]], bins), "jump", str(chain(nd, gs[1:], cp.num)))
        cp.leads = [a, b]
        return cp.num

    def emit(nd: Node) -> int:
        n = chain(nd, groups(nd), None)
        return n

    emit(root)
    # backref：被哪个偶句指向
    for cp in cps:
        for ld in cp.leads:
            if ld.kind == "jump":
                nxt = next(c for c in cps if c.num == int(ld.target))
                if nxt.backref is None:
                    nxt.backref = cp.num
    return KeyIR(heading, cps, lang, "dash")


# ---------- 发表交付：检索表一律出 DOCX + PDF ----------
def publish(m: Matrix, root: Node, prefix: Path | str, title: str, bins: dict[str, list[str]] | None = None,
            lang: str = "en", source_style: str = "dash") -> int:
    """写 <prefix>.key.txt（内部核对用）、<prefix>.ir.json，再走 keykit make 出 <prefix>.docx/.pdf/.report.json。

    返回 make 的退出码（1 = 有 critical/major，报告在 .report.json）。
    """
    from .__main__ import main
    from .ir import dump_irs
    p = Path(prefix)
    p.parent.mkdir(parents=True, exist_ok=True)
    Path(str(p) + ".key.txt").write_text(render_key(m, root) + "\n", "utf-8")
    ir = to_ir(m, root, bins or {}, title, lang)
    irp = Path(str(p) + ".ir.json")
    dump_irs([ir], irp)  # type: ignore[list-item]
    return main(["make", str(irp), "-o", str(p) + ".docx", "--lang", lang, "--source-style", source_style])
