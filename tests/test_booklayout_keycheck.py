"""Tests for booklayout.keycheck (identification-key checks and repairs)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from booklayout import keycheck as kc


def blk(text: str, tr: str, role: str = "key") -> dict[str, Any]:
    return {"role": role, "text": text, "translation": tr}


def book(*blocks: dict[str, Any], page: int = 10) -> dict[str, Any]:
    head = {"role": "heading", "text": "Clave de especies", "translation": "物种检索表"}
    return {"pages": [{"page": page, "blocks": [head, *blocks]}]}


GOOD = [
    blk("1. Ojos presentes ..... 2", "1. 眼存在 ..... 2"),
    blk("• Ojos ausentes ..... Aus bus (p. 12)", "• 眼缺失 ..... Aus bus（第12页）"),
    blk("2. Palpos largos ..... Aus cus (p. 13)", "2. 触须长 ..... Aus cus（第13页）"),
    blk("• Palpos cortos ..... Aus dus (p. 14)", "• 触须短 ..... Aus dus（第14页）"),
]


def codes(data: dict[str, Any]) -> list[str]:
    return sorted(f.code for f in kc.run(data)[1] if f.level == "error")


def test_clean_key_has_no_errors() -> None:
    assert codes(book(*copy.deepcopy(GOOD))) == []


def test_dangling_target() -> None:
    b = copy.deepcopy(GOOD)
    b[0] = blk("1. Ojos presentes ..... 7", "1. 眼存在 ..... 7")
    found = codes(book(*b))
    assert "K_DANGLING" in found and "K_UNREACHED" in found


def test_backward_jump() -> None:
    b = copy.deepcopy(GOOD)
    b[2] = blk("2. Palpos largos ..... 1", "2. 触须长 ..... 1")
    assert "K_BACKWARD" in codes(book(*b))


def test_alternative_missing() -> None:
    b = copy.deepcopy(GOOD)
    del b[3]
    assert "K_ALT_MISSING" in codes(book(*b))


def test_translation_target_mismatch_fixed_from_source() -> None:
    b = copy.deepcopy(GOOD)
    b[0]["translation"] = "1. 眼存在 ..... 3"
    b[1]["translation"] = "• 眼缺失 ..... Aus bas（第21页）"
    data = book(*b)
    found = {f.code for f in kc.run(data)[1]}
    assert {"K_TR_GOTO", "K_TR_NAME", "K_TR_PAGE"} <= found
    out, log = kc.repair(data)
    blocks = out["pages"][0]["blocks"]
    assert blocks[1]["translation"].endswith("..... 2")
    assert blocks[2]["translation"].endswith("Aus bus（第12页）")
    assert codes(out) == [] and log


def test_untranslated_page_reference() -> None:
    b = copy.deepcopy(GOOD)
    b[1]["translation"] = "• 眼缺失 ..... Aus bus (p. 12)"
    data = book(*b)
    assert "K_TR_PAGEFMT" in {f.code for f in kc.run(data)[1]}
    out, _ = kc.repair(data)
    assert out["pages"][0]["blocks"][2]["translation"].endswith("Aus bus（第12页）")


def test_index_line_typed_as_key_is_reported() -> None:
    b = copy.deepcopy(GOOD)
    b.append(blk("(branchialis) ..... 384", "(branchialis) ..... 384"))
    assert "K_INDEX_AS_KEY" in {f.code for f in kc.run(book(*b))[1]}


def test_hidden_lead_filed_as_index_is_restored() -> None:
    b = copy.deepcopy(GOOD)
    b[1]["role"] = "index"
    data = book(*b)
    assert "K_HIDDEN_LEAD" in codes(data)
    out, _ = kc.repair(data)
    assert out["pages"][0]["blocks"][2]["role"] == "key"
    assert codes(out) == []


def test_split_target_merged_back() -> None:
    b = copy.deepcopy(GOOD)
    b[1] = blk("• Ojos ausentes", "• 眼缺失")
    b.insert(2, blk(".....Aus bus (p. 12)", ".....Aus bus（第12页）", role="body"))
    data = book(*b)
    assert "K_SPLIT_TARGET" in {f.code for f in kc.run(data)[1]}
    out, _ = kc.repair(data)
    bl = out["pages"][0]["blocks"]
    assert bl[2]["text"].endswith("Aus bus (p. 12)")
    assert bl[2]["translation"].endswith("Aus bus（第12页）")
    assert bl[3]["translation"] == "" and bl[3]["keycheck"] == "merged"
    assert codes(out) == []


def test_text_continuation_is_not_a_lone_target() -> None:
    # "15-30 dientes.....P. x (p. 9)" carries text and its own leader: join as text
    assert kc._lone_target("15-30 dientes.....Aus bus (p. 12)") is None
    assert kc._lone_target(".....Aus bus (p. 12)") is not None


def test_lost_bullet_restored_and_target_not_duplicated() -> None:
    b = copy.deepcopy(GOOD)
    b[1] = blk("Ojos ausentes (fig. 7A) Aus bus (p. 12)", "眼缺失（图7A）Aus bus（第12页）", role="body")
    data = book(*b)
    assert "K_LOST_MARKER" in {f.code for f in kc.run(data)[1]}
    out, _ = kc.repair(data)
    tr = out["pages"][0]["blocks"][2]["translation"]
    assert tr.startswith("• ") and tr.count("Aus bus") == 1
    assert codes(out) == []


def test_ocr_paired_numbering_renumbered() -> None:
    b = [
        blk("1. Ojos presentes ..... 2", "1. 眼存在 ..... 2"),
        blk("2. Ojos ausentes ..... Aus bus (p. 12)", "2. 眼缺失 ..... Aus bus（第12页）"),
        blk("2. Palpos largos ..... Aus cus (p. 13)", "2. 触须长 ..... Aus cus（第13页）"),
        blk("3. Palpos cortos ..... Aus dus (p. 14)", "3. 触须短 ..... Aus dus（第14页）"),
    ]
    data = book(*b)
    assert "K_MARKER_OCR" in {f.code for f in kc.run(data)[1]}
    out, _ = kc.repair(data)
    marks = [x["text"].split()[0] for x in out["pages"][0]["blocks"][1:]]
    assert marks == ["1.", "•", "2.", "•"]
    assert codes(out) == []


def test_restored_lead_takes_couplet_style_of_its_key() -> None:
    b = copy.deepcopy(GOOD)
    b[0] = {"role": "couplet", "text": b[0]["text"], "translation": "眼存在",
            "couplet": {"marker": "1.", "name": "", "target": "2"}}
    b[1] = blk("Ojos ausentes (fig. 7A) Aus bus (p. 12)", "眼缺失（图7A）Aus bus（第12页）", role="body")
    out, log = kc.repair(book(*b))
    x = out["pages"][0]["blocks"][2]
    assert x["role"] == "couplet" and x["translation"] == "眼缺失（图7A）"
    assert x["couplet"] == {"marker": "•", "name": "Aus bus（第12页）", "target": ""}
    assert any(e["rule"] == "K_STYLE_COUPLET" for e in log)


def _with_names(extra: str) -> dict[str, Any]:
    body = blk("Aus rathkei se cita aquí. Aus rathkei vive. Aus rathkei es común. " + extra, "", role="body")
    b = copy.deepcopy(GOOD)
    b[3] = blk("• Palpos cortos ..... Aus ratbkei (p. 14)", "• 触须短 ..... Aus ratbkei（第14页）")
    data = book(*b)
    data["pages"].insert(0, {"page": 9, "blocks": [body]})
    return data


def test_ocr_name_with_unique_close_candidate_autofixed() -> None:
    data = _with_names("")
    f = [x for x in kc.run(data)[1] if x.code == "K_NAME_SPELL"]
    assert f and f[0].fix == {"replace": ["ratbkei", "rathkei"]}
    out, _ = kc.repair(data)
    assert out["pages"][1]["blocks"][4]["translation"].endswith("Aus rathkei（第14页）")


def test_distance_one_name_is_reported_not_fixed() -> None:
    b = copy.deepcopy(GOOD)
    b[3] = blk("• Palpos cortos ..... Diplosyllis dus (p. 14)", "• 触须短 ..... Diplosyllis dus（第14页）")
    data = book(*b)
    data["pages"].insert(0, {"page": 9, "blocks": [blk("Dioplosyllis a. Dioplosyllis b. Dioplosyllis c.", "",
                                                       role="body")]})
    f = [x for x in kc.run(data)[1] if x.code == "K_NAME_SPELL"]
    assert f and not f[0].fix
    out, _ = kc.repair(data)
    assert "Diplosyllis" in out["pages"][1]["blocks"][4]["translation"]


def test_cli_never_overwrites_input(tmp_path: Path) -> None:
    src = tmp_path / "a.json"
    src.write_text(json.dumps(book(*copy.deepcopy(GOOD))), encoding="utf-8")
    before = src.read_bytes()
    with pytest.raises(SystemExit):
        kc.main([str(src), "--fix", str(src), "--fail-on", "never"])
    assert src.read_bytes() == before
    out = tmp_path / "b.json"
    assert kc.main([str(src), "--fix", str(out), "--report", str(tmp_path / "r.json"), "--fail-on", "error"]) == 0
    assert src.read_bytes() == before and out.exists()
