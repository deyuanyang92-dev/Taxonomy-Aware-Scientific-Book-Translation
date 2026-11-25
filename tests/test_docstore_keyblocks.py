"""docstore.keyblocks + scripts/keys_report.py（合成行框，不含书籍原文；issue #38）。"""
import json
import sys
from pathlib import Path

import pytest

from docstore import keyblocks, keys
from tests.test_docstore_keys import W, basic_page, heading, lead, parse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import keys_report  # noqa: E402


def test_blocks_one_per_couplet_with_terminals_separate():
    res = parse(basic_page())
    blocks = keyblocks.couplet_blocks(res)
    assert [b["lead"] for b in blocks] == ["1", "1'", "2", "2'"]
    assert blocks[0]["terminals"] == ["2"] and blocks[0]["id"] == "K1-p1-1"


def test_check_translation_flags_every_class():
    blocks = keyblocks.couplet_blocks(parse(basic_page()))
    good = {b["id"]: {"text": "译" + b["text"], "terminals": b["terminals"]} for b in blocks}
    assert keyblocks.check_translation(blocks, good) == []
    bad = dict(good)
    del bad["K1-p1-1'"]
    bad["K1-p1-2"] = {"text": "x", "terminals": ["Harmothoe imbricata2"]}
    bad["K9-extra"] = "x"
    codes = {(f["code"], f["id"]) for f in keyblocks.check_translation(blocks, bad)}
    assert ("missing", "K1-p1-1'") in codes and ("extra", "K9-extra") in codes
    assert ("terminal_changed", "K1-p1-2") in codes


def test_name_table_maps_taxon_terminals_and_numbers_must_survive():
    blocks = [{"id": "a", "key": 1, "lead": "1", "kind": "dash", "page": 1,
               "text": "Setae 12 pairs, Nereis virens", "terminals": ["ウロコムシ科"], "index": 0}]
    ok = {"a": {"text": "刚毛 12 对, Nereis virens", "terminals": ["Aphroditidae"]}}
    assert keyblocks.check_translation(blocks, ok, {"ウロコムシ科": "Aphroditidae"}) == []
    lost = {"a": {"text": "刚毛对", "terminals": ["Aphroditidae"]}}
    codes = [f["code"] for f in keyblocks.check_translation(blocks, lost, {"ウロコムシ科": "Aphroditidae"})]
    assert codes == ["number_lost", "latin_lost"]


def test_list_form_reports_duplicates():
    blocks = keyblocks.couplet_blocks(parse(basic_page()))
    items = [{"id": b["id"], "text": "译" + b["text"]} for b in blocks] + [{"id": blocks[0]["id"], "text": "再"}]
    assert ("duplicate", blocks[0]["id"]) in {(f["code"], f["id"]) for f in keyblocks.check_translation(blocks, items)}


def test_repair_plan_needs_why_before_apply():
    page = heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……ウロコムシ科") + lead(280, "—", "体は短く頭部がない")
    res = parse(page)
    plan = keyblocks.repair_plan(res)
    assert plan["pages_to_check"] == [1]
    assert plan["fixes"][0]["why"] == "" and plan["fixes"][0]["op"] == "set"
    with pytest.raises(keys.FixError):
        keys.apply_fixes(res, plan)
    plan["fixes"][0].update(terminals=["ウロコムシ科"], why="对照 p1 页面图像")
    keys.apply_fixes(res, {"fixes": [plan["fixes"][0]]})
    assert not [k for k in res["keys"] if k["problems"]]


def test_keys_report_before_after_on_synthetic_cache(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    page = heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……ウロコムシ科") + lead(280, "—", "体は短く頭部がない")
    (cache / "p0001.json").write_text(json.dumps({"width": W, "rows": page}), encoding="utf-8")
    fix = tmp_path / "fix.json"
    fix.write_text(json.dumps({"fixes": [{"op": "set", "page": 1, "lead": "1'", "terminals": ["ウロコムシ科"],
                                          "why": "对照页面图像"}]}), encoding="utf-8")
    r = keys_report.run_volume("syn", cache, 1, fix)
    assert r["before"]["problems"] == 1 and r["after"]["problems"] == 0 and r["fixes_applied"] == 1
    md = keys_report.to_md([r, keys_report.run_volume("x", tmp_path / "none", 1, None)], {"syn": (0, 5)})
    assert "0→0" in md or "0→" in md
    assert "跳过" in md


def test_cli_blocks_and_plan(tmp_path, capsys):
    from docstore import cli

    page = heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……ウロコムシ科") + lead(280, "—", "体は短く頭部がない")
    res = parse(page)
    f = tmp_path / "keys.json"
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    cmd = cli.cmd_keys
    ns = type("A", (), {})
    a = ns()
    a.keys_cmd, a.file, a.out = "blocks", str(f), str(tmp_path / "b.json")
    cmd(None, a)
    assert len(json.loads((tmp_path / "b.json").read_text())) == 2
    a = ns()
    a.keys_cmd, a.file, a.out, a.pdf, a.render_dir = "plan", str(f), str(tmp_path / "p.json"), None, ""
    cmd(None, a)
    assert json.loads((tmp_path / "p.json").read_text())["pages_to_check"] == [1]


def test_booklayout_renders_docstore_couplets():
    from docx import Document

    from booklayout import keymodel
    from booklayout.builder import setup

    res = parse(basic_page())
    doc = Document()
    setup(doc)
    paras = keymodel.render_key(doc, keymodel.from_docstore(res)[0])
    assert len(paras) == 5  # heading + 4 couplets
    assert [bool(p.paragraph_format.keep_with_next) for p in paras[1:]] == [True, False, True, False]
