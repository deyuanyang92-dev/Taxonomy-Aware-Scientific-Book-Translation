"""术语决策日志：译者对 SOFT 术语的取舍，逐行 JSON（term_decisions.jsonl）。

每行 {"en", "zh", "sense", "reason", "source", "chunk"}（均为字符串；source 可为空，表示没有出处，会被 review 标出）。
可选 "accept": false 表示主会话驳回，apply 时跳过。
流程：译者随译文输出 -> yiku decide validate（格式）-> yiku decide review（列出须主会话裁定的）
     -> 主会话删改/标 accept -> yiku decide apply（写回术语库：候选，来源 决策_<书>；--verified 才记已核）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db as D
from .classify import HARD, classify
from .match import variants

REQUIRED = ("en", "zh", "sense", "reason", "chunk")
_FENCE = re.compile(r"^```[A-Za-z]*$")


def validate_record(obj: Any) -> list[str]:
    """返回错误说明列表，空列表表示合法。"""
    if not isinstance(obj, dict):
        return ["不是 JSON 对象"]
    errs = [f"缺字段 {k}（须为非空字符串）" for k in REQUIRED if not isinstance(obj.get(k), str) or not obj[k].strip()]
    if obj.get("source") is not None and not isinstance(obj["source"], str):
        errs.append("source 须为字符串或 null")
    if "accept" in obj and not isinstance(obj["accept"], bool):
        errs.append("accept 只能是布尔值")
    return errs


def parse_decisions(text: str) -> tuple[list[dict], list[str]]:
    """严格解析：返回 (合法记录, 错误说明)。围栏标记行和空行忽略，其余每行都必须是合法的决策对象。"""
    ok: list[dict] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        ln = raw.strip()
        if not ln or _FENCE.match(ln):
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as exc:
            errors.append(f"第 {n} 行不是合法 JSON：{ln[:50]!r}（{exc.msg}）")
            continue
        errs = validate_record(obj)
        if errs:
            errors.append(f"第 {n} 行：" + "；".join(errs))
        else:
            ok.append(obj)
    return ok, errors


def read_files(paths: list[str | Path]) -> tuple[list[dict], list[str]]:
    """读若干 JSONL 文件（目录则取其中全部 *.jsonl）。错误说明前加文件名。"""
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])
    ok: list[dict] = []
    errors: list[str] = []
    for f in files:
        recs, errs = parse_decisions(f.read_text(encoding="utf8"))
        ok.extend(recs)
        errors.extend(f"{f}：{e}" for e in errs)
    return ok, errors


def _same_zh(a: str, b: str) -> bool:
    return b in variants(a) or a in variants(b)


def review(con, records: list[dict], domain: str = "*", scope: set[str] | None = None,
           fallback_domains: list[str] | str | None = None) -> list[dict]:
    """列出须主会话裁定的决策（去重后）：SOFT 术语有多个译名、无出处、zh 不在库里候选中、违反 HARD 译名、
    同一英文+义项登记了不同译名。被 accept:false 驳回的不列。每项带 flags、chunks、count、库中候选。"""
    fb = D.resolve_fallback(domain, fallback_domains)
    live = [r for r in records if r.get("accept") is not False]
    zhs_by_sense: dict[tuple[str, str], set[str]] = {}
    for r in live:
        zhs_by_sense.setdefault((D.norm(r["en"]), r["sense"]), set()).add(r["zh"])
    merged: dict[tuple[str, str, str], dict] = {}
    for r in live:
        k = (D.norm(r["en"]), r["zh"], r["sense"])
        if k in merged:
            merged[k]["count"] += 1
            merged[k]["chunks"].append(r["chunk"])
        else:
            merged[k] = {**r, "count": 1, "chunks": [r["chunk"]]}
    out = []
    for (en_norm, zh, sense), r in merged.items():
        hits = D.candidates(con, r["en"], domain, scope, fb)
        cls = classify(hits)
        cand = list(dict.fromkeys(h.zh for h in hits))
        flags = []
        if not (r.get("source") or "").strip():
            flags.append("无出处")
        if cls.kind == HARD and cls.zh and not _same_zh(zh, cls.zh):
            flags.append(f"与 HARD 译名不符：应为「{cls.zh}」")
        elif not cand:
            flags.append("不在候选：库中无此术语")
        elif not any(_same_zh(zh, c) for c in cand):
            flags.append("不在候选：库中译名为 " + "、".join(cand))
        if cls.kind != HARD and len(cand) > 1:
            flags.append("SOFT 多译名：" + "、".join(cand))
        other = zhs_by_sense[(en_norm, sense)] - {zh}
        if other:
            flags.append("同一义项登记了不同译名：" + "、".join(sorted(other)))
        if flags:
            out.append({**r, "flags": flags, "candidates": cand})
    return out


@dataclass
class ApplyResult:
    added: int = 0
    upgraded: int = 0
    merged: int = 0
    skipped: int = 0
    invalid: int = 0


def apply(con, records: list[dict], book: str, domain: str = "*", scope: str = "*", verified: bool = False) -> ApplyResult:
    """把决策写回术语库：来源 决策_<book>（首次登记为 model 层级 9，之后不改动，用户调过层级会保留），
    状态默认候选，note=reason，page=chunk，context=义项与依据；只有 verified=True 才记已核。
    已核层级仍按来源层级排：杨孙等一级来源永远胜过决策（改层级用 yiku source set）。"""
    key = f"决策_{book}"
    if not con.execute("SELECT 1 FROM sources WHERE key=?", (key,)).fetchone():
        D.add_source(con, key, f"术语决策：{book}", "model", domain=domain,
                     note="译者在翻译中对 SOFT 术语的取舍记录，经 yiku decide apply 写回")
    res = ApplyResult()
    status = "已核" if verified else "候选"
    for r in records:
        if r.get("accept") is False:
            res.skipped += 1
            continue
        if validate_record(r):
            res.invalid += 1
            continue
        ctx = f"义项：{r['sense']}" + (f"；依据：{r['source']}" if (r.get("source") or "").strip() else "")
        where = (D.norm(r["en"]), r["zh"].strip(), domain or "*", scope or "*", key)
        old = con.execute("SELECT id, status, context FROM terms WHERE en_norm=? AND zh=? AND domain=? AND scope=? AND source=?",
                          where).fetchone()
        if old is None:
            D.add_term(con, r["en"], r["zh"], key, domain, scope, page=r["chunk"], context=ctx, status=status, note=r["reason"])
            res.added += 1
            continue
        if verified and old["status"] != "已核":
            con.execute("UPDATE terms SET status='已核' WHERE id=?", (old["id"],))
            res.upgraded += 1
        if ctx not in (old["context"] or ""):  # 同一译名的另一义项/依据：并入语境，不另起一行
            con.execute("UPDATE terms SET context=? WHERE id=?", (((old["context"] or "") + "｜" + ctx).strip("｜"), old["id"]))
            res.merged += 1
    con.commit()
    return res
