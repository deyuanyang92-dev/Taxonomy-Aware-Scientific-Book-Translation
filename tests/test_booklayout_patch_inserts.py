import copy

import pytest

from booklayout.normalize import apply_block_edits


def _data():
    return {"pages": [{"page": 5, "blocks": [
        {"block_id": "p005_b00", "role": "body", "translation": "uno"},
        {"block_id": "p005_b01", "role": "body", "translation": "tres"}]}]}


def test_insert_goes_right_after_anchor():
    d = _data()
    rep = apply_block_edits(d, {"version": 1, "edits": [], "inserts": [
        {"after_block_id": "p005_b00", "block": {"block_id": "p005_b00i", "role": "body", "translation": "dos"}}]})
    assert rep["inserted"] == ["p005_b00i"] and not rep["invalid"] and not rep["missing"]
    assert [b["translation"] for b in d["pages"][0]["blocks"]] == ["uno", "dos", "tres"]


def test_insert_before_first_block():
    d = _data()
    rep = apply_block_edits(d, {"version": 1, "edits": [], "inserts": [
        {"before_block_id": "p005_b00", "block": {"block_id": "p005_b0x", "role": "body", "translation": "cero"}}]})
    assert rep["inserted"] == ["p005_b0x"]
    assert [b["translation"] for b in d["pages"][0]["blocks"]] == ["cero", "uno", "tres"]


def test_insert_rejects_duplicate_id_and_unknown_anchor():
    d = _data()
    before = copy.deepcopy(d)
    rep = apply_block_edits(d, {"version": 1, "edits": [], "inserts": [
        {"after_block_id": "p005_b00", "block": {"block_id": "p005_b01", "role": "body", "translation": "x"}},
        {"after_block_id": "nope", "block": {"block_id": "p005_b09", "role": "body", "translation": "x"}}]})
    assert rep["inserted"] == [] and rep["missing"] == ["nope"] and len(rep["invalid"]) == 1
    assert d == before


def test_insert_must_be_array():
    with pytest.raises(ValueError):
        apply_block_edits(_data(), {"version": 1, "edits": [], "inserts": {}})
