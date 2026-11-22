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


def _aligned_with_meta():
    return {"metadata": {"title": "T"}, "pages": [
        {"page": 1, "chapter": "Front", "kind": "front", "blocks": []},
        {"page": 2, "chapter": "A", "blocks": [
            {"block_id": "p002_00", "role": "heading", "text": "H", "translation": "标题"},
            {"role": "table", "rows": [[{"text": "a", "colspan": 2}]], "extra_field": [1, 2]},
            {"block_id": "p002_k0", "role": "couplet", "source_page": 2, "text": "x", "translation": "甲",
             "couplet": {"marker": "1.", "lead": "1", "key": 1, "name": None, "target": "2"}},
            {"block_id": "p002_k1", "role": "couplet", "source_page": 2, "text": "y", "translation": "乙",
             "couplet": {"marker": "—", "lead": "1'", "key": 1, "name": None, "target": "Nereis"}},
        ]},
        {"page": 2, "chapter": "A", "blocks": [{"role": "body", "text": "dup page number"}]},
    ]}


def test_aligned_roundtrip_is_lossless():
    a = _aligned_with_meta()
    d = sd.build("x", aligned=json.loads(json.dumps(a)))
    assert sd.to_aligned(d) == a


def test_roundtrip_survives_json_dump_and_block_reorder():
    a = _aligned_with_meta()
    d = json.loads(json.dumps(sd.build("x", aligned=a)))
    d["blocks"].reverse()
    assert sd.to_aligned(d) == a


def test_legacy_couplet_enters_key_graph_check():
    a = _aligned_with_meta()
    d = sd.build("x", aligned=a)
    kinds = [b["type"] for b in d["blocks"]]
    assert kinds.count("key_couplet") == 2
    # 跳转号 2 不存在
    assert any(p["scope"] == "aligned:key:1" and "unknown 2" in p["detail"] for p in d["problems"])
    bad = [b for b in d["blocks"] if b["status"] == "uncertain"]
    assert [b["data"]["lead"] for b in bad] == ["1"]


def test_keys_and_aligned_do_not_mix_key_numbers():
    d = sd.build("x", keys=KEYS, aligned=_aligned_with_meta())
    scopes = {p["scope"] for p in d["problems"]}
    assert scopes == {"keys:key:1", "aligned:key:1"}


def test_to_aligned_requires_aligned_origin():
    import pytest
    with pytest.raises(ValueError):
        sd.to_aligned(sd.build("x", keys=KEYS))


REAL = [Path("/mnt/p/翻译-译作/日本-imajima/交付/Imajima2009/zh/aligned.json"),
        Path("/mnt/p/翻译-译作/日本-imajima/交付/Imajima2001/en/aligned.json"),
        Path("/mnt/p/翻译-译作/yanjie/work/Vol48/layout/aligned_v2.json")]


def test_real_books_roundtrip_if_present():
    import pytest
    found = [p for p in REAL if p.is_file()]
    if not found:
        pytest.skip("real aligned.json not available")
    for p in found:
        a = json.loads(p.read_text(encoding="utf-8"))
        assert sd.to_aligned(sd.build(p.stem, aligned=a)) == a, p


# ---- 切片 3：treatment、图号绑定、译后逐块检查 ----

def _treat(latin="Exogone gemmifera Pagenstecher, 1862", **kw):
    r = {"page": 11, "block_id": "p011_b03", "latin": latin, "rank": "species", "caption": [{"no": 2, "text": "Fig.2"}],
         "ja": "コンボウ", "ref": ["r"], "description": ["d"], "distribution": ["x"]}
    r.update(kw)
    return r


def _cap_aligned(text="図2.体前部", tr="图2 体前部"):
    return {"pages": [{"page": 11, "blocks": [
        {"role": "caption", "text": text, "translation": tr, "block_id": "p011_b05"}]}]}


def test_treatment_block_and_missing_field():
    d = sd.build("x", treatments=[_treat(), _treat(latin="Nereis virens Sars, 1835", block_id="p012_b01", description=[])])
    assert [b["type"] for b in d["blocks"]] == ["treatment", "treatment"]
    assert [b["status"] for b in d["blocks"]] == ["ok", "uncertain"]
    assert {"scope": "treatment:T-p012_b01", "code": "missing_description", "detail": "Nereis virens Sars, 1835"} in d["problems"]


def test_figure_binds_caption_to_treatment():
    d = sd.build("x", aligned=_cap_aligned(), treatments=[_treat()])
    fig = [b for b in d["blocks"] if b["type"] == "figure"][0]
    assert fig["data"]["no"] == 2 and fig["data"]["treatment"] == "T-p011_b03" and fig["status"] == "ok"


def test_unbound_and_gap_and_duplicate_figures():
    a = {"pages": [{"page": 11, "blocks": [
        {"role": "caption", "text": "図1.a", "block_id": "c1"},
        {"role": "caption", "text": "図3.b", "block_id": "c3"},
        {"role": "caption", "text": "図3.c", "block_id": "c3b"}]}]}
    d = sd.build("x", aligned=a, treatments=[_treat(caption=[{"no": 1, "text": "図1"}])])
    codes = {(p["code"], p["detail"]) for p in d["problems"]}
    assert ("figure_no_gap", "2") in codes and ("duplicate_figure_no", "3") in codes
    assert ("unbound_caption", "3") in codes and ("unbound_caption", "1") not in codes


def test_translation_checks_flag_lost_number_latin_and_figno():
    a = {"pages": [{"page": 1, "blocks": [
        {"role": "body", "text": "体長2.8mm，Exogone gemmifera が33節", "translation": "体长2.8mm，Exogone gemmifera 有33节",
         "block_id": "b1"},
        {"role": "body", "text": "体長2.8mm，Exogone gemmifera が33節", "translation": "体长28mm，Exogene gemmifera 有33节",
         "block_id": "b2"},
        {"role": "caption", "text": "図5.a", "translation": "图6.a", "block_id": "b3"}]}]}
    d = sd.build("x", aligned=a)
    st = {b["id"]: b["issues"] for b in d["blocks"]}
    assert st["b1"] == []
    assert st["b2"] == ["tr_numbers", "tr_latin"]
    assert "tr_figno" in st["F5-b3"] and "tr_numbers" in st["F5-b3"]


def test_translation_check_survives_revalidate_and_roundtrip():
    a = _cap_aligned("図2.x", "图3.x")
    d = sd.validate(json.loads(json.dumps(sd.build("x", aligned=a))))
    assert any(p["code"] == "tr_figno" for p in d["problems"])
    assert sd.to_aligned(d) == a


def test_treatment_codes_match_booklayout_validate():
    import pytest
    from booklayout import treatments as bt
    recs = [_treat(), _treat(latin="Nereis virens Sars, 1835", block_id="p012_b01", ref=[], caption=[]),
            _treat(block_id="p013_b01", legend=["a:b"], caption=[])]
    want = sorted((i["code"], i["latin"]) for i in bt.validate(recs) if "latin" in i)
    d = sd.build("x", treatments=recs)
    got = sorted((p["code"], p["detail"]) for p in d["problems"] if p["scope"].startswith("treatment:"))
    assert got == want
    _ = pytest


def test_real_book_slice3_flags_are_counted_if_present():
    import pytest
    p = REAL[0]
    if not p.is_file():
        pytest.skip("real aligned.json not available")
    from booklayout import treatments as bt
    a = json.loads(p.read_text(encoding="utf-8"))
    recs = bt.parse(a)
    d = sd.build("imajima2009", aligned=a, treatments=recs)
    assert d["summary"]["by_type"]["treatment"] == len(recs)
    assert sd.to_aligned(d) == a
    booklayout_codes = sorted(i["code"] for i in bt.validate(recs) if "latin" in i)
    ours = sorted(pr["code"] for pr in d["problems"] if pr["scope"].startswith("treatment:"))
    assert ours == booklayout_codes
