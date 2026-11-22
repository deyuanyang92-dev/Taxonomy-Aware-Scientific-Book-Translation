"""StructDoc 自动生成（切片 4）：识别缓存 → keys → StructDoc，并对人工金标计分。零模型、不 OCR。

- keys_from_cache：读 PP-OCR 行框缓存重建检索表偶句（可选行尾跳转号补读）。
- auto：keys_from_cache + structdoc.build，写 structdoc.json。
- score / ledger_row：对人工金标的结构准确率，追加到 docs/ocr_eval/STRUCT_LEDGER.tsv。
金标格式见 docs/ocr_eval/struct_gold/README.md：{"doc","set","pages":[...],"couplets":[{page,key,lead,terminals}]}，
必须由人对照原页图像写成，不得由本流水线的输出生成。
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LEDGER_HEADER = ("date\tdoc\tgold_set\tn_gold\tn_pred\trecall\tprecision\tterminal_acc\t"
                 "wrong_flagged\tnote")


def keys_from_cache(cache: Path, first: int, last: int, *, pdf: str | None = None, dpi: int = 200,
                    recover_tail: bool = False) -> dict[str, Any]:
    from . import keys, keytail

    if not cache.is_dir() or last < first:
        raise FileNotFoundError(f"行框缓存不存在或页范围为空：{cache}（先 docstore text --engines ppocr）")
    pages, missing = keys.read_cache_pages(cache, first, last)
    data = keys.extract(pages)
    data["missing_pages"] = missing
    if recover_tail:
        if not pdf:
            raise ValueError("recover_tail 需要原件 PDF")
        data["tail_recovery"] = keytail.recover_tail_jumps(data, keytail.pdf_renderer(pdf, dpi),
                                                           keytail.tesseract_digits)
    return data


def auto(doc: str, keys_data: Mapping[str, Any], *, aligned: Mapping[str, Any] | None = None,
         treatments: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    from . import structdoc

    return structdoc.build(doc, keys=keys_data, aligned=aligned, treatments=treatments)


def score(sd: Mapping[str, Any], gold: Mapping[str, Any]) -> dict[str, Any]:
    """只在金标覆盖的页上比对。匹配键 (page, key, lead)。

    wrong_flagged：预测中终点与金标不符的偶句里，有多少被标成 uncertain（图检查的查全）。
    """
    pages = set(gold["pages"])
    g = {(c["page"], c["key"], str(c["lead"])): [str(t) for t in c.get("terminals", [])] for c in gold["couplets"]}
    pred: dict[tuple[int, int, str], dict[str, Any]] = {}
    for b in sd.get("blocks", []):
        if b.get("type") == "key_couplet" and b.get("src", {}).get("origin") == "keys" and b["page"] in pages:
            d = b["data"]
            pred[(b["page"], d["key"], str(d["lead"]))] = b
    hit = [k for k in g if k in pred]
    term_ok = [k for k in hit if [str(t) for t in pred[k]["data"].get("terminals", [])] == g[k]]
    wrong = [k for k in hit if k not in term_ok]
    flagged = [k for k in wrong if pred[k]["status"] == "uncertain"]
    return {
        "n_gold": len(g), "n_pred": len(pred), "matched": len(hit),
        "recall": len(hit) / len(g) if g else None,
        "precision": len(hit) / len(pred) if pred else None,
        "terminal_acc": len(term_ok) / len(hit) if hit else None,
        "wrong_terminals": len(wrong), "wrong_flagged": len(flagged),
        "missing": sorted(k for k in g if k not in pred), "extra": sorted(k for k in pred if k not in g),
    }


def _f(x: float | None) -> str:
    return "NA" if x is None else f"{x:.3f}"


def ledger_row(doc: str, gold_set: str, r: Mapping[str, Any], note: str = "") -> str:
    return "\t".join([_dt.date.today().isoformat(), doc, gold_set, str(r["n_gold"]), str(r["n_pred"]),
                      _f(r["recall"]), _f(r["precision"]), _f(r["terminal_acc"]),
                      f"{r['wrong_flagged']}/{r['wrong_terminals']}", note])


def append_ledger(path: Path, row: str) -> None:
    new = not path.exists()
    with path.open("a", encoding="utf-8") as fh:
        if new:
            fh.write(LEDGER_HEADER + "\n")
        fh.write(row + "\n")
