"""检索表偶句块：交给翻译、回收译文校验、残留修复计划（issue #38 步骤 2/3 的 docstore 一侧）。

- `couplet_blocks(data)`   keys.json → 翻译单元。每个偶句一个单元；`text` 交模型译，`terminals`（跳转号、
  类群名）与 `lead` 不交模型，由调用方原样回填，译文里的号和学名不会漂移。
- `check_translation(...)` 译文回收后逐单元校验：一一对应（缺/多/重）、终点逐字相同（类群名可经
  名称表映射）、正文里的数字和拉丁学名不丢。
- `repair_plan(data)`      把自洽检查的缺陷变成 `keys_fix.json` 骨架（`why` 留空，必须人对照页面图像
  填写后才能被 `apply_fixes` 接受）；`render_pages` 可把缺陷页渲成 PNG 供核对。零 token。
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_NUM = re.compile(r"\d+")
_BINOMIAL = re.compile(r"\b[A-Z][a-z]+\s+[a-z]{3,}\b")


def _latin(text: str) -> set[str]:
    """句中的拉丁双名（句首大写词不算，避免把 "Setae long" 当学名）。"""
    return {m.group() for m in _BINOMIAL.finditer(text)
            if m.start() > 0 and not re.search(r"[.!?。]\s*$", text[:m.start()])}


def block_id(c: Mapping[str, Any]) -> str:
    return f"K{c['key']}-p{c['page']}-{c['lead']}"


def couplet_blocks(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """每个偶句一个单元，保持表内顺序；同页同号（图规则已报缺陷）会得到相同 id，由 check 报重复。"""
    return [{"id": block_id(c), "key": c["key"], "lead": c["lead"], "kind": c["kind"], "page": c["page"],
             "text": c["text"], "terminals": list(c.get("terminals") or []), "index": i}
            for i, c in enumerate(data["couplets"])]


def check_translation(blocks: Sequence[Mapping[str, Any]],
                      translated: Mapping[str, Any] | Sequence[Mapping[str, Any]],
                      name_table: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """`translated`：`{id: "译文"}` 或 `{id: {"text", "terminals"}}`，或带 id 的单元列表（可含重复 id）。"""
    if isinstance(translated, Mapping):
        items = [(k, v) for k, v in translated.items()]
    else:
        items = [(t["id"], t) for t in translated]
    count = Counter(k for k, _ in items)
    got = dict(items)
    names = name_table or {}
    out: list[dict[str, Any]] = []
    src_ids = {b["id"] for b in blocks}
    for k, n in count.items():
        if n > 1:
            out.append({"code": "duplicate", "id": k, "count": n})
        if k not in src_ids:
            out.append({"code": "extra", "id": k})
    for b in blocks:
        v = got.get(b["id"])
        if v is None:
            out.append({"code": "missing", "id": b["id"], "page": b["page"], "lead": b["lead"]})
            continue
        text = v if isinstance(v, str) else str(v.get("text", ""))
        if not text.strip():
            out.append({"code": "empty", "id": b["id"]})
        if not isinstance(v, str) and v.get("terminals") is not None:
            want = [names.get(t, t) for t in b["terminals"]]
            if list(v["terminals"]) != want:
                out.append({"code": "terminal_changed", "id": b["id"], "src": b["terminals"], "tgt": v["terminals"]})
        lost = Counter(_NUM.findall(b["text"])) - Counter(_NUM.findall(text))
        if lost:
            out.append({"code": "number_lost", "id": b["id"], "numbers": sorted(lost.elements())})
        lat = sorted(_latin(b["text"]) - _latin(text))
        if lat:
            out.append({"code": "latin_lost", "id": b["id"], "names": lat})
    return out


def repair_plan(data: Mapping[str, Any]) -> dict[str, Any]:
    """缺陷 → `keys_fix.json` 骨架。`why` 留空：未对照页面图像填写前 `apply_fixes` 会拒绝。"""
    cs = data["couplets"]
    fixes: list[dict[str, Any]] = []
    pages: set[int] = set()
    for k in data.get("keys", []):
        for pr in k.get("problems", []):
            m = re.search(r"(?:missing alternate for|no terminal:|jump to unknown \S+ from)\s+(\S+)(?:\s+p(\d+))?", pr)
            entry: dict[str, Any] = {"problem": pr, "key": k["key"], "why": ""}
            if m:
                lead = m.group(1)
                page = int(m.group(2)) if m.group(2) else None
                if page is None:
                    hit = [c for c in cs if c["key"] == k["key"] and c["lead"] == lead]
                    page = hit[0]["page"] if hit else k.get("first_page")
                entry.update({"op": "add" if pr.startswith("missing alternate") else "set",
                              "page": page, "lead": lead})
                if page:
                    pages.add(int(page))
            fixes.append(entry)
    return {"fixes": fixes, "pages_to_check": sorted(pages)}


def render_pages(pdf: Path, pages: Sequence[int], out_dir: Path, dpi: int = 110) -> list[Path]:
    """把待核对页渲成 PNG（缺陷页图像核对用）。"""
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    paths = []
    for p in pages:
        dest = out_dir / f"p{p:04d}.png"
        doc[p - 1].get_pixmap(dpi=dpi).save(str(dest))
        paths.append(dest)
    return paths
