import json

from booklayout.cli import _residue_check_applies
from booklayout.normalize import normalize_aligned


def test_cross_page_merge_skips_body_caption_at_top_of_next_page():
    data = {"pages": [
        {"page": 13, "blocks": [{"block_id": "a", "role": "body", "text": "el distal es el que se reduce o desa-", "translation": "el distal se reduce y los"}]},
        {"page": 14, "blocks": [
            {"block_id": "c", "role": "body", "text": "Fig. 1. Fotografías al microscopio.", "translation": "Fig. 1. Fotografías al microscopio."},
            {"block_id": "b", "role": "body", "text": "parápodos siguen.", "translation": "parápodos siguen."}]},
    ]}
    normalize_aligned(data, source_only=True)
    out = data
    a = out["pages"][0]["blocks"][0]["translation"]
    assert a.endswith("los parápodos siguen.")
    assert [b["block_id"] for b in out["pages"][1]["blocks"]] == ["c"]


def test_residue_check_skipped_for_spanish_profile(tmp_path):
    es, en = tmp_path / "es.json", tmp_path / "en.json"
    es.write_text(json.dumps({"lang": "es-ES"}), encoding="utf-8")
    en.write_text(json.dumps({"lang": "en-US"}), encoding="utf-8")
    assert not _residue_check_applies(es)
    assert _residue_check_applies(en) and _residue_check_applies(None)


def test_paragraph_carries_over_a_caption_only_page():
    data = {"pages": [
        {"page": 27, "blocks": [{"block_id": "a", "role": "body", "text": "Se han estudiado algunos", "translation": "Se han estudiado algunos"}]},
        {"page": 28, "blocks": [{"block_id": "c", "role": "body", "label": "vision_footnote", "text": "Fig. 5. Fotografias.", "translation": "Fig. 5. Fotografias."}]},
        {"page": 29, "blocks": [{"block_id": "b", "role": "body", "text": "casos más.", "translation": "casos más."}]},
    ]}
    normalize_aligned(data, source_only=True)
    assert data["pages"][0]["blocks"][0]["translation"] == "Se han estudiado algunos casos más."
    assert data["pages"][2]["blocks"] == []


def test_parenthesis_continues_an_unfinished_sentence():
    data = {"pages": [
        {"page": 21, "blocks": [{"block_id": "a", "role": "body", "text": "incubación de los huevos", "translation": "incubación de los huevos"}]},
        {"page": 22, "blocks": [{"block_id": "b", "role": "body", "text": "(Heacox y Schröder, 1978). Sin embargo.", "translation": "(Heacox y Schröder, 1978). Sin embargo."}]},
    ]}
    normalize_aligned(data, source_only=True)
    assert data["pages"][0]["blocks"][0]["translation"].endswith("huevos (Heacox y Schröder, 1978). Sin embargo.")


def test_missing_block_check_ignores_capitals(tmp_path):
    import fitz
    from booklayout.cli import _delivery_problems
    pdf = tmp_path / "x.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "FAMILIA SYLLIDAE GRUBE, 1850")
    doc.save(pdf)
    data = {"pages": [{"page": 10, "blocks": [{"role": "heading", "translation": "Familia SYLLIDAE Grube, 1850"}]}]}
    assert _delivery_problems(data, str(pdf))["blocks_missing_in_pdf"] == []
