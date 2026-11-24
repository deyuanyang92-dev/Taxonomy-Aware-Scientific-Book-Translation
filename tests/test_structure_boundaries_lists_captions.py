from booklayout.normalize import apply_block_edits
from booklayout.structure import uncertain_boundaries


def _page(n, *blocks):
    return {"page": n, "blocks": [dict(b) for b in blocks]}


def test_checklist_block_is_not_an_unfinished_sentence():
    data = {"pages": [
        _page(41, {"block_id": "a", "role": "body",
                   "translation": "Odontosyllis fulgurans (Audouin y Milne Edwards, 1834)\nOdontosyllis gibba Claparède, 1863"}),
        _page(42, {"block_id": "b", "role": "body", "translation": "Género Dioplosyllis Gidholm, 1962"}),
    ]}
    assert uncertain_boundaries(data) == []


def test_boundary_looks_past_caption_only_pages():
    data = {"pages": [
        _page(27, {"block_id": "a", "role": "body", "translation": "Se han estudiado algunos"}),
        _page(28, {"block_id": "c", "role": "body", "label": "vision_footnote", "translation": "Fig. 5. Fotos."}),
        _page(29, {"block_id": "b", "role": "body", "translation": "Polybostrichus al microscopio."}),
    ]}
    found = uncertain_boundaries(data)
    assert [(f["page"], f["next_page"], f["next_block_id"]) for f in found] == [(27, 29, "b")]


def test_unfinished_prose_still_flagged():
    data = {"pages": [
        _page(1, {"block_id": "a", "role": "body", "translation": "el cuerpo de los"}),
        _page(2, {"block_id": "b", "role": "body", "translation": "Sílidos es largo."}),
    ]}
    assert len(uncertain_boundaries(data)) == 1


def test_patch_can_record_boundary_review():
    data = {"pages": [
        _page(1, {"block_id": "a", "role": "body", "translation": "Museo Nacional"}),
        _page(2, {"block_id": "b", "role": "body", "translation": "FAUNA IBERICA"}),
    ]}
    rep = apply_block_edits(data, {"version": 1, "edits": [{"block_id": "a", "boundary_reviewed": True}]})
    assert rep["applied"] == ["a"] and rep["invalid"] == []
    assert uncertain_boundaries(data) == []
    bad = apply_block_edits(data, {"version": 1, "edits": [{"block_id": "a", "boundary_reviewed": "yes"}]})
    assert bad["invalid"]


def test_copyright_notice_in_capitals_is_not_flagged(tmp_path):
    from booklayout.cli import _report
    data = {"pages": [{"page": 3, "chapter": 1, "blocks": [{"block_id": "c", "role": "body",
        "text": "© MUSEO NACIONAL DE CIENCIAS NATURALES CONSEJO SUPERIOR DE INVESTIGACIONES CIENTIFICAS",
        "translation": "© MUSEO NACIONAL DE CIENCIAS NATURALES CONSEJO SUPERIOR DE INVESTIGACIONES CIENTIFICAS"}]}]}
    assert _report(data, tmp_path)["all_caps_body"] == []


def test_literal_latex_in_pdf_is_reported(tmp_path):
    import fitz
    from booklayout.cli import _delivery_problems
    pdf = tmp_path / "x.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "la Dra. M $ ^{a} $ Angeles Ramos")
    doc.save(pdf)
    assert _delivery_problems({"pages": []}, str(pdf))["literal_markup_in_pdf"]
