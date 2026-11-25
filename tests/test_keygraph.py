"""Tests for booklayout.keygraph (generic dichotomous-key graph layer)."""
from __future__ import annotations

import json

import pytest

from booklayout import keygraph as kg


def one(md: str) -> kg.GKey:
    keys = kg.parse_text(md)
    assert len(keys) == 1, keys
    return keys[0]


def codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


def leads(k: kg.GKey) -> list[str]:
    return [b.lead for b in k.branches]


# ---- norm_lead: every numbering format

@pytest.mark.parametrize("raw,prev,expect", [
    ("1.", None, ("1", "", None)),
    ("1", None, ("1", "", None)),
    ("1'", None, ("1", "b", None)),
    ("1′", None, ("1", "b", None)),
    ("1’", None, ("1", "b", None)),
    ("1a", None, ("1", "a", None)),
    ("1b", None, ("1", "b", None)),
    ("1A", None, ("1", "a", None)),
    ("1B", None, ("1", "b", None)),
    ("1(3)", None, ("1", "", "3")),
    ("1a(3)", None, ("1", "a", "3")),
    ("—", "4", ("4", "+", None)),
    ("-", "4", ("4", "+", None)),
    ("•", "4", ("4", "+", None)),
    ("１．", None, ("1", "", None)),
    ("１ａ", None, ("1", "a", None)),
    ("II.", None, ("2", "", None)),
    ("I'.", None, ("1", "b", None)),
])
def test_norm_lead_formats(raw, prev, expect):
    assert kg.norm_lead(raw, prev) == expect


@pytest.mark.parametrize("raw,prev", [("—", None), ("", "1"), ("abc", "1"), ("1.5", None)])
def test_norm_lead_none(raw, prev):
    assert kg.norm_lead(raw, prev) is None


# ---- parse_target

@pytest.mark.parametrize("s,kind,jump,page,taxon", [
    ("5", "jump", "5", None, ""),
    ("5'", "jump", "5", None, ""),
    ("5-6", "jump", "5", None, ""),
    ("5–6", "jump", "5", None, ""),
    ("(p. 76)", "page", None, 76, ""),
    ("p. 76", "page", None, 76, ""),
    ("pp. 76-78", "page", None, 76, ""),
    ("S. 12", "page", None, 12, ""),
    ("pág. 3", "page", None, 3, ""),
    ("第12页", "page", None, 12, ""),
    ("12頁", "page", None, 12, ""),
    ("Nereis pelagica (p. 76)", "taxon", None, 76, "Nereis pelagica"),
    ("Nereis pelagica", "taxon", None, None, "Nereis pelagica"),
    ("Nereis sp. 3", "taxon", None, None, "Nereis sp. 3"),
    ("", "none", None, None, ""),
    ("....", "none", None, None, ""),
])
def test_parse_target(s, kind, jump, page, taxon):
    t = kg.parse_target(s)
    assert (t.kind, t.jump, t.page, t.taxon) == (kind, jump, page, taxon)
    assert tuple(t)[0] == kind  # tuple-like


# ---- parse_text numbering styles

def test_prime_style():
    k = one("Key to genera\n1. Body long ........ 2\n1'. Body short ........ Nereis (p. 76)\n"
            "2. Eyes ........ Aus bus\n2'. No eyes ........ Cus dus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]
    assert [b.kind for b in k.branches] == ["jump", "taxon", "taxon", "taxon"]
    assert k.branches[1].page == 76
    assert k.heading == "Key to genera"


def test_ab_style_and_polytomy():
    k = one("Key to genera\n1a Foo ... 2\n1b Bar ... 3\n1c Baz ... Aus bus\n2a x ... Cus dus\n2b y ... Eus fus\n"
            "3a q ... Gus hus\n3b r ... Ius jus\n")
    assert leads(k)[:3] == ["1a", "1b", "1c"]
    assert not codes(kg.check(k))


def test_uppercase_ab():
    k = one("Key to genera\n1A Foo ... 2\n1B Bar ... Aus bus\n2A x ... Cus dus\n2B y ... Eus fus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]


def test_dash_and_bullet_alternates():
    k = one("Key to genera\n1. Foo ... 2\n— Bar ... Aus bus\n2. x ... Cus dus\n• y ... Eus fus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]


def test_backref_style():
    k = one("Key to genera\n1(3) Foo ... Aus bus\n1'(3) Bar ... Cus dus\n2(3) x ... Eus fus\n2'(3) y ... Gus hus\n"
            "3. Z ... 1\n3'. W ... 2\n")
    assert [b.backref for b in k.branches][:2] == ["3", "3"]
    assert leads(k)[:2] == ["1a", "1b"]
    assert kg.check(k, entries=["3"]) == []


def test_fullwidth_digits():
    k = one("Key to genera\n１． Foo ... ２\n１′． Bar ... Aus bus\n２． x ... Cus dus\n２′． y ... Eus fus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]
    assert k.branches[0].jump == "2"


def test_bare_numbers_no_punct():
    k = one("Key to genera\n1 Foo ... 2\n1' Bar ... Aus bus\n2 x ... Cus dus\n2' y ... Eus fus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]


def test_roman_couplets():
    k = one("Key to genera\nI. Foo ... II\nI'. Bar ... Aus bus\nII. x ... Cus dus\nII'. y ... Eus fus\n")
    assert leads(k) == ["1a", "1b", "2a", "2b"]
    assert k.branches[0].jump == "2"


# ---- layout robustness

def test_cross_page_and_header_skipped():
    md = ("Key to genera\n1. Foo ... 2\n1'. Bar ... Aus bus\n<!-- PDF p.12 -->\n45 NEREIDIDAE\n"
          "2. x ... Cus dus\n2'. y ... Eus fus\n12\n<!-- PDF p.13 -->\nBody text resumes here.\n")
    k = one(md)
    assert leads(k) == ["1a", "1b", "2a", "2b"]
    assert [b.src_page for b in k.branches] == [0, 0, 12, 12]


def test_wrapped_lines():
    k = one("Key to genera\n1. Body very long and\n   composed of many\n   segments ........ 2\n"
            "1'. Body short ........ Aus bus\n2. x ... Cus dus\n2'. y ... Eus fus\n")
    assert k.branches[0].text == "Body very long and composed of many segments"
    assert k.branches[0].jump == "2"


def test_target_on_next_line():
    k = one("Key to genera\n1. Body very long ......\n2\n1'. Body short ..........\nAus bus (p. 4)\n"
            "2. x ... Cus dus\n2'. y ... Eus fus\n")
    assert k.branches[0].jump == "2"
    assert k.branches[1].kind == "taxon" and k.branches[1].page == 4


def test_no_leader_trailing_number():
    k = one("Key to genera\n1. Body long 2\n1'. Body short Aus bus (p. 5)\n2. x 3\n2'. y 4\n")
    assert [b.jump for b in k.branches][:1] == ["2"]


def test_markdown_table():
    md = "Key to genera\n\n| No. | Character | Go to |\n|---|---|---|\n| 1 | Long | 2 |\n| 1' | Short | Aus bus (p. 3) |\n" \
         "| 2 | x | Cus dus |\n| 2' | y | Eus fus |\n\nText after.\n"
    k = one(md)
    assert leads(k) == ["1a", "1b", "2a", "2b"]
    assert k.branches[1].kind == "taxon" and k.branches[1].page == 3


def test_indented_style():
    md = ("Key to genera\n"
          "Eyes present\n"
          "    Legs long ........ Aus bus\n"
          "    Legs short ........ Cus dus\n"
          "Eyes absent\n"
          "    Foot simple ........ Eus fus\n"
          "    Foot forked ........ Gus hus\n"
          "\nBody text after the key.\n")
    k = one(md)
    cp = sorted({b.couplet for b in k.branches})
    assert cp == ["1", "2", "3"]
    top = [b for b in k.branches if b.couplet == "1"]
    assert [b.alt for b in top] == ["a", "b"]
    assert {b.jump for b in top} == {"2", "3"}
    assert not codes(kg.check(k))


def test_letter_pairs_with_indented_children():
    k = one("Key to conifers\nA. Needles in bundles ........ Pinus\nAA. Needles solitary\n"
            "    B. Pegs ........ Picea\n    BB. Scars ........ Abies\n")
    assert [(b.lead, b.kind) for b in k.branches] == [("1a", "taxon"), ("1b", "jump"), ("2a", "taxon"), ("2b", "taxon")]
    assert k.branches[1].jump == "2" and kg.check(k) == []


def test_letter_pairs_lone_letter_jump():
    k = one("Key to conifers\nA. Bundles ........ Pinus\naa. Solitary ........ B\nB. Pegs ........ Picea\n"
            "bb. Scars ........ Abies\n")
    assert [(b.lead, b.kind, b.jump) for b in k.branches][1] == ("1b", "jump", "2")
    assert kg.check(k) == []


def test_running_head_uppercase_after_page_break():
    k = one("<!-- PDF p.41 -->\nKey to conifers\n1. Bundles ........ Pinus\n<!-- PDF p.42 -->\n"
            "CONIFERS OF THE VALLEY\n42\n1’. Solitary ........ Picea\n")
    assert leads(k) == ["1a", "1b"]


def test_taxon_target_excludes_page_and_figure():
    k = one("Key\n1. a ... Pinus sylvestris (p. 12)\n1'. b ... Pinus strobus (p. 18)\n")
    assert [b.target for b in k.branches] == ["Pinus sylvestris", "Pinus strobus"]
    assert [b.page for b in k.branches] == [12, 18]
    for fig in ["図3 Pinus", "图3 Pinus", "Fig. 3 Pinus", "Figs 3-4 Pinus", "рис. 3 Pinus", "Abb. 3 Pinus",
                "fig. 3 Pinus", "Pinus (Fig. 3)"]:
        assert kg.parse_target(fig).taxon == "Pinus", fig


def test_lost_glyph_table_is_not_a_key():
    md = "Таблица для определения\n□ │ □□□ … □\n□ └ □□□ … □\n"
    ks = kg.parse_text(md)
    assert [len(k.branches) for k in ks] == [0]  # heading kept as an empty key
    assert [f["code"] for f in kg.check(ks[0])] == ["empty_key"]


def test_only_alternate_reports_both_codes():
    k = one("Key\n1'. b ... Aus bus\n")
    assert {"single_branch", "lone_alternate"} <= codes(kg.check(k))


def test_two_keys_same_page_new_heading():
    md = ("Key to genera A\n1. a ... Aus bus\n1'. b ... Cus dus\nKey to species B\n1. c ... Eus fus\n"
          "1'. d ... Gus hus\n")
    assert len(kg.parse_text(md)) == 2


def test_two_keys_same_page_numbering_restart():
    md = ("Key to genera\n1. a ... 2\n1'. b ... Aus bus\n2. c ... Cus dus\n2'. d ... Eus fus\n"
          "1. e ... Gus hus\n1'. f ... Ius jus\n")
    ks = kg.parse_text(md)
    assert len(ks) == 2 and len(ks[1].branches) == 2


def test_key_ends_at_body_text():
    k = one("Key to genera\n1. a ... Aus bus\n1'. b ... Cus dus\nThe genus Aus is common in the Atlantic.\n"
            "More prose follows here.\n")
    assert len(k.branches) == 2


def test_no_key_in_prose():
    assert kg.parse_text("Just a paragraph.\nAnother one with 3 mm length.\n") == []


def test_continued_heading_not_split():
    md = ("Key to genera\n1. a ... 2\n1'. b ... Aus bus\n<!-- PDF p.5 -->\nKey to genera (continued)\n"
          "2. c ... Cus dus\n2'. d ... Eus fus\n")
    assert len(one(md).branches) == 4


# ---- seven languages of headings

@pytest.mark.parametrize("heading", [
    "Key to the genera", "属の検索表", "分属检索表", "Определительная таблица родов", "Ключ для определения",
    "Clé des genres", "Bestimmungsschlüssel der Gattungen", "Clave de géneros", "Clavis generum",
])
def test_headings_in_languages(heading):
    k = one(f"{heading}\n1. a ... Aus bus\n1'. b ... Cus dus\n")
    assert k.heading == heading


def test_heading_regexes_directly():
    for h in ["Key to X", "検索", "检索表", "Таблица", "Ключ", "Clé", "Bestimmungsschl", "Clave", "Clavis"]:
        assert kg.HEADING_RE.match(h), h
    assert not kg.HEADING_RE.match("The monkey sat down.")


def test_custom_heading_re():
    import re
    ks = kg.parse_text("MY TABLE\n1. a ... Aus bus\n1'. b ... Cus dus\n", re.compile(r"MY TABLE"))
    assert ks[0].heading == "MY TABLE"


# ---- check: problem codes, 1 positive + 1 negative each

GOOD = "Key\n1. a ... 2\n1'. b ... Aus bus\n2. c ... Cus dus\n2'. d ... Eus fus\n"


def test_good_key_clean():
    assert kg.check(one(GOOD)) == []


def test_single_branch():
    assert "single_branch" in codes(kg.check(one("Key\n1. a ... 2\n1'. b ... Aus bus\n2. c ... Cus dus\n")))
    assert "single_branch" not in codes(kg.check(one(GOOD)))


def test_lone_alternate():
    k = one("Key\n1. a ... 2\n1'. b ... Aus bus\n2'. c ... Cus dus\n2b. d ... Eus fus\n")
    assert "lone_alternate" in codes(kg.check(k))
    assert "lone_alternate" not in codes(kg.check(one(GOOD)))


def test_duplicate_lead():
    k = one("Key\n1a x ... 2\n1a y ... Aus bus\n2a c ... Cus dus\n2b d ... Eus fus\n")
    assert "duplicate_lead" in codes(kg.check(k))
    assert "duplicate_lead" not in codes(kg.check(one(GOOD)))


def test_plain_repeat_gets_alts_not_duplicate():
    k = one("Key\n1. x ... Aus bus\n1. y ... Cus dus\n")
    assert leads(k) == ["1a", "1b"] and "duplicate_lead" not in codes(kg.check(k))


def test_no_target():
    k = one("Key\n1. a ... 2\n1'. b ...\n2. c ... Cus dus\n2'. d ... Eus fus\n")
    assert "no_target" in codes(kg.check(k))
    assert "no_target" not in codes(kg.check(one(GOOD)))


def test_dangling_jump():
    k = one("Key\n1. a ... 9\n1'. b ... Aus bus\n")
    assert "dangling_jump" in codes(kg.check(k))
    assert "dangling_jump" not in codes(kg.check(one(GOOD)))


def test_unreachable_default_and_declared_entries():
    md = "Key\n1. a ... Aus bus\n1'. b ... Cus dus\n5. c ... Eus fus\n5'. d ... Gus hus\n"
    k = one(md)
    assert "unreachable" in codes(kg.check(k))
    assert "unreachable" not in codes(kg.check(k, entries=["1", "5"]))
    assert "unreachable" not in codes(kg.check(one(GOOD)))


def test_cycle_with_path():
    k = one("Key\n1. a ... 2\n1'. b ... Aus bus\n2. c ... 3\n2'. d ... Cus dus\n3. e ... 2\n3'. f ... Eus fus\n")
    cy = [f for f in kg.check(k) if f["code"] == "cycle"]
    assert cy and "2>3>2" in cy[0]["detail"]
    assert "cycle" not in codes(kg.check(one(GOOD)))


def test_backward_jump_without_cycle_ok():
    k = one("Key\n1. a ... 3\n1'. b ... 2\n2. c ... Aus bus\n2'. d ... Cus dus\n3. e ... 2\n3'. f ... Eus fus\n")
    f = kg.check(k)
    assert "cycle" not in codes(f)
    assert {x["severity"] for x in f if x["code"] == "multi_parent"} <= {"warn"}


def test_multi_parent_is_warn_only():
    k = one("Key\n1. a ... 3\n1'. b ... 2\n2. c ... 3\n2'. d ... Aus bus\n3. e ... Cus dus\n3'. f ... Eus fus\n")
    mp = [f for f in kg.check(k) if f["code"] == "multi_parent"]
    assert mp and mp[0]["severity"] == "warn"
    assert not [f for f in kg.check(one(GOOD)) if f["code"] == "multi_parent"]


def test_backref_mismatch():
    bad = one("Key\n1(3) a ... Aus bus\n1'(3) b ... Cus dus\n2. x ... 1\n2'. y ... Eus fus\n3. z ... 2\n3'. w ... Gus hus\n")
    assert "backref_mismatch" in codes(kg.check(bad))
    ok = one("Key\n1. a ... 3\n1'. b ... 2\n2(1) c ... Aus bus\n2'(1) d ... Cus dus\n3(1) e ... Eus fus\n3'(1) f ... Gus hus\n")
    assert "backref_mismatch" not in codes(kg.check(ok))


# ---- align

SRC = "Key\n1. a ... 2\n1'. b ... Nereis pelagica (p. 76)\n2. c ... Aus bus\n2'. d ... Cus dus\n"


def al(tgt: str) -> set[str]:
    return codes(kg.align(kg.parse_text(SRC), kg.parse_text(tgt)))


def test_align_identical():
    assert al(SRC.replace("a ...", "甲 ...")) == set()


def test_key_count():
    assert "key_count" in al(SRC + "Key\n1. x ... Aus bus\n1'. y ... Cus dus\n")


def test_missing_and_extra_branch():
    assert "missing_branch" in al("Key\n1. a ... 2\n1'. b ... Nereis pelagica (p. 76)\n2. c ... Aus bus\n")
    assert "extra_branch" in al(SRC + "2c. e ... Eus fus\n")
    assert "missing_branch" not in al(SRC)


def test_target_changed_variants():
    assert "target_changed" in al(SRC.replace("... 2\n", "... 3\n"))  # jump number
    assert "target_changed" in al(SRC.replace("(p. 76)", "(p. 77)"))  # page
    assert "target_changed" in al(SRC.replace("Nereis pelagica", "Nereis"))  # species -> genus
    assert "target_changed" in al(SRC.replace("Nereis pelagica (p. 76)", "沙蚕 (p. 76)"))  # name -> Chinese
    assert "target_changed" in al(SRC.replace("Aus bus", "Aus bus 5"))  # extra digits
    assert "target_changed" in al(SRC.replace("... 2\n", "... Aus bus\n"))  # kind changed
    assert "target_changed" not in al(SRC)


def test_order_changed():
    tgt = "Key\n1'. b ... Nereis pelagica (p. 76)\n1. a ... 2\n2. c ... Aus bus\n2'. d ... Cus dus\n"
    assert "order_changed" in al(tgt)
    assert "order_changed" not in al(SRC)


def test_latin_names_never_empty_match():
    assert kg.latin_names("") == []
    assert kg.latin_names("沙蚕 12") == []
    assert kg.latin_names("N. pelagica and Nereis virens") == ["N. pelagica", "Nereis virens"]


# ---- gate and CLI

def test_gate():
    assert codes(kg.gate([], True)) == {"no_keys"}
    assert kg.gate([], False) == []
    assert kg.gate(kg.parse_text(GOOD), True) == []


def test_cli(tmp_path, capsys):
    a = tmp_path / "a.md"
    a.write_text("Key\n1. a ... 9\n1'. b ... Aus bus\n", encoding="utf-8")
    out = tmp_path / "r.json"
    assert kg.main(["--source", str(a), "--out", str(out)]) == 1
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["findings"][0]["code"] == "dangling_jump"
    b = tmp_path / "b.md"
    b.write_text(GOOD, encoding="utf-8")
    assert kg.main(["--source", str(b)]) == 0
    assert kg.main(["--source", str(b), "--translation", str(b), "--entries", "1"]) == 0
    c = tmp_path / "c.md"
    c.write_text("nothing\n", encoding="utf-8")
    assert kg.main(["--source", str(c), "--expect-keys"]) == 1
    assert kg.main(["--source", str(c)]) == 0
    capsys.readouterr()


# ---------------------------------------------------------------- round 2


def _br(md: str) -> list[tuple[str, str, str]]:
    ks = kg.parse_text(md)
    return [(b.lead, b.kind, b.jump or b.target) for k in ks for b in k.branches]


def test_taxon_keeps_trinomial_and_rank_epithet():
    assert kg.parse_target("Larus argentatus michahellis Naumann").taxon == "Larus argentatus michahellis"
    assert kg.parse_target("Rosa canina var. glauca Pourr.").taxon == "Rosa canina var. glauca"
    assert kg.parse_target("Rosa cf. canina").taxon == "Rosa cf. canina"
    assert kg.latin_names("Larus argentatus michahellis") == ["Larus argentatus michahellis"]


def test_taxon_strips_authority_year_part_and_botanical():
    assert kg.parse_target("Aphrodita aculeata Linnaeus, 1758").taxon == "Aphrodita aculeata"
    assert kg.parse_target("Aphrodita aculeata (Grube, 1850)").taxon == "Aphrodita aculeata"
    assert kg.parse_target("Poa annua L.").taxon == "Poa annua"
    assert kg.parse_target("Carex acuta Hook. f.").taxon == "Carex acuta"
    assert kg.parse_target("Nereididae (part)").taxon == "Nereididae"
    assert kg.parse_target("Nereis sp.").taxon == "Nereis sp."
    assert kg.parse_target("Nereis spp.").taxon == "Nereis spp."


def test_compact_lead_cjk_and_cyrillic_letters():
    md = "检索表\n１ａ．触角长……甲\n１ｂ．触角短……乙\n"
    assert _br(md) == [("1a", "taxon", "甲"), ("1b", "taxon", "乙")]
    md = "Определитель\n1а. Усики длинные ...... Alpha\n1б. Усики короткие ...... Beta\n"
    assert _br(md) == [("1a", "taxon", "Alpha"), ("1b", "taxon", "Beta")]


def test_sparse_numbering_follows_explicit_jump():
    md = "Key\n1 Legs long ...... 7\n— Legs short ...... Alpha\n7 Wings clear ...... Beta\n— Wings dark ...... Gamma\n"
    ks = kg.parse_text(md)
    assert [b.lead for b in ks[0].branches] == ["1a", "1b", "7a", "7b"]
    assert not [f for f in kg.check(ks[0]) if f["severity"] == "error"]


def test_bare_trailing_number_is_jump_only_if_couplet_exists():
    md = "Key\n1a. Body with 40 segments, tail at segment 9\n1b. Body short ...... Alpha\n"
    ks = kg.parse_text(md)
    assert ks[0].branches[0].kind == "none"
    assert "no_target" in {f["code"] for f in kg.check(ks[0])}
    ks2 = kg.parse_text("Key\n1a. Tail as drawn, see Fig. 4\n1b. Short ...... Alpha\n")
    assert ks2[0].branches[0].kind == "none"


def test_wrapped_lead_like_number_and_wrapped_epithet():
    md = "Key\n1a. Anterior limbs with\n3 claws each ...... Alpha\n1b. Limbs smooth ...... Beta\n"
    assert _br(md) == [("1a", "taxon", "Alpha"), ("1b", "taxon", "Beta")]
    md = "Key\n1a. Spines fused ...... P.\nlongicauda\n1b. Spines free ...... Pagurus\n"
    assert _br(md) == [("1a", "taxon", "P. longicauda"), ("1b", "taxon", "Pagurus")]
    md = "Key\n1a. Bands present ...... Vanessa cardui\nkershawi\n1b. Bands absent ...... Vanessa\n"
    assert _br(md)[0] == ("1a", "taxon", "Vanessa cardui kershawi")


def test_ocr_prime_as_digit_or_ell_and_inline_page_marker():
    md = "Key\n1. Hairy ...... 2\n11. Bald ...... Alpha\n2. Red ...... Beta\n2'. Blue ...... Gamma\n"
    assert [b[0] for b in _br(md)] == ["1a", "1b", "2a", "2b"]
    md = "Key\n1. Hairy ...... Alpha\n1l. Bald ...... Beta\n"
    assert [b[0] for b in _br(md)] == ["1a", "1b"]
    md = "<!-- PDF p.3 -->1a. Hairy ...... Alpha\n1b. Bald ...... Beta\n"
    assert [b[0] for b in _br(md)] == ["1a", "1b"]


def test_page_end_number_is_target_when_next_page_continues_key():
    md = "Key\n1a. Gills present\n4\n<!-- PDF p.2 -->\n1b. Gills absent ...... Alpha\n4a. Jaws ...... Beta\n4b. No jaws ...... Gamma\n"
    ks = kg.parse_text(md)
    assert (ks[0].branches[0].kind, ks[0].branches[0].jump) == ("jump", "4")


def test_table_columns_by_header_and_continuation_target():
    md = "| No | Character | Taxon | Page |\n| 1a | long | Alpha | p. 5 |\n| 1b | short | Beta | p. 9 |\n"
    ks = kg.parse_text(md)
    assert [(b.target, b.page) for b in ks[0].branches] == [("Alpha", 5), ("Beta", 9)]
    md = "| 1a | Simple | |\n| | entirely | Gamma (p. 7) |\n| 1b | Branched | Delta |\n"
    assert kg.parse_text(md)[0].branches[0].target == "Gamma"
    assert kg.parse_target("12ページ").kind == "page"


def test_paired_numbering_bracket_is_opposite_lead():
    md = (
        "### Key to genera\n"
        "1(4) Body long\n"
        "2(3) Eyes absent ..... 1. Genus *Alpha* Smith\n"
        "3(2) Eyes present ..... 2. Genus *Beta* Jones\n"
        "4(1) Body short ..... 3. Genus *Gamma* Lee\n"
    )
    ks = kg.parse_text(md)
    assert [(b.lead, b.kind, b.jump or b.target) for b in ks[0].branches] == [
        ("1a", "jump", "2"), ("2a", "taxon", "Alpha"), ("2b", "taxon", "Beta"), ("1b", "taxon", "Gamma")]
    assert kg.check(ks[0]) == []


def test_paired_numbering_not_used_for_backref_style():
    md = "Key\n1 Wings ...... 2\n1 No wings ...... 3\n2(1) Red ...... Alpha\n2 Blue ...... Beta\n3(1) Big ...... Gamma\n3 Small ...... Delta\n"
    ks = kg.parse_text(md)
    assert not [f for f in kg.check(ks[0]) if f["code"] == "backref_mismatch"]


def test_serial_prefixed_target_without_leader_after_dash():
    md = "### Key\n1(2) Spines long\n2(1) Spines short—3. Genus *Omega* Kin\n"
    ks = kg.parse_text(md)
    assert [b.target for b in ks[0].branches][-1] == "Omega"


# ---------------------------------------------------------------- round 3

def test_count_noun_trailing_number_is_not_jump():
    md = "Key\n1a. Antennae 3 ...... 2\n1b. Antennae absent ...... Alpha\n2a. With 5 segments 4\n2b. Fewer ...... Beta\n"
    ks = kg.parse_text(md)
    assert (ks[0].branches[2].kind, ks[0].branches[2].text.endswith("4")) == ("none", True)


def test_hanging_indent_line_joins_previous_branch():
    md = "Key to stems\nStems hairy\n    Hairs very\n        long ...... p. 3\n    Hairs short ...... p. 4\nStems bare ...... p. 5\n"
    ks = kg.parse_text(md)
    assert len(ks) == 1 and [b.page for b in ks[0].branches if b.page] == [3, 4, 5]


def test_chinese_rank_words_stripped_from_target():
    for t in ["3. 科 Nereididae Blainville, 1818", "属 Nereis Linnaeus", "亚科 Polynoinae Kinberg"]:
        assert kg.parse_target(t).taxon.split()[0] in {"Nereididae", "Nereis", "Polynoinae"}, t


def test_closed_paired_key_restarts_at_one():
    md = "1(2) Short ..... Alpha\n2(1) Long ..... Beta\n\n1(2) Red ..... Gamma\n2(1) Blue ..... Delta\n"
    assert len(kg.parse_text(md)) == 2


def test_serial_taxon_without_leader_and_page():
    md = "Key\n1a. Soft body 7. Genus Alpha Smith, 1900 (p. 31)\n1b. Hard body 8. Beta gamma (Jones, 1901)\n"
    ks = kg.parse_text(md)
    assert [b.target for b in ks[0].branches] == ["Alpha", "Beta gamma"]
    assert ks[0].branches[0].page == 31


def test_two_letter_epithet_kept_and_change_reported():
    src = kg.parse_text("1a. Long ...... Ia io\n1b. Short ...... Myotis myotis\n")
    tgt = kg.parse_text("1a. Lang ...... Ia xx\n1b. Kurz ...... Myotis myotis\n")
    assert src[0].branches[0].target == "Ia io"
    assert "target_changed" in codes(kg.align(src, tgt))


def test_full_genus_then_epithet_line_merges():
    ks = kg.parse_text("Key\n1a. Spotted ...... Phyllodoce\nmucosa\n1b. Smooth ...... Eteone\n")
    assert [b.target for b in ks[0].branches] == ["Phyllodoce mucosa", "Eteone"]


def test_empty_key_reported():
    ks = kg.parse_text("Key to genera\n\nSee plate.\n")
    assert [k.heading for k in ks] == ["Key to genera"]
    f = kg.check(ks[0])
    assert [(x["code"], x["severity"]) for x in f] == [("empty_key", "error")]
