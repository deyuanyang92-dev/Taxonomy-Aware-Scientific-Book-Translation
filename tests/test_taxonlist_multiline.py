from booklayout.taxonlist import unify_taxon_lists


def test_merged_rank_blocks_become_one_line_each_and_no_headings():
    blocks = [{"role": "body", "text": "Orden Abida Levinsen, 1883\nFamilia Aidae Malmgren, 1866\nFamilia Bidae Malmgren, 1867",
               "translation": "Orden Abida Levinsen, 1883\nFamilia Aidae Malmgren, 1866\nFamilia Bidae Malmgren, 1867"},
              {"role": "body", "text": "Superfamilia Cacea Grube, 1850"},
              {"role": "ref", "text": "Familia Cidae Ehlers, 1864"},
              {"role": "body", "text": "Familia Didae Ehlers, 1865"}]
    page = {"page": 16, "blocks": blocks}
    unify_taxon_lists({"pages": [page]})
    assert [b["role"] for b in page["blocks"]] == ["taxon"] * 6
    assert page["blocks"][1]["translation"] == "Familia Aidae Malmgren, 1866"


def test_uppercase_order_names_are_list_lines():
    names = ["Orden PHYLLODOCIDA Levinsen, 1883", "Familia Aidae Malmgren, 1866", "Orden OWENIDA Dales, 1963",
             "Familia Bidae Rioja, 1917", "Orden Nerillida Pettibone, 1982", "Familia Cidae Levinsen, 1883"]
    page = {"page": 16, "blocks": [{"role": "heading", "level": 2, "text": names[0]}]
            + [{"role": "body", "text": t} for t in names[1:]]}
    unify_taxon_lists({"pages": [page]})
    assert [b["role"] for b in page["blocks"]] == ["taxon"] * 6


def test_prose_block_with_a_rank_line_is_not_split():
    page = {"page": 1, "blocks": [{"role": "body", "text": "Familia Aidae Malmgren, 1866\nEl cuerpo es largo y delgado."}]}
    unify_taxon_lists({"pages": [page]})
    assert len(page["blocks"]) == 1 and page["blocks"][0]["role"] == "body"
