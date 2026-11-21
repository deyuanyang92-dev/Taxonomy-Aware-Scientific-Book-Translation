from booklayout.treatments import parse, validate


def page(*blocks, n=1):
    return {"pages": [{"page": n, "blocks": [
        {"block_id": f"b{i}", "role": r, "text": t} for i, (r, t) in enumerate(blocks)]}]}


FULL = [("caption", "図14"), ("body", "Eunoe barbata Moore, 1910"), ("body", "ヒゲウロコムシ"),
        ("ref", "Eunoe barbata : Imajima, 1964"), ("body", "体長41mm"), ("body", "分布—北海道.")]


def codes(blocks):
    return {i["code"] for i in validate(parse(page(*blocks)))}


def test_complete_species_ok():
    assert codes(FULL) == set()


def test_caption_before_name_attaches_to_species():
    r = parse(page(("heading", "Eunoe Malmgren, 1865"), *FULL))
    assert [x["rank"] for x in r] == ["genus", "species"]
    assert r[1]["caption"][0]["no"] == 14


def test_missing_fields_flagged():
    assert {"missing_ja", "missing_caption"} <= codes([b for b in FULL if b[0] != "caption" and b[1] != "ヒゲウロコムシ"])


def test_ocr_dash_variant_counts_as_distribution():
    assert "missing_distribution" not in codes([*FULL[:-1], ("body", "分布一北海道.")])


def test_figure_number_gap():
    d = page(*FULL, ("body", "Eunoe nova Moore, 1911"), ("caption", "図16"))
    assert "figure_no_gap" in {i["code"] for i in validate(parse(d))}
