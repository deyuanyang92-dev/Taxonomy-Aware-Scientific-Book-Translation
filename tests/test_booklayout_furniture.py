"""Issue #15: running headers and folios are not body text."""
from __future__ import annotations

from booklayout.furniture import (
    body_stream,
    check_body_paragraphs,
    detect_furniture,
    strip_furniture,
)

H = 700.0


def page(n: int, body: list[str], header: str | None, folio_left: bool = True) -> dict:
    lines = []
    if header is not None:
        lines.append({"text": header, "y0": 20.0, "y1": 30.0})
    for i, t in enumerate(body):
        lines.append({"text": t, "y0": 100.0 + 14 * i, "y1": 110.0 + 14 * i})
    return {"page": n, "height": H, "lines": lines}


def alternating(n_pages: int = 8) -> list[dict]:
    pages = []
    for n in range(1, n_pages + 1):
        head = f"{n} FAUNA IBÉRICA" if n % 2 else f"M. A. RAMOS ET AL. {n}"
        pages.append(page(n, [f"Body line one of page {n}.", f"Body line two of page {n}."], head))
    return pages


def test_alternating_headers_and_folios_are_detected_by_coordinates() -> None:
    pages = alternating()
    rep = detect_furniture(pages)
    kinds = {sig for sig in rep.signatures}
    assert len(kinds) == 2
    clean, prov = strip_furniture(pages, rep)
    for p in clean:
        assert len(p["lines"]) == 2
    assert prov[1][0]["text"] == "1 FAUNA IBÉRICA"
    assert prov[2][0]["kind"] == "header"


def test_legitimate_body_text_matching_header_is_kept() -> None:
    pages = alternating()
    pages[3]["lines"].insert(3, {"text": "12 FAUNA IBÉRICA", "y0": 300.0, "y1": 310.0})  # mid-page
    rep = detect_furniture(pages)
    clean, _ = strip_furniture(pages, rep)
    assert any(ln["text"] == "12 FAUNA IBÉRICA" for ln in clean[3]["lines"])


def test_detection_without_coordinates_uses_edge_lines() -> None:
    pages = []
    for n in range(1, 7):
        body = [{"text": t} for t in (f"Unique opening {n}.", "Middle line stays.",
                                      "Another middle line.", f"Closing words of page {n}.")]
        # edge_lines=2 would be too greedy on a 4-line body, so use edge_lines=1
        pages.append({"page": n, "lines": [{"text": "IBERIAN FAUNA"}, *body, {"text": str(n + 10)}]})
    rep = detect_furniture(pages, edge_lines=1)
    clean, prov = strip_furniture(pages, rep)
    assert [ln["text"] for ln in clean[0]["lines"]] == [
        "Unique opening 1.", "Middle line stays.", "Another middle line.", "Closing words of page 1."]
    assert {r["kind"] for r in prov[1]} == {"header", "folio"}


def test_multilingual_header_variants_via_known_headers() -> None:
    pages = [page(1, ["Alpha beta."], "FAUNA IBÉRICA 4"), page(2, ["Gamma."], "IBERIAN FAUNA 5")]
    rep = detect_furniture(pages, known_headers=["FAUNA IBÉRICA", "IBERIAN FAUNA"])
    clean, _ = strip_furniture(pages, rep)
    assert all(len(p["lines"]) == 1 for p in clean)


def test_sentence_joins_across_stripped_furniture() -> None:
    pages = [
        page(1, ["Thanks to the Universidad de", ], "2 FAUNA IBÉRICA"),
        page(2, ["Sevilla and the Museo Nacional (MNCN 4521)."], "M. A. RAMOS ET AL. 3"),
        page(3, ["Next paragraph."], "4 FAUNA IBÉRICA"),
        page(4, ["More."], "M. A. RAMOS ET AL. 5"),
    ]
    rep = detect_furniture(pages, min_repeat=2)
    clean, _ = strip_furniture(pages, rep)
    paras = body_stream(clean)
    assert paras[0] == "Thanks to the Universidad de Sevilla and the Museo Nacional (MNCN 4521)."
    assert "FAUNA" not in " ".join(paras)
    assert "4521" in paras[0]  # adjacent numbers survive


def test_check_flags_header_tokens_in_body_paragraphs() -> None:
    pages = alternating()
    rep = detect_furniture(pages)
    ok = ["The Fauna Ibérica project started in 1989."]
    bad = ["Institutions such as Universidad 12 FAUNA IBÉRICA de Sevilla."]
    assert check_body_paragraphs(ok, rep) == []
    assert len(check_body_paragraphs(bad, rep)) == 1


def test_aligned_json_flags_header_block_rendered_as_body() -> None:
    from booklayout.furniture import aligned_furniture_blocks

    closing = {1: "Alpha closes.", 2: "Beta ends here.", 3: "Gamma trails off.", 4: "Delta stops."}

    def pg(n: int, role: str) -> dict:
        return {"page": n, "blocks": [
            {"block_id": f"h{n}", "role": role, "text": f"{n} FAUNA IBÉRICA", "translation": f"{n} FAUNA IBÉRICA", "y0": 20},
            {"block_id": f"b{n}", "role": "body", "text": f"Real text {n}.", "translation": f"Real text {n}.", "y0": 100},
            {"block_id": f"c{n}", "role": "body", "text": closing[n], "translation": "x", "y0": 200},
        ]}
    bad = {"pages": [pg(n, "body") for n in range(1, 5)]}
    assert [f["block_id"] for f in aligned_furniture_blocks(bad)] == ["h1", "h2", "h3", "h4"]
    good = {"pages": [pg(n, "header") for n in range(1, 5)]}
    assert aligned_furniture_blocks(good) == []
