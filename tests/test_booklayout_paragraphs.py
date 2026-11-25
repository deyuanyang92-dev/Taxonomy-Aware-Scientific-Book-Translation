"""Issue #37: JA continuation lines, multi-entry references, kana residue."""
from __future__ import annotations

from booklayout.normalize import normalize_aligned
from booklayout.paragraphs import (
    kana_residue, merge_continuation_paragraphs, split_reference_entries)


def test_p5_latin_lines_merge_into_one_paragraph() -> None:
    paras = [
        "分類—ウロコムシ科は多くの属を含み Lepidas",
        "theniinae などを含む。",
        "日本における研究は Imajima &",
        "Hartman (1964)",
        "に始まる。",
        "日本における分布。",
    ]
    out = merge_continuation_paragraphs(paras)
    assert out == [
        "分類—ウロコムシ科は多くの属を含み Lepidas theniinae などを含む。",
        "日本における研究は Imajima & Hartman (1964)に始まる。",
        "日本における分布。",
    ]


def test_comma_year_continuation_merges() -> None:
    out = merge_continuation_paragraphs(["Polynoe scolopendrina Savigny, 1818 (1938,", "1939, 1940)。"])
    assert len(out) == 1


def test_heading_and_numbered_not_merged() -> None:
    paras = ["## 科", "本文は続く", "1. 次の項目"]
    assert merge_continuation_paragraphs(paras) == paras


def test_split_reference_entries() -> None:
    t = "32. Imajima, M. 1966. Fauna Japonica 4: 1-10. 40. Hartman, O. 1959. Cat. 3: 5-9."
    assert split_reference_entries(t) == [
        "32. Imajima, M. 1966. Fauna Japonica 4: 1-10.",
        "40. Hartman, O. 1959. Cat. 3: 5-9."]
    t2 = "173' Foo, A. 1900. X. 175. Bar, B. 1901. Y."
    assert len(split_reference_entries(t2)) == 2


def test_split_reference_keeps_single_and_no_false_split() -> None:
    t = "57. Foo, A. 1938. Bull. No. 12. Tokyo 5: 1-3."
    assert split_reference_entries(t) == [t]
    assert split_reference_entries("Foo 1999. 2000. Bar") == ["Foo 1999. 2000. Bar"]


def test_normalize_splits_ref_block() -> None:
    data = {"pages": [{"page": 294, "chapter": "R", "blocks": [
        {"block_id": "r1", "role": "ref",
         "text": "32. A. 1900. X. 40. B. 1901. Y.",
         "translation": "32. A. 1900. X. 40. B. 1901. Y."}]}]}
    normalize_aligned(data)
    blocks = data["pages"][0]["blocks"]
    assert [b["translation"] for b in blocks] == ["32. A. 1900. X.", "40. B. 1901. Y."]
    assert [b["role"] for b in blocks] == ["ref", "ref"]
    assert blocks[0]["block_id"] == "r1" and blocks[1]["block_id"] != "r1"


def test_kana_only_allowed_in_ref() -> None:
    data = {"pages": [{"page": 38, "blocks": [
        {"block_id": "a", "role": "body", "translation": "Gorgonians (ヤギ類) occur."},
        {"block_id": "b", "role": "ref", "translation": "今島実 2001. ウロコムシ."},
        {"block_id": "c", "role": "body", "translation": "Clean."}]}]}
    found = kana_residue(data)
    assert [f["block_id"] for f in found] == ["a"]


def test_kana_check_cli(tmp_path) -> None:
    import json
    from booklayout.cli import main
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"pages": [{"page": 1, "blocks": [
        {"block_id": "a", "role": "body", "translation": "ヤギ類"}]}]}), encoding="utf-8")
    assert main(["kana-check", "--aligned", str(p), "--out", str(tmp_path / "r.json")]) == 1
