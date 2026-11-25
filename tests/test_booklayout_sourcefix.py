import json
from pathlib import Path

from booklayout import sourcefix
from booklayout.sourcecheck import aligned_tokens


def _aligned(text: str) -> dict:
    return {"pages": [{"page": 3, "blocks": [{"block_id": "p003_b01", "role": "body", "translation": text}]}]}


def test_aligned_tokens_carry_block_spans(tmp_path: Path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_aligned("la reprografia es")), encoding="utf-8")
    words, pages, refs = aligned_tokens(p, [])
    assert words == ["la", "reprografia", "es"] and pages == [3, 3, 3]
    assert refs[1] == {"block_id": "p003_b01", "start": 3, "end": 14}


def test_to_patch_replaces_by_span_right_to_left():
    al = _aligned("Martin y Martin")
    fixes = [{"ref": {"block_id": "p003_b01", "start": 0, "end": 6}, "source": "Martín"},
             {"ref": {"block_id": "p003_b01", "start": 9, "end": 15}, "source": "Martín"}]
    patch = sourcefix.to_patch(fixes, al)
    assert patch["version"] == 1
    assert patch["edits"] == [{"block_id": "p003_b01", "old_translation": "Martin y Martin",
                               "translation": "Martín y Martín"}]


def test_accent_unsafe_guards_names_and_dropped_marks():
    assert sourcefix.accent_unsafe("Claparede", "Claparéde")      # source has fewer marks: tess dropped one
    assert sourcefix.accent_unsafe("Búhrmann", "Bührmann")        # ü in the output: name, look at the image
    assert not sourcefix.accent_unsafe("Martín", "Martin")        # plain Spanish accent restored
    assert not sourcefix.accent_unsafe("especie", "superficie")   # not an accent-only difference


def test_plan_skips_truncation_and_stale_span(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sourcefix, "vote", lambda *a, **k: "n")
    al = _aligned("Ref nº PB95")
    base = {"type": "output_error", "src_page": 3, "box": [0, 0, 1, 1], "conf": 90.0}
    rep = {"items": [
        {**base, "id": "a", "source": "n", "output": "nº", "ref": {"block_id": "p003_b01", "start": 4, "end": 6}},
        {**base, "id": "b", "source": "n", "output": "zzz", "ref": {"block_id": "p003_b01", "start": 4, "end": 6}},
    ]}
    fixes, todo, keep = sourcefix.plan(rep, al, tmp_path / "x.pdf", 300, 450, 80.0)
    assert fixes == [] and keep == []
    assert {t["id"]: t["why"] for t in todo}["b"] == "span does not match aligned text"
