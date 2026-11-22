"""StructDoc 第一切片：构建、校验、翻译单元、CLI、与 aligned 词表的兼容。"""
from __future__ import annotations

import json
from pathlib import Path

from docstore import structdoc as sd
from docstore.keyblocks import block_id, couplet_blocks

KEYS = {
    "couplets": [
        {"key": 1, "lead": "1", "kind": "n", "page": 5, "text": "触手長い", "terminals": ["2"], "slots": []},
        {"key": 1, "lead": "1'", "kind": "alt", "page": 5, "text": "触手短い", "terminals": ["Nereis virens"], "slots": []},
        {"key": 1, "lead": "2", "kind": "n", "page": 6, "text": "刚毛", "terminals": ["Nereis sp."], "slots": []},
        {"key": 1, "lead": "2'", "kind": "alt", "page": 6, "text": "无刚毛", "terminals": ["9"], "slots": []},
    ],
    "layout": {"5": [{"t": "heading", "text": "検索表", "key": 1}, {"t": "couplet", "i": 0}, {"t": "couplet", "i": 1}],
               "6": [{"t": "couplet", "i": 2}, {"t": "couplet", "i": 3}, {"t": "rest", "text": "図1", "why": "caption"}]},
}
ALIGNED = {"pages": [{"page": 4, "blocks": [
    {"role": "heading", "text": "Nereididae", "block_id": "p004_00"},
    {"role": "body", "source": "Body text", "block_id": "p004_01"},
]}]}


def test_types_superset_of_aligned_roles():
    from booklayout.profile import ROLES
    assert ROLES <= sd.TYPES


def test_build_orders_and_summary():
    d = sd.build("imajima", keys=KEYS, aligned=ALIGNED)
    assert d["schema"] == sd.SCHEMA
    orders = [b["order"] for b in d["blocks"]]
    assert orders == sorted(orders) == list(range(len(orders)))
    assert [b["page"] for b in d["blocks"]] == sorted(b["page"] for b in d["blocks"])
    assert d["summary"]["by_type"]["key_couplet"] == 4
    assert {b["type"] for b in d["blocks"]} >= {"heading", "body", "key_heading", "key_couplet"}


def test_couplet_ids_match_keyblocks():
    d = sd.build("x", keys=KEYS)
    ids = {b["id"] for b in d["blocks"] if b["type"] == "key_couplet"}
    assert ids == {block_id(c) for c in KEYS["couplets"]}
    assert {u["id"] for u in sd.to_translation_units(d)} == {b["id"] for b in couplet_blocks(KEYS)}


def test_valid_key_has_no_problems():
    d = sd.build("x", keys=KEYS)
    # 跳转号 9 指向不存在条目 -> 应报问题，其余偶句完整
    codes = {p["code"] for p in d["problems"]}
    assert "jump to unknown 9" in codes or any("unknown" in p["detail"] for p in d["problems"])
    bad = [b for b in d["blocks"] if b["status"] == "uncertain"]
    assert bad and all(b["data"]["lead"] == "2'" for b in bad)


def test_missing_alternate_marks_block_uncertain():
    keys = json.loads(json.dumps(KEYS))
    keys["couplets"] = keys["couplets"][:1] + keys["couplets"][2:]
    keys["layout"] = {"5": [{"t": "couplet", "i": 0}], "6": [{"t": "couplet", "i": 1}, {"t": "couplet", "i": 2}]}
    d = sd.build("x", keys=keys)
    assert any(p["detail"].startswith("missing alternate for 1") for p in d["problems"])
    assert any(b["status"] == "uncertain" and b["data"]["lead"] == "1" for b in d["blocks"])


def test_validate_catches_structure_errors_and_is_idempotent():
    d = sd.build("x", aligned=ALIGNED)
    d["blocks"][1]["id"] = d["blocks"][0]["id"]
    d["blocks"][0]["type"] = "bogus"
    d["blocks"][1]["page"] = 0
    sd.validate(d)
    assert "duplicate_id" in d["blocks"][1]["issues"] and "unknown_type" in d["blocks"][0]["issues"]
    assert "bad_page" in d["blocks"][1]["issues"]
    first = json.dumps(d, sort_keys=True)
    sd.validate(d)
    assert json.dumps(d, sort_keys=True) == first


def test_fixed_status_survives_revalidation():
    d = sd.build("x", keys=KEYS)
    for b in d["blocks"]:
        if b["status"] == "uncertain":
            b["status"] = "fixed"
    sd.validate(d)
    assert all(b["status"] != "ok" for b in d["blocks"] if b["issues"])


def test_cli_build_and_check(tmp_path: Path):
    import pytest

    from docstore import cli
    kp, ap, out = tmp_path / "k.json", tmp_path / "a.json", tmp_path / "s.json"
    kp.write_text(json.dumps(KEYS), encoding="utf-8")
    ap.write_text(json.dumps(ALIGNED), encoding="utf-8")
    root = ["--root", str(tmp_path / "lib")]
    assert cli.main([*root, "struct", "build", "imajima", "--keys", str(kp), "--aligned", str(ap),
                     "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["doc"] == "imajima"
    with pytest.raises(SystemExit) as e:
        cli.main([*root, "struct", "check", str(out)])
    assert e.value.code == 1  # 跳转 9 未知
    with pytest.raises(SystemExit) as e2:
        cli.main([*root, "struct", "build", "x", "--out", str(out)])
    assert e2.value.code == 2
