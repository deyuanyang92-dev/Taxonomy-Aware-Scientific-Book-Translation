"""StructDoc 切片 4：金标计分、账本、auto 的缓存缺失报错。"""
from __future__ import annotations

from pathlib import Path

import pytest

from docstore import structauto, structdoc

KEYS = {"couplets": [
    {"key": 1, "lead": "1", "kind": "n", "page": 5, "text": "a", "terminals": ["2"], "slots": []},
    {"key": 1, "lead": "1'", "kind": "alt", "page": 5, "text": "b", "terminals": ["Nereis"], "slots": []},
    {"key": 1, "lead": "2", "kind": "n", "page": 6, "text": "c", "terminals": ["X"], "slots": []},
    {"key": 1, "lead": "2'", "kind": "alt", "page": 6, "text": "d", "terminals": [], "slots": []},
], "layout": {}}
GOLD = {"doc": "d", "set": "t", "pages": [5, 6], "couplets": [
    {"page": 5, "key": 1, "lead": "1", "terminals": ["2"]},
    {"page": 5, "key": 1, "lead": "1'", "terminals": ["Nereis"]},
    {"page": 6, "key": 1, "lead": "2", "terminals": ["Y"]},
    {"page": 6, "key": 1, "lead": "2'", "terminals": ["9"]},
    {"page": 6, "key": 1, "lead": "3", "terminals": ["Z"]},
]}


def test_score_counts():
    sd = structauto.auto("d", KEYS)
    r = structauto.score(sd, GOLD)
    assert (r["n_gold"], r["n_pred"], r["matched"]) == (5, 4, 4)
    assert r["recall"] == 0.8 and r["precision"] == 1.0
    assert r["terminal_acc"] == 0.5  # 2、2' 终点错（Y≠X、空≠9）
    assert r["wrong_terminals"] == 2
    assert r["missing"] == [(6, 1, "3")] and r["extra"] == []


def test_wrong_flagged_counts_uncertain_only():
    sd = structauto.auto("d", KEYS)
    r = structauto.score(sd, GOLD)
    # 2' 无终点 → no_terminal → uncertain；2 终点错但图自洽 → 未标出
    assert r["wrong_flagged"] == 1


def test_score_ignores_pages_outside_gold():
    sd = structauto.auto("d", KEYS)
    g = {**GOLD, "pages": [5], "couplets": GOLD["couplets"][:2]}
    r = structauto.score(sd, g)
    assert (r["n_pred"], r["recall"], r["precision"], r["terminal_acc"]) == (2, 1.0, 1.0, 1.0)


def test_score_ignores_aligned_origin():
    a = {"pages": [{"page": 5, "blocks": [{"role": "couplet", "text": "x", "block_id": "q",
         "couplet": {"lead": "1", "key": 1, "target": "2"}}]}]}
    sd = structdoc.build("d", aligned=a)
    assert structauto.score(sd, {"pages": [5], "couplets": []})["n_pred"] == 0


def test_ledger_row_and_append(tmp_path: Path):
    r = structauto.score(structauto.auto("d", KEYS), GOLD)
    row = structauto.ledger_row("d", "t", r, "n=5")
    p = tmp_path / "L.tsv"
    structauto.append_ledger(p, row)
    structauto.append_ledger(p, row)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == structauto.LEDGER_HEADER and len(lines) == 3
    assert len(lines[1].split("\t")) == len(lines[0].split("\t"))
    assert "1/2" in lines[1]


def test_keys_from_cache_missing_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        structauto.keys_from_cache(tmp_path / "nope", 1, 5)
    with pytest.raises(FileNotFoundError):  # 页范围为空同样拒绝
        structauto.keys_from_cache(tmp_path, 5, 1)
    with pytest.raises(ValueError):
        structauto.keys_from_cache(tmp_path, 1, 5, recover_tail=True)
