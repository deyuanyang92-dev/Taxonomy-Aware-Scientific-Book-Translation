import fitz

from booklayout.taxonlist import pdf_list_style_mismatches, taxon_line_rank, unify_taxon_lists

LINES = ["Género Haplosyllis Langerhans, 1879", "Haplosyllis chamaeleon Laubier, 1960",
         "Haplosyllis spongicola (Grube, 1855)", "Syllis armillaris (O.F. Müller, 1771)",
         "Syllis beneliahuae (Campoy y Alquézar, 1982", "Syllis licheri Ravara, San Martin y Moreira, en prensa"]


def test_line_rank():
    assert taxon_line_rank(LINES[0]) == 0
    assert all(taxon_line_rank(x) == 1 for x in LINES[1:])  # dot inside the author, missing paren, "en prensa"
    assert taxon_line_rank("Los palpos están más desarrollados que en el caso de Syllis gracilis (fig. 7B).") is None


def test_checklist_run_becomes_one_list_whatever_the_aligner_label():
    roles = ["body", "body", "ref", "body", "body", "ref"]
    page = {"page": 44, "blocks": [{"role": r, "text": t, "translation": t} for r, t in zip(roles, LINES)]}
    assert unify_taxon_lists({"pages": [page]}) == 6
    assert [b["role"] for b in page["blocks"]] == ["taxon"] * 6
    assert [b["rank"] for b in page["blocks"]] == [0, 1, 1, 1, 1, 1]


def test_garbled_name_inside_list_and_heading_at_tail():
    lines = LINES[:3] + ["Parapionosyllis cabezal" + chr(0x131) + " Parapar, San Martin y Moreira, 2000"] + LINES[3:]
    page = {"page": 1, "blocks": [{"role": "ref", "text": t, "translation": t} for t in lines]}
    assert unify_taxon_lists({"pages": [page]}) == 7


def test_short_run_and_prose_untouched():
    page = {"page": 1, "blocks": [{"role": "body", "text": t, "translation": t} for t in LINES[:2]]
            + [{"role": "body", "text": "Texto corrido de una frase larga.", "translation": "x"}]}
    assert unify_taxon_lists({"pages": [page]}) == 0
    assert page["blocks"][0]["role"] == "body"


def _pdf(tmp_path, sizes):
    doc = fitz.open()
    pg = doc.new_page()
    y = 100
    for t, s in zip(LINES, sizes):
        pg.insert_text((72, y), t, fontsize=s, fontname="hebo" if s == 12 else "helv")
        y += 20
    f = str(tmp_path / "t.pdf")
    doc.save(f)
    return f


def test_pdf_gate_flags_mixed_style_and_passes_uniform(tmp_path):
    bad = pdf_list_style_mismatches(_pdf(tmp_path, [8, 12, 8, 10, 12, 8]))
    assert bad and bad[0]["odd"]
    assert pdf_list_style_mismatches(_pdf(tmp_path, [8] * 6)) == []
    assert pdf_list_style_mismatches(_pdf(tmp_path, [12, 12, 8, 8, 8, 8])) == []  # bold heading at the head is a boundary, not a defect
