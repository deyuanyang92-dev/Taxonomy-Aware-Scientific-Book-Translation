"""aligned.json（Fauna Ibérica 21 卷）约定的回归：分表、'•' 续支、名字+页码、误标 INDEX 行。"""
import json

from keykit.ir import from_imajima_json


def _b(role, text, **c):
    d = {"role": role, "translation": text}
    if c:
        d["couplet"] = c
    return d


def _load(tmp_path, blocks):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"pages": [{"page": 1, "blocks": blocks}]}), "utf-8")
    return from_imajima_json(p)


def test_bullet_continues_couplet_and_name_page(tmp_path):
    irs = _load(tmp_path, [
        _b("INDEX", "属的检索表"),
        _b("couplet", "甲", marker="1.", name="", target="2"),
        _b("couplet", "乙", marker="•", name="Neopetitia（第49页）", target=""),
        _b("couplet", "丙", marker="2.", name="S. gracilis", target="(p. 413)"),
        _b("couplet", "丁", marker="•", name="", target="3"),
    ])
    assert len(irs) == 1 and irs[0].heading == "属的检索表"
    c1, c2 = irs[0].couplets
    assert [ld.kind for ld in c1.leads] == ["jump", "taxon"]
    assert (c1.leads[1].target, c1.leads[1].fig) == ("Neopetitia", "（第49页）")
    assert c2.num == 2 and (c2.leads[0].target, c2.leads[0].fig) == ("S. gracilis", "(p. 413)")
    assert c2.leads[1].target == "3"


def test_split_on_number_restart(tmp_path):
    irs = _load(tmp_path, [
        _b("couplet", "a", marker="1.", name="", target="2"),
        _b("couplet", "b", marker="•", name="", target="3"),
        _b("couplet", "c", marker="2.", name="X", target=""),
        _b("couplet", "d", marker="•", name="Y", target=""),
        _b("couplet", "e", marker="1.", name="", target="2"),
        _b("couplet", "f", marker="•", name="Z", target=""),
    ])
    assert len(irs) == 2 and len(irs[0].couplets) == 2 and irs[1].couplets[0].num == 1


def test_split_on_number_gap(tmp_path):
    irs = _load(tmp_path, [
        _b("couplet", "a", marker="1.", name="", target="2"),
        _b("couplet", "b", marker="•", name="X", target=""),
        _b("couplet", "c", marker="19.", name="", target="20"),
        _b("couplet", "d", marker="•", name="Y", target=""),
    ])
    assert [[c.num for c in k.couplets] for k in irs] == [[1], [19]]


def test_misroled_index_lines_absorbed(tmp_path):
    irs = _load(tmp_path, [
        _b("couplet", "a", marker="1.", name="", target="2"),
        _b("couplet", "b", marker="•", name="", target="3"),
        _b("couplet", "c", marker="2.", name="P. a（第3页）", target=""),
        _b("couplet", "d", marker="•", name="", target="3"),
        _b("INDEX", "3. 触手体节具隆起"),
        _b("INDEX", "P. brevicirra（第281页）"),
        _b("INDEX", "• 无隆起。"),
    ])
    c3 = irs[0].couplets[2]
    assert c3.num == 3
    assert (c3.leads[0].target, c3.leads[0].fig) == ("P. brevicirra", "（第281页）")
    assert c3.leads[1].text == "无隆起。" and c3.leads[1].kind == "none"


def test_index_lead_right_after_heading(tmp_path):
    irs = _load(tmp_path, [
        _b("heading", "种的检索表"),
        _b("index", "1. 体节间沟内具乳突。"),
        _b("index", "P. papillosa（第278页）"),
        _b("couplet", "无乳突", marker="•", name="", target="2"),
    ])
    c = irs[0].couplets[0]
    assert [ld.kind for ld in c.leads] == ["taxon", "jump"]


def test_multiline_tail_block_starts_key(tmp_path):
    irs = _load(tmp_path, [
        _b("body", "7. 触手相似。\nE. (E.) verugera（第271页）\n中央触手长。\nE. (E.) dispar（第274页）"),
    ])
    c = irs[0].couplets[0]
    assert c.num == 7 and [ld.target for ld in c.leads] == ["E. (E.) verugera", "E. (E.) dispar"]


def test_dotted_continuation_gets_target(tmp_path):
    irs = _load(tmp_path, [
        _b("couplet", "a", marker="1.", name="", target="2"),
        _b("couplet", "b", marker="•", name="", target=""),
        _b("INDEX", "续文 ..... S. cruzi (p. 397)"),
    ])
    ld = irs[0].couplets[0].leads[1]
    assert ld.kind == "taxon" and (ld.target, ld.fig) == ("S. cruzi", "(p. 397)") and ld.text.endswith("续文")
