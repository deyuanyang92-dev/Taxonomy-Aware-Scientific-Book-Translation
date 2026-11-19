"""Issue #11/#38: structured key model, multi-page fixture, alignment and rendering."""
from __future__ import annotations

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT

from booklayout import keymodel as km
from booklayout.builder import setup

SRC = """<!-- PDF p.10 -->
Some preface text of the chapter.
Key to genera of Fooidae
1. Prostomium with two eyes ........ 2
• Prostomium without eyes ........ Alpha (p. 14)
<!-- PDF p.11 -->
12 FAUNA IBERICA
2. Parapodia biramous, notopodial
cirri present ........ Beta bella (p. 20)
• Parapodia uniramous ........ 3
3. Pygidium with two anal cirri ........ Gamma longa (p. 31)
<!-- PDF p.12 -->
• Pygidium without anal cirri ........ Delta (p. 33)
Remarks. The key is artificial.
"""
TGT = """<!-- PDF p.10 -->
Clave de géneros de Fooidae
1. Prostomio con dos ojos ........ 2
• Prostomio sin ojos ........ Alpha (p. 14)
<!-- PDF p.11 -->
2. Parápodos birrámeos, con
cirros notopodiales ........ Beta bella (p. 20)
• Parápodos unirrámeos ........ 3
3. Pigidio con dos cirros anales ........ Gamma longa (p. 31)
<!-- PDF p.12 -->
• Pigidio sin cirros anales ........ Delta (p. 33)
"""


def _src():
    return km.parse_key_text(SRC)


def test_multipage_key_is_one_key_with_pages_alternates_and_wraps():
    keys = _src()
    assert len(keys) == 1
    k = keys[0]
    assert k.heading == "Key to genera of Fooidae"
    assert [b.lead for b in k.branches] == ["1", "1'", "2", "2'", "3", "3'"]
    assert [b.page for b in k.branches] == [10, 10, 11, 11, 11, 12]
    assert k.branches[2].text.startswith("Parapodia biramous, notopodial cirri present")
    assert [b.kind for b in k.branches] == ["jump", "taxon", "taxon", "jump", "taxon", "taxon"]
    assert k.closed_by == "text"  # "Remarks." ends it; running header skipped
    assert km.validate_key(k) == []


def test_validate_reports_missing_alternate_dangling_jump_and_no_target():
    bad = km.parse_key_text("1. a ........ 5\n2. b ........ Foo (p. 1)\n2'. c\n")
    msgs = km.validate_key(bad[0])
    assert any("missing alternate for 1" in m for m in msgs)
    assert any("dangling jump 5" in m for m in msgs)
    assert any("no target: 2'" in m for m in msgs)


def test_align_clean_translation_has_no_findings():
    assert km.align_keys(_src(), km.parse_key_text(TGT)) == []


def test_align_flags_missing_duplicate_changed_target_and_order():
    t = TGT.replace("• Prostomio sin ojos ........ Alpha (p. 14)\n", "")  # missing 1'
    t = t.replace("3. Pigidio", "2. Pigidio")  # duplicate 2 / lost 3
    t = t.replace("Beta bella (p. 20)", "Beta bella (p. 21)")  # page ref changed
    codes = {(f["code"], f.get("lead")) for f in km.align_keys(_src(), km.parse_key_text(t))}
    assert ("missing_branch", "1'") in codes
    assert ("duplicate_branch", "2") in codes
    assert ("missing_branch", "3") in codes
    assert ("target_changed", "2") in codes


def test_taxon_target_changed_is_detected_by_latin_name():
    t = TGT.replace("Delta (p. 33)", "Omega (p. 33)")
    f = km.align_keys(_src(), km.parse_key_text(t))
    assert [x["code"] for x in f] == ["target_changed"]


def test_blocks_roundtrip_keeps_lead_target_and_flags_empty_translation():
    keys = _src()
    blocks = km.key_blocks(keys)
    assert blocks[0]["kind"] == "heading" and blocks[1]["target"] == "2"
    tr = {b["id"]: "T:" + b["text"] for b in blocks if b["id"] != "K1-3'"}
    merged = km.merge_translation(blocks, tr)
    assert [b.target for b in merged[0].branches] == [b.target for b in keys[0].branches]
    assert km.check_merge(merged) == ["empty translation: 3' p12"]


def test_render_key_aligns_and_keeps_pairs_together():
    doc = Document()
    setup(doc)
    paras = km.render_key(doc, _src()[0])
    assert paras[0].runs[0].bold and paras[0].paragraph_format.keep_with_next
    branch_ps = paras[1:]
    assert len(branch_ps) == 6
    assert all(p.paragraph_format.keep_together for p in branch_ps)
    assert [bool(p.paragraph_format.keep_with_next) for p in branch_ps] == [True, False] * 3
    right = [t for t in branch_ps[0].paragraph_format.tab_stops if t.alignment == WD_TAB_ALIGNMENT.RIGHT]
    assert right and not branch_ps[0].paragraph_format.first_line_indent
    assert "".join(r.text for r in branch_ps[0].runs).startswith("1. Prostomium")


def test_from_docstore_matches_model():
    data = {"couplets": [{"key": 1, "lead": "1", "page": 3, "text": "a", "terminals": ["2"]},
                         {"key": 1, "lead": "1'", "page": 3, "text": "b", "terminals": ["Foo bar"]}],
            "layout": {"3": [{"t": "heading", "text": "検索", "key": 1}]}}
    k = km.from_docstore(data)[0]
    assert k.heading == "検索" and [b.kind for b in k.branches] == ["jump", "taxon"]


def test_cli_key_model_reports_alignment(tmp_path, capsys):
    import json

    from booklayout import cli

    s, t = tmp_path / "s.md", tmp_path / "t.md"
    s.write_text(SRC, encoding="utf-8")
    t.write_text(TGT.replace("Delta (p. 33)", "Omega (p. 33)"), encoding="utf-8")
    out = tmp_path / "r.json"
    rc = cli.main(["key-model", "--source", str(s), "--translation", str(t), "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 1 and rep["alignment"][0]["code"] == "target_changed" and rep["blocks"]
    t.write_text(TGT, encoding="utf-8")
    assert cli.main(["key-model", "--source", str(s), "--translation", str(t)]) == 0
