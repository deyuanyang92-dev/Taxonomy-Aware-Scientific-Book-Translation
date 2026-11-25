"""Issue #16: paragraph and heading structure across page boundaries."""
from __future__ import annotations

import copy
import re
from collections import Counter

from booklayout.normalize import normalize_aligned
from booklayout.structure import uncertain_boundaries


def words(data: dict) -> Counter:
    return Counter(
        w for p in data["pages"] for b in p["blocks"]
        for w in re.findall(r"\w+", b.get("translation") or "")
    )


def fixture() -> dict:
    return {"pages": [
        {"page": 1, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "h1", "role": "heading", "translation": "Family Alphidae"},
            {"block_id": "p1", "role": "body", "translation": "Specimens were collected from"},
            {"block_id": "f1", "role": "caption", "translation": "Fig. 1. Habitat."},
        ]},
        {"page": 2, "chapter": "C", "kind": "body", "blocks": [
            {"block_id": "f2", "role": "caption", "translation": "Fig. 2. Mid-sentence figure."},
            {"block_id": "p2", "role": "body", "translation": "rocky shores at low tide."},
            {"block_id": "h2", "role": "heading", "translation": "Family Betidae"},
            {"block_id": "p3", "role": "body", "translation": "Body elongate."},
        ]},
    ]}


def test_paragraph_joins_across_page_break_with_intervening_figures() -> None:
    data = fixture()
    before = words(data)
    normalize_aligned(data)
    p1, p2 = data["pages"]
    assert p1["blocks"][1]["translation"] == (
        "Specimens were collected from rocky shores at low tide.")
    assert [b["block_id"] for b in p2["blocks"]] == ["f2", "h2", "p3"]
    assert [b["block_id"] for b in p1["blocks"]] == ["h1", "p1", "f1"]
    # nothing lost, nothing duplicated, heading kept in place
    assert words(data) == before
    assert p2["blocks"][1]["translation"] == "Family Betidae"


def test_new_heading_midpage_keeps_its_own_paragraph() -> None:
    data = fixture()
    normalize_aligned(data)
    assert data["pages"][1]["blocks"][-1]["translation"] == "Body elongate."


def test_uncertain_when_fragment_is_followed_by_capitalised_body() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "blocks": [
            {"block_id": "a", "role": "body", "translation": "The setae are long and"}]},
        {"page": 2, "chapter": "C", "blocks": [
            {"block_id": "b", "role": "body", "translation": "Pygidium with two cirri."}]},
    ]}
    found = uncertain_boundaries(data)
    assert [(f["page"], f["reason"]) for f in found] == [(1, "unfinished_before_capital")]


def test_uncertain_when_unfinished_paragraph_precedes_heading() -> None:
    data = {"pages": [
        {"page": 1, "chapter": "C", "blocks": [
            {"block_id": "a", "role": "body", "translation": "The setae are long and"}]},
        {"page": 2, "chapter": "C", "blocks": [
            {"block_id": "b", "role": "heading", "translation": "Family Betidae"}]},
    ]}
    assert uncertain_boundaries(data)[0]["reason"] == "unfinished_before_heading"


def test_clean_and_reviewed_boundaries_are_not_reported() -> None:
    data = fixture()
    normalize_aligned(data)
    assert uncertain_boundaries(data) == []
    data2 = {"pages": [
        {"page": 1, "chapter": "C", "blocks": [
            {"block_id": "a", "role": "body", "translation": "Ends without stop",
             "boundary_reviewed": True}]},
        {"page": 2, "chapter": "C", "blocks": [
            {"block_id": "b", "role": "body", "translation": "New paragraph."}]},
    ]}
    assert uncertain_boundaries(data2) == []


def test_whole_page_in_one_block_is_flagged() -> None:
    data = {"pages": [{"page": 1, "chapter": "C", "blocks": [
        {"block_id": "a", "role": "body", "translation": "word " * 500}]}]}
    assert [f["reason"] for f in uncertain_boundaries(data)] == ["page_is_single_block"]


def test_normalize_is_idempotent_and_lossless() -> None:
    data = fixture()
    normalize_aligned(data)
    snap = copy.deepcopy(data)
    normalize_aligned(data)
    assert data == snap


def test_check_command_blocks_release_on_uncertain_boundary(tmp_path) -> None:
    import json
    from pathlib import Path

    from booklayout.cli import main
    from tests.test_booklayout import make_book

    aligned, figs, _ = make_book(Path(tmp_path))
    data = json.loads(aligned.read_text(encoding="utf-8"))
    data["pages"][0]["blocks"][1]["translation"] = "Unfinished sentence without stop"
    data["pages"][1]["chapter"] = data["pages"][0]["chapter"]
    data["pages"][1]["blocks"].insert(0, {"role": "heading", "translation": "Family X", "y0": 1})
    aligned.write_text(json.dumps(data), encoding="utf-8")
    out = Path(tmp_path) / "report.json"
    rc = main(["check", "--aligned", str(aligned), "--figures", str(figs), "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 1
    assert report["uncertain_boundaries"]
    assert any("uncertain paragraph boundaries" in p for p in report["problems"])
