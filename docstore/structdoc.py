"""StructDoc：识别后的统一结构化 JSON 层（派生视图，可由主库重建）。

设计见 docs/superpowers/specs/2026-11-22-structdoc-design.md。零模型，确定性。
本模块只依赖 docstore 内部，不 import booklayout。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "structdoc/1"

# aligned.json 的 role 词表（booklayout/profile.py ROLES）的超集；tests 校验包含关系。
ROLE_TYPES = frozenset({
    "heading", "body", "caption", "key", "ref", "entry", "citation", "index", "note", "couplet", "legend",
    "table", "list", "quote", "box", "footnote", "figure_group",
})
EXTRA_TYPES = frozenset({"key_couplet", "key_heading", "treatment", "figure", "toc_entry", "toc_author"})
TREATMENT_REQUIRED = ("latin", "ja", "ref", "description", "distribution", "caption")
FIGNO = re.compile(r"^(?:図|Fig\.?|图)\s*(\d+)")
NUM = re.compile(r"\d+(?:\.\d+)?")
BINOMIAL = re.compile(r"\b[A-Z][a-z]{2,} (?:\([A-Z][a-z]+\) )?[a-z]{3,}\b")
CJK = re.compile(r"[ぁ-ヿ一-鿿]")
TYPES = ROLE_TYPES | EXTRA_TYPES
STATUSES = frozenset({"ok", "uncertain", "fixed"})


def _block(bid: str, typ: str, page: int, text: str, origin: str, ref: str,
           data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"id": bid, "type": typ, "page": page, "order": 0, "text": text, "data": dict(data or {}),
            "src": {"origin": origin, "ref": ref}, "status": "ok", "issues": []}


def couplet_id(c: Mapping[str, Any]) -> str:
    """与 docstore.keyblocks.block_id 同一规则，保证翻译单元 id 不变。"""
    return f"K{c['key']}-p{c['page']}-{c['lead']}"


def from_keys(keys: Mapping[str, Any]) -> list[dict[str, Any]]:
    """keys.json → 块。页内顺序取 keys['layout']（缺则按偶句顺序）。"""
    couplets = keys.get("couplets", [])
    blocks: list[dict[str, Any]] = []
    used: set[int] = set()
    layout = keys.get("layout") or {}
    for pg in sorted(layout, key=lambda x: int(x)):
        for it in layout[pg]:
            t = it.get("t")
            if t == "couplet" and 0 <= it["i"] < len(couplets):
                c = couplets[it["i"]]
                used.add(it["i"])
                blocks.append(_couplet_block(c))
            elif t == "heading":
                blocks.append(_block(f"KH-p{int(pg)}-{len(blocks)}", "key_heading", int(pg), it.get("text", ""),
                                     "keys", "layout", {"key": it.get("key")}))
            elif t == "rest" and it.get("text"):
                blocks.append(_block(f"KR-p{int(pg)}-{len(blocks)}", "body", int(pg), it["text"], "keys", "layout",
                                     {"why": it.get("why")}))
    for i, c in enumerate(couplets):
        if i not in used:
            blocks.append(_couplet_block(c))
    return blocks


def _couplet_block(c: Mapping[str, Any]) -> dict[str, Any]:
    cid = couplet_id(c)
    return _block(cid, "key_couplet", int(c["page"]), c.get("text", ""), "keys", cid,
                  {"key": c["key"], "lead": c["lead"], "kind": c.get("kind"),
                   "terminals": list(c.get("terminals", [])), "slots": list(c.get("slots", []))})


def from_aligned(aligned: Mapping[str, Any]) -> list[dict[str, Any]]:
    """aligned.json → 块。

    role 原样作 type（旧 `couplet` 归为 `key_couplet`）；原文取 text、无则取 source。
    整个原块存在 data.raw，位置存在 src.pi/src.bi，`to_aligned` 据此无损还原。
    """
    blocks: list[dict[str, Any]] = []
    for pi, p in enumerate(aligned.get("pages", [])):
        page = int(p.get("page", 0))
        for bi, b in enumerate(p.get("blocks", [])):
            role = b.get("role", "body")
            bid = b.get("block_id") or f"p{page:04d}_{bi:02d}"
            text = b.get("text") or b.get("source") or ""
            data: dict[str, Any] = {"raw": b}
            if b.get("translation"):
                data["translation"] = b["translation"]
            typ = role
            if role == "couplet" and isinstance(b.get("couplet"), dict):
                c = b["couplet"]
                typ = "key_couplet"
                tgt = c.get("target")
                data.update({"key": c.get("key"), "lead": c.get("lead"), "kind": None,
                             "terminals": [tgt] if tgt else []})
            blk = _block(bid, typ, page, text, "aligned", bid, data)
            blk["src"].update({"pi": pi, "bi": bi})
            blocks.append(blk)
    return blocks


def from_treatments(recs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """booklayout treatments.json（每个分类单元一条）→ treatment 块。

    不 import booklayout：记录由 `booklayout treatments <aligned> --out` 产出，这里只读其字段。
    """
    out = []
    for r in recs:
        ref = r.get("block_id") or f"p{int(r['page']):04d}"
        out.append(_block(f"T-{ref}", "treatment", int(r["page"]), r.get("latin", ""), "treatments", ref,
                          {k: v for k, v in r.items() if k not in ("page", "block_id")}))
    return out


def from_figures(aligned: Mapping[str, Any], treatments: list[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """aligned 里带图号的 caption 块 → figure 块；有 treatments 时按图号绑定到所属分类单元。

    aligned 没有图像路径，所以这里只绑定「图号 ↔ 图注块 ↔ 分类单元」，不声称绑定了图像文件。
    """
    owner: dict[int, str] = {}
    for r in treatments or []:
        for c in r.get("caption", []):
            if c.get("no") is not None:
                owner.setdefault(int(c["no"]), f"T-{r.get('block_id') or 'p%04d' % int(r['page'])}")
    out = []
    for p in aligned.get("pages", []):
        page = int(p.get("page", 0))
        for bi, b in enumerate(p.get("blocks", [])):
            if b.get("role") != "caption":
                continue
            m = FIGNO.match((b.get("text") or b.get("source") or "").strip())
            if not m:
                continue
            bid = b.get("block_id") or f"p{page:04d}_{bi:02d}"
            no = int(m.group(1))
            out.append(_block(f"F{no}-{bid}", "figure", page, b.get("text") or "", "figures", bid,
                              {"no": no, "caption_ref": bid, "treatment": owner.get(no),
                               "translation": b.get("translation") or None}))
    return out


def to_aligned(sd: Mapping[str, Any]) -> dict[str, Any]:
    """StructDoc → aligned.json。只还原 origin=aligned 的块；keys 来源块不进 aligned。

    往返等价：`to_aligned(build(doc, aligned=a)) == a`（块内容、页内顺序、页与顶层元数据）。
    """
    meta = sd.get("aligned_meta")
    if meta is None:
        raise ValueError("StructDoc has no aligned_meta: it was not built from an aligned.json")
    pages = [{**pm, "blocks": []} for pm in meta["pages"]]
    placed = sorted((b for b in sd.get("blocks", []) if b.get("src", {}).get("origin") == "aligned"),
                    key=lambda b: (b["src"]["pi"], b["src"]["bi"]))
    for b in placed:
        pages[b["src"]["pi"]]["blocks"].append(b["data"]["raw"])
    return {**meta["top"], "pages": pages}


def build(doc: str, *, keys: Mapping[str, Any] | None = None, aligned: Mapping[str, Any] | None = None,
          treatments: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    if aligned is not None:
        blocks += from_aligned(aligned)
        blocks += from_figures(aligned, treatments)
    if treatments is not None:
        blocks += from_treatments(treatments)
    if keys is not None:
        blocks += from_keys(keys)
    # 稳定排序：页号，再保持各来源内部顺序（sort 稳定）
    blocks.sort(key=lambda b: b["page"])
    for n, b in enumerate(blocks):
        b["order"] = n
    sd: dict[str, Any] = {"schema": SCHEMA, "doc": doc, "blocks": blocks, "problems": [], "summary": {}}
    if aligned is not None:
        sd["aligned_meta"] = {
            "top": {k: v for k, v in aligned.items() if k != "pages"},
            "pages": [{k: v for k, v in p.items() if k != "blocks"} for p in aligned.get("pages", [])],
        }
    return validate(sd, keys=keys)


_PROB_LEAD = re.compile(r"(?:^missing alternate for (\S+)$|^no terminal: (\S+) p\d+$|^jump to unknown \d+ from (\S+) p\d+$)")


def _problem_lead(prob: str) -> str | None:
    """keys.check 问题文字 → 出问题的条目号（精确匹配，不用子串）。"""
    m = _PROB_LEAD.match(prob)
    if not m:
        return None
    return next(g for g in m.groups() if g)


def validate(sd: dict[str, Any], keys: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """写回 status、issues、problems、summary；返回同一对象。可重复调用。"""
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_order = -1
    for b in sd.get("blocks", []):
        b["issues"] = []
        if b.get("id") in seen:
            b["issues"].append("duplicate_id")
        seen.add(b.get("id"))
        if b.get("type") not in TYPES:
            b["issues"].append("unknown_type")
        pg = b.get("page")
        if isinstance(pg, bool) or not isinstance(pg, int) or pg < 1:
            b["issues"].append("bad_page")
        if b.get("order", 0) < last_order:
            b["issues"].append("order_not_monotonic")
        last_order = max(last_order, b.get("order", 0))
        if b.get("type") == "key_couplet":
            d = b.get("data", {})
            if d.get("key") is None or not d.get("lead"):
                b["issues"].append("couplet_missing_key_or_lead")
            if not d.get("terminals"):
                b["issues"].append("no_terminal")
    problems += _check_treatments_and_figures(sd)
    for b in sd.get("blocks", []):
        for code in translation_issues(b):
            b["issues"].append(code)
            problems.append({"scope": f"translation:{b['id']}", "code": code, "detail": b["id"]})
    from .keys import check_couplets

    for origin in sorted({b["src"].get("origin") for b in sd.get("blocks", [])}):
        group = [b for b in sd.get("blocks", []) if b.get("type") == "key_couplet"
                 and b.get("src", {}).get("origin") == origin
                 and b.get("data", {}).get("key") is not None and b["data"].get("lead")]
        couplets = [{"key": b["data"]["key"], "lead": b["data"]["lead"], "kind": b["data"].get("kind"),
                     "page": b["page"], "text": b["text"], "terminals": b["data"].get("terminals", [])}
                    for b in group]
        if not couplets:
            continue
        for kid, info in check_couplets(couplets).items():
            for prob in info["problems"]:
                code = prob.split(":")[0].split(" from ")[0]
                problems.append({"scope": f"{origin}:key:{kid}", "code": code, "detail": prob})
                lead = _problem_lead(prob)
                for b in group:
                    if b["data"]["key"] == kid and lead is not None and b["data"]["lead"] == lead:
                        b["issues"].append("key_graph")
    for b in sd.get("blocks", []):
        if b["issues"]:
            b["status"] = "uncertain" if b.get("status") != "fixed" else "fixed"
        elif b.get("status") not in STATUSES:
            b["status"] = "ok"
    sd["problems"] = problems
    cnt = Counter(b.get("type") for b in sd.get("blocks", []))
    sd["summary"] = {"blocks": len(sd.get("blocks", [])), "by_type": dict(cnt),
                     "uncertain": sum(1 for b in sd.get("blocks", []) if b.get("status") == "uncertain")}
    return sd


def _norm_nums(s: str, decimal_comma: bool = False) -> list[str]:
    s = s.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    if decimal_comma:  # 西语小数逗号 2,5
        s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    # 1-3 的整数常被译成数词（1対→a pair），不参与比对；小数、年份、大数、范围端点照查
    return sorted(n for n in NUM.findall(s) if not (n.isdigit() and int(n) <= 3))


def _nums_equal(src: str, tr: str) -> bool:
    """逗号既可能是列表分隔也可能是小数点：两种读法任一一致即算一致，宁漏报不误报。"""
    return any(_norm_nums(src, a) == _norm_nums(tr, b) for a in (False, True) for b in (False, True))


def translation_issues(b: Mapping[str, Any]) -> list[str]:
    """块的译文与原文逐块比对（确定性，零模型）。无译文的块不查。

    - tr_numbers：数字（含小数；不含 1-3 的整数，它们常译成数词）多重集不一致（丢数、多数）。
    - tr_latin：原文含 CJK 时，原文里的学名二名法必须原样出现在译文里。
    - tr_figno：图注的图号必须保留。
    检索表偶句的终点不交模型（只在 data.terminals 里），所以不查终点是否出现在译文。
    """
    d = b.get("data", {})
    tr = d.get("translation")
    if not tr or not isinstance(tr, str):
        return []
    src = b.get("text", "")
    out = []
    if not _nums_equal(src, tr):
        out.append("tr_numbers")
    if CJK.search(src):
        flat = re.sub(r"\s+", " ", tr)
        if any(re.sub(r"\s+", " ", m) not in flat for m in BINOMIAL.findall(src)):
            out.append("tr_latin")
    if b.get("type") == "figure":
        m = FIGNO.match(src.strip())
        if m and not re.search(rf"(?<!\d){m.group(1)}(?!\d)", tr):
            out.append("tr_figno")
    return out


def _check_treatments_and_figures(sd: Mapping[str, Any]) -> list[dict[str, Any]]:
    """treatment 必备字段、图号重复/缺号、图注无归属。与 booklayout.treatments.validate 同码（测试核对）。"""
    probs: list[dict[str, Any]] = []

    def flag(b: dict[str, Any], scope: str, code: str, detail: str) -> None:
        b["issues"].append(code)
        probs.append({"scope": scope, "code": code, "detail": detail})

    for b in sd.get("blocks", []):
        if b.get("type") != "treatment":
            continue
        d = b.get("data", {})
        if d.get("rank") != "species":
            continue
        sc = f"treatment:{b['id']}"
        for fld in TREATMENT_REQUIRED:
            if not d.get(fld):
                flag(b, sc, f"missing_{fld}", d.get("latin", ""))
        if d.get("legend") and not d.get("caption"):
            flag(b, sc, "legend_without_caption", d.get("latin", ""))
        if len(d.get("caption", [])) > 1:
            flag(b, sc, "multiple_captions", d.get("latin", ""))
    has_t = any(x.get("type") == "treatment" for x in sd.get("blocks", []))
    seen: set[int] = set()
    for b in (x for x in sd.get("blocks", []) if x.get("type") == "figure"):
        n = b["data"]["no"]
        if n in seen:
            flag(b, "figures", "duplicate_figure_no", str(n))
        seen.add(n)
        if has_t and not b["data"].get("treatment"):
            flag(b, "figures", "unbound_caption", str(n))
    if seen:
        for n in range(min(seen), max(seen) + 1):
            if n not in seen:
                probs.append({"scope": "figures", "code": "figure_no_gap", "detail": str(n)})
    return probs


def to_translation_units(sd: Mapping[str, Any]) -> list[dict[str, Any]]:
    """key_couplet 块 → 翻译单元；终点和条目号不交模型（与 keyblocks 同约定）。"""
    return [{"id": b["id"], "text": b["text"], "lead": b["data"]["lead"],
             "terminals": b["data"].get("terminals", [])}
            for b in sd.get("blocks", []) if b.get("type") == "key_couplet"]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(sd: Mapping[str, Any], path: Path) -> None:
    path.write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
