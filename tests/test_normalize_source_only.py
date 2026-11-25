from booklayout.normalize import normalize_aligned


def test_source_only_keeps_spanish_structure_words():
    """Vol. 21 原文排版：normalize 不得把 Subfamilia/y 改成英文（translation 就是西文原文）。"""
    t = "Subfamilia EUSYLLINAE Malaquin, 1893"
    body = "Cuerpo de talla pequeña y media."
    data = {"pages": [{"page": 46, "blocks": [
        {"block_id": "p046_b00", "role": "heading", "level": 2, "text": t, "translation": t},
        {"block_id": "p046_b01", "role": "body", "text": body, "translation": body}]}]}
    normalize_aligned(data, source_only=True)
    assert [b["translation"] for b in data["pages"][0]["blocks"]] == [t, body]
