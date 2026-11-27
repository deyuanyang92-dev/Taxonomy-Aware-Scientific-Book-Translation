from booklayout import docstruct as D


def ln(text, x0, y0, x1=None, bold=False, size=9.5):
    x1 = x1 if x1 is not None else x0 + 6 * len(text)
    font = "DGMetaScience-Bold" if bold else "DGMetaScience"
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y0 + 13, "dir": (1, 0),
            "spans": [{"text": text, "font": font, "size": size, "flags": 16 if bold else 0}]}


def test_toc_rows_wrap_authors_part_and_columns():
    lines = [
        ln("viii", 62, 30), ln("Contents", 98, 30),                       # running head
        ln("Part 1: Introduction", 51, 60, bold=True, size=12),
        ln("Geoffrey B. Read", 51, 86),                                    # author, above its entry
        ln("1", 51, 99, bold=True), ln("A History of Annelida Research", 85, 99, 214, bold=True),
        ln("3", 229, 99, bold=True),
        ln("1.1", 51, 112), ln("Introduction", 102, 112, 154), ln("3", 169, 112, bold=True),
        ln("5.1", 51, 125, bold=True), ln("Apistobranchidae Mesnil & Caullery,", 102, 125, 270, bold=True),
        ln("1898", 102, 138, 125, bold=True), ln("133", 140, 137, bold=True),   # wrapped title
        ln("Morphology", 102, 151, 160), ln("138", 175, 151, bold=True),     # unnumbered child
        ln("7.1", 309, 99, bold=True), ln("Sedentaria: Orbiniida", 360, 99, 451, bold=True),
        ln("217", 466, 99, bold=True),
        ln("Index", 309, 112, bold=True), ln("467", 340, 112, bold=True),
    ]
    es = D.parse_toc_lines(lines, 595)
    D.toc_levels(es)
    got = [(e["number"], e["title"], e["printed"], e["level"]) for e in es]
    assert got == [
        (None, "Part 1: Introduction", None, 0),
        ("1", "A History of Annelida Research", "3", 1),
        ("1.1", "Introduction", "3", 2),
        ("5.1", "Apistobranchidae Mesnil & Caullery, 1898", "133", 2),
        (None, "Morphology", "138", 3),
        ("7.1", "Sedentaria: Orbiniida", "217", 2),
        (None, "Index", "467", 1),
    ]
    assert es[1]["authors"] == ["Geoffrey B. Read"]


def test_toc_drops_watermark_and_email():
    lines = [ln("Index", 51, 100, bold=True), ln("467", 90, 100, bold=True),
             ln("Authenticated | someone@example.com", 51, 760), ln("Download Date | 3/29/19", 51, 770)]
    es = D.parse_toc_lines(lines, 595)
    assert "example.com" not in repr(es)


def test_table_rows_from_html():
    rows = D.table_rows("<table><tr><td>Author</td><td>Date</td></tr><tr><td>Pliny &amp; co</td><td><i>77</i></td></tr></table>")
    assert rows == [["Author", "Date"], ["Pliny & co", "77"]]
    assert D.table_rows("<table><tr><td>Seville $ \n^{1} $ x</td><td>H $ _{2} $ O</td></tr></table>") == [["Seville¹ x", "H₂ O"]]


def test_table_trailing_full_width_rows_become_notes():
    rows = D.table_rows('<table><tr><td>A</td><td>B</td><td>C</td></tr>'
                        '<tr><td colspan="2">wide</td><td>c</td></tr>'
                        '<tr><td colspan="3">These early titles ...</td></tr>'
                        '<tr><td colspan=3>1 Footnote one</td></tr></table>')
    body, notes = D.split_table_notes(rows)
    assert body == [["A", "B", "C"], [{"text": "wide", "colspan": 2}, "c"]]
    assert notes == ["These early titles ...", "1 Footnote one"]
    sd = _sd()
    sd["pages"][4]["blocks"][0].update(rows=body, notes=notes)
    blocks = {p["page"]: p for p in D.to_aligned(sd)["pages"]}[13]["blocks"]
    assert [b["role"] for b in blocks] == ["table", "note", "note", "caption"]
    assert blocks[1]["text"] == "These early titles ..."


def test_assign_lines_smallest_box_and_orphans():
    boxes = [{"bbox": [0, 0, 500, 500]}, {"bbox": [10, 10, 200, 40]}]
    a = ln("inner", 20, 15, 100)
    b = ln("outer", 20, 300, 100)
    c = ln("nowhere", 520, 600, 560)
    owned, orphans = D.assign_lines([a, b, c], boxes)
    assert owned[1] == [a] and owned[0] == [b] and orphans == [c]


def test_page_kinds():
    assert D.page_kind(6, [("doc_title", "Contents")], ["Contents"], "", False)[0] == "toc"
    assert D.page_kind(10, [("paragraph_title", "List of contributing authors")], [], "", False)[0] == "authors"
    assert D.page_kind(5, [("text", "ISBN 978-3-11-029146-9")], [], "", False)[0] == "copyright"
    assert D.page_kind(1, [("doc_title", "HANDBOOK OF ZOOLOGY")], [], "", False)[0] == "cover"
    assert D.page_kind(12, [("doc_title", "1 A History of Annelida Research")], [], "", False)[0] == "chapter_start"
    assert D.page_kind(13, [("text", "body")], [], "1 A History", True)[0] == "body"


def test_check_toc_flags_missing_heading():
    toc = [{"title": "Introduction", "printed": "3", "number": "1.1"},
           {"title": "The written record", "printed": "4", "number": "1.3"}]
    tree = [{"title": "Introduction", "page": 12, "level": 2}]
    probs = D.check_toc(toc, tree, 9, list(range(1, 21)))
    assert [p["code"] for p in probs] == ["toc_no_heading"] and probs[0]["page"] == 13


def test_paddle_blocks_scale_px_to_pt():
    lay = {"width_px": 1191, "pruned_result": {"parsing_res_list": [
        {"block_label": "text", "block_content": "x", "block_order": 1, "block_bbox": [0, 0, 1191, 100]}]}}
    b = D.paddle_blocks(lay, 595.3)[0]
    assert abs(b["bbox"][2] - 595.3) < 0.01 and abs(b["bbox"][3] - 49.98) < 0.1


def _b(i, role, text, **kw):
    return dict({"id": i, "role": role, "text": text, "src": {"bbox": [0, 10, 100, 20], "b": role}}, **kw)


def _sd():
    return {"pages": [
        {"page": 1, "kind": "cover", "blocks": [_b("a", "heading", "HANDBOOK", level=1)]},
        {"page": 3, "kind": "title", "blocks": [_b("b", "heading", "Volume 1: Annelida", level=1)]},
        {"page": 6, "kind": "toc", "blocks": [_b("c", "toc_entry", "1 A History 3")]},
        {"page": 12, "kind": "chapter_start", "blocks": [
            _b("d", "heading", "1 A History", level=1), _b("e", "byline", "Geoffrey B. Read"),
            _b("f", "body", "Annelids ..."), _b("g", "figure", ""), _b("h", "panel_label", "A")]},
        {"page": 13, "kind": "body", "blocks": [
            _b("i", "table", "", rows=[["Author", "Date"]]), _b("j", "caption", "Tab. 1.1 ...")]}],
        "toc": [{"number": "1", "title": "A History", "printed": "3", "level": 1, "page": 6}],
        "summary": {"errors": 0}, "source": {"pages": [1, 3, 6, 12, 13]}}


def test_to_aligned_roles_and_contents():
    a = D.to_aligned(_sd())
    pages = {p["page"]: p for p in a["pages"]}
    assert [b["role"] for b in pages[6]["blocks"]] == ["heading", "index"]   # "Contents" title, then lines
    assert "A History" in pages[6]["blocks"][1]["text"]
    assert [b["role"] for b in pages[12]["blocks"]] == ["heading", "entry", "body"]   # figure/panel dropped
    assert pages[13]["blocks"][0]["role"] == "table" and pages[13]["blocks"][0]["rows"] == [["Author", "Date"]]
    assert pages[12]["kind"] == "chapter" and pages[1]["kind"] == "front"


def test_meta_from_struct_loads_as_bookmeta(tmp_path):
    import json

    from booklayout.builder import BookMeta
    m = D.meta_from_struct(_sd(), "")
    assert m["front_pages"] == [1, 3] and m["body_start_page"] == 1 and m["contents_in_place"]
    assert m["title"] == "Volume 1: Annelida" and m["own_pages"] == [1, 3, 6]
    assert m["folio_first_page"] == 12     # contents pages print no book running head (2026-11-27)
    assert m["toc_pages"] == [6]
    f = tmp_path / "meta.json"
    f.write_text(json.dumps(m), encoding="utf-8")
    assert BookMeta.from_json(f).body_start_page == 1
