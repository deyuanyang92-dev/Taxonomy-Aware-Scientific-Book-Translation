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
EXTRA_TYPES = frozenset({"key_couplet", "key_heading", "treatment", "figure"})
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


def build(doc: str, *, keys: Mapping[str, Any] | None = None, aligned: Mapping[str, Any] | None = None) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    if aligned is not None:
        blocks += from_aligned(aligned)
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


def to_translation_units(sd: Mapping[str, Any]) -> list[dict[str, Any]]:
    """key_couplet 块 → 翻译单元；终点和条目号不交模型（与 keyblocks 同约定）。"""
    return [{"id": b["id"], "text": b["text"], "lead": b["data"]["lead"],
             "terminals": b["data"].get("terminals", [])}
            for b in sd.get("blocks", []) if b.get("type") == "key_couplet"]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(sd: Mapping[str, Any], path: Path) -> None:
    path.write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
